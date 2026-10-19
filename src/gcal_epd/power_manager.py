"""
Power manager for a display on a PiSugar 3 battery.

The Pi is off most of the day. The PiSugar's RTC alarm switches it on a few
minutes before each slot of the power schedule; it boots, joins Wi-Fi and
redraws the calendar, and then this sets the alarm for the next wake-up
and powers off. The e-paper keeps its image without power.

Runs at boot as root (deploy/epd-power.service):

    python -m gcal_epd.power_manager boot            # clock from RTC, timer drop-in
    python -m gcal_epd.power_manager run             # wait for the refresh, then off
    python -m gcal_epd.power_manager run --dry-run   # decide, never power off
    python -m gcal_epd.power_manager status          # what it sees and would do
    python -m gcal_epd.power_manager apply-schedule  # gcal-epd.timer follows the slots

Powering off is the risky step, so it is refused whenever in doubt: a
person may be setting the display up or logged in, a refresh may be
drawing, or the alarm may not have taken (the Pi would never wake again).
Without a PiSugar (pisugar-server not answering) it does nothing at all,
and the Pi behaves as the always-on display it was before.

To keep a battery Pi on for debugging, create the stay-awake flag on the
boot partition from any computer: an empty file named `epd-stay-awake`.
"""
import argparse
import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from gcal_epd.domain.power_schedule import PowerSchedule, format_slot
from gcal_epd.infrastructure.power.pisugar import EVERY_DAY, PiSugar, PiSugarError
from gcal_epd.infrastructure.power.system import System
from gcal_epd.infrastructure.power.timer_dropin import DROPIN, TIMER_UNIT, write_dropin

log = logging.getLogger(__name__)

GRACE = 120            # seconds to stay up after the refresh, for a quick SSH check
AWAKE_CAP = 900        # give up on a refresh this long after waking, to save battery
MIN_OFF = 180          # never power off for a wake-up closer than this: shutdown
                       # takes ~30 s on a Zero, and a missed alarm waits a day
POLL = 20              # seconds between checks
PISUGAR_WAIT = 15      # seconds for pisugar-server to answer at boot
STAY_AWAKE_FLAG = Path("/boot/firmware/epd-stay-awake")
REFRESH_UNITS = ("gcal-epd.service", "epd-feed-setup.service")
SETUP_UNITS = ("epd-wifi-setup.service",)
# An RTC older than this was never set (or lost its battery): not a clock.
RTC_FLOOR = datetime(2026, 1, 1, tzinfo=timezone.utc)
RTC_BEHIND = timedelta(minutes=5)


def _hm(when: datetime) -> str:
    return when.strftime("%H:%M")


@dataclass(frozen=True)
class Snapshot:
    """Everything the decision depends on, gathered at one moment."""
    now: datetime                 # aware, in the schedule's timezone
    boot: datetime                # when this boot began
    schedule: PowerSchedule
    pisugar: bool = True          # pisugar-server answers
    stay_awake: bool = False      # the flag file exists
    setup: str = ""               # a setup that is running, "" if none
    refreshing: str = ""          # a refresh that is running, "" if none
    ssh_sessions: int | None = 0  # None: cannot tell
    last_refresh: datetime | None = None  # when a refresh last finished


@dataclass(frozen=True)
class Decision:
    power_off: bool
    reason: str
    final: bool = False  # nothing to manage on this Pi: stop watching


def decide(s: Snapshot) -> Decision:
    """Whether to power off now, and why. Pure, so every rule is testable.

    The reasons to stay on come first, in order of who would be hurt: no
    PiSugar (nothing could switch the Pi back on), the user's choices, a
    person at the display, a refresh drawing. Only then the timing.
    """
    if not s.pisugar:
        return Decision(False, "pisugar-server is not reachable: no PiSugar, "
                               "so this Pi stays always on", final=True)
    if not s.schedule.enabled:
        return Decision(False, "the power schedule is turned off")
    if s.stay_awake:
        return Decision(False, f"the stay-awake flag {STAY_AWAKE_FLAG} exists")
    if s.setup:
        return Decision(False, f"{s.setup} is running: someone is setting up")
    if s.ssh_sessions is None:
        return Decision(False, "cannot tell whether someone is logged in over SSH")
    if s.ssh_sessions:
        return Decision(False, f"{s.ssh_sessions} SSH session(s) open")
    if s.refreshing:
        return Decision(False, f"{s.refreshing} is running")

    schedule, now = s.schedule, s.now
    wake = schedule.next_wake(now)
    if wake - now < timedelta(seconds=MIN_OFF):
        return Decision(False, f"the next wake-up ({_hm(wake)}) is too close to power "
                               f"off for; staying on for that refresh")

    # Inside a wake-up window (between a wake-up and its slot) the refresh
    # must be one for this slot: one that ended after the window opened.
    # Outside, any refresh since boot will do.
    slot = schedule.next_slot(now)
    in_window = schedule.lead and slot - now <= schedule.lead
    required = max(s.boot, slot - schedule.lead) if in_window else s.boot
    deadline = required + timedelta(seconds=AWAKE_CAP)
    if in_window:
        deadline = max(deadline, slot)  # never give up before the timer's refresh

    if s.last_refresh is not None and s.last_refresh >= required:
        done = s.last_refresh + timedelta(seconds=GRACE)
        if now >= done:
            return Decision(True, f"the refresh finished at {_hm(s.last_refresh)}")
        return Decision(False, f"the refresh finished; grace period until {_hm(done)}")
    if now >= deadline:
        return Decision(True, f"no refresh finished since {_hm(required)}; "
                              f"giving up to save the battery")
    return Decision(False, f"waiting for the refresh (gives up at {_hm(deadline)})")


