"""
Carry a display's own files from an old git checkout into the data directory.

Used once, when a Pi that ran from ~/google-calendar-api moves to the
release layout. Files are copied, never moved: the old checkout keeps
working until the new release is proven, and is the way back if not.
Nothing that is already in the data directory is overwritten. File
contents are never logged: the feeds file holds bearer tokens.
"""
import logging
import os
import shutil
import tomllib
from pathlib import Path
from typing import Callable

from gcal_epd.config import DEFAULT_FEEDS_FILE, LOCAL_CONFIG
from gcal_epd.infrastructure.feeds_file import pending_feeds_path

log = logging.getLogger(__name__)

# Written by the PiSugar power schedule (setup form); kept if present.
SCHEDULE_FILE = "power_schedule.toml"
PREVIEW = "preview.png"
LOCAL_CONFIG_NOTE = (
    "# Carried over from {checkout}/config.toml when this display moved to\n"
    "# the release layout. Settings here override the shipped config.toml;\n"
    "# delete any you did not change, so updates can change their defaults.\n"
)


def _feeds_name(config: dict) -> str:
    for source in config.get("sources", []):
        if source.get("type") == "ics":
            return source.get("feeds_file", DEFAULT_FEEDS_FILE)
    return DEFAULT_FEEDS_FILE


def _read_toml(path: Path) -> dict | None:
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return None


def migrate_checkout(checkout: Path, release: Path, data: Path,
                     chown: Callable[[Path], None] = lambda p: None) -> list[str]:
    """Copy the checkout's own files into `data`; returns what was copied.

    - the feeds file (named as in the checkout's config.toml) and any
      links parked by the Wi-Fi form;
    - the power schedule and the last preview, if present;
    - config.toml, as config.local.toml, only if it differs from the one
      the new release ships (someone changed the city, say).

    `chown` gives each copied file to the app's user.
    """
    checkout, data = Path(checkout), Path(data)
    old_config = _read_toml(checkout / "config.toml") or {}
    feeds = _feeds_name(old_config)
    names = [feeds, pending_feeds_path(Path(feeds)).name, SCHEDULE_FILE, PREVIEW,
             LOCAL_CONFIG]
    copied = []
    data.mkdir(parents=True, exist_ok=True)
    for name in names:
        src, dst = checkout / name, data / name
        if not src.is_file():
            continue
        if dst.exists():
            log.info("Kept %s: already in %s.", name, data)
            continue
        shutil.copy2(src, dst)
        chown(dst)
        copied.append(name)

    shipped = _read_toml(release / "config.toml")
    local = data / LOCAL_CONFIG
    if old_config and old_config != shipped and not local.exists():
        text = (checkout / "config.toml").read_text()
        local.write_text(LOCAL_CONFIG_NOTE.format(checkout=checkout) + text)
        os.chmod(local, 0o644)
        chown(local)
        copied.append(f"config.toml -> {LOCAL_CONFIG}")
    return copied
