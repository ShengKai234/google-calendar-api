"""
Make gcal-epd.timer fire at the slots of the power schedule.

The timer unit installed from deploy/ holds the default 07:00 / 19:00. The
slots chosen on the setup form go into a drop-in instead, so reinstalling
the unit never loses them and the unit file stays a plain template. On a
Pi that is never powered off (mains, no PiSugar) the timer is what
refreshes the panel; on a PiSugar it refreshes once more if the Pi is
still up at the slot.

    [Timer]
    OnCalendar=
    OnCalendar=*-*-* 07:00:00 Asia/Taipei

The empty OnCalendar= first clears the unit's own lines (systemd.timer(5):
"If the empty string is assigned to any of these options, the list of
timers is reset").

epd-update.timer (installed releases) gets a drop-in too: one update check
a day, a minute after the LAST slot, so it follows that slot's refresh and
the Pi is awake anyway. Never at another slot (the morning one is for
reading the calendar, not for a five-minute build), and a check missed
while the Pi was off is not made up at the next boot.
"""
import logging
import os
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from gcal_epd.domain.power_schedule import PowerSchedule, format_slot

log = logging.getLogger(__name__)

TIMER_UNIT = "gcal-epd.timer"
DROPIN = Path("/etc/systemd/system") / f"{TIMER_UNIT}.d" / "power-schedule.conf"
UPDATE_TIMER = "epd-update.timer"
UPDATE_DROPIN = Path("/etc/systemd/system") / f"{UPDATE_TIMER}.d" / "power-schedule.conf"
UPDATE_AFTER = timedelta(minutes=1)   # epd-update.service also waits for the refresh
_HEADER = [
    "# Written by `python -m gcal_epd.power_manager apply-schedule` from the",
    "# power schedule (setup form). Edits here are overwritten.",
]


def update_time(schedule: PowerSchedule) -> time:
    """When the daily update check runs: just after the last slot."""
    last = datetime.combine(datetime.min.date(), schedule.slots[-1]) + UPDATE_AFTER
    return last.time()


def render_dropin(schedule: PowerSchedule, tz: ZoneInfo) -> str:
    lines = _HEADER + ["[Timer]", "OnCalendar="]
    lines += [f"OnCalendar=*-*-* {format_slot(s)}:00 {tz.key}" for s in schedule.slots]
    return "\n".join(lines) + "\n"


def render_update_dropin(schedule: PowerSchedule, tz: ZoneInfo) -> str:
    lines = _HEADER + ["[Timer]", "OnCalendar=",
                       f"OnCalendar=*-*-* {format_slot(update_time(schedule))}:00 {tz.key}",
                       "RandomizedDelaySec=0", "Persistent=false"]
    return "\n".join(lines) + "\n"


def write_dropin(schedule: PowerSchedule, tz: ZoneInfo, path: Path = DROPIN,
                 render=render_dropin) -> bool:
    """Write the drop-in; True if it changed (so the timer needs a reload)."""
    text = render(schedule, tz)
    try:
        if path.read_text() == text:
            return False
    except OSError:
        pass  # missing or unreadable: write it
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    tmp.chmod(0o644)
    os.replace(tmp, path)
    return True


def apply_schedule(schedule: PowerSchedule, tz: ZoneInfo, system,
                   path: Path = DROPIN, update_path: Path = UPDATE_DROPIN) -> bool:
    """Point gcal-epd.timer at the schedule's slots and epd-update.timer just
    after the last one; True if that changed either."""
    refresh = write_dropin(schedule, tz, path)
    update = write_dropin(schedule, tz, update_path, render_update_dropin)
    if not (refresh or update):
        log.info("%s and %s already follow the schedule.", TIMER_UNIT, UPDATE_TIMER)
        return False
    system.daemon_reload()
    if refresh:
        system.try_restart(TIMER_UNIT)
        log.info("%s now fires at %s (%s).", TIMER_UNIT,
                 ", ".join(format_slot(s) for s in schedule.slots), tz.key)
    if update:
        system.try_restart(UPDATE_TIMER)   # stopped (not installed): left alone
        log.info("%s now fires at %s (%s).", UPDATE_TIMER,
                 format_slot(update_time(schedule)), tz.key)
    return True
