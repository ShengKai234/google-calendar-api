"""
Install, list, switch and roll back releases of the app under /opt/e-pages.

Run as root, with the system python3 and the source's src/ on the path
(deploy/install-release.sh does both):

    install --source DIR|TAR [--user U] [--wheels DIR] [--migrate-from DIR]
    list
    switch VERSION [--user U]
    rollback [--user U]
    prune [--keep N]
    update [--channel stable|beta] [--check]
    status

`install` builds the new release beside the running one (see
infrastructure/release/), switches `current` to it only once it imports
and names itself, then points the systemd units at /opt/e-pages/current.
`switch` and `rollback` reinstall the units too, from the release they
switch to: releases may ship different units, and the running ones must
be the ones that release expects.
`update` is the over-the-air update (epd-update.timer runs it): fetch the
newest signed release for this display's channel from GitHub, install it
as above, check that the calendar renders with it, and roll back if not.
Standard library only, so it runs before any venv exists.
"""
import argparse
import logging
import os
import pwd
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from gcal_epd.config import load_config
from gcal_epd.infrastructure.release import installer, updater
from gcal_epd.infrastructure.release.installer import InstallError, Source
from gcal_epd.infrastructure.release.layout import DEFAULT_BASE, ReleaseError, ReleaseLayout
from gcal_epd.infrastructure.release.migrate import migrate_checkout

log = logging.getLogger(__name__)
KEEP = 2
# The new release must render the calendar within this long after an update.
HEALTH_TIMEOUT = 300
# A release whose build fails this many times is not tried again.
MAX_ATTEMPTS = 3
DOWNLOAD_PREFIX = ".download-"


def _owner(user: str):
    try:
        entry = pwd.getpwnam(user)
    except KeyError:
        raise InstallError(f"There is no user {user!r} on this system.") from None

    def chown(path: Path) -> None:
        os.chown(path, entry.pw_uid, entry.pw_gid)
    return chown


def _app_user(args, layout: ReleaseLayout) -> str:
    """--user, else whoever owns the old checkout or the data directory."""
    if args.user:
        return args.user
    for path in (getattr(args, "migrate_from", None), layout.data):
        if path and Path(path).exists():
            return pwd.getpwuid(Path(path).stat().st_uid).pw_name
    raise InstallError("Say which user runs the app: --user NAME.")


def _install_units(layout: ReleaseLayout, user: str, run=installer.run) -> None:
    """(Re)install the systemd units with the current release's install.sh."""
    log.info("Pointing the systemd units at %s...", layout.current_link)
    run(["bash", str(layout.current_link / "deploy" / "install.sh"), "--yes"],
        env=installer.child_env({"EPD_USER": user}))


def install(args, layout: ReleaseLayout, run=installer.run) -> str:
    source = Source(Path(args.source).resolve())
    label = source.label(run)
    if source.uncommitted(run):
        log.warning("Uncommitted changes in %s are NOT installed (only HEAD is).",
                    source.path)
    user = _app_user(args, layout)
    chown = _owner(user)
    on_pi = installer.on_raspberry_pi()
    wheels = Path(args.wheels).resolve() if args.wheels else None

    with layout.locked():
        release = layout.path(label)
        layout.data.mkdir(parents=True, exist_ok=True)
        os.chmod(layout.data, 0o700)   # feed links are bearer tokens
        chown(layout.data)
        if layout.is_complete(label):
            # Built before (say, then rolled back from): switch to it as it is.
            log.info("Release %s is already installed.", label)
        else:
            log.info("Building release %s in %s...", label, release)
            layout.begin(label)
            source.extract(release, run)
            installer.build_venv(release, wheels, on_pi, run)
            installer.smoke_test(release, label, layout.data, on_pi, run, user=user)
            layout.finish(label)

        if args.migrate_from:
            copied = migrate_checkout(Path(args.migrate_from), release, layout.data, chown)
            log.info("Carried over from %s: %s", args.migrate_from,
                     ", ".join(copied) if copied else "nothing new")

        old = layout.switch(label)
        log.info("Now running %s%s.", label, f" (was {old})" if old else "")

        if not args.no_units:
            _install_units(layout, user, run)
        removed = layout.prune(KEEP)
        if removed:
            log.info("Removed old releases: %s", ", ".join(removed))
    return label


