"""
Build a release's published files from a git checkout's HEAD.

    python -m gcal_epd.build_release                 # into dist/<label>/
    python -m gcal_epd.build_release --out DIR
    python -m gcal_epd.build_release --refresh-debs  # re-pin deploy/sdcard/debs.lock

Run by .github/workflows/release.yml on a v* tag, and on a Mac to make a
card from code that is not released yet (deploy/sdcard/prepare.sh --bundle).
Needs the network: piwheels, PyPI and the Raspberry Pi OS archive.
See docs/DEPLOYMENT.md.
"""
import argparse
import logging
import subprocess
import sys
import tempfile
from pathlib import Path

from gcal_epd.config import PROJECT_ROOT
from gcal_epd.infrastructure.release import artifacts
from gcal_epd.infrastructure.release.installer import InstallError, Source

log = logging.getLogger(__name__)


def build(source: Source, out: Path | None = None) -> Path:
    """All published files of `source`'s HEAD; returns the folder they are in."""
    label = source.label()
    if source.uncommitted():
        log.warning("Uncommitted changes in %s are NOT in the release (only HEAD is).",
                    source.path)
    names = artifacts.Names(label)
    out = (out or source.path / "dist" / label).resolve()
    out.mkdir(parents=True, exist_ok=True)
    log.info("Release %s -> %s", label, out)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        log.info("Code...")
        app = out / names.app
        artifacts.app_tar(source, label, app)
        # Requirements, debs.lock and firstboot.sh as committed, not as edited.
        code = tmp / "code"
        code.mkdir()
        Source(app).extract(code)

        log.info("Python packages for %s, Python %s...",
                 artifacts.PLATFORM, artifacts.PYTHON_VERSION)
        wheels = tmp / "wheels"
        for name in artifacts.download_wheels(code, wheels):
            log.info("  %s", name)
        artifacts.wheels_tar(wheels, out / names.wheels)

        lock = artifacts.read_debs_lock(code / artifacts.DEBS_LOCK)
        log.info("System packages a new card lacks, from %s %s...", lock.archive, lock.suite)
        debs = tmp / "debs"
        for name in artifacts.download_debs(lock, debs):
            log.info("  %s", name)

        log.info("SD card bundle...")
        artifacts.sdcard_zip(out / names.sdcard, app, wheels, debs,
                             code / artifacts.FIRSTBOOT)

    artifacts.write_sums(out, [names.app, names.wheels, names.sdcard])
    for f in sorted(out.iterdir()):
        log.info("  %-48s %6.1f MB", f.name, f.stat().st_size / 1e6)
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build the e-Paper calendar's release files")
    parser.add_argument("--source", default=str(PROJECT_ROOT),
                        help="A git checkout; its HEAD is built (default: this one)")
    parser.add_argument("--out", help="Where the files go (default: <source>/dist/<label>)")
    parser.add_argument("--refresh-debs", action="store_true",
                        help="Re-pin deploy/sdcard/debs.lock to the archive's current "
                             "versions, then stop")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    source = Source(Path(args.source).resolve())
    try:
        if args.refresh_debs:
            lock = artifacts.refresh_debs_lock(source.path / artifacts.DEBS_LOCK)
            for deb in lock.debs:
                log.info("%s %s", deb.package, deb.version)
            log.info("Review and commit %s.", artifacts.DEBS_LOCK)
        else:
            out = build(source, Path(args.out) if args.out else None)
            print(out)
    except (InstallError, subprocess.CalledProcessError, OSError) as e:
        log.error("%s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
