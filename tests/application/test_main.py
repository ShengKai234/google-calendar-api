"""Tests for when main opens the feed setup form."""
import pytest

from gcal_epd import main as main_mod


@pytest.fixture
def harness(monkeypatch, tmp_path):
    calls = {"onboarding": 0, "display": 0, "error": None, "repos": []}
    monkeypatch.setattr(main_mod, "load_config", lambda: {})
    monkeypatch.setattr(main_mod, "feeds_file", lambda config: tmp_path / "ics_feeds.toml")
    monkeypatch.setattr(main_mod, "_build_event_repos",
                        lambda config, budget=None, is_private=None: calls["repos"])
    monkeypatch.setattr(main_mod, "_build_weather_repo", lambda config, budget=None: None)

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
    """The timer's unit has a 3 min timeout; a 10 min form would be killed."""
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


def test_refresh_builds_one_budget_after_onboarding(monkeypatch, tmp_path):
    from gcal_epd.infrastructure.fetch_budget import FetchBudget
    events = []
    builds = []
    budgets = []
    monkeypatch.setattr(main_mod, "load_config", lambda: {})
    monkeypatch.setattr(main_mod, "feeds_file", lambda config: tmp_path / "absent.toml")
    monkeypatch.setattr("sys.argv", ["gcal-epd", "--setup"])
    ready = [False]

    def setup(*args, **kwargs):
        ready[0] = True
        return True

    def make_budget():
        assert ready[0], "the form must not consume the refresh's time budget"
        b = FetchBudget()
        budgets.append(b)
        return b

    def repos(config, budget=None, is_private=None):
        builds.append(budget)
        return events

    def weather(config, budget=None):
        assert budget is budgets[0]
        return None

    monkeypatch.setattr(main_mod, "FetchBudget", make_budget)
    monkeypatch.setattr(main_mod, "_build_event_repos", repos)
    monkeypatch.setattr(main_mod, "_build_weather_repo", weather)
    monkeypatch.setattr(main_mod, "run_onboarding", setup)
    monkeypatch.setattr(main_mod, "run_display", lambda **kwargs: None)
    main_mod.main()
    assert len(budgets) == 1 and builds[-1] is budgets[0]


def test_builders_pass_the_same_budget_to_both_transports(monkeypatch):
    from gcal_epd.infrastructure.fetch_budget import FetchBudget
    from unittest.mock import MagicMock
    budget = FetchBudget()
    config = {"sources": [{"type": "ics"}, {"type": "open_meteo", "latitude": 0, "longitude": 0}]}
    monkeypatch.setattr(main_mod, "load_feeds", lambda p: [{"url": "https://calendar.example.test/sample", "name": "Home"}])
    calendar, weather = MagicMock(), MagicMock()
    monkeypatch.setattr(main_mod, "ICSRepository", calendar)
    monkeypatch.setattr(main_mod, "OpenMeteoRepository", weather)
    main_mod._build_event_repos(config, budget=budget)
    main_mod._build_weather_repo(config, budget=budget)
    assert calendar.call_args.kwargs["budget"] is budget
    assert weather.call_args.kwargs["budget"] is budget


# --- the privacy page (PiSugar button, single press) ---

def test_privacy_mode_draws_the_privacy_page_without_events(harness, monkeypatch):
    """Every refresh (timer, boot, a double press) keeps the events hidden."""
    from gcal_epd.infrastructure import display_mode_file as dm
    monkeypatch.setattr(main_mod, "DATA_DIR", harness.tmp)
    dm.save_mode(harness.tmp / dm.MODE_FILE, dm.PRIVACY)
    harness.calls["repos"] = ["a feed"]
    seen = {}
    monkeypatch.setattr(main_mod, "run_display", lambda **kw: seen.update(kw))
    harness("--display", "--no-setup")
    assert seen["privacy"] is True
    assert seen["event_repos"] == []


def test_calendar_mode_draws_the_calendar(harness, monkeypatch):
    monkeypatch.setattr(main_mod, "DATA_DIR", harness.tmp)
    harness.calls["repos"] = ["a feed"]
    seen = {}
    monkeypatch.setattr(main_mod, "run_display", lambda **kw: seen.update(kw))
    harness("--display", "--no-setup")
    assert seen["privacy"] is False
    assert seen["event_repos"] == ["a feed"]


def test_privacy_mode_keeps_calendar_names_out_of_the_log(monkeypatch, tmp_path, caplog):
    """Review 56-3: while the privacy page is on, a feed problem is logged
    without its calendar's name."""
    caplog.set_level("INFO")
    feeds = tmp_path / "ics_feeds.toml"
    feeds.write_text('[[feed]]\nname = "Secret Doctor Visits"\nurl = ""\n')
    config = {"sources": [{"type": "ics", "feeds_file": str(feeds)}]}
    monkeypatch.setattr(main_mod, "DATA_DIR", tmp_path)
    assert main_mod._build_event_repos(config, is_private=lambda: True) == []
    assert "Secret Doctor Visits" not in caplog.text
    assert main_mod._build_event_repos(config) == []
    assert "Secret Doctor Visits" in caplog.text


def test_every_feed_asks_the_mode_again_before_naming_itself(monkeypatch, tmp_path):
    """Review 56-5: a press during the download must still hide the name,
    so the feeds of a calendar refresh look at the mode when they log."""
    feeds = tmp_path / "ics_feeds.toml"
    feeds.write_text('[[feed]]\nname = "Home"\nurl = "https://calendar.example.test/a"\n')
    config = {"sources": [{"type": "ics", "feeds_file": str(feeds)}]}
    monkeypatch.setattr(main_mod, "DATA_DIR", tmp_path)
    mode = [False]
    (repo,) = main_mod._build_event_repos(config, is_private=lambda: mode[0])
    assert "Home" in repo._log_label
    mode[0] = True
    assert "Home" not in repo._log_label


def test_privacy_is_read_before_the_feeds(harness, monkeypatch):
    from gcal_epd.infrastructure import display_mode_file as dm
    monkeypatch.setattr(main_mod, "DATA_DIR", harness.tmp)
    dm.save_mode(harness.tmp / dm.MODE_FILE, dm.PRIVACY)
    seen = []
    monkeypatch.setattr(main_mod, "_build_event_repos",
                        lambda config, budget=None, is_private=None:
                        seen.append(is_private is not None and is_private()) or ["a"])
    monkeypatch.setattr(main_mod, "run_display", lambda **kw: None)
    harness("--display", "--no-setup")
    assert seen and all(seen)


# --- the battery (PiSugar) in the footer ---

def test_refresh_reads_the_pisugar_battery(harness, monkeypatch):
    from gcal_epd.infrastructure.power.battery import read_battery
    seen = {}
    monkeypatch.setattr(main_mod, "run_display", lambda **kw: seen.update(kw))
    harness("--no-setup")
    assert seen["battery"] is read_battery


def test_mains_powered_display_shows_no_battery(harness, monkeypatch):
    """[power] board = "none": there is no battery to show, so no X either."""
    monkeypatch.setattr(main_mod, "load_config", lambda: {"power": {"board": "none"}})
    seen = {}
    monkeypatch.setattr(main_mod, "run_display", lambda **kw: seen.update(kw))
    harness("--no-setup")
    assert seen["battery"] is None
