"""Tests for the power service: what it observes, and what it does first.

The PiSugar, systemd and the clocks are all faked. Times are Asia/Taipei;
the default schedule wakes at 06:55 and 18:55 for 07:00 and 19:00.
"""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from gcal_epd.application.power_service import PowerService
from gcal_epd.domain.power_policy import GRACE, decide
from gcal_epd.domain.power_ports import Activity
from gcal_epd.infrastructure.power.activity import SystemdActivity, classify_processes
from gcal_epd.domain.power_schedule import PowerSchedule
from gcal_epd.infrastructure.power.boards import NullBoard
from gcal_epd.infrastructure.power.pisugar import PiSugar, PiSugar3Board
from gcal_epd.infrastructure.power.system import UnitState
from gcal_epd.infrastructure.power.timer_dropin import apply_schedule
from tests.infrastructure.power.fake_pisugar import FakePiSugarServer

TPE = ZoneInfo("Asia/Taipei")
UTC = timezone.utc
BOARD_WAIT = 15


def at(h, m, s=0, day=19):
    return datetime(2026, 10, day, h, m, s, tzinfo=TPE)


# --- processes ---------------------------------------------------------
def test_classify_processes():
    py = "/home/pi/e-pages/.venv/bin/python"
    assert classify_processes([[py, "-m", "gcal_epd.wifi_setup", "--display"]])[0]
    assert classify_processes([[py, "-m", "gcal_epd.main", "--setup"]])[0]
    setup, refresh = classify_processes([[py, "-m", "gcal_epd.main", "--display"]])
    assert not setup and refresh
    assert classify_processes([["/usr/sbin/sshd"], [py, "-m", "gcal_epd.power_manager"]]) \
        == ("", "")


# --- the manager, with fakes -------------------------------------------
class FakeSystem:
    def __init__(self):
        self.units = {
            "epd-wifi-setup.service": UnitState("inactive", 40.0),
            "gcal-epd.service": UnitState("inactive", 130.0),
            "epd-feed-setup.service": UnitState("inactive", None),
        }
        self.ntp = False
        self.sessions = 0
        self.argvs = []
        self.poweroffs = 0
        self.poweroff_ok = True
        self.reloads = []

    def unit_state(self, unit):
        return self.units.get(unit)

    def ntp_synchronized(self):
        return self.ntp

    def remote_sessions(self):
        return self.sessions

    def command_lines(self):
        return self.argvs

    def poweroff(self):
        self.poweroffs += 1
        return self.poweroff_ok

    def daemon_reload(self):
        self.reloads.append("daemon-reload")
        return True

    def try_restart(self, unit):
        self.reloads.append(unit)
        return True


class Rig:
    """06:55:00 wake-up; monotonic 0 at boot. The refresh ended at 130 s."""

    def __init__(self, tmp_path, now=at(6, 59), uptime=240.0, **server_kw):
        self.server = FakePiSugarServer(**server_kw)
        self.system = FakeSystem()
        self.schedule = PowerSchedule()
        self.t = now
        self.mono = uptime
        self.flag = tmp_path / "epd-stay-awake"
        self.sleeps = []
        self.max_sleeps = 50
        self.manager = PowerService(
            PiSugar3Board(PiSugar(self.server), startup_wait=BOARD_WAIT),
            SystemdActivity(self.system), self.system, self, TPE,
            stay_awake_flag=self.flag, clock=lambda: self.t.astimezone(UTC),
            monotonic=lambda: self.mono, sleep=self.sleep)

    def load(self):  # the rig is its own ScheduleStore
        return self.schedule

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        if len(self.sleeps) > self.max_sleeps:
            raise RuntimeError("still looping")
        self.t += timedelta(seconds=seconds)
        self.mono += seconds


def test_snapshot_converts_monotonic_stamps(tmp_path):
    rig = Rig(tmp_path)
    s = rig.manager.snapshot()
    assert s.now == at(6, 59)
    assert s.boot == at(6, 55)
    assert s.last_refresh == at(6, 57, 10)
    assert s.board and not s.stay_awake and not s.setup and not s.refreshing
    assert s.ssh_sessions == 0


def test_snapshot_sees_busy_units_flag_and_processes(tmp_path):
    rig = Rig(tmp_path)
    rig.system.units["epd-wifi-setup.service"] = UnitState("activating", None)
    rig.system.units["epd-feed-setup.service"] = UnitState("activating", None)
    rig.flag.touch()
    s = rig.manager.snapshot()
    assert s.setup == "epd-wifi-setup.service"
    assert s.refreshing == "epd-feed-setup.service"
    assert s.stay_awake


