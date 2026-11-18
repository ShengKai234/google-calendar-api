"""LICENSE, THIRD_PARTY_NOTICES.md and the font licenses stay complete (issue #44).

A dependency re-pin or a new font must not leave the notices behind: each
check here fails until the notice is updated.
"""
import re
import tomllib

import pytest

from gcal_epd.config import PROJECT_ROOT
from gcal_epd.infrastructure.release import artifacts

NOTICES = PROJECT_ROOT / "THIRD_PARTY_NOTICES.md"
FONTS = PROJECT_ROOT / "assets" / "fonts"
REQUIREMENTS = ("requirements.txt", "requirements-pi.txt", "requirements-build.txt")


def _table_rows(section: str) -> list[list[str]]:
    """The cells of each body row of the first table under `## section`."""
    assert NOTICES.is_file(), "THIRD_PARTY_NOTICES.md is missing"
    text = NOTICES.read_text(encoding="utf-8")
    assert f"## {section}\n" in text, f"no '## {section}' section"
    body = text.split(f"## {section}\n", 1)[1].split("\n## ", 1)[0]
    rows = [line for line in body.splitlines() if line.startswith("|")]
    return [[c.strip() for c in row.strip("|").split("|")] for row in rows[2:]]


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def test_project_is_mit_licensed():
    assert (PROJECT_ROOT / "LICENSE").is_file(), "LICENSE is missing"
    text = (PROJECT_ROOT / "LICENSE").read_text(encoding="utf-8")
    assert text.startswith("MIT License\n")
    assert "Copyright (c) 2024-2026 Kai (ShengKai234)" in text
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())["project"]
    assert project["license"] == "MIT"
    assert project["license-files"] == ["LICENSE"]


@pytest.mark.parametrize("font", sorted(
    p.name for p in FONTS.iterdir() if p.suffix.lower() in (".otf", ".ttf", ".ttc")))
def test_every_font_ships_with_its_license(font):
    """OFL 1.1 asks for the license and copyright notice beside each copy."""
    licenses = [p for p in FONTS.glob("*-OFL.txt") if font.startswith(p.name[:-len("-OFL.txt")])]
    assert licenses, f"{font} has no <family>-OFL.txt next to it"
    text = licenses[0].read_text(encoding="utf-8")
    assert "SIL OPEN FONT LICENSE Version 1.1" in text
    assert "Copyright" in text or "©" in text


def test_every_pinned_python_package_is_listed():
    listed = {_normalize(row[0]) for row in _table_rows("Python packages")}
    for name in REQUIREMENTS:
        for line in (PROJECT_ROOT / name).read_text().splitlines():
            if m := re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)==", line):
                assert _normalize(m.group(1)) in listed, f"{m.group(1)} ({name})"


def test_every_bundled_debian_package_is_listed_at_its_version():
    rows = {row[0]: row for row in _table_rows("Debian packages on the SD card")}
    lock = artifacts.read_debs_lock(PROJECT_ROOT / artifacts.DEBS_LOCK)
    for deb in lock.debs:
        assert deb.package in rows, deb.package
        assert rows[deb.package][1] == deb.version, deb.package
    assert set(rows) == {deb.package for deb in lock.debs}, "listed but no longer bundled"


def test_gpl_packages_say_where_their_source_is():
    rows = _table_rows("Debian packages on the SD card")
    assert any("GPL" in row[2] for row in rows), "no GPL package listed"
    for package, version, license_, source in rows:
        if "GPL" in license_:
            assert source.startswith(("http", "`apt-get source")), package


@pytest.mark.parametrize("readme, section", [
    ("README.md", "## Acknowledgements"),
    ("README.zh-TW.md", "## 致謝"),
])
def test_readmes_credit_glance_and_link_the_licenses(readme, section):
    text = (PROJECT_ROOT / readme).read_text(encoding="utf-8")
    assert section in text, f"{readme} has no {section} section"
    credit = text.split(section, 1)[1]
    assert "https://github.com/bolintw/Glance" in credit
    assert "](LICENSE)" in text and "](THIRD_PARTY_NOTICES.md)" in text
    assert "open-meteo.com" in text.lower()
