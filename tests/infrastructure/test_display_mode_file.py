"""Which page the display shows: the calendar, or the privacy page."""
import pytest

from gcal_epd.infrastructure import display_mode_file as dm


def test_no_file_shows_the_calendar(tmp_path):
    assert dm.load_mode(tmp_path / dm.MODE_FILE) == dm.CALENDAR


def test_toggle_goes_to_privacy_and_back(tmp_path):
    path = tmp_path / dm.MODE_FILE
    assert dm.toggle(path) == dm.PRIVACY
    assert dm.load_mode(path) == dm.PRIVACY
    assert dm.toggle(path) == dm.CALENDAR
    assert dm.load_mode(path) == dm.CALENDAR
    assert not list(tmp_path.glob("*.tmp"))


def test_the_file_says_when(tmp_path):
    path = tmp_path / dm.MODE_FILE
    dm.toggle(path)
    text = path.read_text()
    assert 'mode = "privacy"' in text and "since = " in text


@pytest.mark.parametrize("text", ["not toml [[[", 'mode = "party"', "mode = 3", ""])
def test_a_file_it_cannot_read_hides_the_calendar(tmp_path, text, caplog):
    """Fail closed: when in doubt, never show the events to a guest."""
    path = tmp_path / dm.MODE_FILE
    path.write_text(text)
    assert dm.load_mode(path) == dm.PRIVACY
    assert dm.MODE_FILE in caplog.text


def test_an_unreadable_file_toggles_back_to_the_calendar(tmp_path):
    """It showed the privacy page, so a press means: show the calendar."""
    path = tmp_path / dm.MODE_FILE
    path.write_text("garbage [[")
    assert dm.toggle(path) == dm.CALENDAR