def switch(args, layout: ReleaseLayout, run=installer.run) -> str:
    """Make args.version (or, with args.version None, the previous release)
    current, then reinstall the units from it. Returns what is current."""
    user = None if args.no_units else _app_user(args, layout)
    if user:
        _owner(user)   # an unknown user fails here, before anything changes
    with layout.locked():
        if args.version is None:
            label = layout.rollback()
        else:
            label = args.version
            layout.switch(label)
        log.info("Now running %s; it takes effect at the next refresh or boot.", label)
        if user:
            _install_units(layout, user, run)
    return label


def health_check(layout: ReleaseLayout, user: str, run=installer.run) -> bool:
    """The current release fetches and renders the calendar, as the app's
    user, without touching the panel (no flash in the middle of the night).

    Unreachable feeds or weather are logged, not failures: only a release
    that crashes or hangs fails here.
    """
    python = layout.current_link / ".venv" / "bin" / "python"
    as_user = ["runuser", "-u", user, "--"] if os.geteuid() == 0 else []
    try:
        run(as_user + [str(python), "-m", "gcal_epd.main", "--no-setup"],
            cwd=layout.current_link, timeout=HEALTH_TIMEOUT)
    except subprocess.TimeoutExpired:
        log.error("The new release did not render within %ss.", HEALTH_TIMEOUT)
        return False
    except InstallError as e:
        log.error("The new release failed to render: %s", e)
        return False
    return True


def _settings(layout: ReleaseLayout) -> updater.Settings:
    """[update] from the running release's config.toml and this display's
    config.local.toml."""
    config = load_config(str(layout.current_link / "config.toml"), data=layout.data)
    return updater.Settings.from_config(config)


def update(args, layout: ReleaseLayout, run=installer.run, fetch=updater.fetch,
           download=updater.download, now=time.time) -> str | None:
    """Install the newest release for this display's channel, if any.

    Returns the release installed (or, with args.check, the one that would
    be), None when up to date. Raises InstallError when an update failed;
    the display is then on the release it ran before.
    """
    current = layout.current()
    if current is None:
        log.info("Not installed as a release (no %s): nothing to update.",
                 layout.current_link)
        return None
    settings = _settings(layout)
    if not settings.enabled and not args.channel:
        log.info("Updates are off ([update] enabled = false).")
        return None
    channel = args.channel or settings.channel
    state = updater.State.load(layout.data)
    state.last_check = now()
    try:
        cand = updater.pick(updater.list_releases(settings.repo, fetch), channel,
                            current, state.rejected)
        if cand is None:
            state.last_result = f"up to date on {current} ({channel})"
            log.info("Up to date: %s (%s channel).", current, channel)
            return None
        log.info("%s %s is newer than %s.",
                 "Pre-release" if cand.prerelease else "Release", cand.label, current)
        if args.check:
            state.last_result = f"{cand.label} available"
            return cand.label
        label = _apply(cand, current, layout, state, run, fetch, download, now,
                       no_units=args.no_units)
        state.last_result = f"updated {current} -> {label}"
        return label
    except (InstallError, ReleaseError, OSError) as e:
        state.last_result = f"failed: {e}".splitlines()[0]
        raise
    finally:
        state.save(layout.data)


def _apply(cand, current, layout, state, run, fetch, download, now, no_units) -> str:
    for leftover in layout.base.glob(f"{DOWNLOAD_PREFIX}*"):   # a power cut mid-download
        shutil.rmtree(leftover, ignore_errors=True)
    if not updater.enough_room(layout.base):
        raise InstallError(f"Less than {updater.MIN_FREE_BYTES // 2**20} MB free "
                           f"on {layout.base}: not updating.")
    user = _app_user(SimpleNamespace(user=None), layout)
    attempts = state.attempts
    attempts[cand.label] = attempts.get(cand.label, 0) + 1
    if attempts[cand.label] >= MAX_ATTEMPTS:
        state.rejected.append(cand.label)   # the next run skips it
    with tempfile.TemporaryDirectory(dir=layout.base, prefix=DOWNLOAD_PREFIX) as tmp:
        app, wheels = updater.fetch_release(cand, Path(tmp),
                                            layout.current_link / updater.SIGNERS,
                                            fetch, download, run)
        named = Source(app).label()
        if named != cand.label:
            raise InstallError(f"{cand.tag}'s code names itself {named}: not installing.")
        install(SimpleNamespace(source=str(app), user=user, wheels=str(wheels),
                                migrate_from=None, no_units=no_units), layout, run)
    attempts.pop(cand.label, None)
    if cand.label in state.rejected:
        state.rejected.remove(cand.label)

    if health_check(layout, user, run):
        state.updated_at, state.updated_to = now(), cand.label
        log.info("Updated %s -> %s.", current, cand.label)
        return cand.label
    switch(SimpleNamespace(version=None, user=user, no_units=no_units), layout, run)
    state.rejected.append(cand.label)
    raise InstallError(f"{cand.label} failed its health check; rolled back to "
                       f"{layout.current()} and will not try it again.")


