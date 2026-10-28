"""
Build the files a release is published as, on a Mac or in CI.

    e-pages-<label>.tar.gz                    the code, with its RELEASE file
    e-pages-<label>-wheels-<platform>.tar     every Python package, prebuilt
    e-pages-<label>-sdcard.zip                epd-bundle/ for a new card's
                                              boot partition (see deploy/sdcard/)
    SHA256SUMS                                checksums of the three above

Nothing here runs on the Pi. The wheels are downloaded for the Pi Zero's
CPU and Python (piwheels builds the ARMv6 ones), so the Pi installs them
with no network and no compiler. The .deb packages a fresh card lacks are
pinned, with their checksums, in deploy/sdcard/debs.lock.

Standard library only, plus pip for the downloads.
"""
import hashlib
import io
import logging
import gzip
import re
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from gcal_epd.config import RELEASE_MARKER
from gcal_epd.infrastructure.release.installer import (
    PI_REQUIREMENTS, InstallError, Run, Source, run as default_run)

log = logging.getLogger(__name__)

# Raspberry Pi OS Trixie on a Pi Zero (W/WH): Python 3.13, ARMv6.
PYTHON_VERSION = "3.13"
PLATFORM = "linux_armv6l"
ABI = "cp313"
# piwheels first: it has the ARMv6 builds PyPI lacks (Pillow, spidev, lgpio).
INDEXES = ["--index-url", "https://www.piwheels.org/simple",
           "--extra-index-url", "https://pypi.org/simple"]
# What pip needs to install the app itself offline (pyproject's build-system).
BUILD_REQUIREMENTS = "requirements-build.txt"

DEBS_LOCK = Path("deploy/sdcard/debs.lock")
FIRSTBOOT = Path("deploy/sdcard/firstboot.sh")
BUNDLE_DIR = "epd-bundle"
SUMS = "SHA256SUMS"

Fetch = Callable[[str], bytes]


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


@dataclass(frozen=True)
class Names:
    """What each published file of release `label` is called."""
    label: str

    @property
    def app(self) -> str:
        return f"e-pages-{self.label}.tar.gz"

    @property
    def wheels(self) -> str:
        return f"e-pages-{self.label}-wheels-{ABI}-{PLATFORM}.tar"

    @property
    def sdcard(self) -> str:
        return f"e-pages-{self.label}-sdcard.zip"


# --- the code ---------------------------------------------------------------

