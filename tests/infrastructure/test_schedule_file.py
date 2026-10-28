"""Tests for the power schedule file."""
from datetime import time

import pytest

from gcal_epd import config as cfg
from gcal_epd.domain.power_schedule import PowerSchedule
from gcal_epd.domain.power_ports import ScheduleStore
from gcal_epd.infrastructure.schedule_file import (
    InMemoryScheduleStore,
    TomlScheduleStore,
    load_schedule,
    read_schedule,
    render_schedule,
    write_schedule,
)


def test_missing_file_is_the_default(tmp_path):
    assert read_schedule(tmp_path / "none.toml") == PowerSchedule()


def test_round_trip(tmp_path):
    s = PowerSchedule(slots=(time(6, 30), time(12), time(21, 15)), enabled=False,
                      wake_lead_minutes=8)
    path = tmp_path / "power_schedule.toml"
    write_schedule(path, s)
    assert read_schedule(path) == s
    assert path.stat().st_mode & 0o777 == 0o644
    assert not (tmp_path / "power_schedule.toml.tmp").exists()


def test_render_is_readable():
    assert 'slots = ["07:00", "19:00"]' in render_schedule(PowerSchedule())


@pytest.mark.parametrize("text", ['slots = ["25:00"]', 'slots = ["07:00", "07:10"]',
                                  "slots = [", 'wake_lead_minutes = "x"'])
def test_bad_file_raises_but_load_falls_back(tmp_path, text):
    path = tmp_path / "p.toml"
    path.write_text(text)
    with pytest.raises(ValueError):
        read_schedule(path)
    assert load_schedule(path) == PowerSchedule()


def test_written_as_root_goes_to_the_checkout_owner(tmp_path):
    seen = []
    write_schedule(tmp_path / "p.toml", PowerSchedule(), owner_of=tmp_path,
                   chown=lambda p, uid, gid: seen.append((uid, gid)))
    st = tmp_path.stat()
    assert seen == [(st.st_uid, st.st_gid)]


def test_config_paths(tmp_path):
    conf = {"power": {"schedule_file": "x.toml", "timezone": "UTC"}}
    assert cfg.schedule_file(conf, data=tmp_path) == tmp_path / "x.toml"
    assert str(cfg.power_timezone(conf)) == "UTC"
    assert cfg.schedule_file({}).name == "power_schedule.toml"
    assert str(cfg.power_timezone({})) == "Asia/Taipei"


def test_repo_config_has_power_section():
    conf = cfg.load_config()
    assert str(cfg.power_timezone(conf)) == "Asia/Taipei"


def test_unreadable_file_falls_back(tmp_path):
    path = tmp_path / "p.toml"
    path.mkdir()  # reading a directory raises OSError, like a permission error
    assert load_schedule(path) == PowerSchedule()


def test_toml_store_round_trip(tmp_path):
    store = TomlScheduleStore(tmp_path / "p.toml")
    assert isinstance(store, ScheduleStore)
    assert store.load() == PowerSchedule()
    chosen = PowerSchedule(slots=(time(8),))
    store.save(chosen)
    assert TomlScheduleStore(tmp_path / "p.toml").load() == chosen


def test_in_memory_store_records_saves():
    store = InMemoryScheduleStore()
    assert isinstance(store, ScheduleStore) and store.load() == PowerSchedule()
    chosen = PowerSchedule(slots=(time(8),))
    store.save(chosen)
    assert store.load() == chosen and store.saved == [chosen]
