"""The systemd units are templates; install.sh must be able to fill every gap."""
import re
from pathlib import Path

import pytest

DEPLOY = Path(__file__).parent.parent.parent / "deploy"
UNITS = sorted(DEPLOY.glob("*.service")) + sorted(DEPLOY.glob("*.timer"))
FILLED_BY_INSTALL = {"PROJECT_DIR", "USER", "FEEDS_FILE", "PENDING_FILE"}


@pytest.mark.parametrize("unit", UNITS, ids=lambda p: p.name)
def test_unit_has_no_hardcoded_home(unit):
    """A fixed /home/<user>/<dir> breaks for any other user or checkout name."""
    assert "/home/" not in unit.read_text()


@pytest.mark.parametrize("unit", UNITS, ids=lambda p: p.name)
def test_unit_placeholders_are_all_filled_by_install(unit):
    used = set(re.findall(r"@([A-Z_]+)@", unit.read_text()))
    assert used <= FILLED_BY_INSTALL


def test_install_fills_every_placeholder():
    script = (DEPLOY / "install.sh").read_text()
    for name in FILLED_BY_INSTALL:
        assert f"s|@{name}@|" in script


def test_install_installs_every_unit():
    script = (DEPLOY / "install.sh").read_text()
    for unit in UNITS:
        stem = unit.name.replace("gcal-epd", "$SERVICE_NAME")
        assert unit.name in script or stem in script, unit.name
