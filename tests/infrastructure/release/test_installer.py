"""Building a release: its name, its code, its venv and its smoke test."""
import io
import subprocess
import tarfile
from pathlib import Path

import pytest

from gcal_epd.infrastructure.release import installer
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
    (repo / "app.py").write_text("print('hi')\n")
    (repo / ".gitignore").write_text("ics_feeds.toml\n")
    (repo / "ics_feeds.toml").write_text('[[feed]]\nurl = "https://secret.example/t"\n')
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    return repo


def _tar(tmp_path, files: dict, name="r.tar"):
    path = tmp_path / name
    with tarfile.open(path, "w") as tar:
        for member, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(member)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


# --- naming ----------------------------------------------------------------

def test_untagged_commit_gets_its_hash(repo):
    label = Source(repo).label()
    commit = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short=7", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    assert label == f"0.2.0+g{commit}"


def test_tagged_commit_is_the_plain_version(repo):
    _git(repo, "tag", "v0.2.0")
    assert Source(repo).label() == "0.2.0"


def test_tag_for_another_version_does_not_count(repo):
    _git(repo, "tag", "v0.1.0")
    assert Source(repo).label().startswith("0.2.0+g")


def test_version_comes_from_the_commit_not_the_working_tree(repo):
    (repo / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "9.9.9"\n')
    assert Source(repo).label().startswith("0.2.0+g")
    assert Source(repo).uncommitted()


def test_clean_checkout_has_nothing_uncommitted(repo):
    assert not Source(repo).uncommitted()


def test_tar_named_by_its_release_file(tmp_path):
    tar = _tar(tmp_path, {"RELEASE": "0.3.0\n", "pyproject.toml": "x"})
    assert Source(tar).label() == "0.3.0"


def test_tar_without_release_file_uses_pyproject(tmp_path):
    tar = _tar(tmp_path, {"./pyproject.toml": '[project]\nversion = "0.3.1"\n'})
    assert Source(tar).label() == "0.3.1"


def test_tar_with_neither_is_refused(tmp_path):
    with pytest.raises(InstallError):
        Source(_tar(tmp_path, {"app.py": ""})).label()


# --- copying the code ------------------------------------------------------

def test_git_source_copies_only_committed_files(repo, tmp_path):
    (repo / "app.py").write_text("print('not committed')\n")
    dest = tmp_path / "release"
    dest.mkdir()
    Source(repo).extract(dest)
    assert (dest / "app.py").read_text() == "print('hi')\n"
    assert not (dest / "ics_feeds.toml").exists()    # gitignored secret
    assert not (dest / ".git").exists()


def test_tar_source_is_extracted(tmp_path):
    dest = tmp_path / "release"
    dest.mkdir()
    Source(_tar(tmp_path, {"src/a.py": "x = 1\n"})).extract(dest)
    assert (dest / "src" / "a.py").read_text() == "x = 1\n"


@pytest.mark.parametrize("member", ["../escape.txt", "/etc/escape.txt", "a/../../x"])
def test_tar_cannot_write_outside_the_release(tmp_path, member):
    dest = tmp_path / "release"
    dest.mkdir()
    with pytest.raises(InstallError):
        Source(_tar(tmp_path, {member: "x"})).extract(dest)
    assert not (tmp_path / "escape.txt").exists()


def test_tar_link_outside_the_release_is_refused(tmp_path):
    path = tmp_path / "r.tar"
    with tarfile.open(path, "w") as tar:
        info = tarfile.TarInfo("evil")
        info.type, info.linkname = tarfile.SYMTYPE, "/etc/passwd"
        tar.addfile(info)
    dest = tmp_path / "release"
    dest.mkdir()
    with pytest.raises(InstallError):
        Source(path).extract(dest)


def test_tar_device_file_is_refused(tmp_path):
    path = tmp_path / "r.tar"
    with tarfile.open(path, "w") as tar:
        info = tarfile.TarInfo("dev")
        info.type = tarfile.CHRTYPE
        tar.addfile(info)
    dest = tmp_path / "release"
    dest.mkdir()
    with pytest.raises(InstallError):
        Source(path).extract(dest)


# --- venv and smoke test -----------------------------------------------------

class FakeRun:
    def __init__(self, stdout=""):
        self.calls, self.stdout = [], stdout

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, self.stdout, "")


