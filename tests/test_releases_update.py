"""`releases update`: fetch, install, check health, roll back."""
import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from gcal_epd import releases
from gcal_epd.infrastructure.release import installer, updater
from gcal_epd.infrastructure.release.installer import InstallError
from gcal_epd.infrastructure.release.layout import ReleaseLayout
from tests.infrastructure.release.test_updater import (
    _keygen, _release, _signers, make_release)

pytestmark = pytest.mark.skipif(not shutil.which("ssh-keygen"), reason="needs ssh-keygen")
API = "https://api.github.com/repos/ShengKai234/google-calendar-api/releases?per_page=30"


class FakeRun:
    """git and ssh-keygen for real; venv, pip, install.sh and the render faked."""
    def __init__(self, healthy=True, fail_on=None):
        self.healthy, self.fail_on, self.commands = healthy, fail_on, []

    def __call__(self, cmd, **kwargs):
        self.commands.append((cmd, kwargs.get("cwd")))
        if cmd[0] in ("git", "ssh-keygen"):
            return installer.run(cmd, **kwargs)
        if self.fail_on and self.fail_on in " ".join(cmd):
            raise InstallError(f"{self.fail_on} failed")
        if "--no-setup" in cmd and not self.healthy:
            raise InstallError("Traceback: render crashed")
        out = ""
        if cmd[-1] == "--version":
            out = "gcal-epd " + (kwargs["cwd"] / "RELEASE").read_text()
        return subprocess.CompletedProcess(cmd, 0, out, "")

    def ran(self, word):
        return [c for c, _ in self.commands if word in " ".join(c)]


@pytest.fixture
def key(tmp_path):
    return _keygen(tmp_path / "release-key")


@pytest.fixture
def layout(tmp_path, key):
    """A display running 0.2.0, which trusts `key`."""
    layout = ReleaseLayout(tmp_path / "e-pages")
    release = layout.begin("0.2.0")
    (release / "config.toml").write_text("")
    (release / "deploy" / "release").mkdir(parents=True)
    _signers(release / updater.SIGNERS, key)
    layout.finish("0.2.0")
    layout.switch("0.2.0")
    layout.data.mkdir()
    return layout


def github(tmp_path, key, *releases_):
    """fetch and download serving the API listing and each release's files."""
    blobs = {API: json.dumps([_release(label, prerelease=pre) for label, pre in releases_])
             .encode()}
    for label, _ in releases_:
        blobs.update(make_release(tmp_path, label, key))

    def download(url, dest, limit):
        dest.write_bytes(blobs[url])
    return blobs.__getitem__, download


def _args(**kw):
    return SimpleNamespace(**{**dict(channel=None, check=False, no_units=False), **kw})


def update(layout, run, fetch, download, **kw):
    return releases.update(_args(**kw), layout, run, fetch, download, now=lambda: 1000.0)


def test_update_installs_the_newer_release_and_records_it(tmp_path, key, layout):
    fetch, download = github(tmp_path, key, ("0.3.0", False))
    run = FakeRun()
    assert update(layout, run, fetch, download) == "0.3.0"
    assert (layout.current(), layout.previous()) == ("0.3.0", "0.2.0")
    state = updater.State.load(layout.data)
    assert (state.updated_to, state.updated_at) == ("0.3.0", 1000.0)
    assert state.last_result == "updated 0.2.0 -> 0.3.0"
    # Health: the new release renders, from its own directory, no panel.
    (health, cwd), = [(c, w) for c, w in run.commands if "--no-setup" in c]
    assert "--display" not in health and cwd == layout.current_link
    assert not list(layout.base.glob(".download-*"))
    # Then the panel is redrawn by the new release, after the update ends.
    assert run.ran("systemctl")[-1] == ["systemctl", "start", "--no-block", "gcal-epd.service"]


def test_no_units_means_no_refresh(tmp_path, key, layout):
    fetch, download = github(tmp_path, key, ("0.3.0", False))
    run = FakeRun()
    assert update(layout, run, fetch, download, no_units=True) == "0.3.0"
    assert not run.ran("systemctl")


def test_a_download_cut_short_earlier_is_cleaned_up(tmp_path, key, layout):
    (layout.base / ".download-old").mkdir()
    (layout.base / ".download-old" / "half.tar.gz").write_bytes(b"x")
    fetch, download = github(tmp_path, key, ("0.3.0", False))
    update(layout, FakeRun(), fetch, download)
    assert not list(layout.base.glob(".download-*"))


