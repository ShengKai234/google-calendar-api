"""Tests for the feeds file — read, write and reset in one place."""
import logging
import stat
import tomllib

from gcal_epd.infrastructure.feeds_file import (
    load_feeds,
    pending_feeds_path,
    render_feeds_toml,
    reset_feeds,
    write_feeds_file,
    write_pending_feeds,
)

# --- writing ---

def test_render_feeds_toml_round_trips():
    feeds = [{"url": "webcal://h/a.ics"}, {"name": "Work", "url": "https://h/b.ics"}]
    parsed = tomllib.loads(render_feeds_toml(feeds))["feed"]
    assert [f["url"] for f in parsed] == ["webcal://h/a.ics", "https://h/b.ics"]
    assert parsed[1]["name"] == "Work"


def test_render_feeds_toml_escapes_quotes():
    parsed = tomllib.loads(render_feeds_toml([{"url": 'https://h/a".ics'}]))["feed"]
    assert parsed[0]["url"] == 'https://h/a".ics'


def test_written_file_is_owner_only(tmp_path):
    """The file holds live calendar credentials."""
    path = tmp_path / "ics_feeds.toml"
    write_feeds_file(path, [{"url": "https://h/a.ics"}])
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


# --- reading: the same module must read back what it writes ---

def test_load_reads_back_what_write_wrote(tmp_path):
    path = tmp_path / "ics_feeds.toml"
    feeds = [{"url": "https://h/a.ics"}, {"name": "Work", "url": "https://h/b.ics"}]
    write_feeds_file(path, feeds)
    assert load_feeds(path) == feeds


def test_load_missing_file_is_empty_and_not_an_error(tmp_path, caplog):
    """A new display has no feeds file yet; that is the setup step, not a fault."""
    with caplog.at_level(logging.INFO):
        assert load_feeds(tmp_path / "ics_feeds.toml") == []
    assert "No calendar feeds yet" in caplog.text
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_load_unparsable_file_is_empty(tmp_path):
    path = tmp_path / "ics_feeds.toml"
    path.write_text("not toml [[[")
    assert load_feeds(path) == []


# --- reset ---

def test_reset_removes_the_file(tmp_path):
    path = tmp_path / "ics_feeds.toml"
    write_feeds_file(path, [{"url": "https://h/a.ics"}])
    assert reset_feeds(path) is True
    assert not path.exists()


def test_reset_is_safe_when_nothing_saved(tmp_path):
    assert reset_feeds(tmp_path / "missing.toml") is False


# --- links parked by the Wi-Fi form ---

def test_pending_path_sits_next_to_feeds(tmp_path):
    assert pending_feeds_path(tmp_path / "ics_feeds.toml").name == "ics_feeds.pending.toml"

def test_write_pending_is_owner_only_and_handed_to_the_owner(tmp_path):
    chowned = []
    path = tmp_path / "ics_feeds.pending.toml"
    write_pending_feeds(path, ["https://h/a.ics"], owner_of=tmp_path,
                        chown=lambda p, u, g: chowned.append((p, u, g)))
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    st = tmp_path.stat()
    assert chowned == [(path, st.st_uid, st.st_gid)]
