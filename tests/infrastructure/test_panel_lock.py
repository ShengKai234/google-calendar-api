"""One process drives the panel at a time: the timer's refresh, a setup
screen or a button action. Two at once fail with 'GPIO busy'."""
import fcntl
import os

import pytest

from gcal_epd.infrastructure.panel_lock import PanelBusy, panel_lock


class Clock:
    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.t += seconds


def _held_elsewhere(path):
    fd = os.open(path, os.O_RDONLY | os.O_CREAT, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


def test_a_free_panel_is_taken_at_once(tmp_path):
    clock = Clock()
    with panel_lock(tmp_path / "panel.lock", clock=clock, sleep=clock.sleep):
        pass
    assert clock.sleeps == []
    assert (tmp_path / "panel.lock").exists()


def test_a_busy_panel_is_waited_for_then_given_up(tmp_path):
    path = tmp_path / "panel.lock"
    fd = _held_elsewhere(path)
    clock = Clock()
    try:
        with pytest.raises(PanelBusy, match="60 s"):
            with panel_lock(path, wait=60, clock=clock, sleep=clock.sleep):
                pytest.fail("must not get the panel")
    finally:
        os.close(fd)
    assert 60 <= clock.t < 61


def test_the_panel_is_taken_once_the_other_lets_go(tmp_path):
    path = tmp_path / "panel.lock"
    fd = _held_elsewhere(path)
    clock = Clock()

    def sleep(seconds):
        clock.sleep(seconds)
        if clock.t >= 5:
            fcntl.flock(fd, fcntl.LOCK_UN)
    try:
        with panel_lock(path, clock=clock, sleep=sleep):
            pass
    finally:
        os.close(fd)
    assert 5 <= clock.t < 60


def test_a_lock_file_it_cannot_write_still_locks(tmp_path):
    """root (the Wi-Fi setup) may create the file; the app user can only read
    it. flock works on a read-only descriptor."""
    path = tmp_path / "panel.lock"
    path.touch()
    path.chmod(0o444)
    with panel_lock(path):
        pass


def test_no_lock_file_possible_draws_anyway(tmp_path, caplog):
    """A missing data directory must not leave the panel blank."""
    with panel_lock(tmp_path / "missing" / "panel.lock"):
        pass
    assert "panel lock" in caplog.text