def test_unhealthy_release_is_rolled_back_and_never_retried(tmp_path, key, layout):
    fetch, download = github(tmp_path, key, ("0.3.0", False))
    run = FakeRun(healthy=False)
    with pytest.raises(InstallError, match="health check"):
        update(layout, run, fetch, download)
    assert layout.current() == "0.2.0"
    assert not run.ran("systemctl")   # a rolled-back release draws nothing
    # The units were reinstalled from 0.2.0 by the rollback.
    assert len(run.ran("install.sh")) == 2
    state = updater.State.load(layout.data)
    assert state.rejected == ["0.3.0"]
    assert state.last_result.startswith("failed: 0.3.0 failed its health check")
    # Next run: nothing to do, 0.3.0 is not tried again.
    assert update(layout, FakeRun(), fetch, download) is None


def test_up_to_date_changes_nothing(tmp_path, key, layout):
    fetch, download = github(tmp_path, key, ("0.2.0", False))
    run = FakeRun()
    assert update(layout, run, fetch, download) is None
    assert run.commands == []
    state = updater.State.load(layout.data)
    assert (state.last_check, state.last_result) == (1000.0, "up to date on 0.2.0 (stable)")


def test_check_only_says_what_is_available(tmp_path, key, layout):
    fetch, download = github(tmp_path, key, ("0.3.0", False))
    assert update(layout, FakeRun(), fetch, download, check=True) == "0.3.0"
    assert layout.current() == "0.2.0"


def test_beta_channel_from_config_local(tmp_path, key, layout):
    (layout.data / "config.local.toml").write_text('[update]\nchannel = "beta"\n')
    fetch, download = github(tmp_path, key, ("0.3.0", True))
    assert update(layout, FakeRun(), fetch, download) == "0.3.0"


def test_stable_display_ignores_pre_releases(tmp_path, key, layout):
    fetch, download = github(tmp_path, key, ("0.3.0", True))
    assert update(layout, FakeRun(), fetch, download) is None


def test_updates_off_in_config_local(tmp_path, key, layout):
    (layout.data / "config.local.toml").write_text("[update]\nenabled = false\n")
    fetch, download = github(tmp_path, key, ("0.3.0", False))
    assert update(layout, FakeRun(), fetch, download) is None
    # --channel on the command line still updates by hand.
    assert update(layout, FakeRun(), fetch, download, channel="stable") == "0.3.0"


def test_release_signed_by_an_untrusted_key_is_not_installed(tmp_path, key, layout):
    stranger = _keygen(tmp_path / "stranger")
    fetch, download = github(tmp_path, stranger, ("0.3.0", False))
    run = FakeRun()
    with pytest.raises(InstallError, match="NOT signed"):
        update(layout, run, fetch, download)
    assert layout.current() == "0.2.0"
    assert not run.ran("pip")
    assert updater.State.load(layout.data).last_result.startswith("failed:")


def test_code_that_names_another_version_is_not_installed(tmp_path, key, layout):
    fetch, download = github(tmp_path, key, ("0.3.0", False))
    # Re-sign a listing that calls 0.3.0's files 0.4.0's.
    blobs = {u.replace("0.3.0", "0.4.0"): fetch(u) for u in
             [f"https://dl/0.3.0/{n}" for n in (updater.Names("0.3.0").app,
                                                  updater.Names("0.3.0").wheels,
                                                  updater.SUMS, updater.SIGNATURE)]}
    names = updater.Names("0.4.0")
    sums = blobs[f"https://dl/0.4.0/{updater.SUMS}"].decode().replace("0.3.0", "0.4.0")
    sums_path = tmp_path / "sums-0.4.0"
    sums_path.write_text(sums)
    subprocess.run(["ssh-keygen", "-Y", "sign", "-q", "-f", str(key), "-n", updater.NAMESPACE,
                    str(sums_path)], check=True, capture_output=True)
    blobs[f"https://dl/0.4.0/{updater.SUMS}"] = sums.encode()
    blobs[f"https://dl/0.4.0/{updater.SIGNATURE}"] = (tmp_path / "sums-0.4.0.sig").read_bytes()
    blobs[API] = json.dumps([_release("0.4.0")]).encode()
    assert names.app in sums
    with pytest.raises(InstallError, match="names itself 0.3.0"):
        update(layout, FakeRun(), blobs.__getitem__,
               lambda url, dest, limit: dest.write_bytes(blobs[url]))
    assert layout.current() == "0.2.0"


def test_a_release_that_never_builds_is_given_up_after_three_tries(tmp_path, key, layout):
    fetch, download = github(tmp_path, key, ("0.3.0", False))
    for _ in range(releases.MAX_ATTEMPTS):
        with pytest.raises(InstallError):
            update(layout, FakeRun(fail_on="pip"), fetch, download)
    assert updater.State.load(layout.data).rejected == ["0.3.0"]
    assert update(layout, FakeRun(), fetch, download) is None


