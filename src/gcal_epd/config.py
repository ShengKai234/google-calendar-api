"""
Where the app lives and what config.toml says.

Shared by both entry points (main, wifi_setup) and the application layer,
so neither entry point has to import the other just to read a setting, and
"a config path, relative to the checkout" is resolved in one place.

Two roots:
- PROJECT_ROOT is the code: config.toml's defaults, fonts, vendor/. In an
  installed release it is read-only and replaced as a whole on update.
- DATA_DIR is this display's own files: feed links, the preview and
  config.local.toml. They survive every update. In a git checkout it is
  the checkout itself, so a development Pi works as before.
"""
import os
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
DEFAULT_FEEDS_FILE = "ics_feeds.toml"
LOCAL_CONFIG = "config.local.toml"
RELEASE_MARKER = "RELEASE"


def data_dir(root: Path = PROJECT_ROOT, env=os.environ) -> Path:
    """Where this display's own files are kept.

    EPD_DATA_DIR wins (tests, unusual installs). A release installed by
    `gcal_epd.releases` sits at <base>/releases/<version> with a RELEASE
    file and keeps its data in <base>/data, next to the releases, so a
    command typed over SSH finds the same files as the units do.
    Anything else is a checkout, which keeps its data in itself.
    """
    if env.get("EPD_DATA_DIR"):
        return Path(env["EPD_DATA_DIR"])
    if root.parent.name == "releases" and (root / RELEASE_MARKER).is_file():
        return root.parent.parent / "data"
    return root


DATA_DIR = data_dir()


def _merge(base: dict, override: dict) -> dict:
    """`override` on top of `base`: tables merge key by key; anything else
    (a value, or a list such as [[sources]]) replaces what was there."""
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: str = "config.toml", data: Path | None = None) -> dict:
    """The shipped config.toml, with this display's config.local.toml on top.

    The local file holds only what differs here (another city, say), so an
    update can change the defaults without overwriting it.
    """
    with open(PROJECT_ROOT / path, "rb") as f:
        config = tomllib.load(f)
    local = (DATA_DIR if data is None else data) / LOCAL_CONFIG
    if local.is_file():
        with open(local, "rb") as f:
            config = _merge(config, tomllib.load(f))
    return config


def resolve(raw: str, root: Path = PROJECT_ROOT) -> str:
    """A path from config.toml, made absolute against `root`.

    An absolute path is kept as is. An empty one stays empty, so callers
    can fall back to their own default (draw.py tries system fonts).
    """
    return str(root / raw) if raw else ""


def font_path(config: dict, root: Path = PROJECT_ROOT) -> str:
    return resolve(config.get("display", {}).get("font_path", ""), root)


def output_path(config: dict, data: Path | None = None) -> str:
    """Where the rendered preview goes: with this display's data, not the code."""
    raw = config.get("display", {}).get("output_path", "preview.png")
    return resolve(raw, DATA_DIR if data is None else data)


def feeds_file(config: dict, data: Path | None = None) -> Path:
    """The gitignored file holding the feed URLs, from the first ics source."""
    data = DATA_DIR if data is None else data
    for source in config.get("sources", []):
        if source.get("type") == "ics":
            return data / source.get("feeds_file", DEFAULT_FEEDS_FILE)
    return data / DEFAULT_FEEDS_FILE
