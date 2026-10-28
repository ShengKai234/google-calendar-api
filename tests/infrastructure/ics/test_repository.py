"""Tests for ICSRepository — feeds are fixtures, HTTP is mocked."""
import datetime
import logging
from unittest.mock import MagicMock, patch

import pytest

from gcal_epd.domain.event import CalendarEvent
from gcal_epd.domain.repositories import EventRepository
from gcal_epd.infrastructure.ics.repository import (
    ICSRepository,
    events_from_ics,
    normalize_feed_url,
)

UTC = datetime.timezone.utc
# A Monday at midnight UTC. Fixtures use Asia/Taipei 10:00 (= 02:00 UTC),
# so a same-day occurrence still falls inside the window.
NOW = datetime.datetime(2026, 1, 5, 0, 0, tzinfo=UTC)


def _feed(*vevents: str, name: str | None = "Test Calendar") -> bytes:
    header = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//test//EN\r\n"
    if name is not None:
        header += f"X-WR-CALNAME:{name}\r\n"
    return (header + "".join(vevents) + "END:VCALENDAR\r\n").encode()


def _vevent(uid: str, dtstart: str, summary: str = "Event", extra: str = "") -> str:
    return (
        f"BEGIN:VEVENT\r\nUID:{uid}\r\nDTSTAMP:20260101T000000Z\r\n"
        f"DTSTART{dtstart}\r\n"
        + (f"SUMMARY:{summary}\r\n" if summary is not None else "")
        + extra
        + "END:VEVENT\r\n"
    )


def _parse(raw: bytes, days_ahead: int = 14, max_results: int = 100, name: str = ""):
    return events_from_ics(raw, days_ahead=days_ahead, max_results=max_results,
                           name=name, now=NOW)


# --- URL normalisation ---

@pytest.mark.parametrize("given,expected", [
    ("webcal://host/a.ics", "https://host/a.ics"),
    ("webcals://host/a.ics", "https://host/a.ics"),
    ("https://host/a.ics", "https://host/a.ics"),
    ("http://host/a.ics", "http://host/a.ics"),
])
def test_normalize_feed_url(given, expected):
    assert normalize_feed_url(given) == expected


def test_repository_normalizes_url_on_construction():
    assert ICSRepository("webcal://host/a.ics")._url == "https://host/a.ics"


def test_satisfies_event_repository_protocol():
    assert isinstance(ICSRepository("https://host/a.ics"), EventRepository)


# --- start formatting ---

def test_all_day_event_yields_bare_date():
    raw = _feed(_vevent("1", ";VALUE=DATE:20260107", "Holiday"))
    assert _parse(raw)[0].start == "2026-01-07"


def test_timed_event_keeps_its_offset():
    raw = _feed(_vevent("1", ":20260107T140000Z", "Call"))
    start = _parse(raw)[0].start
    assert start.startswith("2026-01-07T14:00:00")
    assert start.endswith("+00:00")


def test_naive_datetime_stays_naive_for_the_render_layer():
    """A floating time carries no offset, so the display timezone applies."""
    raw = _feed(_vevent("1", ":20260107T140000", "Floating"))
    assert _parse(raw)[0].start == "2026-01-07T14:00:00"


def test_zoned_event_is_converted_with_its_tzid():
    raw = _feed(_vevent("1", ";TZID=Asia/Taipei:20260107T090000", "TW meeting"))
    assert _parse(raw)[0].start.startswith("2026-01-07T09:00:00+08:00")


# --- windowing ---

def test_event_before_window_is_excluded():
    raw = _feed(_vevent("1", ";VALUE=DATE:20251201", "Past"))
    assert _parse(raw) == []


def test_event_after_window_is_excluded():
    raw = _feed(_vevent("1", ";VALUE=DATE:20260401", "Far future"))
    assert _parse(raw, days_ahead=14) == []


def test_days_ahead_widens_the_window():
    raw = _feed(_vevent("1", ";VALUE=DATE:20260201", "Next month"))
    assert _parse(raw, days_ahead=14) == []
    assert len(_parse(raw, days_ahead=90)) == 1


# --- recurrence (the reason a feed needs expanding at all) ---