def test_snapshot_unknown_unit_state_blocks(tmp_path):
    rig = Rig(tmp_path)
    del rig.system.units["gcal-epd.service"]
    s = rig.manager.snapshot()
    assert "unknown" in s.refreshing
    assert not decide(s).power_off


def test_snapshot_hand_run_setup(tmp_path):
    rig = Rig(tmp_path)
    rig.system.argvs = [["python", "-m", "gcal_epd.wifi_setup", "--force"]]
    assert "Wi-Fi setup" in rig.manager.snapshot().setup


def test_run_sets_verified_alarm_then_powers_off(tmp_path):
    rig = Rig(tmp_path)
    assert rig.manager.run() == "powered-off"
    assert rig.system.poweroffs == 1
    assert "rtc_alarm_set 2026-10-19T18:55:00+08:00 127" in rig.server.commands
    assert rig.server.alarm == (10, 55, 0) and rig.server.alarm_enabled


def test_run_writes_ntp_time_to_rtc_before_the_alarm(tmp_path):
    rig = Rig(tmp_path)
    rig.system.ntp = True
    rig.manager.run()
    cmds = rig.server.commands
    assert cmds.index("rtc_pi2rtc") < next(i for i, c in enumerate(cmds)
                                          if c.startswith("rtc_alarm_set"))


def test_run_does_not_write_unsynced_time_to_rtc(tmp_path):
    rig = Rig(tmp_path)
    rig.manager.run()
    assert "rtc_pi2rtc" not in rig.server.commands


def test_alarm_not_verified_never_powers_off(tmp_path):
    rig = Rig(tmp_path)
    rig.server.drop_alarm = True
    rig.max_sleeps = 5
    with pytest.raises(RuntimeError, match="still looping"):
        rig.manager.run()
    assert rig.system.poweroffs == 0
    # It kept trying, in case the failure passes.
    assert sum(c.startswith("rtc_alarm_set") for c in rig.server.commands) >= 5


def test_alarm_refused_never_powers_off(tmp_path):
    rig = Rig(tmp_path)
    rig.server.auto_power_on = True
    assert not rig.manager.arm_and_power_off()
    assert rig.system.poweroffs == 0


def test_alarm_after_pisugar_vanishes_never_powers_off(tmp_path):
    rig = Rig(tmp_path)
    rig.server.up = False
    assert not rig.manager.arm_and_power_off()
    assert rig.system.poweroffs == 0


def test_failed_poweroff_is_reported(tmp_path):
    rig = Rig(tmp_path)
    rig.system.poweroff_ok = False
    assert not rig.manager.arm_and_power_off()


def test_dry_run_neither_sets_the_alarm_nor_powers_off(tmp_path):
    rig = Rig(tmp_path)
    assert rig.manager.run(dry_run=True) == "powered-off"
    assert rig.system.poweroffs == 0
    assert not any(c.startswith("rtc_alarm_set") for c in rig.server.commands)


def test_run_without_pisugar_does_nothing(tmp_path):
    rig = Rig(tmp_path, up=False)
    assert rig.manager.run() == "no-board"
    assert rig.system.poweroffs == 0
    assert sum(rig.sleeps) >= BOARD_WAIT


def test_run_waits_for_pisugar_server_to_come_up(tmp_path):
    rig = Rig(tmp_path, up=False)
    original = rig.sleep

    def sleep(seconds):
        original(seconds)
        if len(rig.sleeps) == 3:
            rig.server.up = True
    rig.manager._sleep = sleep
    assert rig.manager.run() == "powered-off"


def test_run_waits_out_the_refresh_and_the_grace(tmp_path):
    rig = Rig(tmp_path, now=at(6, 56), uptime=60.0)
    rig.system.units["gcal-epd.service"] = UnitState("activating", None)
    original = rig.sleep

    def sleep(seconds):
        original(seconds)
        if rig.t >= at(6, 58):  # the refresh finishes at 06:58
            rig.system.units["gcal-epd.service"] = UnitState("inactive", 180.0)
    rig.manager._sleep = sleep
    assert rig.manager.run() == "powered-off"
    assert rig.t >= at(6, 58) + timedelta(seconds=GRACE)
    assert rig.system.poweroffs == 1


def test_run_stays_on_while_someone_is_logged_in(tmp_path):
    rig = Rig(tmp_path)
    rig.system.sessions = 1
    rig.max_sleeps = 10
    with pytest.raises(RuntimeError):
        rig.manager.run()
    assert rig.system.poweroffs == 0


