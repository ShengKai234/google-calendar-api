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
"""
import logging
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from gcal_epd.domain.power_schedule import PowerSchedule, format_slot

log = logging.getLogger(__name__)

TIMER_UNIT = "gcal-epd.timer"
DROPIN = Path("/etc/systemd/system") / f"{TIMER_UNIT}.d" / "power-schedule.conf"


def render_dropin(schedule: PowerSchedule, tz: ZoneInfo) -> str:
    lines = [
        "# Written by `python -m gcal_epd.power_manager apply-schedule` from the",
        "# power schedule (setup form). Edits here are overwritten.",
        "[Timer]",
        "OnCalendar=",
    ]
    lines += [f"OnCalendar=*-*-* {format_slot(s)}:00 {tz.key}" for s in schedule.slots]
    return "\n".join(lines) + "\n"


def write_dropin(schedule: PowerSchedule, tz: ZoneInfo, path: Path = DROPIN) -> bool:
    """Write the drop-in; True if it changed (so the timer needs a reload)."""
    text = render_dropin(schedule, tz)
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
