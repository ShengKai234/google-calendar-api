"""Tests for the Wi-Fi setup form."""
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

from gcal_epd.infrastructure.wifi.nmcli import Network
from gcal_epd.infrastructure.wifi.server import (
    WifiSetupServer,
    generate_ap_password,
    generate_ap_ssid,
    validate_credentials,
)

NETWORKS = [Network("Home", 70, True), Network("<script>x</script>", 40, True),
            Network("Cafe", 30, False)]


@pytest.fixture
def server():
    srv = WifiSetupServer(NETWORKS, port=0)
    srv.port = srv._httpd.server_address[1]
    yield srv
    srv.close()


def _request(srv, data: dict | None = None, timeout: float = 5):
    url = f"http://127.0.0.1:{srv.port}/"
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    try:
        with urllib.request.urlopen(url, data=body, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


# --- helpers ---

def test_ap_ssid_shape():
    assert generate_ap_ssid().startswith("ePaper-Setup-")


def test_ap_password_is_valid_wpa_and_unambiguous():
    for _ in range(50):
        pw = generate_ap_password()
        assert len(pw) == 10
        assert not set(pw) & set("0o1li")


def test_ap_passwords_differ():
    assert len({generate_ap_password() for _ in range(20)}) > 1


@pytest.mark.parametrize("ssid,pw", [("", "12345678"), ("x" * 33, "12345678"),
                                     ("Home", "short")])
def test_validate_credentials_rejects(ssid, pw):
    with pytest.raises(ValueError):
        validate_credentials(ssid, pw)


def test_validate_credentials_allows_open_network():
    assert validate_credentials("Cafe", "") == ("Cafe", "")


def test_url_omits_default_port():
    srv = WifiSetupServer([], port=0)
    try:
        srv.port = 80
        assert srv.url == "http://10.42.0.1"
    finally:
        srv.close()


# --- HTTP ---

def test_get_lists_networks_escaped(server):
    status, body = _request(server)
    assert status == 200
    assert ">Home<" in body
    assert "<script>x</script>" not in body
    assert "&lt;script&gt;" in body
    assert "Cafe (open)" in body


def test_get_shows_last_error(server):
    server.set_error("Could not join Home.")
    _, body = _request(server)
    assert "Could not join Home." in body


def test_post_records_credentials(server):
    status, body = _request(server, {"ssid": "Home", "other_ssid": "",
                                     "password": "correct-horse"})
    assert status == 200
    assert "Connecting to Home" in body
    assert server.take_pending() == ("Home", "correct-horse", [])
    assert server.take_pending() is None


def test_post_hidden_network_uses_typed_name(server):
    _request(server, {"ssid": "__other__", "other_ssid": " Secret Net ",
                      "password": "correct-horse"})
    assert server.take_pending() == ("Secret Net", "correct-horse", [])


def test_post_short_password_is_rejected(server):
    status, body = _request(server, {"ssid": "Home", "password": "short"})
    assert status == 400
    assert "8 to 63" in body
    assert server.take_pending() is None


def test_post_never_echoes_password(server):
    _, body = _request(server, {"ssid": "Home", "password": "short-pw"})
    assert "short-pw" not in body


def test_requests_update_last_activity(server):
    before = server.last_activity
    _request(server)
    assert server.last_activity > before


# --- responsiveness ---

def test_idle_connection_does_not_block_the_page(server):
    """A browser preconnect that never sends must not hold up the real request."""
    idle = socket.create_connection(("127.0.0.1", server.port))
    try:
        start = time.monotonic()
        status, _ = _request(server, timeout=3)
        assert status == 200
        assert time.monotonic() - start < 1
    finally:
        idle.close()


def test_form_answers_while_the_controller_is_busy(server):
    """The controller blocks ~40 s per panel refresh; nothing calls handle_once then."""
    status, _ = _request(server, timeout=3)
    assert status == 200


def test_handle_once_returns_early_on_submission(server):
    _request(server, {"ssid": "Home", "password": "correct-horse"})
    start = time.monotonic()
    server.handle_once()
    assert time.monotonic() - start < 0.5
    assert server.take_pending() == ("Home", "correct-horse", [])


# --- calendar links ---

def test_post_with_calendar_links(server):
    status, body = _request(server, {"ssid": "Home", "password": "correct-horse",
                                     "feeds": "webcal://h/a.ics\n\n https://h/b.ics "})
    assert status == 200
    assert "2 calendar link(s)" in body
    assert server.take_pending() == ("Home", "correct-horse",
                                     ["webcal://h/a.ics", "https://h/b.ics"])


def test_post_bad_calendar_link_is_rejected_and_kept_for_editing(server):
    status, body = _request(server, {"ssid": "Home", "password": "correct-horse",
                                     "feeds": "ftp://h/a.ics"})
    assert status == 400
    assert "Calendar link" in body
    assert "ftp://h/a.ics" in body  # still in the box, to fix
    assert server.take_pending() is None


def test_parse_feed_links_skips_blanks():
    from gcal_epd.infrastructure.wifi.server import parse_feed_links
    assert parse_feed_links("\n https://h/a.ics \n\n") == ["https://h/a.ics"]
