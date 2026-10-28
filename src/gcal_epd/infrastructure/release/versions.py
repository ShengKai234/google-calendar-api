"""Release names as versions: "X.Y.Z" (a tag) or "X.Y.Z+local" (a build)."""
import re

_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:\+([0-9A-Za-z.]+))?")


def version_key(label: str) -> tuple | None:
    """A sortable key for "X.Y.Z" or "X.Y.Z+local"; None if not a version.

    A local build ("0.2.0+gabc1234", from an untagged commit) sorts just
    above its plain version and below the next one, as in PEP 440: a
    display running a test build of 0.2.0 takes 0.2.1, not 0.2.0.
    """
    m = _VERSION.fullmatch(label)
    if not m:
        return None
    major, minor, patch, local = m.groups()
    return (int(major), int(minor), int(patch), 1 if local else 0, local or "")
