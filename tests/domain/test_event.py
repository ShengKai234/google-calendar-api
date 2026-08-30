"""Tests for domain.event — CalendarEvent dataclass."""
import dataclasses

from gcal_epd.domain.event import CalendarEvent


def test_calendar_event_fields():
    event = CalendarEvent(start="2024-01-15T09:00:00", title="Team standup", calendar_name="Work")
    assert event.start == "2024-01-15T09:00:00"
    assert event.title == "Team standup"
    assert event.calendar_name == "Work"


def test_calendar_event_is_dataclass():
    assert dataclasses.is_dataclass(CalendarEvent)


def test_calendar_event_equality():
    e1 = CalendarEvent(start="2024-01-15", title="Meeting", calendar_name="Work")
    e2 = CalendarEvent(start="2024-01-15", title="Meeting", calendar_name="Work")
    assert e1 == e2


def test_calendar_event_inequality():
    e1 = CalendarEvent(start="2024-01-15", title="Meeting", calendar_name="Work")
    e2 = CalendarEvent(start="2024-01-16", title="Meeting", calendar_name="Work")
    assert e1 != e2


def test_calendar_event_all_day():
    event = CalendarEvent(start="2024-01-15", title="Holiday", calendar_name="Holidays")
    assert "T" not in event.start
