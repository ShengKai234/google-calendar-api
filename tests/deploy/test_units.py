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


def test_every_refresh_checks_for_an_update_first():
    """No clock of its own: gcal-epd.service wants epd-update.service, which
    runs BEFORE it, so the panel is drawn by the newest release; Wants= (not
    Requires=), so a failed or offline check still lets the refresh run."""
    refresh = (DEPLOY / "gcal-epd.service").read_text().split("[Service]", 1)[0]
    assert re.search(r"^Wants=.*\bepd-update\.service\b", refresh, re.M)
    assert not re.search(r"^Requires=.*epd-update", refresh, re.M)
    update = (DEPLOY / "epd-update.service").read_text()
    assert re.search(r"^Before=.*\bgcal-epd\.service\b", update, re.M)
    assert not re.search(r"^After=.*\bgcal-epd\.service\b", update, re.M)
    assert not (DEPLOY / "epd-update.timer").exists()


def test_update_check_runs_after_the_clock_and_setup():
    """It now runs first: after the RTC sets the clock (TLS needs it) and
    after Wi-Fi and calendar setup, never alongside them."""
    power = (DEPLOY / "epd-power.service").read_text()
    before = re.search(r"^Before=(.*)$", power, re.M).group(1).split()
    assert "epd-update.service" in before
    update = (DEPLOY / "epd-update.service").read_text()
    after = " ".join(re.findall(r"^After=(.*)$", update, re.M)).split()
    assert {"epd-wifi-setup.service", "epd-feed-setup.service"} <= set(after)


def test_update_hook_lives_in_a_unit_file_every_installer_rewrites():
    """Review 50-1: an enablement link (WantedBy= + systemctl enable) would
    outlive a rollback, since an older release's install.sh never removes
    it. The Wants= line in gcal-epd.service goes with the unit file."""
    update = (DEPLOY / "epd-update.service").read_text()
    assert "[Install]" not in update
    script = (DEPLOY / "install.sh").read_text()
    assert "enable epd-update.service" not in script
    assert "enable --now epd-update.service" not in script
    assert "enable epd-update.timer" not in script and "start  epd-update.timer" not in script


def test_install_retires_the_daily_update_timer():
    """Displays updated from a release with epd-update.timer lose it."""
    script = (DEPLOY / "install.sh").read_text()
    assert "systemctl disable --now epd-update.timer" in script
    assert "/etc/systemd/system/epd-update.timer" in script
    assert "/etc/systemd/system/epd-update.timer.d" in script


def test_ordered_jobs_have_no_job_timeout():
    """Reviews 50-5/50-6: JobTimeoutSec= cancels a job without stopping its
    service, so the update's ordering barrier could vanish mid-install, and
    a merged refresh job keeps an old deadline. A stuck queue is bounded by
    the power manager instead (power_policy.QUEUE_WAIT)."""
    for unit in ("epd-update.service", "gcal-epd.service", "epd-feed-setup.service"):
        assert "JobTimeoutSec" not in (DEPLOY / unit).read_text(), unit


def _setting(unit, key):
    m = re.search(rf"^{key}=(.*)$", (DEPLOY / unit).read_text(), re.M)
    return m and m.group(1).strip()


@pytest.mark.parametrize("unit, limit", [
    ("epd-update.service", "6min"),   # check + download + verify + build + test render
    ("gcal-epd.service", "3min"),     # fetch calendars and weather + draw the panel
    ("epd-power.service", "2min"),    # its setup: clock from the RTC, schedule
])
def test_each_unit_has_its_own_run_time_limit(unit, limit):
    """A unit that hangs while running would keep a battery Pi on until it is
    empty; the 5-minute queue rule only covers waiting. TimeoutStartSec
    counts from the unit's own start, and stopping it kills the whole
    control group (pip, the build), unlike JobTimeoutSec."""
    assert _setting(unit, "TimeoutStartSec") == limit
    assert _setting(unit, "KillMode") in (None, "control-group")
    assert _setting(unit, "RuntimeMaxSec") is None


def test_the_refresh_still_runs_after_a_failed_or_stopped_update():
    refresh = (DEPLOY / "gcal-epd.service").read_text()
    for strict in ("Requires", "Requisite", "BindsTo", "PartOf"):
        assert not re.search(rf"^{strict}=.*epd-update", refresh, re.M), strict
    assert _setting("epd-update.service", "Type") == "oneshot"
    assert _setting("gcal-epd.service", "Type") == "oneshot"


def test_a_stopped_update_has_time_to_go_back():
    """On SIGTERM the updater switches back to the old release and reinstalls
    its units before it exits; then systemd's SIGKILL."""
    assert _setting("epd-update.service", "TimeoutStopSec") == "90s"


def test_timer_defaults_match_the_default_schedule():
    from gcal_epd.domain.power_schedule import DEFAULT_SLOTS, format_slot

    timer = (DEPLOY / "gcal-epd.timer").read_text()
    times = re.findall(r"^OnCalendar=\*-\*-\* (\d\d:\d\d):00 Asia/Taipei$", timer, re.M)
    assert times == [format_slot(s) for s in DEFAULT_SLOTS]
