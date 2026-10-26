"""`python -m gcal_epd.releases`: install beside the running release, then switch."""
import getpass
import subprocess
from types import SimpleNamespace

import pytest

from gcal_epd import releases
from gcal_epd.infrastructure.release import installer
from gcal_epd.infrastructure.release.installer import InstallError
from gcal_epd.infrastructure.release.layout import ReleaseLayout


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path):
    repo = tmp_path / "checkout"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0.2.0"\n')
    (repo / "config.toml").write_text('[[sources]]\ntype = "ics"\n')
    (repo / "requirements.txt").write_text("")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    _git(repo, "tag", "v0.2.0")
    return repo


class FakeRun:
    """Runs git for real; pretends pip, venv and install.sh succeed."""
    def __init__(self, layout, fail_on=None):
        self.layout, self.fail_on, self.commands = layout, fail_on, []

    def __call__(self, cmd, **kwargs):
        self.commands.append(cmd)
        if cmd[0] == "git":
            return installer.run(cmd, **kwargs)
        if self.fail_on and self.fail_on in " ".join(cmd):
            raise InstallError(f"{self.fail_on} failed")
        out = ""
        if cmd[-1] == "--version":
            out = "gcal-epd " + (kwargs["cwd"] / "RELEASE").read_text()
        return subprocess.CompletedProcess(cmd, 0, out, "")


def _args(repo, **kw):
    base = dict(source=str(repo), user=getpass.getuser(), wheels=None,
                migrate_from=None, no_units=False)
    return SimpleNamespace(**{**base, **kw})


def test_install_builds_switches_and_points_the_units(repo, tmp_path):
    layout = ReleaseLayout(tmp_path / "e-pages")
    run = FakeRun(layout)
    assert releases.install(_args(repo), layout, run) == "0.2.0"
    assert layout.current() == "0.2.0"
    assert layout.is_complete("0.2.0")
    assert (layout.current_link / "config.toml").is_file()
    assert run.commands[-1] == ["bash", str(layout.current_link / "deploy" / "install.sh"),
                                "--yes"]
    assert (layout.data.stat().st_mode & 0o777) == 0o700


def test_failed_build_leaves_the_running_release_alone(repo, tmp_path):
    layout = ReleaseLayout(tmp_path / "e-pages")
    releases.install(_args(repo), layout, FakeRun(layout))
    (repo / "app.py").write_text("x\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "next")
    with pytest.raises(InstallError):
        releases.install(_args(repo), layout, FakeRun(layout, fail_on="pip"))
    assert layout.current() == "0.2.0"
    assert layout.labels() == ["0.2.0"]


def test_failed_smoke_test_does_not_switch(repo, tmp_path):
    layout = ReleaseLayout(tmp_path / "e-pages")
    with pytest.raises(InstallError):
        releases.install(_args(repo), layout, FakeRun(layout, fail_on="import"))
    assert layout.current() is None


def test_migrate_carries_the_checkout_feeds_over(repo, tmp_path):
    (repo / "ics_feeds.toml").write_text("secret")   # untracked, as on a Pi
    layout = ReleaseLayout(tmp_path / "e-pages")
    releases.install(_args(repo, migrate_from=str(repo)), layout, FakeRun(layout))
    assert (layout.data / "ics_feeds.toml").read_text() == "secret"
    assert not (layout.current_link / "ics_feeds.toml").exists()


def test_installing_an_installed_release_switches_back_to_it(repo, tmp_path):
    layout = ReleaseLayout(tmp_path / "e-pages")
    releases.install(_args(repo), layout, FakeRun(layout))
    layout.begin("0.3.0")
    layout.finish("0.3.0")
    layout.switch("0.3.0")
    run = FakeRun(layout)
    assert releases.install(_args(repo), layout, run) == "0.2.0"
    assert layout.current() == "0.2.0"
    assert not any("pip" in " ".join(c) or "venv" in c for c in run.commands)


def test_no_units_skips_install_sh(repo, tmp_path):
    layout = ReleaseLayout(tmp_path / "e-pages")
    run = FakeRun(layout)
    releases.install(_args(repo, no_units=True), layout, run)
    assert not any(c[0] == "bash" for c in run.commands)


def test_unknown_user_is_refused_before_building(repo, tmp_path):
    layout = ReleaseLayout(tmp_path / "e-pages")
    with pytest.raises(InstallError, match="no user"):
        releases.install(_args(repo, user="no-such-user-xyz"), layout, FakeRun(layout))
    assert layout.labels() == []


def test_cli_switch_rollback_and_list(repo, tmp_path, capsys):
    layout = ReleaseLayout(tmp_path / "e-pages")
    for label in ("0.2.0", "0.3.0"):
        layout.begin(label)
        layout.finish(label)
    base = ["--base", str(layout.base)]
    assert releases.main(base + ["switch", "0.2.0"]) == 0
    assert releases.main(base + ["switch", "0.3.0"]) == 0
    assert releases.main(base + ["list"]) == 0
    assert capsys.readouterr().out.splitlines() == ["0.2.0 (previous)", "0.3.0 (current)"]
    assert releases.main(base + ["rollback"]) == 0
    assert layout.current() == "0.2.0"


def test_cli_reports_errors_without_a_traceback(tmp_path):
    assert releases.main(["--base", str(tmp_path), "switch", "9.9.9"]) == 1
    assert releases.main(["--base", str(tmp_path), "rollback"]) == 1
