"""
Which page the display shows, kept in DATA_DIR/display_mode.toml:

    mode = "privacy"                      # or "calendar"
    since = "2026-11-22T19:30:00+08:00"

A single press of the PiSugar button toggles it (gcal_epd.buttons); every
refresh after that, timed, at boot or a double press, draws that page, so
a wake-up while guests are over does not bring the events back. No file
means the calendar. A file that cannot be read means the privacy page:
when in doubt, never show the events.
"""
import logging
import os
import tomllib
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

MODE_FILE = "display_mode.toml"
CALENDAR = "calendar"
PRIVACY = "privacy"
MODES = (CALENDAR, PRIVACY)


def load_mode(path: Path) -> str:
    """The page to show. Only a path with nothing at all there means the
    calendar; anything there that does not say which page means privacy.
    The file's contents are never logged: a corrupted file may hold anything.
    """
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        if path.is_symlink():   # a link to nothing: something is there
            log.warning("%s is a broken link: showing the privacy page.", path.name)
            return PRIVACY
        return CALENDAR
    except OSError as e:
        log.warning("Cannot read %s (%s): showing the privacy page.",
                    path.name, type(e).__name__)
        return PRIVACY
    try:
        mode = tomllib.loads(data.decode()).get("mode")
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        log.warning("%s is not valid TOML: showing the privacy page.", path.name)
        return PRIVACY
    if mode not in MODES:
        log.warning("%s names no known page (%s): showing the privacy page.",
                    path.name, ", ".join(MODES))
        return PRIVACY
    return mode


def save_mode(path: Path, mode: str, now: datetime | None = None) -> None:
    if mode not in MODES:
        raise ValueError(f"unknown display mode {mode!r}")
    since = (now or datetime.now().astimezone()).isoformat(timespec="seconds")
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(f'mode = "{mode}"\nsince = "{since}"\n')
    os.replace(tmp, path)  # a reader sees the old file or the new, never half


def toggle(path: Path) -> str:
    """Switch to the other page; returns the new mode."""
    mode = CALENDAR if load_mode(path) == PRIVACY else PRIVACY
    save_mode(path, mode)
    return mode