def test_weekly_rrule_is_expanded_into_occurrences():
    raw = _feed(_vevent("1", ";TZID=Asia/Taipei:20260105T100000", "Standup",
                        extra="RRULE:FREQ=WEEKLY;COUNT=10\r\n"))
    events = _parse(raw, days_ahead=21)
    assert len(events) == 3, "expect 3 weekly occurrences inside a 21-day window"
    assert [e.start[:10] for e in events] == ["2026-01-05", "2026-01-12", "2026-01-19"]


def test_daily_rrule_until_stops_at_until():
    raw = _feed(_vevent("1", ";TZID=Asia/Taipei:20260105T100000", "Daily",
                        extra="RRULE:FREQ=DAILY;UNTIL=20260108T000000Z\r\n"))
    assert len(_parse(raw)) == 3


def test_exdate_removes_a_single_occurrence():
    raw = _feed(_vevent("1", ";TZID=Asia/Taipei:20260105T100000", "Standup",
                        extra="RRULE:FREQ=WEEKLY;COUNT=5\r\n"
                              "EXDATE;TZID=Asia/Taipei:20260112T100000\r\n"))
    dates = [e.start[:10] for e in _parse(raw, days_ahead=21)]
    assert "2026-01-12" not in dates
    assert dates == ["2026-01-05", "2026-01-19"]


def test_recurrence_id_override_replaces_that_instance():
    """A moved instance must appear at its new time, not the original."""
    raw = _feed(
        _vevent("1", ";TZID=Asia/Taipei:20260105T100000", "Standup",
                extra="RRULE:FREQ=WEEKLY;COUNT=5\r\n"),
        _vevent("1", ";TZID=Asia/Taipei:20260112T160000", "Standup (moved)",
                extra="RECURRENCE-ID;TZID=Asia/Taipei:20260112T100000\r\n"),
    )
    events = _parse(raw, days_ahead=21)
    moved = [e for e in events if e.start.startswith("2026-01-12")]
    assert len(moved) == 1
    assert moved[0].start.startswith("2026-01-12T16:00:00")
    assert moved[0].title == "Standup (moved)"


# --- field handling ---

def test_cancelled_event_is_skipped():
    raw = _feed(_vevent("1", ";VALUE=DATE:20260107", "Called off",
                        extra="STATUS:CANCELLED\r\n"))
    assert _parse(raw) == []


def test_event_without_summary_gets_placeholder():
    raw = _feed(_vevent("1", ";VALUE=DATE:20260107", summary=None))
    assert _parse(raw)[0].title == "(no title)"


def test_unicode_summary_survives():
    raw = _feed(_vevent("1", ";VALUE=DATE:20260107", "看屋：上城後棟"))
    assert _parse(raw)[0].title == "看屋：上城後棟"


def test_returns_calendar_event_instances():
    raw = _feed(_vevent("1", ";VALUE=DATE:20260107"))
    assert all(isinstance(e, CalendarEvent) for e in _parse(raw))


# --- calendar naming ---

def test_calendar_name_comes_from_the_feed():
    raw = _feed(_vevent("1", ";VALUE=DATE:20260107"), name="個人")
    assert _parse(raw)[0].calendar_name == "個人"


def test_configured_name_overrides_the_feed():
    raw = _feed(_vevent("1", ";VALUE=DATE:20260107"), name="個人")
    assert _parse(raw, name="Apple")[0].calendar_name == "Apple"


def test_unnamed_feed_falls_back_to_placeholder():
    raw = _feed(_vevent("1", ";VALUE=DATE:20260107"), name=None)
    assert _parse(raw)[0].calendar_name == "Calendar"


# --- ordering and limits ---

def test_events_are_sorted_chronologically():
    raw = _feed(
        _vevent("1", ":20260109T100000Z", "Later"),
        _vevent("2", ":20260107T100000Z", "Earlier"),
    )
    assert [e.title for e in _parse(raw)] == ["Earlier", "Later"]


def test_all_day_sorts_ahead_of_timed_events_same_day():
    raw = _feed(
        _vevent("1", ":20260107T100000Z", "Timed"),
        _vevent("2", ";VALUE=DATE:20260107", "All day"),
    )
    assert [e.title for e in _parse(raw)] == ["All day", "Timed"]


