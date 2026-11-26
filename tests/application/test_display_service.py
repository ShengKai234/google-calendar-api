"""Tests for application.display_service — repos and render are mocked."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gcal_epd.domain.event import CalendarEvent
from gcal_epd.domain.weather import WeatherInfo


_CONFIG = {
    "sources": [
        {
            "type": "ics",
            "feeds_file": "ics_feeds.toml",
            "days_ahead": 7,
            "max_results_per_calendar": 50,
        },
        {
            "type": "open_meteo",
            "latitude": 25.033,
            "longitude": 121.565,
            "location": "Taipei",
        },
    ],
    "display": {
        "output_path": "preview.png",
        "font_path": "",
    },
}

_EVENTS = [
    CalendarEvent(start="2024-01-15T09:00:00", title="Standup", calendar_name="Work"),
    CalendarEvent(start="2024-01-16T10:00:00", title="Review", calendar_name="Work"),
]

_WEATHER = WeatherInfo(temperature=25.0, condition="Clear", humidity=60, location="Taipei")


def _make_event_repo(events=None):
    repo = MagicMock()
    repo.fetch_events.return_value = events if events is not None else _EVENTS
    return repo


def _make_weather_repo(weather=None):
    repo = MagicMock()
    repo.fetch_weather.return_value = weather or _WEATHER
    return repo


@patch("gcal_epd.application.display_service.render")
def test_run_calls_fetch_events(mock_render, tmp_path):
    from gcal_epd.application.display_service import run

    mock_render.return_value = MagicMock()
    event_repo = _make_event_repo()
    weather_repo = _make_weather_repo()

    run(
        event_repos=[event_repo],
        weather_repo=weather_repo,
        config=_CONFIG,
        project_root=tmp_path,
    )

    event_repo.fetch_events.assert_called_once_with(days_ahead=7, max_results=50)


@patch("gcal_epd.application.display_service.render")
def test_run_calls_fetch_weather(mock_render, tmp_path):
    from gcal_epd.application.display_service import run

    mock_render.return_value = MagicMock()
    event_repo = _make_event_repo()
    weather_repo = _make_weather_repo()

    run(
        event_repos=[event_repo],
        weather_repo=weather_repo,
        config=_CONFIG,
        project_root=tmp_path,
    )

    weather_repo.fetch_weather.assert_called_once()


@patch("gcal_epd.application.display_service.render")
def test_run_no_weather_repo(mock_render, tmp_path):
    from gcal_epd.application.display_service import run

    mock_render.return_value = MagicMock()
    event_repo = _make_event_repo()

    run(
        event_repos=[event_repo],
        weather_repo=None,
        config=_CONFIG,
        project_root=tmp_path,
    )

    # render should be called with weather=None
    _, kwargs = mock_render.call_args
    assert kwargs.get("weather") is None


@patch("gcal_epd.application.display_service.render")
def test_run_passes_weather_to_render(mock_render, tmp_path):
    from gcal_epd.application.display_service import run

    mock_render.return_value = MagicMock()
    event_repo = _make_event_repo()
    weather_repo = _make_weather_repo()

    run(
        event_repos=[event_repo],
        weather_repo=weather_repo,
        config=_CONFIG,
        project_root=tmp_path,
    )

    _, kwargs = mock_render.call_args
    assert kwargs.get("weather") == _WEATHER


@patch("gcal_epd.application.display_service.render")
def test_run_merges_multiple_repos(mock_render, tmp_path):
    from gcal_epd.application.display_service import run

    mock_render.return_value = MagicMock()
    repo1 = _make_event_repo([CalendarEvent("2024-01-15", "A", "Cal1")])
    repo2 = _make_event_repo([CalendarEvent("2024-01-16", "B", "Cal2")])

    run(
        event_repos=[repo1, repo2],
        weather_repo=None,
        config=_CONFIG,
        project_root=tmp_path,
    )

    args, _ = mock_render.call_args
    passed_events = args[0]
    titles = [e.title for e in passed_events]
    assert "A" in titles
    assert "B" in titles


@patch("gcal_epd.application.display_service.render")
def test_run_events_sorted_by_start(mock_render, tmp_path):
    from gcal_epd.application.display_service import run

    mock_render.return_value = MagicMock()
    events = [
        CalendarEvent("2024-01-17", "Later", "Cal"),
        CalendarEvent("2024-01-15", "Earlier", "Cal"),
    ]
    event_repo = _make_event_repo(events)

    run(
        event_repos=[event_repo],
        weather_repo=None,
        config=_CONFIG,
        project_root=tmp_path,
    )

    args, _ = mock_render.call_args
    passed_events = args[0]
    assert passed_events[0].title == "Earlier"
    assert passed_events[1].title == "Later"


@patch("gcal_epd.application.display_service.render")
def test_run_push_display_calls_epd(mock_render, tmp_path):
    """When push_display=True, push_to_display should be called."""
    from gcal_epd.application.display_service import run

    fake_img = MagicMock()
    mock_render.return_value = fake_img
    event_repo = _make_event_repo()

    # push_to_display is imported locally inside run(), so patch it at its source
    with patch("gcal_epd.epd.push_to_display") as mock_epd_push:
        run(
            event_repos=[event_repo],
            weather_repo=None,
            config=_CONFIG,
            project_root=tmp_path,
            push_display=True,
            data_dir=tmp_path,
        )
        # The panel lock is already held by run() (review 56-1).
        mock_epd_push.assert_called_once_with(fake_img, (0, 0), take_lock=False)


@patch("gcal_epd.application.display_service.render")
def test_run_push_display_passes_the_frame_offset(mock_render, tmp_path):
    """[display] frame_offset_px reaches the panel push."""
    from gcal_epd.application.display_service import run

    config = {**_CONFIG, "display": {**_CONFIG.get("display", {}), "frame_offset_px": [3, -2]}}
    with patch("gcal_epd.epd.push_to_display") as mock_epd_push:
        run(event_repos=[_make_event_repo()], weather_repo=None, config=config,
            project_root=tmp_path, push_display=True, data_dir=tmp_path)
    mock_epd_push.assert_called_once_with(mock_render.return_value, (3, -2), take_lock=False)


@patch("gcal_epd.application.display_service.render")
def test_preview_goes_to_the_data_dir_not_the_code(mock_render, tmp_path):
    """An installed release's code is read-only; the preview lives with the data."""
    from gcal_epd.application.display_service import run

    code, data = tmp_path / "code", tmp_path / "data"
    run(event_repos=[], weather_repo=None, config=_CONFIG,
        project_root=code, data_dir=data)

    assert mock_render.call_args.kwargs["output_path"] == str(data / "preview.png")


