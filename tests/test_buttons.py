"""The PiSugar's custom button: what each press does."""
import pytest

from gcal_epd import buttons


def test_a_double_press_refreshes():
    assert buttons.GESTURES == {"double": "refresh"}


def test_pisugar_server_only_starts_a_unit():
    """pisugar-server runs this as root through /bin/sh, and joins its words
    with single spaces: one plain command, no quoting, no app code."""
    cmd = buttons.command("refresh")
    assert cmd == "systemctl start --no-block epd-button@refresh.service"
    assert not set(cmd) & set("'\"$`;&|<>\\")


def test_commands_cover_every_gesture():
    assert buttons.commands() == {
        "double": "systemctl start --no-block epd-button@refresh.service"}


def test_refresh_redraws_like_the_timer(monkeypatch):
    calls = []
    monkeypatch.setattr("gcal_epd.main.main", lambda argv=None: calls.append(argv))
    assert buttons.main(["refresh"]) == 0
    assert calls == [["--display", "--no-setup"]]


def test_an_unknown_action_is_refused(monkeypatch):
    monkeypatch.setattr("gcal_epd.main.main", lambda argv=None: pytest.fail("ran"))
    with pytest.raises(SystemExit) as e:
        buttons.main(["reset"])
    assert e.value.code == 2
