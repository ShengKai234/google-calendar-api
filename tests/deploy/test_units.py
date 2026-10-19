"""The systemd units are templates; install.sh must be able to fill every gap."""
import re
from pathlib import Path

import pytest

DEPLOY = Path(__file__).parent.parent.parent / "deploy"
UNITS = sorted(DEPLOY.glob("*.service")) + sorted(DEPLOY.glob("*.timer")) \
    + sorted(DEPLOY.glob("*.path"))
FILLED_BY_INSTALL = {"PROJECT_DIR", "USER", "FEEDS_FILE", "PENDING_FILE", "SCHEDULE_FILE"}


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


def test_panel_units_are_ordered():
    """Two processes driving the panel at once fail with 'GPIO busy'."""
    wifi = (DEPLOY / "epd-wifi-setup.service").read_text()
    feed = (DEPLOY / "epd-feed-setup.service").read_text()
    assert re.search(r"^Before=.*gcal-epd\.service.*epd-feed-setup\.service", wifi, re.M)
    assert re.search(r"^Before=gcal-epd\.service", feed, re.M)


def test_documented_manual_wifi_setup_hands_over_like_boot():
    """Without --start-unit, parked links stay unchecked and block the refresh."""
    root = DEPLOY.parent
    boot = (DEPLOY / "epd-wifi-setup.service").read_text()
    for unit in ("gcal-epd.service", "epd-feed-setup.service"):
        assert f"--start-unit {unit}" in boot
    for doc in ("README.md", "README.zh-TW.md", "deploy/install.sh",
                "src/gcal_epd/wifi_setup.py"):
        text = (root / doc).read_text()
        assert "--force" in text, doc
        for unit in ("gcal-epd.service", "epd-feed-setup.service"):
            assert f"--start-unit {unit}" in text, f"{doc} misses {unit}"


def test_power_manager_is_installed_and_enabled():
    script = (DEPLOY / "install.sh").read_text()
    assert "systemctl enable epd-power.service" in script
    assert "systemctl enable --now epd-power-schedule.path" in script
    assert "gcal_epd.power_manager apply-schedule" in script


def test_power_manager_sets_the_clock_before_anything_draws():
    """The Pi boots with a stale clock; the RTC time must be in before a date is drawn."""
    unit = (DEPLOY / "epd-power.service").read_text()
    assert re.search(r"^User=root$", unit, re.M)
    assert re.search(r"^ExecStartPre=-.*gcal_epd\.power_manager boot$", unit, re.M)
    assert re.search(r"^ExecStart=.*gcal_epd\.power_manager run$", unit, re.M)
    before = re.search(r"^Before=(.*)$", unit, re.M).group(1).split()
    assert {"epd-wifi-setup.service", "gcal-epd.service", "epd-feed-setup.service"} <= set(before)
    assert re.search(r"^After=pisugar-server\.service$", unit, re.M)


def test_schedule_path_unit_triggers_apply_schedule():
    path = (DEPLOY / "epd-power-schedule.path").read_text()
    assert re.search(r"^PathChanged=@SCHEDULE_FILE@$", path, re.M)
    assert re.search(r"^Unit=epd-power-schedule\.service$", path, re.M)
    service = (DEPLOY / "epd-power-schedule.service").read_text()
    assert re.search(r"^ExecStart=.*gcal_epd\.power_manager apply-schedule$", service, re.M)


def test_refresh_never_shuts_down_on_its_own():
    """Only the power manager powers off: it sets the wake-up alarm first."""
    for unit in UNITS:
        text = unit.read_text()
        assert "shutdown -h" not in text, unit.name
        if unit.name != "epd-power.service":
            assert "poweroff" not in text, unit.name


def test_timer_defaults_match_the_default_schedule():
    from gcal_epd.domain.power_schedule import DEFAULT_SLOTS, format_slot

    timer = (DEPLOY / "gcal-epd.timer").read_text()
    times = re.findall(r"^OnCalendar=\*-\*-\* (\d\d:\d\d):00 Asia/Taipei$", timer, re.M)
    assert times == [format_slot(s) for s in DEFAULT_SLOTS]
