"""
Which version of the app this is.

An installed release says so in its RELEASE file (written by
`gcal_epd.releases`, e.g. "0.2.0" or "0.2.0+g1a2b3c4" for an untagged
commit). A checkout has none and reports pyproject.toml's version.
Read from files rather than package metadata: an editable install keeps
the metadata of the day it was installed.
"""
import tomllib
from pathlib import Path

from gcal_epd.config import PROJECT_ROOT, RELEASE_MARKER

UNKNOWN = "unknown"


def project_version(root: Path = PROJECT_ROOT) -> str:
    """The version in pyproject.toml, or UNKNOWN."""
    try:
        with open(root / "pyproject.toml", "rb") as f:
            return str(tomllib.load(f)["project"]["version"])
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return UNKNOWN


def version(root: Path = PROJECT_ROOT) -> str:
    """This release's label, else the project version."""
    try:
        label = (root / RELEASE_MARKER).read_text().strip()
    except OSError:
        label = ""
    return label or project_version(root)
