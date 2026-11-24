"""`power_manager buttons`: the installer's way to set up the PiSugar button."""
from gcal_epd import buttons, power_manager
from gcal_epd.infrastructure.power.boards import NullBoard
from gcal_epd.infrastructure.power.pisugar import PiSugar, PiSugar3Board
from tests.infrastructure.power.fake_pisugar import FakePiSugarServer


def _run(monkeypatch, board):
    monkeypatch.setattr(power_manager, "make_board", lambda name: board)
    return power_manager.main(["buttons"])


def test_sets_every_gesture_on_a_pisugar(monkeypatch):
    server = FakePiSugarServer()
    assert _run(monkeypatch, PiSugar3Board(PiSugar(server), startup_wait=0)) == 0
    assert server.button_shell == buttons.commands()
    assert all(server.button_enable[g] for g in buttons.commands())


def test_no_board_is_fine(monkeypatch, caplog):
    caplog.set_level("INFO")
    assert _run(monkeypatch, NullBoard()) == 0
    assert "no buttons" in caplog.text


def test_a_board_that_does_not_answer_is_a_warning_not_a_failure(monkeypatch, caplog):
    """The installer goes on: the display works without its button."""
    server = FakePiSugarServer(up=False)
    assert _run(monkeypatch, PiSugar3Board(PiSugar(server), startup_wait=0)) == 0
    assert "button" in caplog.text


def test_a_refused_command_is_reported(monkeypatch, caplog):
    server = FakePiSugarServer()
    server.errors["set_button_shell"] = "I2C not connected"
    assert _run(monkeypatch, PiSugar3Board(PiSugar(server), startup_wait=0)) == 1
    assert "I2C not connected" in caplog.text
