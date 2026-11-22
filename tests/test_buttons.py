"""The PiSugar's custom button: what each press does."""
import pytest

from gcal_epd import buttons


def test_single_press_is_privacy_double_is_refresh():
    assert buttons.GESTURES == {"single": "privacy", "double": "refresh"}


def test_pisugar_server_only_starts_a_unit():
    """pisugar-server runs this as root through /bin/sh, and joins its words
    with single spaces: one plain command, no quoting, no app code."""
    cmd = buttons.command("refresh")
    assert cmd == "systemctl start --no-block epd-button@refresh.service"
    assert not set(cmd) & set("'\"$`;&|<>\\")


def test_commands_cover_every_gesture():
    assert buttons.commands() == {
        "single": "systemctl start --no-block epd-button@privacy.service",
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


def test_privacy_switches_the_page_then_redraws(monkeypatch, tmp_path):
    from gcal_epd.infrastructure import display_mode_file as dm
    path = tmp_path / dm.MODE_FILE
    monkeypatch.setattr(buttons, "mode_file", lambda: path)
    seen = []
    monkeypatch.setattr("gcal_epd.main.main",
                        lambda argv=None: seen.append((dm.load_mode(path), argv)))
    assert buttons.main(["privacy"]) == 0
    assert buttons.main(["privacy"]) == 0
    assert seen == [(dm.PRIVACY, ["--display", "--no-setup"]),
                    (dm.CALENDAR, ["--display", "--no-setup"])]


def test_the_switch_waits_for_a_drawing_in_progress(monkeypatch, tmp_path):
    """Review 56-1: a refresh looks at the mode and draws in one hold of
    the panel lock; the switch takes the same lock, so it never lands
    between that look and the push. The redraw comes after, unlocked."""
    from contextlib import contextmanager

    from gcal_epd.infrastructure import display_mode_file as dm
    path = tmp_path / dm.MODE_FILE
    monkeypatch.setattr(buttons, "mode_file", lambda: path)
    order = []

    @contextmanager
    def lock(lock_path):
        assert lock_path == tmp_path / buttons.PANEL_LOCK
        order.append("lock")
        yield
        order.append("unlock")

    monkeypatch.setattr(buttons, "panel_lock", lock)
    monkeypatch.setattr(dm, "toggle", lambda p: order.append("toggle") or dm.PRIVACY)
    monkeypatch.setattr("gcal_epd.main.main", lambda argv=None: order.append("redraw"))
    assert buttons.main(["privacy"]) == 0
    assert order == ["lock", "toggle", "unlock", "redraw"]