def test_a_checkout_is_not_updated(tmp_path):
    layout = ReleaseLayout(tmp_path / "nothing")
    assert releases.update(_args(), layout, FakeRun(), lambda u: b"[]") is None


def test_status_shows_the_state(tmp_path, key, layout, capsys):
    updater.State(last_check=0.0, rejected=["0.3.0"]).save(layout.data)
    releases._status(layout)
    out = capsys.readouterr().out
    assert "current   0.2.0" in out
    assert "channel   stable" in out
    assert "rejected  0.3.0" in out


# --- an update stopped by its time limit (epd-update.service TimeoutStartSec)
class StoppedRun(FakeRun):
    """systemd's SIGTERM, which releases turns into Terminated, arrives the
    first time a command containing `word` runs."""
    def __init__(self, word, **kw):
        super().__init__(**kw)
        self.word, self.stopped = word, False

    def __call__(self, cmd, **kwargs):
        if not self.stopped and self.word in " ".join(map(str, cmd)):
            self.stopped = True
            self.commands.append((cmd, kwargs.get("cwd")))
            raise releases.Terminated()
        return super().__call__(cmd, **kwargs)


def test_update_stopped_during_the_build_keeps_the_old_release(tmp_path, key, layout):
    fetch, download = github(tmp_path, key, ("0.3.0", False))
    with pytest.raises(releases.Terminated):
        update(layout, StoppedRun("pip"), fetch, download)
    assert layout.current() == "0.2.0"
    assert not layout.is_complete("0.3.0")
    assert not list(layout.base.glob(".download-*"))
    state = updater.State.load(layout.data)
    assert state.attempts == {"0.3.0": 1}                 # one failure
    assert state.last_result.startswith("stopped")


@pytest.mark.parametrize("word", ["install.sh", "--no-setup"])
def test_update_stopped_after_the_switch_goes_back(tmp_path, key, layout, word):
    """Stopped while the units are installed or the new release renders:
    the Pi is put back on the release it was running, units included."""
    fetch, download = github(tmp_path, key, ("0.3.0", False))
    units_for = []

    class Watch(StoppedRun):
        def __call__(self, cmd, **kwargs):
            if "install.sh" in " ".join(map(str, cmd)):
                units_for.append(layout.current())
            return super().__call__(cmd, **kwargs)
    run = Watch(word)
    with pytest.raises(releases.Terminated):
        update(layout, run, fetch, download)
    assert layout.current() == "0.2.0"
    assert units_for[0] == "0.3.0" and units_for[-1] == "0.2.0"   # units went back too
    assert not run.ran("systemctl")         # no refresh started by a stopped update
    assert updater.State.load(layout.data).attempts == {"0.3.0": 1}


def test_the_attempt_is_on_disk_before_the_build(tmp_path, key, layout):
    """A SIGKILL leaves no time to save: the failure must already be counted."""
    fetch, download = github(tmp_path, key, ("0.3.0", False))
    seen = []

    class Peek(FakeRun):
        def __call__(self, cmd, **kwargs):
            if "venv" in cmd:
                seen.append(updater.State.load(layout.data).attempts.get("0.3.0"))
            return super().__call__(cmd, **kwargs)
    update(layout, Peek(), fetch, download)
    assert seen == [1]


def test_a_release_stopped_every_time_is_given_up(tmp_path, key, layout):
    fetch, download = github(tmp_path, key, ("0.3.0", False))
    for _ in range(releases.MAX_ATTEMPTS):
        with pytest.raises(releases.Terminated):
            update(layout, StoppedRun("pip"), fetch, download)
    assert "0.3.0" in updater.State.load(layout.data).rejected
    assert update(layout, FakeRun(), fetch, download) is None
    assert layout.current() == "0.2.0"


def test_leftovers_are_cleaned_before_every_check(tmp_path, key, layout):
    """A build or download cut short by a timeout or a power cut goes, even
    when there is nothing new to install."""
    (layout.base / ".download-old").mkdir()
    half = layout.begin("0.9.9")            # INCOMPLETE
    (half / "junk").write_text("x")
    fetch, download = github(tmp_path, key, ("0.2.0", False))
    assert update(layout, FakeRun(), fetch, download) is None
    assert not (layout.base / ".download-old").exists()
    assert not half.exists()
    assert layout.current() == "0.2.0" and layout.is_complete("0.2.0")


def test_sigterm_becomes_terminated(monkeypatch):
    import signal
    handlers = {}
    monkeypatch.setattr(signal, "signal", lambda sig, h: handlers.__setitem__(sig, h))
    releases._stop_on_sigterm()
    with pytest.raises(releases.Terminated):
        handlers[signal.SIGTERM](signal.SIGTERM, None)
