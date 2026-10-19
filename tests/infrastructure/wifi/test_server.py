"""Tests for the Wi-Fi setup form."""
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import time as clock

import pytest

from gcal_epd.domain.power_schedule import PowerSchedule
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


# --- wake-up times ---

THREE = PowerSchedule(slots=(clock(6, 0), clock(12, 30), clock(21, 15)),
                      enabled=False, wake_lead_minutes=9)


@pytest.fixture
def scheduled():
    """Start a form with a recording save function; yields a starter."""
    started = []

    def start(schedule=None, save=None):
        saved = []
        srv = WifiSetupServer(NETWORKS, port=0, schedule=schedule,
                              save_schedule=save or saved.append)
        srv.port = srv._httpd.server_address[1]
        started.append(srv)
        return srv, saved
    yield start
    for srv in started:
        srv.close()


def _submit(srv, fields: list[tuple[str, str]], timeout: float = 5):
    """POST fields in order, repeated names included, as a browser does."""
    return _request(srv, fields, timeout)


def _wifi_form(*slots, enabled=True, password="correct-horse", feeds=""):
    fields = [("ssid", "Home"), ("other_ssid", ""), ("password", password),
              ("feeds", feeds), ("schedule", "1")]
    fields += [("slot", s) for s in slots]
    if enabled:
        fields.append(("enabled", "1"))
    return fields


def _time_inputs(body: str) -> list[str]:
    return re.findall(r'<input type="time" name="slot"[^>]*value="([^"]*)"', body)


def test_form_prefills_the_default_two_times(scheduled):
    srv, _ = scheduled()
    _, body = _request(srv)
    assert "Display wake-up times" in body
    assert _time_inputs(body) == ["07:00", "19:00"]
    assert 'name="enabled" value="1" checked' in body


def test_form_shows_one_input_per_slot_and_the_checkbox_state(scheduled):
    srv, _ = scheduled(schedule=THREE)
    _, body = _request(srv)
    assert _time_inputs(body) == ["06:00", "12:30", "21:15"]
    assert 'name="enabled" value="1">' in body


def test_accepted_form_saves_the_times(scheduled):
    srv, saved = scheduled(schedule=THREE)
    status, _ = _submit(srv, _wifi_form("08:00", "", "20:00"))
    assert status == 200
    assert saved == [PowerSchedule(slots=(clock(8, 0), clock(20, 0)), enabled=True,
                                   wake_lead_minutes=9)]
    assert srv.take_pending() == ("Home", "correct-horse", [])


def test_times_are_saved_without_calendar_links(scheduled):
    """The schedule must not depend on links being present or valid."""
    srv, saved = scheduled()
    _submit(srv, _wifi_form("06:30", "18:30", enabled=False))
    assert saved[0].slots == (clock(6, 30), clock(18, 30))
    assert saved[0].enabled is False


def test_reloaded_form_shows_the_times_just_saved(scheduled):
    """A failed join brings the hotspot back; the form should show the new times."""
    srv, _ = scheduled()
    _submit(srv, _wifi_form("06:30", "18:30"))
    _, body = _request(srv)
    assert _time_inputs(body) == ["06:30", "18:30"]


@pytest.mark.parametrize("slots,message", [
    (("07:00", "24:00"), "24:00 is not a time of day"),
    (("07:00", "07:20"), "at least 30 minutes apart"),
    (("",), "Set between 1 and 8 times"),
])
def test_bad_times_reject_the_form_and_keep_what_was_typed(scheduled, slots, message):
    srv, saved = scheduled()
    status, body = _submit(srv, _wifi_form(*slots, enabled=False,
                                           feeds="https://h.example/a.ics"))
    assert status == 400
    assert message in body and 'class="msg err"' in body
    assert _time_inputs(body) == list(slots)
    assert "https://h.example/a.ics" in body
    assert 'name="enabled" value="1">' in body
    assert "correct-horse" not in body  # the password is never echoed
    assert saved == [] and srv.take_pending() is None


def test_bad_credentials_keep_the_times_and_save_nothing(scheduled):
    srv, saved = scheduled()
    status, body = _submit(srv, _wifi_form("05:00", "17:00", password="short"))
    assert status == 400
    assert _time_inputs(body) == ["05:00", "17:00"]
    assert saved == []


def test_a_form_without_the_section_leaves_the_schedule_alone(scheduled):
    srv, saved = scheduled()
    _request(srv, {"ssid": "Home", "password": "correct-horse"})
    assert saved == []
    assert srv.take_pending() == ("Home", "correct-horse", [])


def test_failed_save_does_not_block_joining(scheduled):
    def broken(schedule):
        raise OSError("read-only file system")
    srv, _ = scheduled(save=broken)
    status, body = _submit(srv, _wifi_form("08:00", "20:00"))
    assert status == 200 and "Connecting to Home" in body
    assert srv.take_pending() == ("Home", "correct-horse", [])
