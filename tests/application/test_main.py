"""Tests for when main opens the feed setup form."""
import pytest

from gcal_epd import main as main_mod


@pytest.fixture
def harness(monkeypatch, tmp_path):
    calls = {"onboarding": 0, "display": 0, "error": None, "repos": []}
    monkeypatch.setattr(main_mod, "load_config", lambda: {})
    monkeypatch.setattr(main_mod, "feeds_file", lambda config: tmp_path / "ics_feeds.toml")
    monkeypatch.setattr(main_mod, "_build_event_repos", lambda config: calls["repos"])
    monkeypatch.setattr(main_mod, "_build_weather_repo", lambda config: None)

    def onboarding(config, push_display, error=""):
        calls["onboarding"] += 1
        calls["error"] = error
        return False

    def display(**kwargs):
        calls["display"] += 1

    monkeypatch.setattr(main_mod, "run_onboarding", onboarding)
    monkeypatch.setattr(main_mod, "run_display", display)

    def run(*argv):
        monkeypatch.setattr("sys.argv", ["gcal-epd", *argv])
        main_mod.main()
        return calls

    run.calls = calls
    run.tmp = tmp_path
    return run


def test_no_feeds_opens_the_setup_form(harness):
    assert harness()["onboarding"] == 1


def test_no_setup_never_waits_on_the_form(harness):
    """The timer's unit has a 120 s timeout; a 10 min form would be killed."""
    calls = harness("--no-setup")
    assert calls["onboarding"] == 0
    assert calls["display"] == 1


def test_explicit_setup_wins_over_no_setup(harness):
    assert harness("--setup", "--no-setup")["onboarding"] == 1


# --- links handed over from the Wi-Fi form ---

def _park(tmp, url="https://h.example/a.ics"):
    (tmp / "ics_feeds.pending.toml").write_text(f'[[feed]]\nurl = "{url}"\n')


def test_failed_pending_link_reopens_setup_with_the_reason(harness, monkeypatch):
    """Even with working feeds, a link the user just entered must not fail silently."""
    harness.calls["repos"] = ["existing feed"]
    _park(harness.tmp)
    monkeypatch.setattr(main_mod, "apply_pending_feeds",
                        lambda p, f: "The link at h.example is not a calendar (iCal) file.")
    calls = harness()
    assert calls["onboarding"] == 1
    assert "not a calendar" in calls["error"]


def test_good_pending_link_skips_setup(harness, monkeypatch):
    _park(harness.tmp)

    def apply(p, f):
        harness.calls["repos"] = ["new feed"]
        return ""

    monkeypatch.setattr(main_mod, "apply_pending_feeds", apply)
    calls = harness()
    assert calls["onboarding"] == 0
    assert calls["display"] == 1


def test_scheduled_refresh_never_waits_even_on_a_failed_link(harness, monkeypatch):
    _park(harness.tmp)
    monkeypatch.setattr(main_mod, "apply_pending_feeds", lambda p, f: "broken")
    assert harness("--no-setup")["onboarding"] == 0
