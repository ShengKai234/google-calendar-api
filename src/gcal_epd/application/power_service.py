"""
The power service: watch this boot, then arm the wake-up board and power off.

It observes the Pi (the WakeBoard, an ActivityProbe, the stay-awake flag;
all interfaces from domain/power_ports.py), asks the
rules in domain/power_policy.py, and acts: sets the clock, sets the alarm,
powers off. power_manager.py is only its command line and wiring.

To keep a battery Pi on for debugging, create the stay-awake flag on the
boot partition from any computer: an empty file named `epd-stay-awake`.
"""
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from gcal_epd.domain.power_policy import Snapshot, decide
from gcal_epd.domain.power_ports import (
    ActivityProbe,
    HostControl,
    ScheduleStore,
    WakeBoard,
    WakeBoardError,
)
from gcal_epd.domain.power_schedule import format_slot

log = logging.getLogger(__name__)

POLL = 20              # seconds between checks
STAY_AWAKE_FLAG = Path("/boot/firmware/epd-stay-awake")
# An RTC older than this was never set (or lost its battery): not a clock.
RTC_FLOOR = datetime(2026, 1, 1, tzinfo=timezone.utc)
RTC_BEHIND = timedelta(minutes=5)


class PowerService:
    def __init__(self, board: WakeBoard, activity: ActivityProbe, host: HostControl,
                 schedules: ScheduleStore, tz: ZoneInfo, *,
                 stay_awake_flag: Path = STAY_AWAKE_FLAG,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 monotonic: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.board = board
        self.activity = activity
        self.host = host
        self.schedules = schedules
        self.tz = tz
        self._flag = stay_awake_flag
        self._clock = clock
        self._monotonic = monotonic
        self._sleep = sleep

    def now(self) -> datetime:
        return self._clock().astimezone(self.tz)

    # --- observing --------------------------------------------------
    def snapshot(self) -> Snapshot:
        now, mono = self.now(), self._monotonic()

        def wall(monotonic_s: float) -> datetime:
            # systemd stamps with CLOCK_MONOTONIC, which no clock change moves:
            # safe across the jump when the clock is set from the RTC or NTP.
            return now - timedelta(seconds=mono - monotonic_s)

        busy = self.activity.activity()
        last_refresh = (None if busy.last_refresh_end is None
                        else wall(busy.last_refresh_end))

        return Snapshot(
            now=now,
            boot=wall(0),
            schedule=self.schedules.load(),
            board=self.board.available(),
            stay_awake=self._flag.exists(),
            setup=busy.setup,
            refreshing=busy.refreshing,
            ssh_sessions=busy.ssh_sessions,
            last_refresh=last_refresh,
            updating=busy.updating,
            update_due=(None if busy.update_next is None else
                        datetime.fromtimestamp(busy.update_next, timezone.utc)
                        .astimezone(self.tz)),
        )

    def wait_for_board(self) -> bool:
        """The board's service starts alongside us at boot; give it a moment."""
        deadline = self._monotonic() + self.board.startup_wait
        while not self.board.available():
            if self._monotonic() >= deadline:
                return False
            self._sleep(1)
        return True

    # --- acting -----------------------------------------------------
    def sync_clock(self) -> None:
        """Put the right time on whichever clock lacks it.

        The Pi has no RTC of its own and boots with the time it shut down
        at, so until NTP syncs it takes the board's RTC time. Once NTP has
        synced, the RTC is corrected from it instead: the alarm fires by the
        RTC, so the RTC is the clock that must be right.
        """
        synced = self.host.ntp_synchronized()
        try:
            if synced:
                self.board.system_to_rtc()
                log.info("System clock is NTP-synchronised; wrote it to the RTC.")
                return
            rtc = self.board.rtc_time()
            system_now = self._clock()
            if rtc < RTC_FLOOR or rtc < system_now - RTC_BEHIND:
                log.warning("RTC reads %s, behind the system clock (%s); "
                            "not using it. Waiting for NTP.", rtc.isoformat(),
                            system_now.isoformat())
                return
            self.board.rtc_to_system()
            log.info("System clock set from the RTC: %s", rtc.isoformat())
        except WakeBoardError as e:
            log.warning("Could not sync the clock with the %s RTC: %s", self.board.name, e)

    def arm_and_power_off(self, dry_run: bool = False) -> bool:
        """Set the alarm for the next wake-up, verify it, then power off.

        Returns False, leaving the Pi on, if the alarm could not be set and
        read back: off without an alarm, it would never come back on.
        """
        try:
            if self.host.ntp_synchronized():
                self.board.system_to_rtc()  # the alarm fires by the RTC
        except WakeBoardError as e:
            log.warning("Could not write the system time to the RTC: %s", e)
        now = self.now()
        wake = self.schedules.load().next_wake(now)
        if dry_run:
            log.info("Dry run: would set the wake-up alarm for %s and power off.",
                     wake.isoformat())
            return True
        try:
            self.board.arm(wake)
        except WakeBoardError as e:
            log.error("NOT powering off: the wake-up alarm for %s could not be set "
                      "and verified (%s). Staying on, or the Pi would never wake.",
                      wake.isoformat(), e)
            return False
        log.info("Wake-up alarm set for %s. Powering off.", wake.isoformat())
        if not self.host.poweroff():
            log.error("systemctl poweroff failed; staying on.")
            return False
        return True

    def run(self, dry_run: bool = False, poll: float = POLL) -> str:
        """Watch until it is time to power off. Returns why it stopped:
        "no-board" or "powered-off" (in a dry run: would have)."""
        if not self.wait_for_board():
            log.info("%s does not answer: nothing to manage.", self.board.name)
            return "no-board"
        for label, value in self.board.report(self.tz):
            log.info("%s: %s %s", self.board.name, label, value)

        last_reason = None
        while True:
            decision = decide(self.snapshot())
            if decision.final:
                log.info("%s", decision.reason)
                return "no-board"
            if decision.power_off:
                log.info("Time to power off: %s.", decision.reason)
                if self.arm_and_power_off(dry_run):
                    return "powered-off"
                last_reason = None
            elif decision.reason != last_reason:
                log.info("Staying on: %s.", decision.reason)
                last_reason = decision.reason
            self._sleep(poll)

    def status(self) -> list[str]:
        """A report for a person at an SSH prompt."""
        reachable = self.board.available()
        lines = [f"{'Board':<14}{self.board.name}, "
                 f"{'reachable' if reachable else 'not reachable'}"]
        if reachable:
            lines += [f"{label:<14}{value}" for label, value in self.board.report(self.tz)]
        synced = self.host.ntp_synchronized()
        lines.append(f"{'Clock synced':<14}"
                     f"{'unknown' if synced is None else 'yes' if synced else 'no'}")
        s = self.snapshot()
        slots = ", ".join(format_slot(t) for t in s.schedule.slots)
        lines.append(f"{'Schedule':<14}{slots} {self.tz.key}, wake {s.schedule.wake_lead_minutes}"
                     f" min early, {'on' if s.schedule.enabled else 'off'}")
        lines.append(f"{'Next wake':<14}{s.schedule.next_wake(s.now).isoformat()}")
        lines.append(f"{'Awake since':<14}{s.boot.isoformat(timespec='seconds')}")
        d = decide(s)
        lines.append(f"{'Decision':<14}{'power off' if d.power_off else 'stay on'}: {d.reason}")
        return lines