def _status(layout: ReleaseLayout) -> None:
    state = updater.State.load(layout.data)
    when = lambda t: datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M") if t else "never"
    try:
        s = _settings(layout) if layout.current() else updater.Settings()
        channel = f"{s.channel}{'' if s.enabled else ' (updates off)'}"
    except (InstallError, OSError) as e:
        channel = f"? ({e})"
    print(f"current   {layout.current() or '-'}")
    print(f"previous  {layout.previous() or '-'}")
    print(f"channel   {channel}")
    print(f"checked   {when(state.last_check)}: {state.last_result or '-'}")
    print(f"updated   {when(state.updated_at)}{' to ' + state.updated_to if state.updated_to else ''}")
    if state.rejected:
        print(f"rejected  {', '.join(state.rejected)}")


def _list(layout: ReleaseLayout) -> None:
    current, previous = layout.current(), layout.previous()
    for label in layout.labels():
        mark = " (current)" if label == current else " (previous)" if label == previous else ""
        print(f"{label}{mark}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Releases of the e-Paper calendar")
    parser.add_argument("--base", default=str(DEFAULT_BASE),
                        help=f"Where releases live (default {DEFAULT_BASE})")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("install", help="Build a release from a source and switch to it")
    p.add_argument("--source", required=True,
                   help="A git checkout (its HEAD is installed) or a release .tar")
    p.add_argument("--user", help="The user the app runs as (default: owner of "
                                  "--migrate-from, or of the data directory)")
    p.add_argument("--wheels", help="Install packages from this folder only (offline)")
    p.add_argument("--migrate-from", help="An old checkout whose feeds and settings "
                                          "to carry over (copied, never moved)")
    p.add_argument("--no-units", action="store_true",
                   help="Do not (re)install the systemd units")
    sub.add_parser("list", help="Installed releases")
    p = sub.add_parser("switch", help="Run another installed release")
    p.add_argument("version")
    rollback = sub.add_parser("rollback", help="Go back to the previous release")
    for p in (p, rollback):
        p.add_argument("--user", help="The user the app runs as (default: owner of "
                                      "the data directory)")
        p.add_argument("--no-units", action="store_true",
                       help="Do not reinstall the systemd units")
    p = sub.add_parser("update", help="Install the newest signed release from GitHub")
    p.add_argument("--channel", choices=updater.CHANNELS,
                   help="stable or beta (default: [update] channel in config.toml)")
    p.add_argument("--check", action="store_true", help="Only say whether one is available")
    p.add_argument("--no-units", action="store_true",
                   help="Do not (re)install the systemd units")
    sub.add_parser("status", help="Running release, channel, last update check")
    p = sub.add_parser("prune", help="Remove old and unfinished releases")
    p.add_argument("--keep", type=int, default=KEEP)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    layout = ReleaseLayout(Path(args.base))
    try:
        if args.command == "install":
            install(args, layout)
        elif args.command == "list":
            _list(layout)
        elif args.command == "switch":
            switch(args, layout)
        elif args.command == "rollback":
            args.version = None
            switch(args, layout)
        elif args.command == "update":
            update(args, layout)
        elif args.command == "status":
            _status(layout)
        elif args.command == "prune":
            with layout.locked():
                removed = layout.prune(args.keep)
            log.info("Removed: %s", ", ".join(removed) if removed else "nothing")
    except (InstallError, ReleaseError, subprocess.CalledProcessError, OSError) as e:
        log.error("%s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
