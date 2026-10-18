"""
Where the app lives and what config.toml says.

Shared by both entry points (main, wifi_setup) and the application layer,
so neither entry point has to import the other just to read a setting, and
"a config path, relative to the checkout" is resolved in one place.
"""
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
DEFAULT_FEEDS_FILE = "ics_feeds.toml"


def load_config(path: str = "config.toml") -> dict:
    with open(PROJECT_ROOT / path, "rb") as f:
        return tomllib.load(f)


def resolve(raw: str, root: Path = PROJECT_ROOT) -> str:
    """A path from config.toml, made absolute against `root`.

    An absolute path is kept as is. An empty one stays empty, so callers
    can fall back to their own default (draw.py tries system fonts).
    """
    return str(root / raw) if raw else ""


def font_path(config: dict, root: Path = PROJECT_ROOT) -> str:
    return resolve(config.get("display", {}).get("font_path", ""), root)


def feeds_file(config: dict) -> Path:
    """The gitignored file holding the feed URLs, from the first ics source."""
    for source in config.get("sources", []):
        if source.get("type") == "ics":
            return PROJECT_ROOT / source.get("feeds_file", DEFAULT_FEEDS_FILE)
    return PROJECT_ROOT / DEFAULT_FEEDS_FILE
