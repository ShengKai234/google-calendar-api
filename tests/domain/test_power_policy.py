"""Tests for the power-off rules: when a woken Pi may power off.

Times are Asia/Taipei; the default schedule wakes at 06:55 and 18:55 for
07:00 and 19:00.
"""
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from gcal_epd.domain.power_policy import GRACE, MIN_OFF, Snapshot, decide
from gcal_epd.domain.power_schedule import PowerSchedule

TPE = ZoneInfo("Asia/Taipei")


def at(h, m, s=0, day=19):
    return datetime(2026, 10, day, h, m, s, tzinfo=TPE)


def snap(now=at(6, 59), boot=at(6, 55), refreshed=at(6, 57), **kw):
    """A woken Pi whose boot refresh finished at 06:57: ready to power off."""
    return Snapshot(now=now, boot=boot, schedule=kw.pop("schedule", PowerSchedule()),
                    last_refresh=refreshed, **kw)


# --- decide: the happy path ------------------------------------------
def test_powers_off_after_refresh_and_grace():
    d = decide(snap())
    assert d.power_off and "06:57" in d.reason


def test_stays_during_grace():
    d = decide(snap(now=at(6, 57) + timedelta(seconds=GRACE - 1)))
    assert not d.power_off and "grace" in d.reason


def test_waits_for_a_refresh_that_has_not_finished():
    d = decide(snap(now=at(6, 58), refreshed=None))
    assert not d.power_off and "waiting for the refresh" in d.reason


# --- decide: never power off when ... --------------------------------
@pytest.mark.parametrize("change,words", [
    ({"board": False}, "no wake-up board"),
    ({"schedule": PowerSchedule(enabled=False)}, "turned off"),
    ({"stay_awake": True}, "stay-awake"),
    ({"setup": "epd-wifi-setup.service"}, "setting up"),
    ({"setup": "calendar setup (gcal_epd.main --setup)"}, "setting up"),
    ({"ssh_sessions": 1}, "SSH session"),
    ({"ssh_sessions": None}, "cannot tell"),
    ({"refreshing": "gcal-epd.service"}, "gcal-epd.service is running"),
    ({"refreshing": "epd-feed-setup.service"}, "epd-feed-setup.service is running"),
])
def test_never_powers_off_when(change, words):
    ready = snap()
    assert decide(ready).power_off
    blocked = replace(ready, **change)
    d = decide(blocked)
    assert not d.power_off
    assert words in d.reason


@pytest.mark.parametrize("change", [
    {"schedule": PowerSchedule(enabled=False)}, {"stay_awake": True},
    {"setup": "epd-wifi-setup.service"}, {"ssh_sessions": 2},
    {"refreshing": "gcal-epd.service"},
])
def test_blockers_beat_the_awake_cap(change):
    """The cap saves battery after a failed refresh, never at a person's expense."""
    late = snap(now=at(9, 0), refreshed=None)
    assert decide(late).power_off
    assert not decide(replace(late, **change)).power_off


def test_no_board_is_final():
    d = decide(snap(board=False))
    assert not d.power_off and d.final


# --- decide: timing ----------------------------------------------------
def test_awake_cap_powers_off_after_a_failed_refresh():
    # Woken 06:55 for 07:00: the deadline is the later of boot+15 and 07:05.
    assert not decide(snap(now=at(7, 9), refreshed=None)).power_off
    d = decide(snap(now=at(7, 10), refreshed=None))
    assert d.power_off and "giving up" in d.reason


def test_awake_cap_outside_a_window():
    boot = at(13, 0)
    assert not decide(snap(now=at(13, 14), boot=boot, refreshed=None)).power_off
    assert decide(snap(now=at(13, 15), boot=boot, refreshed=None)).power_off


def test_refresh_from_before_boot_does_not_count():
    d = decide(snap(now=at(13, 5), boot=at(13, 0), refreshed=at(12, 0)))
    assert not d.power_off


def test_wake_too_close_keeps_it_on():
    """Off at 06:53 with an alarm at 06:55 risks missing the alarm for a day."""
    now = at(6, 55) - timedelta(seconds=MIN_OFF - 1)
    d = decide(snap(now=now, boot=at(6, 0), refreshed=at(6, 10)))
    assert not d.power_off and "too close" in d.reason


def test_up_before_a_window_waits_for_that_slots_refresh():
    """Booted by hand at 06:30: the 06:40 refresh is not the 07:00 one."""
    boot, refreshed = at(6, 30), at(6, 40)
    d = decide(snap(now=at(6, 56), boot=boot, refreshed=refreshed))
    assert not d.power_off and "waiting" in d.reason
    # The timer's 07:00 refresh finishes at 07:01; off after the grace.
    d = decide(snap(now=at(7, 3, 1), boot=boot, refreshed=at(7, 1)))
    assert d.power_off


def test_window_never_gives_up_before_its_slot():
    """Up since 06:00, lead 30: the 06:30-07:00 window waits for the 07:00 timer,
    although boot + AWAKE_CAP (06:15) and window + AWAKE_CAP (06:45) have passed."""
    s = PowerSchedule(wake_lead_minutes=30)
    boot = at(6, 0)
    for now in (at(6, 50), at(6, 59, 59)):
        d = decide(snap(now=now, boot=boot, refreshed=at(6, 10), schedule=s))
        assert not d.power_off and "07:00" in d.reason


def test_woken_by_the_alarm_does_not_wait_for_the_slot():
    s = PowerSchedule(wake_lead_minutes=30)
    d = decide(snap(now=at(6, 35), boot=at(6, 30), refreshed=at(6, 33), schedule=s))
    assert d.power_off


def test_zero_lead():
    s = PowerSchedule(wake_lead_minutes=0)
    d = decide(snap(now=at(7, 4), boot=at(7, 0), refreshed=at(7, 2), schedule=s))
    assert d.power_off
