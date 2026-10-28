"""The release's published files: code tar, wheels, pinned .debs, SD bundle."""
import gzip
import hashlib
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

from gcal_epd.config import PROJECT_ROOT
from gcal_epd.infrastructure.release import artifacts
from gcal_epd.infrastructure.release.installer import InstallError, Source


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    repo = tmp_path / "checkout"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0.2.0"\n')
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("print('hi')\n")
    (repo / ".gitignore").write_text("ics_feeds.toml\n")
    (repo / "ics_feeds.toml").write_text('[[feed]]\nurl = "https://secret.example/t"\n')
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    return repo


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --- names -----------------------------------------------------------------

def test_names_carry_the_label_and_the_platform():
    n = artifacts.Names("0.2.0")
    assert n.app == "e-pages-0.2.0.tar.gz"
    assert n.wheels == "e-pages-0.2.0-wheels-cp313-linux_armv6l.tar"
    assert n.sdcard == "e-pages-0.2.0-sdcard.zip"


# --- the code tar -----------------------------------------------------------

def test_app_tar_has_the_committed_files_and_release(repo, tmp_path):
    out = tmp_path / "app.tar.gz"
    artifacts.app_tar(Source(repo), "0.2.0", out)
    with tarfile.open(out) as tar:
        names = tar.getnames()
        assert tar.extractfile("RELEASE").read() == b"0.2.0\n"
        assert {m.uname for m in tar.getmembers()} == {"root"}
    assert "src/app.py" in names
    assert "ics_feeds.toml" not in names   # gitignored secrets never ride along


def test_app_tar_installs_with_the_release_label(repo, tmp_path):
    out = tmp_path / "app.tar.gz"
    artifacts.app_tar(Source(repo), "0.2.0+gabc1234", out)
    assert Source(out).label() == "0.2.0+gabc1234"


def test_app_tar_is_the_same_for_the_same_commit(repo, tmp_path):
    a, b = tmp_path / "a.tar.gz", tmp_path / "b.tar.gz"
    artifacts.app_tar(Source(repo), "0.2.0", a)
    artifacts.app_tar(Source(repo), "0.2.0", b)
    assert gzip.decompress(a.read_bytes()) == gzip.decompress(b.read_bytes())


# --- wheels -----------------------------------------------------------------

def _reqs(root: Path):
    for name in ("requirements.txt", "requirements-pi.txt", "requirements-build.txt"):
        (root / name).write_text("")


def test_wheels_are_downloaded_for_the_pi_zero(tmp_path):
    _reqs(tmp_path)
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        dest = Path(cmd[cmd.index("--dest") + 1])
        (dest / "pillow-12.2.0-cp313-cp313-linux_armv6l.whl").write_bytes(b"w")
        (dest / "six-1.17.0-py2.py3-none-any.whl").write_bytes(b"w")

    wheels = artifacts.download_wheels(tmp_path, tmp_path / "w", run=run, python="py")
    cmd = calls[0]
    assert cmd[cmd.index("--platform") + 1] == "linux_armv6l"
    assert cmd[cmd.index("--python-version") + 1] == "3.13"
    assert "--only-binary=:all:" in cmd
    assert cmd.count("-r") == 3
    assert wheels == ["pillow-12.2.0-cp313-cp313-linux_armv6l.whl",
                      "six-1.17.0-py2.py3-none-any.whl"]


def test_a_wheel_for_another_cpu_is_refused(tmp_path):
    # An ARMv7 wheel crashes a Pi Zero with "Illegal instruction".
    _reqs(tmp_path)

    def run(cmd, **kw):
        dest = Path(cmd[cmd.index("--dest") + 1])
        (dest / "pillow-12.2.0-cp313-cp313-linux_armv7l.whl").write_bytes(b"w")

    with pytest.raises(InstallError, match="armv7l"):
        artifacts.download_wheels(tmp_path, tmp_path / "w", run=run)


def test_missing_requirements_file_is_named(tmp_path):
    (tmp_path / "requirements.txt").write_text("")
    with pytest.raises(InstallError, match="requirements-pi.txt"):
        artifacts.download_wheels(tmp_path, tmp_path / "w", run=lambda *a, **k: None)


def test_wheels_tar_holds_them_under_wheels(tmp_path):
    w = tmp_path / "w"
    w.mkdir()
    (w / "a-1-py3-none-any.whl").write_bytes(b"a")
    artifacts.wheels_tar(w, tmp_path / "w.tar")
    with tarfile.open(tmp_path / "w.tar") as tar:
        assert tar.getnames() == ["wheels/a-1-py3-none-any.whl"]


# --- pinned .debs -----------------------------------------------------------

LOCK = """# comment
archive http://archive.example/raspbian/
suite trixie
watchdog 5.16-1.1 pool/main/w/watchdog/watchdog_5.16-1.1_armhf.deb {sha}
"""


