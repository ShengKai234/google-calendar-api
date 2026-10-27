"""
Install, list, switch and roll back releases of the app under /opt/e-pages.

Run as root, with the system python3 and the source's src/ on the path
(deploy/install-release.sh does both):

    install --source DIR|TAR [--user U] [--wheels DIR] [--migrate-from DIR]
    list
    switch VERSION
    rollback
    prune [--keep N]

`install` builds the new release beside the running one (see
infrastructure/release/), switches `current` to it only once it imports
and names itself, then points the systemd units at /opt/e-pages/current.
Standard library only, so it runs before any venv exists.
"""
import argparse
import logging
import os
import pwd
import subprocess
import sys
from pathlib import Path

from gcal_epd.infrastructure.release import installer
from gcal_epd.infrastructure.release.installer import InstallError, Source
from gcal_epd.infrastructure.release.layout import DEFAULT_BASE, ReleaseError, ReleaseLayout
from gcal_epd.infrastructure.release.migrate import migrate_checkout

log = logging.getLogger(__name__)
KEEP = 2


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
    for path in (args.migrate_from, layout.data):
        if path and Path(path).exists():
            return pwd.getpwuid(Path(path).stat().st_uid).pw_name
    raise InstallError("Say which user runs the app: --user NAME.")


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
            log.info("Pointing the systemd units at %s...", layout.current_link)
            run(["bash", str(layout.current_link / "deploy" / "install.sh"), "--yes"],
                env=installer.child_env({"EPD_USER": user}))
        removed = layout.prune(KEEP)
        if removed:
            log.info("Removed old releases: %s", ", ".join(removed))
    return label


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
    sub.add_parser("rollback", help="Go back to the previous release")
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
            with layout.locked():
                layout.switch(args.version)
            log.info("Now running %s; it takes effect at the next refresh or boot.",
                     args.version)
        elif args.command == "rollback":
            with layout.locked():
                log.info("Back to %s.", layout.rollback())
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
