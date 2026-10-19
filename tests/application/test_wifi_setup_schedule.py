"""Tests for the wake-up times chosen on the hotspot form, as wifi_setup wires them."""
from datetime import time

import pytest

from gcal_epd import config, wifi_setup
from gcal_epd.domain.power_schedule import PowerSchedule
from gcal_epd.infrastructure import schedule_file


def test_save_writes_the_configured_file_owned_by_the_checkout(monkeypatch, tmp_path):
    """wifi_setup runs as root; the forms that edit the file later do not."""
    calls = []
    monkeypatch.setattr(config, "load_config", lambda: {"power": {}})
    monkeypatch.setattr(config, "schedule_file", lambda cfg: tmp_path / "power_schedule.toml")
    monkeypatch.setattr(schedule_file, "write_schedule",
                        lambda path, s, owner_of=None: calls.append((path, s, owner_of)))
    chosen = PowerSchedule(slots=(time(8, 0), time(20, 0)))
    wifi_setup._save_schedule(chosen)
    assert calls == [(tmp_path / "power_schedule.toml", chosen, config.PROJECT_ROOT)]


def test_save_really_writes_a_readable_file(monkeypatch, tmp_path):
    path = tmp_path / "power_schedule.toml"
    monkeypatch.setattr(config, "load_config", lambda: {})
    monkeypatch.setattr(config, "schedule_file", lambda cfg: path)
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)  # chown to ourselves
    chosen = PowerSchedule(slots=(time(6, 0), time(18, 0)), enabled=False)
    wifi_setup._save_schedule(chosen)
    assert schedule_file.read_schedule(path) == chosen


def test_current_schedule_reads_the_file(monkeypatch, tmp_path):
    path = tmp_path / "power_schedule.toml"
    saved = PowerSchedule(slots=(time(5, 30), time(12, 0), time(22, 0)), wake_lead_minutes=8)
    schedule_file.write_schedule(path, saved)
    monkeypatch.setattr(config, "load_config", lambda: {})
    monkeypatch.setattr(config, "schedule_file", lambda cfg: path)
    assert wifi_setup._current_schedule() == saved


def test_current_schedule_never_stops_wifi_setup(monkeypatch):
    """No config.toml must not keep the display offline."""
    def missing():
        raise FileNotFoundError("config.toml")
    monkeypatch.setattr(config, "load_config", missing)
    assert wifi_setup._current_schedule() == PowerSchedule()


@pytest.fixture
def factory(monkeypatch):
    """Run main() with the loop faked; return the server it would build."""
    seen = {}
    current = PowerSchedule(slots=(time(9, 0), time(21, 0)))

    def fake_run(wifi, server_factory, *args, **kwargs):
        seen["server"] = server_factory([])
        return "online"

    monkeypatch.setattr(wifi_setup, "run", fake_run)
    monkeypatch.setattr(wifi_setup, "_current_schedule", lambda: current)
    monkeypatch.setattr(wifi_setup, "WifiSetupServer",
                        lambda networks, **kwargs: kwargs)
    monkeypatch.setattr(wifi_setup.NetworkManager, "available", staticmethod(lambda: True))
    monkeypatch.setattr("signal.signal", lambda *a: None)
    monkeypatch.setattr("sys.argv", ["wifi_setup"])
    wifi_setup.main()
    return seen["server"], current


def test_main_gives_the_form_the_current_times_and_the_root_save(factory):
    kwargs, current = factory
    assert kwargs["schedule"] == current
    assert kwargs["save_schedule"] is wifi_setup._save_schedule
