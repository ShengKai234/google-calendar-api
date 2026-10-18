"""Tests for the calendar setup flow, with the form and panel faked."""
import stat
import tomllib

from gcal_epd.application import setup_service
from gcal_epd.application.setup_service import apply_pending_feeds
from gcal_epd.infrastructure.feeds_file import write_feeds_file, write_pending_feeds


class FakeServer:
    url = "http://192.168.0.5:8080"
    pin = "123456"

    def __init__(self, feeds_path, saves=True, notice=""):
        self.feeds_path = feeds_path
        self.saves = saves
        self.notice = notice

    def serve_until_configured(self):
        return self.saves


def _run(monkeypatch, saves, push_display=True, error=""):
    screens, servers = [], []

    def make(path, notice=""):
        servers.append(FakeServer(path, saves, notice))
        return servers[-1]

    monkeypatch.setattr(setup_service, "FeedSetupServer", make)
    monkeypatch.setattr(setup_service, "push_setup_screen",
                        lambda config, kind, **kw: screens.append((kind, kw)))
    saved = setup_service.run_onboarding({}, push_display=push_display, error=error)
    _run.server = servers[0]
    return saved, screens


def test_saved_shows_setup_then_success(monkeypatch):
    saved, screens = _run(monkeypatch, saves=True)
    assert saved is True
    assert screens[0] == ("setup", {"url": FakeServer.url, "pin": FakeServer.pin, "error": ""})
    assert screens[1][0] == "success"


def test_reopened_setup_shows_why_on_panel_and_form(monkeypatch):
    why = "The link at h.example is not a calendar (iCal) file."
    _, screens = _run(monkeypatch, saves=False, error=why)
    assert screens[0][1]["error"] == why
    assert _run.server.notice == why


def test_window_closed_leaves_setup_screen(monkeypatch):
    saved, screens = _run(monkeypatch, saves=False)
    assert saved is False
    assert [k for k, _ in screens] == ["setup"]


def test_no_panel_no_screens(monkeypatch):
    _, screens = _run(monkeypatch, saves=True, push_display=False)
    assert screens == []


def test_push_setup_screen_never_raises(monkeypatch):
    """No panel attached (e.g. on a laptop) must not abort setup."""
    import gcal_epd.epd as epd
    monkeypatch.setattr(epd, "push_to_display",
                        lambda img: (_ for _ in ()).throw(RuntimeError("no panel")))
    setup_service.push_setup_screen({}, "setup", url="http://x", pin="1")


# --- links parked by the Wi-Fi form ---

def test_apply_pending_saves_feeds_when_all_work(tmp_path):
    pending, feeds = tmp_path / "p.toml", tmp_path / "ics_feeds.toml"
    write_pending_feeds(pending, ["https://h/a.ics", "https://h/b.ics"])
    assert apply_pending_feeds(pending, feeds, check=lambda u: "") == ""
    saved = [f["url"] for f in tomllib.load(open(feeds, "rb"))["feed"]]
    assert saved == ["https://h/a.ics", "https://h/b.ics"]
    assert stat.S_IMODE(feeds.stat().st_mode) == 0o600
    assert not pending.exists()

def test_apply_pending_failure_keeps_old_feeds_and_drops_pending(tmp_path):
    """A broken link must not be retried every boot, nor replace working feeds."""
    pending, feeds = tmp_path / "p.toml", tmp_path / "ics_feeds.toml"
    write_feeds_file(feeds, [{"url": "https://old/a.ics"}])
    write_pending_feeds(pending, ["https://h/bad.ics"])
    msg = apply_pending_feeds(pending, feeds, check=lambda u: "not a calendar")
    assert msg == "not a calendar"
    assert not pending.exists()
    assert tomllib.load(open(feeds, "rb"))["feed"][0]["url"] == "https://old/a.ics"

def test_apply_pending_unreadable_file(tmp_path):
    pending = tmp_path / "p.toml"
    pending.write_text("not toml [[[")
    assert "No calendar links" in apply_pending_feeds(pending, tmp_path / "f.toml")
    assert not pending.exists()
