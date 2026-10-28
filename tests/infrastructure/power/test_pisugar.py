"""Tests for the pisugar-server client — the server and the socket are faked."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from gcal_epd.infrastructure.power.pisugar import (
    EVERY_DAY,
    PiSugar,
    PiSugarError,
    TcpTransport,
    parse_time,
    time_of_day_utc,
)
from tests.infrastructure.power.fake_pisugar import FakePiSugarServer

TPE = ZoneInfo("Asia/Taipei")
WAKE = datetime(2026, 10, 20, 6, 55, tzinfo=TPE)


@pytest.fixture
def server():
    return FakePiSugarServer()


@pytest.fixture
def sugar(server):
    return PiSugar(server)


# --- reads ------------------------------------------------------------
def test_reads(sugar, server):
    assert sugar.available()
    assert sugar.model() == "PiSugar 3"
    assert sugar.battery() == 87.5
    assert sugar.power_plugged() is False
    assert sugar.rtc_time() == server.rtc
    assert server.commands[:2] == ["get model", "get model"]


def test_unreachable_server_is_not_available():
    assert not PiSugar(FakePiSugarServer(up=False)).available()


def test_error_reply_raises(sugar, server):
    server.errors["battery"] = "I2C bus error"
    with pytest.raises(PiSugarError, match="I2C bus error"):
        sugar.battery()


def test_reply_for_another_command_raises():
    with pytest.raises(PiSugarError, match="unexpected reply"):
        PiSugar(lambda cmd: "single").battery()


@pytest.mark.parametrize("text", ["yes", "", "2026-10-19"])
def test_bad_values_raise(text):
    with pytest.raises(PiSugarError):
        PiSugar(lambda cmd: f"battery_power_plugged: {text}").power_plugged()
    with pytest.raises(PiSugarError):
        PiSugar(lambda cmd: f"rtc_time: {text}").rtc_time()


def test_parse_time_needs_an_offset():
    assert parse_time("2026-10-19T06:55:00.000+08:00").utcoffset() == timedelta(hours=8)
    with pytest.raises(PiSugarError):
        parse_time("2026-10-19T06:55:00")


# --- clock sync -------------------------------------------------------
def test_clock_sync_commands(sugar, server):
    sugar.pi_to_rtc()
    sugar.rtc_to_pi()
    assert server.commands == ["rtc_pi2rtc", "rtc_rtc2pi"]


def test_clock_sync_failure_raises(sugar, server):
    server.errors["rtc_pi2rtc"] = "I2C write failed"
    with pytest.raises(PiSugarError, match="rtc_pi2rtc failed: I2C write failed"):
        sugar.pi_to_rtc()


# --- alarm ------------------------------------------------------------
def test_set_alarm_sends_iso_time_and_daily_mask(sugar, server):
    sugar.set_alarm(WAKE.replace(microsecond=1234))
    assert server.commands == ["rtc_alarm_set 2026-10-20T06:55:00+08:00 127"]
    assert EVERY_DAY == 127


def test_set_alarm_needs_an_aware_time(sugar):
    with pytest.raises(ValueError):
        sugar.set_alarm(datetime(2026, 10, 20, 6, 55))


def test_alarm_verified_compares_time_of_day_only(sugar, server):
    """The PiSugar 3 stores no date: the read-back date is a placeholder."""
    sugar.set_alarm_verified(WAKE)
    assert server.alarm == (22, 55, 0)  # UTC
    assert sugar.alarm_time().year == 2000
    assert time_of_day_utc(sugar.alarm_time()) == time_of_day_utc(WAKE)
    assert sugar.alarm_enabled() and sugar.alarm_repeat() == 127


def test_alarm_verified_in_another_server_zone():
    server = FakePiSugarServer(server_offset=0)  # Pi's own zone is UTC
    PiSugar(server).set_alarm_verified(WAKE)


def test_alarm_not_stored_fails_verification(sugar, server):
    server.drop_alarm = True
    with pytest.raises(PiSugarError, match="reads back"):
        sugar.set_alarm_verified(WAKE)


def test_alarm_refused_with_auto_power_on(sugar, server):
    server.auto_power_on = True
    with pytest.raises(PiSugarError, match="auto_power_on"):
        sugar.set_alarm_verified(WAKE)


def test_alarm_disabled_fails_verification(sugar, server):
    server.errors["rtc_alarm_enabled"] = "false"  # reads "rtc_alarm_enabled: false"
    with pytest.raises(PiSugarError, match="disabled"):
        sugar.set_alarm_verified(WAKE)


def test_alarm_wrong_repeat_fails_verification(sugar, server):
    server.errors["alarm_repeat"] = "0"
    with pytest.raises(PiSugarError, match="repeat"):
        sugar.set_alarm_verified(WAKE)


def test_alarm_unreadable_fails_verification(sugar, server):
    server.errors["rtc_alarm_time"] = "Invalid"
    with pytest.raises(PiSugarError):
        sugar.set_alarm_verified(WAKE)


# --- TCP transport ----------------------------------------------------
class FakeSocket:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.sent = b""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def sendall(self, data):
        self.sent += data

    def recv(self, size):
        return self.chunks.pop(0) if self.chunks else b""


def test_tcp_sends_a_line_and_reads_one_back():
    sock = FakeSocket([b"batt", b"ery: 80.1\n", b"single\n"])
    calls = []

    def connect(address, timeout):
        calls.append((address, timeout))
        return sock

    reply = TcpTransport(connect=connect)("get battery")
    assert reply == "battery: 80.1"
    assert sock.sent == b"get battery\n"
    assert calls == [(("127.0.0.1", 8423), 5.0)]


def test_tcp_unreachable_raises():
    def connect(address, timeout):
        raise ConnectionRefusedError("refused")

    with pytest.raises(PiSugarError, match="not reachable"):
        TcpTransport(connect=connect)("get model")


def test_tcp_empty_reply_raises():
    with pytest.raises(PiSugarError, match="no answer"):
        TcpTransport(connect=lambda a, timeout: FakeSocket([]))("get model")


def test_tcp_against_a_real_socket():
    """One round trip over a real loopback socket."""
    import socket
    import threading

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)

    def serve():
        conn, _ = listener.accept()
        with conn:
            assert conn.recv(100) == b"get model\n"
            conn.sendall(b"model: PiSugar 3\n")

    t = threading.Thread(target=serve)
    t.start()
    try:
        transport = TcpTransport(port=listener.getsockname()[1])
        assert PiSugar(transport).model() == "PiSugar 3"
    finally:
        t.join(5)
        listener.close()


def test_utc_time_of_day():
    assert time_of_day_utc(WAKE) == (22, 55, 0)
    assert time_of_day_utc(WAKE.astimezone(timezone.utc)) == (22, 55, 0)