@patch("gcal_epd.application.display_service.render")
def test_preview_defaults_to_the_checkout(mock_render, tmp_path):
    from gcal_epd.application.display_service import run

    run(event_repos=[], weather_repo=None, config=_CONFIG, project_root=tmp_path)

    assert mock_render.call_args.kwargs["output_path"] == str(tmp_path / "preview.png")


# --- the privacy page ---

@patch("gcal_epd.application.display_service.render")
@patch("gcal_epd.application.display_service.render_privacy")
def test_privacy_fetches_no_events_and_draws_the_privacy_page(mock_privacy, mock_render,
                                                              tmp_path):
    from gcal_epd.application.display_service import run

    mock_privacy.return_value = MagicMock()
    event_repo = _make_event_repo()
    weather_repo = _make_weather_repo()
    run(event_repos=[event_repo], weather_repo=weather_repo, config=_CONFIG,
        project_root=tmp_path, privacy=True)

    event_repo.fetch_events.assert_not_called()
    mock_render.assert_not_called()
    _, kwargs = mock_privacy.call_args
    assert kwargs["weather"] == _WEATHER


@patch("gcal_epd.application.display_service.render")
@patch("gcal_epd.application.display_service.render_privacy")
def test_a_press_during_the_fetch_wins(mock_privacy, mock_render, tmp_path):
    """Review 56-1: the calendar was fetched, but the privacy page was
    switched on meanwhile; the calendar must not be drawn after it."""
    from gcal_epd.application.display_service import run

    mock_privacy.return_value = MagicMock()
    run(event_repos=[_make_event_repo()], weather_repo=_make_weather_repo(), config=_CONFIG,
        project_root=tmp_path, data_dir=tmp_path, is_private=lambda: True)

    mock_render.assert_not_called()
    mock_privacy.assert_called_once()


