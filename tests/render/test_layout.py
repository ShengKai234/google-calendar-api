"""Tests for render.layout — pure geometry, no Pillow needed."""
import datetime
from unittest.mock import patch

import pytest

from gcal_epd.domain.event import CalendarEvent
from gcal_epd.render.layout import (
    HEADER_H,
    HEIGHT,
    WIDTH,
    PADDING,
    build_layout,
    _parse_start,
    _assign_cal_colors,
    ACCENT_COLORS,
    TW_TZ,
)


def _event(start: str, title: str = "Event", cal: str = "Cal") -> CalendarEvent:
    return CalendarEvent(start=start, title=title, calendar_name=cal)


# --- _parse_start ---

def test_parse_start_date_only():
    date, time_str = _parse_start("2024-01-15")
    assert date == datetime.date(2024, 1, 15)
    assert time_str == ""


def test_parse_start_datetime_with_tz():
    date, time_str = _parse_start("2024-01-15T09:30:00+08:00")
    assert date == datetime.date(2024, 1, 15)
    assert time_str == "09:30"


def test_parse_start_datetime_naive_treated_as_tw():
    date, time_str = _parse_start("2024-01-15T14:00:00")
    assert date == datetime.date(2024, 1, 15)
    assert time_str == "14:00"


# --- _assign_cal_colors ---

def test_assign_cal_colors_single_calendar():
    events = [_event("2024-01-15", cal="Work"), _event("2024-01-16", cal="Work")]
    colors = _assign_cal_colors(events)
    assert set(colors.keys()) == {"Work"}
    assert colors["Work"] == ACCENT_COLORS[0]


def test_assign_cal_colors_multiple_calendars():
    events = [
        _event("2024-01-15", cal="Work"),
        _event("2024-01-16", cal="Personal"),
        _event("2024-01-17", cal="Work"),
    ]
    colors = _assign_cal_colors(events)
    assert set(colors.keys()) == {"Work", "Personal"}
    assert colors["Work"] != colors["Personal"]


def test_assign_cal_colors_cycles_after_five():
    cals = [f"Cal{i}" for i in range(7)]
    events = [_event("2024-01-15", cal=c) for c in cals]
    colors = _assign_cal_colors(events)
    assert colors["Cal0"] == colors["Cal5"]  # wraps at ACCENT_COLORS length (5)


# --- build_layout ---

def _today_str(offset_days: int = 0) -> str:
    today = datetime.datetime.now(TW_TZ).date() + datetime.timedelta(days=offset_days)
    return today.isoformat()


def test_build_layout_empty_events():
    blocks = build_layout([])
    assert blocks == []


def test_build_layout_today_label():
    events = [_event(f"{_today_str()}T09:00:00")]
    blocks = build_layout(events)
    assert any(b.label == "Today" for b in blocks)


def test_build_layout_tomorrow_label():
    events = [_event(f"{_today_str(1)}T10:00:00")]
    blocks = build_layout(events)
    assert any(b.label == "Tomorrow" for b in blocks)


def test_build_layout_future_date_label():
    events = [_event(f"{_today_str(3)}")]
    blocks = build_layout(events)
    labels = [b.label for b in blocks]
    assert not any(l in ("Today", "Tomorrow") for l in labels)


def test_build_layout_rows_per_block():
    events = [
        _event(f"{_today_str()}T09:00:00", title="First"),
        _event(f"{_today_str()}T10:00:00", title="Second"),
    ]
    blocks = build_layout(events)
    today_block = next(b for b in blocks if b.label == "Today")
    assert len(today_block.rows) == 2


def test_build_layout_all_day_time_str():
    events = [_event(_today_str())]  # date-only = all day
    blocks = build_layout(events)
    today_block = next(b for b in blocks if b.label == "Today")
    assert today_block.rows[0].time_str == "All day"


def test_build_layout_y_starts_after_header():
    events = [_event(f"{_today_str()}T09:00:00")]
    blocks = build_layout(events)
    assert blocks[0].y >= HEADER_H


def test_build_layout_does_not_exceed_screen_height():
    # Generate many events — layout must clamp to HEIGHT
    events = [_event(f"{_today_str()}T{h:02d}:00:00", title=f"Event {h}") for h in range(20)]
    blocks = build_layout(events)
    for block in blocks:
        assert block.y < HEIGHT
        for row in block.rows:
            assert row.y < HEIGHT
