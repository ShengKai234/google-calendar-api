"""Tests for the gcal-epd.timer drop-in that follows the power schedule."""
from datetime import time
from zoneinfo import ZoneInfo

from gcal_epd.domain.power_schedule import PowerSchedule
from gcal_epd.infrastructure.power.timer_dropin import render_dropin, write_dropin

TPE = ZoneInfo("Asia/Taipei")


def test_render_resets_then_lists_each_slot():
    text = render_dropin(PowerSchedule(slots=(time(19), time(6, 30))), TPE)
    lines = [line for line in text.splitlines() if not line.startswith("#")]
    assert lines == ["[Timer]", "OnCalendar=",
                     "OnCalendar=*-*-* 06:30:00 Asia/Taipei",
                     "OnCalendar=*-*-* 19:00:00 Asia/Taipei"]


def test_write_reports_change_only_once(tmp_path):
    path = tmp_path / "gcal-epd.timer.d" / "power-schedule.conf"
    assert write_dropin(PowerSchedule(), TPE, path)
    assert path.read_text() == render_dropin(PowerSchedule(), TPE)
    assert oct(path.stat().st_mode & 0o777) == "0o644"
    assert not write_dropin(PowerSchedule(), TPE, path)
    assert write_dropin(PowerSchedule(slots=(time(8),)), TPE, path)
    assert "08:00:00" in path.read_text()
    assert not (path.parent / "power-schedule.conf.tmp").exists()


def test_disabled_schedule_still_drives_the_timer(tmp_path):
    """A mains-powered Pi refreshes by the timer, whatever the power-off switch says."""
    path = tmp_path / "d.conf"
    write_dropin(PowerSchedule(enabled=False), TPE, path)
    assert "07:00:00" in path.read_text()
