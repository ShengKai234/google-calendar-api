"""
The power schedule on disk — one small TOML file, owned by this module.

Written by the setup forms (as the checkout's owner, or as root from the
Wi-Fi setup), read by the power manager (root). Not a secret, unlike the
feeds file. A missing file means the default 07:00 / 19:00.

    enabled = true
    wake_lead_minutes = 5
    slots = ["07:00", "19:00"]
"""
import logging
import os
import tomllib
from pathlib import Path

from gcal_epd.domain.power_schedule import PowerSchedule, format_slot, parse_slot

log = logging.getLogger(__name__)


def render_schedule(schedule: PowerSchedule) -> str:
    slots = ", ".join(f'"{format_slot(s)}"' for s in schedule.slots)
    return (
        "# Power schedule for the e-Paper display. Edit through the setup form.\n"
        f"enabled = {'true' if schedule.enabled else 'false'}\n"
        f"wake_lead_minutes = {schedule.wake_lead_minutes}\n"
        f"slots = [{slots}]\n"
    )


def read_schedule(path: Path) -> PowerSchedule:
    """The schedule in `path`, or the default if there is no file.

    Raises ValueError if the file exists but is not a valid schedule.
    """
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        return PowerSchedule()
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"{path} is not valid TOML: {e}") from None
    try:
        slots = tuple(parse_slot(s) for s in data.get("slots", []))
        return PowerSchedule(
            slots=slots or PowerSchedule().slots,
            enabled=bool(data.get("enabled", True)),
            wake_lead_minutes=int(data.get("wake_lead_minutes", PowerSchedule().wake_lead_minutes)),
        )
    except (TypeError, ValueError, AttributeError) as e:
        raise ValueError(f"{path}: {e}") from None


def load_schedule(path: Path) -> PowerSchedule:
    """Like read_schedule, but a broken file falls back to the default.

    For the power manager: a typo must never leave the Pi without a wake-up.
    """
    try:
        return read_schedule(path)
    except ValueError as e:
        log.warning("Using the default power schedule: %s", e)
        return PowerSchedule()


def write_schedule(path: Path, schedule: PowerSchedule, owner_of=None, chown=os.chown) -> None:
    """Write atomically (a reader never sees half a file), mode 644.

    `owner_of`: when written as root (Wi-Fi setup), hand the file to the
    owner of that path, as feeds_file.write_pending_feeds does.
    """
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(render_schedule(schedule))
    tmp.chmod(0o644)
    if owner_of is not None:
        st = Path(owner_of).stat()
        chown(tmp, st.st_uid, st.st_gid)
    os.replace(tmp, path)
