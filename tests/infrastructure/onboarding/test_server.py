"""Tests for the onboarding setup server."""
import datetime
import logging
import stat
import threading
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from gcal_epd.infrastructure.onboarding.server import (
    FeedSetupServer,
    detect_lan_ip,
    generate_pin,
    probe_feed,
    render_feeds_toml,
    reset_feeds,
    validate_feed_url,
    write_feeds_file,
)

# A token-shaped string that must never appear in output.
SECRET_PATH = "private-000000000000000000000000deadbeef"


def _ics(dtstart: str, name: str = "Fixture") -> bytes:
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//t//EN\r\n"
        f"X-WR-CALNAME:{name}\r\n"
        "BEGIN:VEVENT\r\nUID:1\r\nDTSTAMP:20260101T000000Z\r\n"
        f"DTSTART;VALUE=DATE:{dtstart}\r\nSUMMARY:Fixture event\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    ).encode()


@pytest.fixture
def feed_server():
    """Serves a fixture .ics with an event a week from now."""
    soon = (datetime.date.today() + datetime.timedelta(days=7)).strftime("%Y%m%d")
    body = _ics(soon)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    yield f"http://127.0.0.1:{port}/{SECRET_PATH}/basic.ics"
    httpd.shutdown()


@pytest.fixture
def setup_server(tmp_path):
    srv = FeedSetupServer(tmp_path / "ics_feeds.toml", port=0, pin="123456", timeout=20)
    yield srv


def _post(base, pin, urls, timeout=30):
    data = urllib.parse.urlencode({"pin": pin, "urls": urls}).encode()
    try:
        with urllib.request.urlopen(base, data=data, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


@pytest.fixture
def running(setup_server):
    """Start the setup server on a free port and hand back its base URL."""
    import socket
    s = socket.socket(); s.bind(("127.0.0.1", 0))
    setup_server.port = s.getsockname()[1]; s.close()
    t = threading.Thread(target=setup_server.serve_until_configured, daemon=True)
    t.start()
    for _ in range(50):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{setup_server.port}", timeout=1)
            break
        except Exception:
            time.sleep(0.05)
    yield f"http://127.0.0.1:{setup_server.port}", setup_server


# --- helpers ---

def test_generate_pin_is_six_digits():
    for _ in range(20):
        pin = generate_pin()
        assert len(pin) == 6 and pin.isdigit()


def test_detect_lan_ip_returns_an_address():
    assert detect_lan_ip().count(".") == 3


@pytest.mark.parametrize("url", [
    "webcal://h/a.ics", "webcals://h/a.ics", "http://h/a.ics", "https://h/a.ics",
])
def test_validate_accepts_calendar_schemes(url):
    assert validate_feed_url(url) == url


@pytest.mark.parametrize("bad", ["", "   ", "ftp://h/a.ics", "javascript:alert(1)",
                                 "file:///etc/passwd", "https://"])
def test_validate_rejects_everything_else(bad):
    with pytest.raises(ValueError):
        validate_feed_url(bad)


def test_validate_strips_surrounding_whitespace():
    assert validate_feed_url("  https://h/a.ics \n") == "https://h/a.ics"


# --- writing the feeds file ---

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


def test_written_file_parses_back(tmp_path):
    path = tmp_path / "ics_feeds.toml"
    write_feeds_file(path, [{"url": "https://h/a.ics"}])
    assert tomllib.load(open(path, "rb"))["feed"][0]["url"] == "https://h/a.ics"


# --- probing ---

def test_probe_counts_events(feed_server):
    assert probe_feed(feed_server) == 1


def test_probe_raises_when_unreachable():
    """A reachable-but-empty feed and an unreachable one must differ."""
    with pytest.raises(Exception):
        probe_feed("http://127.0.0.1:9/none.ics", timeout=2)


# --- the form ---

def test_get_serves_the_form(running):
    base, _ = running
    with urllib.request.urlopen(base, timeout=5) as r:
        body = r.read().decode()
    assert r.status == 200 and "Calendar Setup" in body


def test_unknown_path_is_404(running):
    base, _ = running
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(base + "/nope", timeout=5)
    assert e.value.code == 404


def test_wrong_pin_is_rejected(running, feed_server):
    base, srv = running
    code, _ = _post(base, "000000", feed_server)
    assert code == 403
    assert not srv.feeds_path.exists(), "must not save on a bad PIN"


def test_bad_scheme_is_rejected(running):
    base, srv = running
    code, _ = _post(base, "123456", "ftp://h/a.ics")
    assert code == 400
    assert not srv.feeds_path.exists()


def test_unreachable_feed_is_rejected(running):
    """Regression: fetch_events swallows errors, so probing must not use it."""
    base, srv = running
    code, _ = _post(base, "123456", "http://127.0.0.1:9/none.ics")
    assert code == 400
    assert not srv.feeds_path.exists(), "a dead URL must never be saved"


def test_empty_submission_is_rejected(running):
    base, srv = running
    code, _ = _post(base, "123456", "   \n  ")
    assert code == 400
    assert not srv.feeds_path.exists()


def test_successful_submission_saves_feeds(running, feed_server):
    base, srv = running
    code, body = _post(base, "123456", feed_server)
    assert code == 200
    saved = tomllib.load(open(srv.feeds_path, "rb"))["feed"]
    assert saved[0]["url"] == feed_server
    assert "1 event(s) found" in body


def test_multiple_feeds_are_saved(running, feed_server):
    base, srv = running
    code, _ = _post(base, "123456", f"{feed_server}\n{feed_server}")
    assert code == 200
    assert len(tomllib.load(open(srv.feeds_path, "rb"))["feed"]) == 2


def test_blank_lines_between_urls_are_ignored(running, feed_server):
    base, srv = running
    code, _ = _post(base, "123456", f"\n{feed_server}\n\n")
    assert code == 200
    assert len(tomllib.load(open(srv.feeds_path, "rb"))["feed"]) == 1


def test_saved_file_is_owner_only(running, feed_server):
    base, srv = running
    _post(base, "123456", feed_server)
    assert stat.S_IMODE(srv.feeds_path.stat().st_mode) == 0o600


# --- the URL is a secret ---

def test_success_page_shows_host_not_token(running, feed_server):
    base, _ = running
    _, body = _post(base, "123456", feed_server)
    assert SECRET_PATH not in body, "the success page must not echo the token"
    assert "127.0.0.1" in body, "but it should say which host it reached"


def test_logs_never_contain_the_token(running, feed_server, caplog):
    base, _ = running
    with caplog.at_level(logging.DEBUG):
        _post(base, "123456", feed_server)
    assert SECRET_PATH not in caplog.text


def test_rejected_pin_does_not_log_the_token(running, feed_server, caplog):
    base, _ = running
    with caplog.at_level(logging.DEBUG):
        _post(base, "000000", feed_server)
    assert SECRET_PATH not in caplog.text


# --- reset ---

def test_reset_removes_the_file(tmp_path):
    path = tmp_path / "ics_feeds.toml"
    write_feeds_file(path, [{"url": "https://h/a.ics"}])
    assert reset_feeds(path) is True
    assert not path.exists()


def test_reset_is_safe_when_nothing_saved(tmp_path):
    assert reset_feeds(tmp_path / "missing.toml") is False


def test_setup_url_is_http_on_the_lan(setup_server):
    setup_server.ip = "192.168.0.5"
    setup_server.port = 8080
    assert setup_server.url == "http://192.168.0.5:8080"
