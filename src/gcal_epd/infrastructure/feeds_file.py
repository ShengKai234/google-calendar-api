"""
The feeds file: the gitignored TOML that holds the calendar feed URLs.

Each URL is a bearer token — anyone holding one can read that calendar — so
the URLs live here rather than in the tracked config.toml. Reading, writing
and deleting the file all sit in this one module so its format has a single
owner; the setup form writes it, the calendar refresh reads it.
"""
import logging
import os
import tomllib
from pathlib import Path

log = logging.getLogger(__name__)

EXAMPLE_FILE = "ics_feeds.example.toml"


def load_feeds(path: Path) -> list[dict]:
    """The `[[feed]]` entries, or [] if the file is missing or unreadable."""
    path = Path(path)
    try:
        with open(path, "rb") as f:
            return tomllib.load(f).get("feed", [])
    except FileNotFoundError:
        # Normal on a new display: setup has simply not run yet.
        log.info(
            "No calendar feeds yet (%s does not exist). Add them with "
            "--setup, or copy %s to %s.",
            path.name, EXAMPLE_FILE, path.name,
        )
        return []
    except tomllib.TOMLDecodeError as e:
        log.error("Could not parse %s: %s", path.name, e)
        return []


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def render_feeds_toml(feeds: list[dict]) -> str:
    lines = [
        "# Written by the onboarding server. Each URL is a bearer token —",
        "# anyone holding one can read that calendar. Never commit this file.",
        "",
    ]
    for feed in feeds:
        lines.append("[[feed]]")
        name = feed.get("name", "").strip()
        if name:
            lines.append(f'name = "{_toml_escape(name)}"')
        lines.append(f'url = "{_toml_escape(feed["url"])}"')
        lines.append("")
    return "\n".join(lines)


def write_feeds_file(path: Path, feeds: list[dict]) -> None:
    """Write the feeds file readable only by its owner."""
    path = Path(path)
    path.write_text(render_feeds_toml(feeds), encoding="utf-8")
    path.chmod(0o600)  # holds live calendar credentials


def reset_feeds(path: Path) -> bool:
    """Delete the saved feed file, returning True if there was one.

    This discards the stored feed URLs. They are recoverable only from
    wherever the user originally copied them, so callers should confirm
    before invoking this.
    """
    path = Path(path)
    if not path.exists():
        log.info("Nothing to reset — %s does not exist.", path.name)
        return False
    path.unlink()
    log.info("Removed %s. Calendar feeds are no longer configured.", path.name)
    return True


# --- links parked by the Wi-Fi hotspot form ----------------------------
# The hotspot has no internet, so links typed there cannot be checked on the
# spot. They wait in a pending file beside the feeds file, in the same
# format, until the calendar setup checks them once the Pi is online.

def pending_feeds_path(feeds_path: Path) -> Path:
    path = Path(feeds_path)
    return path.with_name(path.stem + ".pending" + path.suffix)


def write_pending_feeds(path: Path, urls: list[str], owner_of=None, chown=os.chown) -> None:
    """Park unchecked feed links, owner-only.

    Written by the Wi-Fi setup, which runs as root; `owner_of` (the
    checkout) hands the file to the user the calendar runs as.
    """
    write_feeds_file(path, [{"url": u} for u in urls])
    if owner_of is not None:
        st = Path(owner_of).stat()
        chown(path, st.st_uid, st.st_gid)