def app_tar(source: Source, label: str, out: Path) -> None:
    """The committed files of `source` (git archive HEAD) plus RELEASE.

    Built with tarfile, not a tar command, so no macOS extended attributes
    (and no AppleDouble ._ files) ride along. Owners are root, times are
    the commit's: the same commit gives the same files.
    """
    data = subprocess.run(["git", "-C", str(source.path), "archive", "HEAD"],
                          check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as src, \
            tarfile.open(out, "w:gz", format=tarfile.PAX_FORMAT) as dst:
        mtime = 0
        for member in src.getmembers():
            if member.name in (RELEASE_MARKER, f"./{RELEASE_MARKER}"):
                continue
            member.uid = member.gid = 0
            member.uname = member.gname = "root"
            member.pax_headers = {}
            mtime = max(mtime, member.mtime)
            dst.addfile(member, src.extractfile(member) if member.isfile() else None)
        marker = tarfile.TarInfo(RELEASE_MARKER)
        body = f"{label}\n".encode()
        marker.size, marker.mtime, marker.mode = len(body), mtime, 0o644
        marker.uname = marker.gname = "root"
        dst.addfile(marker, io.BytesIO(body))


# --- Python packages --------------------------------------------------------

def requirement_files(root: Path) -> list[Path]:
    files = [root / "requirements.txt", root / PI_REQUIREMENTS, root / BUILD_REQUIREMENTS]
    missing = [f.name for f in files if not f.is_file()]
    if missing:
        raise InstallError(f"Missing {', '.join(missing)} in {root}.")
    return files


def download_wheels(root: Path, dest: Path, run: Run = default_run,
                    python: str = sys.executable) -> list[str]:
    """Every package the Pi installs, as wheels for its CPU and Python.

    --only-binary: a source package would need a compiler on the Pi.
    Returns the wheel file names.
    """
    dest.mkdir(parents=True, exist_ok=True)
    cmd = [python, "-m", "pip", "download", "--disable-pip-version-check",
           "--no-input", "--quiet", "--dest", str(dest), "--only-binary=:all:",
           "--platform", PLATFORM, "--python-version", PYTHON_VERSION,
           "--implementation", "cp", "--abi", ABI, *INDEXES]
    for f in requirement_files(root):
        cmd += ["-r", str(f)]
    run(cmd)
    wheels = sorted(p.name for p in dest.glob("*.whl"))
    wrong = [w for w in wheels if not (w.endswith("-any.whl") or PLATFORM in w)]
    if wrong:
        raise InstallError(f"Wheels for another CPU slipped in: {', '.join(wrong)}")
    return wheels


def wheels_tar(wheels: Path, out: Path) -> None:
    """The wheels in one uncompressed tar (they are zip files already)."""
    with tarfile.open(out, "w", format=tarfile.PAX_FORMAT) as tar:
        for wheel in sorted(wheels.glob("*.whl")):
            info = tar.gettarinfo(str(wheel), arcname=f"wheels/{wheel.name}")
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            info.mode = 0o644
            with open(wheel, "rb") as f:
                tar.addfile(info, f)


# --- .deb packages a fresh card lacks ----------------------------------------

@dataclass(frozen=True)
class Deb:
    package: str
    version: str
    path: str        # in the archive's pool
    sha256: str

    @property
    def filename(self) -> str:
        return self.path.rsplit("/", 1)[-1]


@dataclass(frozen=True)
class DebsLock:
    archive: str     # e.g. http://raspbian.raspberrypi.com/raspbian
    suite: str       # e.g. trixie
    debs: list[Deb]

    @property
    def packages(self) -> list[str]:
        return [d.package for d in self.debs]


def read_debs_lock(path: Path) -> DebsLock:
    """`archive URL`, `suite NAME`, then one `package version path sha256`
    per line; # starts a comment."""
    archive = suite = None
    debs = []
    for n, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        fields = line.split()
        if fields[0] == "archive" and len(fields) == 2:
            archive = fields[1].rstrip("/")
        elif fields[0] == "suite" and len(fields) == 2:
            suite = fields[1]
        elif len(fields) == 4 and re.fullmatch(r"[0-9a-f]{64}", fields[3]):
            debs.append(Deb(*fields))
        else:
            raise InstallError(f"{path}:{n}: cannot read {raw!r}")
    if not archive or not suite:
        raise InstallError(f"{path} needs an `archive` and a `suite` line.")
    return DebsLock(archive, suite, debs)


def parse_packages_index(text: str, wanted: list[str]) -> dict[str, Deb]:
    """The entries of a Debian Packages index for the `wanted` packages."""
    found = {}
    for stanza in text.split("\n\n"):
        fields = dict(re.findall(r"^([A-Za-z0-9-]+): (.*)$", stanza, re.M))
        name = fields.get("Package")
        if name in wanted and name not in found:
            found[name] = Deb(name, fields["Version"], fields["Filename"], fields["SHA256"])
    return found


def refresh_debs_lock(path: Path, fetch: Fetch = fetch) -> DebsLock:
    """Re-pin the same packages to what the archive has now.

    The archive keeps only current versions, so an old pin stops
    downloading once a security update lands; this is the fix. Review the
    diff before committing it: these files go on every new card.
    """
    old = read_debs_lock(path)
    # .gz, not .xz: some Python builds lack lzma, every one has gzip.
    index = gzip.decompress(fetch(f"{old.archive}/dists/{old.suite}/main/binary-armhf/Packages.gz"))
    found = parse_packages_index(index.decode(), old.packages)
    missing = [p for p in old.packages if p not in found]
    if missing:
        raise InstallError(f"Not in {old.archive} {old.suite}: {', '.join(missing)}")
    new = DebsLock(old.archive, old.suite, [found[p] for p in old.packages])
    header = [l for l in path.read_text().splitlines() if l.startswith("#")]
    body = [f"archive {new.archive}", f"suite {new.suite}"]
    body += [f"{d.package} {d.version} {d.path} {d.sha256}" for d in new.debs]
    path.write_text("\n".join(header + body) + "\n")
    return new


def download_debs(lock: DebsLock, dest: Path, fetch: Fetch = fetch) -> list[str]:
    """Each pinned .deb, checked against its pinned SHA-256."""
    dest.mkdir(parents=True, exist_ok=True)
    names = []
    for deb in lock.debs:
        url = f"{lock.archive}/{deb.path}"
        try:
            data = fetch(url)
        except OSError as e:
            raise InstallError(
                f"{deb.package} {deb.version} is no longer in the archive ({e}). "
                f"Re-pin with: python -m gcal_epd.build_release --refresh-debs") from None
        if sha256(data) != deb.sha256:
            raise InstallError(f"{deb.filename}: checksum differs from {DEBS_LOCK}.")
        (dest / deb.filename).write_bytes(data)
        names.append(deb.filename)
    return names


# --- the SD card bundle and the checksums ------------------------------------

def sdcard_zip(out: Path, app: Path, wheels: Path, debs: Path, firstboot: Path) -> None:
    """epd-bundle/ as deploy/sdcard/prepare.sh copies it to a boot partition:
    app.tar.gz, wheels/, debs/, firstboot.sh."""
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(app, f"{BUNDLE_DIR}/app.tar.gz")
        z.write(firstboot, f"{BUNDLE_DIR}/firstboot.sh")
        for folder in (wheels, debs):
            for f in sorted(folder.iterdir()):
                z.write(f, f"{BUNDLE_DIR}/{folder.name}/{f.name}")


def write_sums(folder: Path, names: list[str]) -> Path:
    """SHA256SUMS in sha256sum's format, so `shasum -a 256 -c` checks it."""
    path = folder / SUMS
    path.write_text("".join(f"{file_sha256(folder / n)}  {n}\n" for n in sorted(names)))
    return path