def test_max_results_caps_the_list():
    raw = _feed(_vevent("1", ";TZID=Asia/Taipei:20260105T100000", "Daily",
                        extra="RRULE:FREQ=DAILY;COUNT=20\r\n"))
    assert len(_parse(raw, max_results=5)) == 5


def test_empty_calendar_yields_no_events():
    assert _parse(_feed()) == []


# --- failure handling ---

def _response(content: bytes = b"", status: int = 200):
    r = MagicMock()
    r.content = content
    r.raise_for_status = MagicMock()
    if status >= 400:
        r.raise_for_status.side_effect = Exception(f"HTTP {status}")
    return r


@patch("gcal_epd.infrastructure.ics.repository.requests.get")
def test_fetch_events_returns_parsed_events(mock_get):
    mock_get.return_value = _response(_feed(_vevent("1", ";VALUE=DATE:20991231")))
    events = ICSRepository("https://host/a.ics").fetch_events(days_ahead=40000,
                                                              max_results=10)
    assert len(events) == 1


@patch("gcal_epd.infrastructure.ics.repository.requests.get")
def test_network_error_returns_empty_list(mock_get):
    mock_get.side_effect = OSError("network unreachable")
    assert ICSRepository("https://host/a.ics").fetch_events(14, 100) == []


@patch("gcal_epd.infrastructure.ics.repository.requests.get")
def test_http_error_returns_empty_list(mock_get):
    mock_get.return_value = _response(status=404)
    assert ICSRepository("https://host/a.ics").fetch_events(14, 100) == []


@patch("gcal_epd.infrastructure.ics.repository.requests.get")
def test_malformed_feed_returns_empty_list(mock_get):
    mock_get.return_value = _response(b"this is not an ics file at all")
    assert ICSRepository("https://host/a.ics").fetch_events(14, 100) == []


@patch("gcal_epd.infrastructure.ics.repository.requests.get")
def test_one_feed_failing_does_not_raise(mock_get):
    """A dead feed must degrade to empty, never take the whole render down."""
    mock_get.side_effect = TimeoutError("timed out")
    ICSRepository("https://host/a.ics", name="Apple").fetch_events(14, 100)


@patch("gcal_epd.infrastructure.ics.repository.requests.get")
def test_request_is_sent_with_a_timeout(mock_get):
    """A hung feed must not block the display refresh forever."""
    mock_get.return_value = _response(_feed())
    ICSRepository("https://host/a.ics", timeout=7).fetch_events(14, 100)
    assert mock_get.call_args.kwargs["timeout"] == 7


# --- the feed URL is a secret ---

# A synthetic stand-in — never put a real feed token in a tracked file.
_SECRET = "private-000000000000000000000000deadbeef"


def test_log_label_never_contains_the_token():
    repo = ICSRepository(f"https://calendar.google.com/ical/{_SECRET}/basic.ics",
                         name="Google")
    assert _SECRET not in repo._log_label
    assert repo._log_label == "Google (calendar.google.com)"


@patch("gcal_epd.infrastructure.ics.repository.requests.get")
def test_failure_log_never_leaks_the_token(mock_get, caplog):
    """These warnings land in the systemd journal — they must stay clean."""
    mock_get.side_effect = OSError("connection refused")
    url = f"https://calendar.google.com/ical/{_SECRET}/basic.ics"
    with caplog.at_level(logging.WARNING):
        ICSRepository(url, name="Google").fetch_events(14, 100)
    assert caplog.text, "expected a warning to be logged"
    assert _SECRET not in caplog.text
    assert url not in caplog.text


@patch("gcal_epd.infrastructure.ics.repository.requests.get")
def test_parse_failure_log_never_leaks_the_token(mock_get, caplog):
    mock_get.return_value = _response(b"not an ics file")
    url = f"https://calendar.google.com/ical/{_SECRET}/basic.ics"
    with caplog.at_level(logging.WARNING):
        ICSRepository(url, name="Google").fetch_events(14, 100)
    assert _SECRET not in caplog.text