def test_a_preview_also_holds_the_lock_while_the_mode_can_change(tmp_path, monkeypatch):
    """Review 56-1: preview.png is saved too, so it is chosen under the
    same lock a single press takes, even without a panel."""
    from contextlib import contextmanager

    from gcal_epd.application import display_service

    order = []

    @contextmanager
    def lock(path):
        assert path == tmp_path / display_service.PANEL_LOCK
        order.append("lock")
        yield
        order.append("unlock")

    monkeypatch.setattr(display_service, "panel_lock", lock)
    monkeypatch.setattr(display_service, "render",
                        lambda *a, **kw: order.append("render") or MagicMock())
    display_service.run(event_repos=[_make_event_repo()], weather_repo=None, config=_CONFIG,
                        project_root=tmp_path, data_dir=tmp_path,
                        is_private=lambda: order.append("check") or False)
    assert order == ["lock", "check", "render", "unlock"]


def test_the_page_is_chosen_and_pushed_under_the_panel_lock(tmp_path, monkeypatch):
    """A single press switches the mode, then waits for the panel: the
    last look at the mode and the push happen in one hold of the lock, so
    whatever is drawn last matches the mode."""
    from contextlib import contextmanager

    from gcal_epd.application import display_service

    order = []

    @contextmanager
    def lock(path):
        order.append("lock")
        yield
        order.append("unlock")

    def is_private():
        order.append("check")
        return False

    def render(*a, **kw):
        order.append("render")
        return MagicMock()

    def push(img, offset, take_lock=True):
        assert take_lock is False
        order.append("push")

    monkeypatch.setattr(display_service, "panel_lock", lock)
    monkeypatch.setattr(display_service, "render", render)
    monkeypatch.setattr("gcal_epd.epd.push_to_display", push)
    display_service.run(event_repos=[_make_event_repo()], weather_repo=None, config=_CONFIG,
                        project_root=tmp_path, push_display=True, data_dir=tmp_path,
                        is_private=is_private)
    assert order == ["lock", "check", "render", "push", "unlock"]


# --- the battery mark -------------------------------------------------

def test_a_refresh_reads_the_battery_once_and_passes_it(monkeypatch, tmp_path):
    from gcal_epd.application import display_service
    from gcal_epd.domain.battery import BatteryStatus

    status = BatteryStatus(85.0, True)
    calls = []
    monkeypatch.setattr(display_service, "read_battery_status",
                        lambda: calls.append("read") or status)
    seen = {}
    monkeypatch.setattr(display_service, "render",
                        lambda *a, **k: seen.update(k) or MagicMock())
    display_service.run(event_repos=[_make_event_repo()], weather_repo=None, config=_CONFIG,
                        project_root=tmp_path, data_dir=tmp_path)
    assert calls == ["read"]
    assert seen["battery"] == status
    assert seen["low_battery_percent"] == 20


def test_the_warning_threshold_comes_from_config(monkeypatch, tmp_path):
    from gcal_epd.application import display_service

    config = {**_CONFIG, "display": {**_CONFIG["display"], "low_battery_percent": 30}}
    seen = {}
    monkeypatch.setattr(display_service, "read_battery_status", lambda: None)
    monkeypatch.setattr(display_service, "render",
                        lambda *a, **k: seen.update(k) or MagicMock())
    display_service.run(event_repos=[], weather_repo=None, config=config,
                        project_root=tmp_path, data_dir=tmp_path)
    assert seen["low_battery_percent"] == 30


def test_a_battery_read_that_raises_still_draws(monkeypatch, tmp_path, caplog):
    import logging

    from gcal_epd.application import display_service

    def boom():
        raise RuntimeError("down")

    monkeypatch.setattr(display_service, "read_battery_status", boom)
    seen = {}
    monkeypatch.setattr(display_service, "render",
                        lambda *a, **k: seen.update(k) or MagicMock())
    with caplog.at_level(logging.WARNING):
        display_service.run(event_repos=[], weather_repo=None, config=_CONFIG,
                            project_root=tmp_path, data_dir=tmp_path)
    assert seen["battery"] is None
    assert "Battery level unavailable" in caplog.text


def test_the_privacy_page_gets_the_same_reading(monkeypatch, tmp_path):
    from gcal_epd.application import display_service
    from gcal_epd.domain.battery import BatteryStatus

    status = BatteryStatus(15.0, False)
    calls = []
    monkeypatch.setattr(display_service, "read_battery_status",
                        lambda: calls.append("read") or status)
    seen = {}
    monkeypatch.setattr(display_service, "render_privacy",
                        lambda *a, **k: seen.update(k) or MagicMock())
    display_service.run(event_repos=[_make_event_repo()], weather_repo=_make_weather_repo(),
                        config=_CONFIG, project_root=tmp_path, data_dir=tmp_path, privacy=True)
    assert calls == ["read"]
    assert seen["battery"] == status
    assert seen["low_battery_percent"] == 20
