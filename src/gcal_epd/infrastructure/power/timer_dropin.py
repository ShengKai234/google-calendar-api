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

The update check has no timer: epd-update.service runs after each refresh
(deploy/epd-update.service). Earlier releases had an epd-update.timer with
a drop-in written here; apply-schedule removes that leftover drop-in.
"""
import logging
import os
import shutil
from pathlib import Path
from zoneinfo import ZoneInfo

from gcal_epd.domain.power_schedule import PowerSchedule, format_slot

log = logging.getLogger(__name__)

TIMER_UNIT = "gcal-epd.timer"
DROPIN = Path("/etc/systemd/system") / f"{TIMER_UNIT}.d" / "power-schedule.conf"
# Left by earlier releases, which checked for updates from a timer.
OLD_UPDATE_DROPIN = Path("/etc/systemd/system/epd-update.timer.d/power-schedule.conf")
_HEADER = [
    "# Written by `python -m gcal_epd.power_manager apply-schedule` from the",
    "# power schedule (setup form). Edits here are overwritten.",
]


def render_dropin(schedule: PowerSchedule, tz: ZoneInfo) -> str:
    lines = _HEADER + ["[Timer]", "OnCalendar="]
    lines += [f"OnCalendar=*-*-* {format_slot(s)}:00 {tz.key}" for s in schedule.slots]
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


def remove_old_update_dropin(path: Path = OLD_UPDATE_DROPIN) -> bool:
    """Delete epd-update.timer's drop-in (and its folder); True if it existed."""
    if not path.exists():
        return False
    shutil.rmtree(path.parent, ignore_errors=True)
    log.info("Removed %s: the update check follows each refresh now.", path)
    return True


def apply_schedule(schedule: PowerSchedule, tz: ZoneInfo, system,
                   path: Path = DROPIN, old_update_path: Path = OLD_UPDATE_DROPIN) -> bool:
    """Point gcal-epd.timer at the schedule's slots (and drop the old update
    timer's drop-in); True if that changed anything."""
    refresh = write_dropin(schedule, tz, path)
    leftover = remove_old_update_dropin(old_update_path)
    if not (refresh or leftover):
        log.info("%s already follows the schedule.", TIMER_UNIT)
        return False
    system.daemon_reload()
    if refresh:
        system.try_restart(TIMER_UNIT)
        log.info("%s now fires at %s (%s).", TIMER_UNIT,
                 ", ".join(format_slot(s) for s in schedule.slots), tz.key)
    return True