def _lock(tmp_path, sha="0" * 64):
    path = tmp_path / "debs.lock"
    path.write_text(LOCK.format(sha=sha))
    return path


def test_lock_is_read(tmp_path):
    lock = artifacts.read_debs_lock(_lock(tmp_path))
    assert lock.archive == "http://archive.example/raspbian"
    assert lock.suite == "trixie"
    assert lock.debs[0].filename == "watchdog_5.16-1.1_armhf.deb"


def test_bad_lock_line_is_reported_with_its_number(tmp_path):
    path = _lock(tmp_path)
    path.write_text(path.read_text() + "watchdog 5.16\n")
    with pytest.raises(InstallError, match=":5:"):
        artifacts.read_debs_lock(path)


def test_committed_lock_reads_and_bundle_script_exists():
    lock = artifacts.read_debs_lock(PROJECT_ROOT / artifacts.DEBS_LOCK)
    assert "watchdog" in lock.packages and "libfreetype6" in lock.packages
    assert (PROJECT_ROOT / artifacts.FIRSTBOOT).is_file()


def test_debs_are_checked_against_the_lock(tmp_path):
    data = b"deb file"
    lock = artifacts.read_debs_lock(_lock(tmp_path, _sha(data)))
    urls = []
    names = artifacts.download_debs(lock, tmp_path / "d",
                                    fetch=lambda u: urls.append(u) or data)
    assert urls == ["http://archive.example/raspbian/pool/main/w/watchdog/"
                    "watchdog_5.16-1.1_armhf.deb"]
    assert (tmp_path / "d" / names[0]).read_bytes() == data


def test_deb_with_another_checksum_is_refused(tmp_path):
    lock = artifacts.read_debs_lock(_lock(tmp_path, _sha(b"expected")))
    with pytest.raises(InstallError, match="checksum"):
        artifacts.download_debs(lock, tmp_path / "d", fetch=lambda u: b"tampered")


def test_deb_gone_from_the_archive_says_how_to_repin(tmp_path):
    lock = artifacts.read_debs_lock(_lock(tmp_path))

    def gone(url):
        raise OSError("HTTP Error 404")
    with pytest.raises(InstallError, match="--refresh-debs"):
        artifacts.download_debs(lock, tmp_path / "d", fetch=gone)


INDEX = """Package: watchdog
Version: 5.17-1
Filename: pool/main/w/watchdog/watchdog_5.17-1_armhf.deb
SHA256: {sha}

Package: other
Version: 1
Filename: pool/o.deb
SHA256: {sha}
"""


def test_refresh_repins_the_same_packages_and_keeps_comments(tmp_path):
    path = _lock(tmp_path)
    index = gzip.compress(INDEX.format(sha="a" * 64).encode())
    urls = []
    lock = artifacts.refresh_debs_lock(path, fetch=lambda u: urls.append(u) or index)
    assert urls == ["http://archive.example/raspbian/dists/trixie/main/binary-armhf/Packages.gz"]
    assert lock.packages == ["watchdog"]
    text = path.read_text()
    assert text.startswith("# comment\n")
    assert f"watchdog 5.17-1 pool/main/w/watchdog/watchdog_5.17-1_armhf.deb {'a' * 64}" in text
    assert artifacts.read_debs_lock(path) == lock


def test_refresh_names_a_package_the_archive_lacks(tmp_path):
    path = _lock(tmp_path)
    index = gzip.compress(b"Package: other\nVersion: 1\nFilename: o\nSHA256: x\n")
    with pytest.raises(InstallError, match="watchdog"):
        artifacts.refresh_debs_lock(path, fetch=lambda u: index)


# --- SD card bundle and checksums ----------------------------------------------

def test_sdcard_zip_is_one_epd_bundle_folder(tmp_path):
    app = tmp_path / "x.tar.gz"
    app.write_bytes(b"code")
    fb = tmp_path / "firstboot.sh"
    fb.write_text("#!/bin/bash\n")
    for folder, name in (("wheels", "a.whl"), ("debs", "b.deb")):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / name).write_bytes(b"x")
    out = tmp_path / "s.zip"
    artifacts.sdcard_zip(out, app, tmp_path / "wheels", tmp_path / "debs", fb)
    with zipfile.ZipFile(out) as z:
        assert sorted(z.namelist()) == ["epd-bundle/app.tar.gz", "epd-bundle/debs/b.deb",
                                        "epd-bundle/firstboot.sh", "epd-bundle/wheels/a.whl"]


def test_sums_are_in_sha256sum_format(tmp_path):
    (tmp_path / "b").write_bytes(b"bee")
    (tmp_path / "a").write_bytes(b"ay")
    path = artifacts.write_sums(tmp_path, ["b", "a"])
    assert path.read_text() == f"{_sha(b'ay')}  a\n{_sha(b'bee')}  b\n"
