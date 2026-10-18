"""Tests for when main opens the feed setup form."""
import pytest

from gcal_epd import main as main_mod


@pytest.fixture
def harness(monkeypatch):
    calls = {"onboarding": 0, "display": 0}
    monkeypatch.setattr(main_mod, "load_config", lambda: {})
    monkeypatch.setattr(main_mod, "_build_event_repos", lambda config: [])
    monkeypatch.setattr(main_mod, "_build_weather_repo", lambda config: None)

    def onboarding(config, push_display):
        calls["onboarding"] += 1
        return False

    def display(**kwargs):
        calls["display"] += 1

    monkeypatch.setattr(main_mod, "run_onboarding", onboarding)
    monkeypatch.setattr(main_mod, "run_display", display)

    def run(*argv):
        monkeypatch.setattr("sys.argv", ["gcal-epd", *argv])
        main_mod.main()
        return calls

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
