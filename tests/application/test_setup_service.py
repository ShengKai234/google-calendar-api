"""Tests for the calendar setup flow, with the form and panel faked."""
from gcal_epd.application import setup_service


class FakeServer:
    url = "http://192.168.0.5:8080"
    pin = "123456"

    def __init__(self, feeds_path, saves=True):
        self.feeds_path = feeds_path
        self.saves = saves

    def serve_until_configured(self):
        return self.saves


def _run(monkeypatch, saves, push_display=True):
    screens = []
    monkeypatch.setattr(setup_service, "FeedSetupServer",
                        lambda path: FakeServer(path, saves))
    monkeypatch.setattr(setup_service, "push_setup_screen",
                        lambda config, kind, **kw: screens.append((kind, kw)))
    return setup_service.run_onboarding({}, push_display=push_display), screens


def test_saved_shows_setup_then_success(monkeypatch):
    saved, screens = _run(monkeypatch, saves=True)
    assert saved is True
    assert screens[0] == ("setup", {"url": FakeServer.url, "pin": FakeServer.pin})
    assert screens[1][0] == "success"


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