def classify_processes(argvs: list[list[str]]) -> tuple[str, str]:
    """(setup, refresh) found among running processes, "" for none."""
    setup = refresh = ""
    for argv in argvs:
        if "gcal_epd.wifi_setup" in argv:
            setup = "Wi-Fi setup (gcal_epd.wifi_setup)"
        elif "gcal_epd.main" in argv:
            if "--setup" in argv:
                setup = setup or "calendar setup (gcal_epd.main --setup)"
            else:
                refresh = "a calendar refresh (gcal_epd.main)"
    return setup, refresh


class PowerManager:
    def __init__(self, pisugar: PiSugar, system: System,
                 load_schedule: Callable[[], PowerSchedule], tz: ZoneInfo, *,
                 stay_awake_flag: Path = STAY_AWAKE_FLAG,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 monotonic: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.pisugar = pisugar
        self.system = system
        self._load_schedule = load_schedule
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

        setup = refreshing = ""
        for unit in SETUP_UNITS:
            state = self.system.unit_state(unit)
            if state is None:
                setup = f"{unit} (state unknown)"
            elif state.busy:
                setup = unit
        last_refresh = None
        for unit in REFRESH_UNITS:
            state = self.system.unit_state(unit)
            if state is None:
                refreshing = f"{unit} (state unknown)"
                continue
            if state.busy:
                refreshing = unit
            if state.last_exit is not None:
                ended = wall(state.last_exit)
                last_refresh = max(last_refresh or ended, ended)
        proc_setup, proc_refresh = classify_processes(self.system.command_lines())

        return Snapshot(
            now=now,
            boot=wall(0),
            schedule=self._load_schedule(),
            pisugar=self.pisugar.available(),
            stay_awake=self._flag.exists(),
            setup=setup or proc_setup,
            refreshing=refreshing or proc_refresh,
            ssh_sessions=self.system.remote_sessions(),
            last_refresh=last_refresh,
        )

    def wait_for_pisugar(self, timeout: float = PISUGAR_WAIT) -> bool:
        """pisugar-server starts alongside us at boot; give it a moment."""
        deadline = self._monotonic() + timeout
        while not self.pisugar.available():
            if self._monotonic() >= deadline:
                return False
            self._sleep(1)
        return True

    # --- acting -----------------------------------------------------
    def sync_clock(self) -> None:
        """Put the right time on whichever clock lacks it.

        The Pi has no RTC of its own and boots with the time it shut down
        at, so until NTP syncs it takes the PiSugar's RTC time. Once NTP has
        synced, the RTC is corrected from it instead: the alarm fires by the
        RTC, so the RTC is the clock that must be right.
        """
        synced = self.system.ntp_synchronized()
        try:
            if synced:
                self.pisugar.pi_to_rtc()
                log.info("System clock is NTP-synchronised; wrote it to the RTC.")
                return
            rtc = self.pisugar.rtc_time()
            system_now = self._clock()
            if rtc < RTC_FLOOR or rtc < system_now - RTC_BEHIND:
                log.warning("RTC reads %s, behind the system clock (%s); "
                            "not using it. Waiting for NTP.", rtc.isoformat(),
                            system_now.isoformat())
                return
            self.pisugar.rtc_to_pi()
            log.info("System clock set from the RTC: %s", rtc.isoformat())
        except PiSugarError as e:
            log.warning("Could not sync the clock with the PiSugar RTC: %s", e)

    def arm_and_power_off(self, dry_run: bool = False) -> bool:
        """Set the alarm for the next wake-up, verify it, then power off.

        Returns False, leaving the Pi on, if the alarm could not be set and
        read back: off without an alarm, it would never come back on.
        """
        try:
            if self.system.ntp_synchronized():
                self.pisugar.pi_to_rtc()  # the alarm fires by the RTC
        except PiSugarError as e:
            log.warning("Could not write the system time to the RTC: %s", e)
        now = self.now()
        wake = self._load_schedule().next_wake(now)
        if dry_run:
            log.info("Dry run: would set the wake-up alarm for %s and power off.",
                     wake.isoformat())
            return True
        try:
            self.pisugar.set_alarm_verified(wake, EVERY_DAY)
        except PiSugarError as e:
            log.error("NOT powering off: the wake-up alarm for %s could not be set "
                      "and verified (%s). Staying on, or the Pi would never wake.",
                      wake.isoformat(), e)
            return False
        log.info("Wake-up alarm set for %s (repeats daily as a safety net). "
                 "Powering off.", wake.isoformat())
        if not self.system.poweroff():
            log.error("systemctl poweroff failed; staying on.")
            return False
        return True

    def run(self, dry_run: bool = False, poll: float = POLL) -> str:
        """Watch until it is time to power off. Returns why it stopped:
        "no-pisugar" or "powered-off" (in a dry run: would have)."""
        if not self.wait_for_pisugar():
            log.info("pisugar-server is not reachable: no PiSugar, nothing to manage.")
            return "no-pisugar"
        try:
            log.info("PiSugar: battery %.0f%%, plugged in: %s",
                     self.pisugar.battery(), self.pisugar.power_plugged())
        except PiSugarError as e:
            log.warning("Could not read the battery: %s", e)

        last_reason = None
        while True:
            decision = decide(self.snapshot())
            if decision.final:
                log.info("%s", decision.reason)
                return "no-pisugar"
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
        lines = []

        def ask(label: str, read: Callable[[], object]) -> None:
            try:
                value = read()
            except PiSugarError as e:
                value = f"unavailable ({e})"
            lines.append(f"{label:<14}{value}")

        reachable = self.pisugar.available()
        lines.append(f"{'PiSugar':<14}{'reachable' if reachable else 'not reachable'}")
        if reachable:
            ask("Battery", lambda: f"{self.pisugar.battery():.0f}%")
            ask("Plugged in", lambda: "yes" if self.pisugar.power_plugged() else "no")
            ask("RTC time", lambda: self.pisugar.rtc_time().astimezone(self.tz).isoformat())
            ask("Alarm", lambda: (
                f"{_hm(self.pisugar.alarm_time().astimezone(self.tz))} "
                f"({'enabled' if self.pisugar.alarm_enabled() else 'disabled'}, "
                f"repeat mask {self.pisugar.alarm_repeat()})"))
        synced = self.system.ntp_synchronized()
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


def apply_schedule(schedule: PowerSchedule, tz: ZoneInfo, system: System,
                   path: Path = DROPIN) -> bool:
    """Point gcal-epd.timer at the schedule's slots; True if that changed it."""
    if not write_dropin(schedule, tz, path):
        log.info("%s already follows the schedule.", TIMER_UNIT)
        return False
    system.daemon_reload()
    system.try_restart(TIMER_UNIT)
    log.info("%s now fires at %s (%s).", TIMER_UNIT,
             ", ".join(format_slot(s) for s in schedule.slots), tz.key)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Power manager for a PiSugar 3 battery")
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="wait for the refresh, set the alarm, power off")
    run_p.add_argument("--dry-run", action="store_true", help="decide, but never power off")
    sub.add_parser("status", help="show the battery, clocks, alarm and decision")
    sub.add_parser("sync-clock", help="set the clock from the RTC, or the RTC from NTP")
    sub.add_parser("apply-schedule", help="make gcal-epd.timer fire at the schedule's slots")
    sub.add_parser("boot", help="sync-clock, then apply-schedule (run at boot)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")  # not at import

    from gcal_epd.config import load_config, power_timezone, schedule_file
    from gcal_epd.infrastructure.schedule_file import load_schedule

    config = load_config()
    tz = power_timezone(config)
    path = schedule_file(config)
    system = System()
    manager = PowerManager(PiSugar(), system, lambda: load_schedule(path), tz)

    if args.command == "status":
        print("\n".join(manager.status()))
        return 0
    if args.command in ("sync-clock", "boot"):
        if manager.wait_for_pisugar():
            manager.sync_clock()
        else:
            log.info("pisugar-server is not reachable: no RTC to sync with.")
    if args.command in ("apply-schedule", "boot"):
        try:
            apply_schedule(load_schedule(path), tz, system)
        except OSError as e:
            log.error("Could not write %s: %s (run as root)", DROPIN, e)
            return 1
    if args.command == "run":
        manager.run(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
