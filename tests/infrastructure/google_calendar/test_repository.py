"""Tests for GoogleCalendarRepository — Google API is fully mocked."""
from unittest.mock import MagicMock, patch

import pytest

from gcal_epd.domain.event import CalendarEvent
from gcal_epd.infrastructure.google_calendar.repository import GoogleCalendarRepository


def _make_repo(calendar_ids=None):
    creds = MagicMock()
    return GoogleCalendarRepository(creds=creds, calendar_ids=calendar_ids or ["test@gmail.com"])


def _fake_service(items, cal_summary="My Calendar"):
    """Build a mock googleapiclient service that returns the given event items."""
    service = MagicMock()
    service.calendars().get().execute.return_value = {"summary": cal_summary}
    service.events().list().execute.return_value = {"items": items}
    return service


@patch("gcal_epd.infrastructure.google_calendar.repository.build")
def test_fetch_events_returns_calendar_events(mock_build):
    mock_build.return_value = _fake_service([
        {"start": {"dateTime": "2024-01-15T09:00:00+08:00"}, "summary": "Standup"},
        {"start": {"date": "2024-01-16"}, "summary": "Holiday"},
    ])
    repo = _make_repo()
    events = repo.fetch_events(days_ahead=7, max_results=10)

    assert len(events) == 2
    assert all(isinstance(e, CalendarEvent) for e in events)


@patch("gcal_epd.infrastructure.google_calendar.repository.build")
def test_fetch_events_uses_calendar_name(mock_build):
    mock_build.return_value = _fake_service(
        [{"start": {"dateTime": "2024-01-15T10:00:00+08:00"}, "summary": "Meeting"}],
        cal_summary="Work Calendar",
    )
    repo = _make_repo()
    events = repo.fetch_events(days_ahead=7, max_results=10)
    assert events[0].calendar_name == "Work Calendar"


@patch("gcal_epd.infrastructure.google_calendar.repository.build")
def test_fetch_events_fallback_no_title(mock_build):
    mock_build.return_value = _fake_service([
        {"start": {"dateTime": "2024-01-15T10:00:00+08:00"}},  # no "summary" key
    ])
    repo = _make_repo()
    events = repo.fetch_events(days_ahead=7, max_results=10)
    assert events[0].title == "(no title)"


@patch("gcal_epd.infrastructure.google_calendar.repository.build")
def test_fetch_events_empty_calendar(mock_build):
    mock_build.return_value = _fake_service([])
    repo = _make_repo()
    events = repo.fetch_events(days_ahead=7, max_results=10)
    assert events == []


@patch("gcal_epd.infrastructure.google_calendar.repository.build")
def test_fetch_events_skips_bad_calendar(mock_build):
    from googleapiclient.errors import HttpError
    from unittest.mock import patch as _patch
    import httplib2

    service = MagicMock()
    service.calendars().get().execute.side_effect = HttpError(
        resp=MagicMock(status=403), content=b"forbidden"
    )
    mock_build.return_value = service

    repo = _make_repo(["bad-cal@gmail.com"])
    events = repo.fetch_events(days_ahead=7, max_results=10)
    # should not raise, just return empty
    assert events == []


@patch("gcal_epd.infrastructure.google_calendar.repository.build")
def test_fetch_events_sorted_by_start(mock_build):
    mock_build.return_value = _fake_service([
        {"start": {"dateTime": "2024-01-17T09:00:00+08:00"}, "summary": "Later"},
        {"start": {"dateTime": "2024-01-15T09:00:00+08:00"}, "summary": "Earlier"},
    ])
    repo = _make_repo()
    events = repo.fetch_events(days_ahead=7, max_results=10)
    assert events[0].title == "Earlier"
    assert events[1].title == "Later"


@patch("gcal_epd.infrastructure.google_calendar.repository.build")
def test_check_access_returns_true_on_success(mock_build):
    service = MagicMock()
    service.events().list().execute.return_value = {"items": []}
    mock_build.return_value = service

    repo = _make_repo()
    assert repo.check_access("test@gmail.com") is True


@patch("gcal_epd.infrastructure.google_calendar.repository.build")
def test_check_access_returns_false_on_http_error(mock_build):
    from googleapiclient.errors import HttpError
    service = MagicMock()
    service.events().list().execute.side_effect = HttpError(
        resp=MagicMock(status=403), content=b"forbidden"
    )
    mock_build.return_value = service

    repo = _make_repo()
    assert repo.check_access("noaccess@gmail.com") is False
