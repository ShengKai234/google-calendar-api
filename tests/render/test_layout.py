"""Tests for render.layout — pure geometry, no Pillow needed."""
import datetime

from gcal_epd.domain.event import CalendarEvent
from gcal_epd.render.layout import (
    ALL_DAY_LABEL,
    CONTENT_BOTTOM,
    CONTENT_TOP,
    DAY_GAP,
    HEIGHT,
    ROW_H,
    TW_TZ,
    WIDTH,
    build_layout,
    format_date,
    format_weekday,
    _parse_start,
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


def test_parse_start_converts_utc_to_taiwan_time():
    date, time_str = _parse_start("2024-01-15T02:00:00+00:00")
    assert date == datetime.date(2024, 1, 15)
    assert time_str == "10:00"  # UTC+8


# --- date formatting ---

def test_format_date_uses_abbreviated_weekday():
    # 2024-01-15 is a Monday
    assert format_date(datetime.date(2024, 1, 15)) == "01/15 (Mon)"


def test_format_date_sunday():
    # 2024-01-21 is a Sunday
    assert format_date(datetime.date(2024, 1, 21)) == "01/21 (Sun)"


def test_format_date_zero_pads():
    assert format_date(datetime.date(2024, 9, 5)).startswith("09/05")


def test_format_weekday_is_full_name():
    assert format_weekday(datetime.date(2024, 1, 21)) == "Sunday"
    assert format_weekday(datetime.date(2024, 1, 15)) == "Monday"


def test_weekday_tables_are_monday_first_and_complete():
    from gcal_epd.render.layout import WEEKDAY_ABBR, WEEKDAY_FULL

    assert len(WEEKDAY_ABBR) == len(WEEKDAY_FULL) == 7
    assert WEEKDAY_ABBR[0] == "Mon" and WEEKDAY_FULL[0] == "Monday"
    assert WEEKDAY_ABBR[6] == "Sun" and WEEKDAY_FULL[6] == "Sunday"


def test_all_day_label_is_english():
    assert ALL_DAY_LABEL == "All day"


# --- build_layout ---

def _day_str(offset_days: int = 0) -> str:
    day = datetime.datetime.now(TW_TZ).date() + datetime.timedelta(days=offset_days)
    return day.isoformat()


def test_build_layout_empty_events():
    assert build_layout([]) == []


def test_build_layout_returns_flat_rows():
    events = [
        _event(f"{_day_str()}T09:00:00", title="First"),
        _event(f"{_day_str()}T10:00:00", title="Second"),
    ]
    rows = build_layout(events)
    assert [r.title for r in rows] == ["First", "Second"]


def test_build_layout_first_row_below_header():
    rows = build_layout([_event(f"{_day_str()}T09:00:00")])
    assert rows[0].y == CONTENT_TOP


def test_build_layout_rows_are_row_height_apart_within_a_day():
    events = [
        _event(f"{_day_str()}T09:00:00"),
        _event(f"{_day_str()}T10:00:00"),
    ]
    rows = build_layout(events)
    assert rows[1].y - rows[0].y == ROW_H


def test_build_layout_inserts_gap_between_days():
    events = [
        _event(f"{_day_str()}T09:00:00"),
        _event(f"{_day_str(1)}T09:00:00"),
    ]
    rows = build_layout(events)
    assert rows[1].y - rows[0].y == ROW_H + DAY_GAP


def test_build_layout_each_row_carries_its_own_date():
    events = [
        _event(f"{_day_str()}T09:00:00"),
        _event(f"{_day_str()}T10:00:00"),
    ]
    rows = build_layout(events)
    assert rows[0].date_str == rows[1].date_str
    assert rows[0].date_str == format_date(datetime.datetime.now(TW_TZ).date())


def test_build_layout_all_day_label():
    rows = build_layout([_event(_day_str())])  # date-only = all day
    assert rows[0].time_str == ALL_DAY_LABEL


def test_build_layout_all_day_sorts_before_timed_events():
    events = [
        _event(f"{_day_str()}T09:00:00", title="Timed"),
        _event(_day_str(), title="AllDay"),
    ]
    rows = build_layout(events)
    assert [r.title for r in rows] == ["AllDay", "Timed"]


def test_build_layout_sorts_timed_events_by_start():
    events = [
        _event(f"{_day_str()}T18:00:00", title="Late"),
        _event(f"{_day_str()}T08:00:00", title="Early"),
    ]
    rows = build_layout(events)
    assert [r.title for r in rows] == ["Early", "Late"]


def test_build_layout_orders_days_chronologically():
    events = [
        _event(f"{_day_str(2)}T09:00:00", title="Later"),
        _event(f"{_day_str()}T09:00:00", title="Sooner"),
    ]
    rows = build_layout(events)
    assert [r.title for r in rows] == ["Sooner", "Later"]


def test_build_layout_clamps_to_content_area():
    """Overflowing events are dropped, never drawn over the footer."""
    events = [
        _event(f"{_day_str(d)}T09:00:00", title=f"Event {d}")
        for d in range(40)
    ]
    rows = build_layout(events)
    assert rows, "expected at least one row to fit"
    for row in rows:
        assert row.y + ROW_H <= CONTENT_BOTTOM
        assert row.y < HEIGHT


def test_build_layout_underline_stays_clear_of_footer():
    """The lowest row's underline must not intrude into the footer strip."""
    from gcal_epd.render.layout import UNDERLINE_DROP

    events = [_event(f"{_day_str(d)}T09:00:00") for d in range(40)]
    rows = build_layout(events)
    lowest = max(r.y for r in rows)
    assert lowest + ROW_H / 2 + UNDERLINE_DROP <= CONTENT_BOTTOM


def test_screen_dimensions_match_panel():
    assert (WIDTH, HEIGHT) == (800, 480)