def test_run_powers_off_once_the_session_ends(tmp_path):
    rig = Rig(tmp_path)
    rig.system.sessions = 1
    original = rig.sleep

    def sleep(seconds):
        original(seconds)
        if len(rig.sleeps) == 3:
            rig.system.sessions = 0
    rig.manager._sleep = sleep
    assert rig.manager.run() == "powered-off"


# --- clock sync --------------------------------------------------------
def test_sync_clock_sets_system_time_from_rtc(tmp_path):
    rig = Rig(tmp_path)  # the system clock says 06:59 on the 19th...
    rig.server.rtc = at(6, 59, 30).astimezone(UTC)  # ...the RTC agrees, a bit later
    rig.manager.sync_clock()
    assert rig.server.commands[-1] == "rtc_rtc2pi"


def test_sync_clock_stale_system_clock_takes_rtc(tmp_path):
    rig = Rig(tmp_path, now=at(10, 0, day=6))  # resumed from 6 Oct
    rig.server.rtc = at(6, 55).astimezone(UTC)
    rig.manager.sync_clock()
    assert "rtc_rtc2pi" in rig.server.commands


@pytest.mark.parametrize("rtc", [datetime(2000, 1, 1, tzinfo=UTC),       # never set
                                 at(5, 0).astimezone(UTC)])            # behind the Pi
def test_sync_clock_ignores_an_implausible_rtc(tmp_path, rtc):
    rig = Rig(tmp_path)
    rig.server.rtc = rtc
    rig.manager.sync_clock()
    assert "rtc_rtc2pi" not in rig.server.commands


def test_sync_clock_ntp_writes_rtc(tmp_path):
    rig = Rig(tmp_path)
    rig.system.ntp = True
    rig.manager.sync_clock()
    assert rig.server.commands == ["rtc_pi2rtc"]


def test_sync_clock_survives_pisugar_errors(tmp_path):
    rig = Rig(tmp_path, up=False)
    rig.manager.sync_clock()  # logged, not raised


# --- status ------------------------------------------------------------
def test_status_reports_everything(tmp_path):
    rig = Rig(tmp_path, now=at(7, 0), uptime=300.0)
    rig.server.plugged = True
    text = "\n".join(rig.manager.status())
    for words in ("reachable", "88%", "Plugged in    yes", "RTC time", "Alarm",
                  "Clock synced  no", "07:00, 19:00 Asia/Taipei", "Next wake",
                  "2026-10-19T18:55:00+08:00", "Decision      power off"):
        assert words in text, words


def test_status_without_pisugar(tmp_path):
    text = "\n".join(Rig(tmp_path, up=False).manager.status())
    assert "not reachable" in text and "stay on" in text


def test_status_survives_pisugar_errors(tmp_path):
    rig = Rig(tmp_path)
    rig.server.errors["battery"] = "I2C bus error"
    assert any("unavailable" in line for line in rig.manager.status())


# --- apply-schedule ----------------------------------------------------
def test_apply_schedule_reloads_only_on_change(tmp_path):
    system = FakeSystem()
    path = tmp_path / "gcal-epd.timer.d" / "power-schedule.conf"
    assert apply_schedule(PowerSchedule(), TPE, system, path)
    assert system.reloads == ["daemon-reload", "gcal-epd.timer"]
    assert not apply_schedule(PowerSchedule(), TPE, system, path)
    assert system.reloads == ["daemon-reload", "gcal-epd.timer"]
    assert apply_schedule(PowerSchedule(slots=(time(8),)), TPE, system, path)
    assert len(system.reloads) == 4


def test_no_pisugar_installed_does_not_wait(tmp_path):
    """A Pi without pisugar-server must not hold up Wi-Fi setup at every boot."""
    rig = Rig(tmp_path, up=False)
    rig.manager.board.startup_wait = 0
    assert rig.manager.run() == "no-board"
    assert rig.sleeps == []


def test_no_board_never_powers_off(tmp_path):
    """board = "none": a mains Pi is managed by nobody and stays on."""
    rig = Rig(tmp_path)
    rig.manager.board = NullBoard()
    assert rig.manager.run() == "no-board"
    assert rig.system.poweroffs == 0 and rig.sleeps == []
    assert "not reachable" in "\n".join(rig.manager.status())


def test_any_activity_probe_will_do(tmp_path):
    """The service needs an ActivityProbe, not systemd: a plain fake works."""
    class Busy:
        def activity(self):
            return Activity(refreshing="a refresh", last_refresh_end=130.0)
    rig = Rig(tmp_path)
    rig.manager.activity = Busy()
    s = rig.manager.snapshot()
    assert s.refreshing == "a refresh" and s.last_refresh == at(6, 57, 10)
    assert not decide(s).power_off
