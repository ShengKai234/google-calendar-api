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
        )
        mock_epd_push.assert_called_once_with(fake_img)
