"""Tests for picking the wake-up board, and the no-board stand-in."""
from datetime import datetime, timezone

import pytest

from gcal_epd import config as cfg
from gcal_epd.domain.power_ports import WakeBoard, WakeBoardError
from gcal_epd.infrastructure.power.boards import BOARDS, NullBoard, make_board
from gcal_epd.infrastructure.power.pisugar import PiSugar, PiSugar3Board
from tests.infrastructure.power.fake_pisugar import FakePiSugarServer

INSTALLED = {"pisugar-server": "/usr/bin/pisugar-server"}.get
MISSING = {}.get


def test_auto_picks_the_pisugar_when_its_server_is_installed():
    board = make_board("auto", which=INSTALLED)
    assert isinstance(board, PiSugar3Board) and board.startup_wait > 0


def test_auto_without_pisugar_server_is_no_board():
    assert isinstance(make_board("auto", which=MISSING), NullBoard)


def test_pisugar3_not_installed_does_not_wait():
    board = make_board("pisugar3", which=MISSING)
    assert isinstance(board, PiSugar3Board) and board.startup_wait == 0


def test_none_and_unknown():
    assert isinstance(make_board("none", which=INSTALLED), NullBoard)
    with pytest.raises(ValueError, match="pisugar3"):
        make_board("wittypi")


@pytest.mark.parametrize("name", list(BOARDS))
def test_every_board_is_a_wake_board(name):
    assert isinstance(make_board(name, which=INSTALLED), WakeBoard)


def test_null_board_never_arms():
    board = NullBoard()
    assert not board.available() and board.report(timezone.utc) == []
    with pytest.raises(WakeBoardError):
        board.arm(datetime(2026, 10, 20, 7, tzinfo=timezone.utc))


def test_pisugar3_board_arms_daily_and_reports():
    server = FakePiSugarServer()
    board = PiSugar3Board(PiSugar(server))
    board.arm(datetime(2026, 10, 19, 18, 55, tzinfo=timezone.utc))
    assert "rtc_alarm_set 2026-10-19T18:55:00+00:00 127" in server.commands
    labels = [label for label, _ in board.report(timezone.utc)]
    assert labels == ["Battery", "Plugged in", "RTC time", "Alarm"]


def test_pisugar_errors_are_board_errors():
    board = PiSugar3Board(PiSugar(FakePiSugarServer(up=False)))
    with pytest.raises(WakeBoardError):
        board.rtc_time()


def test_config_board():
    assert cfg.power_board({}) == "auto"
    assert cfg.power_board({"power": {"board": "none"}}) == "none"
    assert cfg.power_board(cfg.load_config()) == "auto"
