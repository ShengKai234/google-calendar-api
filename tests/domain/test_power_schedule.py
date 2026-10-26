"""Tests for the wake-up schedule model."""
from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from gcal_epd.domain.power_schedule import (
    DEFAULT_SLOTS,
    MAX_SLOTS,
    PowerSchedule,
    format_slot,
    parse_slot,
)

TPE = ZoneInfo("Asia/Taipei")


def at(h, m, day=19):
    return datetime(2026, 10, day, h, m, tzinfo=TPE)


def test_default_is_seven_and_nineteen_with_five_minutes_lead():
    s = PowerSchedule()
    assert s.slots == DEFAULT_SLOTS == (time(7, 0), time(19, 0))
    assert s.enabled and s.wake_lead_minutes == 5


@pytest.mark.parametrize("text,expected", [("07:00", time(7)), (" 19:30 ", time(19, 30)),
                                           ("0:05", time(0, 5)), ("23:59", time(23, 59))])
def test_parse_slot(text, expected):
    assert parse_slot(text) == expected


@pytest.mark.parametrize("text", ["", "7", "7:5", "24:00", "12:60", "ab:cd", "07:00pm"])
def test_parse_slot_rejects(text):
    with pytest.raises(ValueError):
        parse_slot(text)


def test_format_slot_round_trips():
    assert format_slot(parse_slot("07:05")) == "07:05"


def test_slots_are_sorted_and_seconds_dropped():
    s = PowerSchedule(slots=(time(19, 0, 30), time(7, 0)))
    assert s.slots == (time(7, 0), time(19, 0))


@pytest.mark.parametrize("slots", [(), tuple(time(h) for h in range(MAX_SLOTS + 1))])
def test_slot_count_is_bounded(slots):
    with pytest.raises(ValueError):
        PowerSchedule(slots=slots)


def test_slots_too_close_are_refused():
    with pytest.raises(ValueError, match="30 minutes apart"):
        PowerSchedule(slots=(time(7, 0), time(7, 20)))


def test_gap_across_midnight_counts():
    with pytest.raises(ValueError):
        PowerSchedule(slots=(time(23, 50), time(0, 10)))


def test_one_slot_is_fine():
    assert PowerSchedule(slots=(time(7),)).slots == (time(7),)


@pytest.mark.parametrize("lead", [-1, 61])
def test_lead_is_bounded(lead):
    with pytest.raises(ValueError):
        PowerSchedule(wake_lead_minutes=lead)


@pytest.mark.parametrize("now,wake", [
    (at(3, 0), at(6, 55)),          # night -> this morning
    (at(6, 55), at(18, 55)),        # woken for 06:55: strictly after, so evening
    (at(6, 56), at(18, 55)),
    (at(18, 54), at(18, 55)),
    (at(18, 55), at(6, 55, day=20)),
    (at(23, 0), at(6, 55, day=20)),
])
def test_next_wake(now, wake):
    assert PowerSchedule().next_wake(now) == wake


def test_next_slot_has_no_lead():
    assert PowerSchedule().next_slot(at(6, 56)) == at(7, 0)


def test_lead_can_cross_midnight():
    s = PowerSchedule(slots=(time(0, 2),), wake_lead_minutes=5)
    assert s.next_wake(at(12, 0)) == at(23, 57)


def test_naive_now_is_refused():
    with pytest.raises(ValueError):
        PowerSchedule().next_wake(datetime(2026, 10, 19, 7))