def _release(tmp_path, pi_reqs=True):
    release = tmp_path / "releases" / "0.2.0"
    release.mkdir(parents=True)
    (release / "requirements.txt").write_text("pillow==1\n")
    if pi_reqs:
        (release / "requirements-pi.txt").write_text("spidev==1\n")
    return release


def test_venv_from_the_bundled_wheels_only(tmp_path):
    release, run = _release(tmp_path), FakeRun()
    wheels = tmp_path / "wheels"
    installer.build_venv(release, wheels, on_pi=True, run=run)
    cmds = [c for c, _ in run.calls]
    assert cmds[0] == ["python3", "-m", "venv", str(release / ".venv")]
    reqs = cmds[1]
    assert ["--no-index", "--find-links", str(wheels)] == reqs[reqs.index("--no-index"):][:3]
    assert str(release / "requirements.txt") in reqs
    assert str(release / "requirements-pi.txt") in reqs
    app = cmds[2]
    assert app[-3:] == ["--no-deps", "-e", str(release)]
    assert "--no-index" in app
    assert cmds[3][1:4] == ["-m", "compileall", "-q"]


def test_venv_off_the_pi_skips_the_panel_driver(tmp_path):
    release, run = _release(tmp_path), FakeRun()
    installer.build_venv(release, None, on_pi=False, run=run)
    reqs = run.calls[1][0]
    assert str(release / "requirements-pi.txt") not in reqs
    assert "--no-index" not in reqs


def test_smoke_test_imports_the_app_and_checks_its_name(tmp_path):
    release, run = _release(tmp_path), FakeRun(stdout="gcal-epd 0.2.0\n")
    installer.smoke_test(release, "0.2.0", tmp_path / "data", on_pi=True, run=run)
    (imports, kw), (version, _) = run.calls
    assert "gcal_epd.main" in imports[-1] and "spidev" in imports[-1]
    assert kw["env"]["EPD_DATA_DIR"] == str(tmp_path / "data")
    assert kw["cwd"] == release
    assert version[-3:] == ["-m", "gcal_epd.main", "--version"]


def test_smoke_test_fails_on_the_wrong_name(tmp_path):
    release, run = _release(tmp_path), FakeRun(stdout="gcal-epd 0.1.0\n")
    with pytest.raises(InstallError, match="0.1.0"):
        installer.smoke_test(release, "0.2.0", tmp_path, on_pi=False, run=run)


def test_failed_command_raises_with_its_output():
    with pytest.raises(InstallError, match="boom"):
        installer.run(["python3", "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"])


def test_missing_command_raises():
    with pytest.raises(InstallError):
        installer.run(["no-such-command-here"])


def test_pi_detected_from_the_device_tree(tmp_path):
    model = tmp_path / "model"
    model.write_text("Raspberry Pi Zero W Rev 1.1\x00")
    assert installer.on_raspberry_pi(model)
    model.write_text("Some other board")
    assert not installer.on_raspberry_pi(model)
    assert not installer.on_raspberry_pi(tmp_path / "missing")


def test_pi_requirements_are_pinned():
    root = Path(__file__).parents[3]
    lines = [l for l in (root / "requirements-pi.txt").read_text().splitlines()
             if l and not l.startswith("#")]
    assert {l.split("==")[0] for l in lines} >= {"spidev", "gpiozero", "lgpio"}
    assert all("==" in l for l in lines)


def test_commands_do_not_inherit_pythonpath(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/somewhere/src")
    monkeypatch.setenv("PYTHONHOME", "/somewhere")
    out = installer.run(["/bin/sh", "-c", 'echo "${PYTHONPATH-unset} ${PYTHONHOME-unset}"']).stdout
    assert out.strip() == "unset unset"
    assert installer.child_env({"A": "1"})["A"] == "1"


def test_install_sh_ignores_an_inherited_pythonpath():
    script = (Path(__file__).parents[3] / "deploy" / "install.sh").read_text()
    unset = script.index("unset PYTHONPATH PYTHONHOME")
    assert unset < script.index('"$PYTHON" -c')
