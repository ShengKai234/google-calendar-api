"""Tests for reading the battery over pisugar-server's TCP text interface.

A fake pisugar-server listens on a loopback ephemeral port (never 0.0.0.0).
"""
import logging
import socket
import threading
import time

import pytest

from gcal_epd.domain.battery import BatteryStatus
from gcal_epd.infrastructure.power.battery import read_battery


class FakeServer:
    """Answers each connection's one line from `replies` (command -> reply).

    A reply of None never answers; a (delay, reply) tuple answers late.
    """

    def __init__(self, replies: dict):
        self.replies = replies
        self.commands: list[str] = []
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(8)
        self.port = self.listener.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        self.listener.settimeout(0.05)
        while not self._stop.is_set():
            try:
                conn, _ = self.listener.accept()
            except OSError:
                continue
            threading.Thread(target=self._answer, args=(conn,), daemon=True).start()

    def _answer(self, conn):
        with conn:
            conn.settimeout(3)
            try:
                command = conn.recv(100).decode().strip()
            except OSError:
                return
            self.commands.append(command)
            reply = self.replies.get(command, "error: unrecognized")
            if isinstance(reply, tuple):
                delay, reply = reply
                time.sleep(delay)
            if reply is None:
                self._stop.wait(3)
                return
            try:
                conn.sendall(reply.encode() + b"\n")
            except OSError:
                pass

    def close(self):
        self._stop.set()
        self._thread.join(2)
        self.listener.close()


@pytest.fixture
def serve():
    servers = []

    def start(battery="battery: 87.5", charging="battery_charging: false"):
        s = FakeServer({"get battery": battery, "get battery_charging": charging})
        servers.append(s)
        return s

    yield start
    for s in servers:
        s.close()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _warnings(caplog):
    return [r for r in caplog.records if r.levelno == logging.WARNING]


def test_reads_percent_and_not_charging(serve, caplog):
    server = serve()
    assert read_battery(port=server.port) == BatteryStatus(87.5, charging=False)
    assert server.commands == ["get battery", "get battery_charging"]
    assert not _warnings(caplog)


def test_reads_charging(serve):
    server = serve(battery="battery: 85", charging="battery_charging: true")
    assert read_battery(port=server.port) == BatteryStatus(85.0, charging=True)


def test_connection_refused_is_unknown_with_one_warning(caplog):
    caplog.set_level(logging.WARNING)
    assert read_battery(port=_free_port()) == BatteryStatus.unknown()
    assert len(_warnings(caplog)) == 1


@pytest.mark.parametrize("battery, charging", [
    ("battery: lots", "battery_charging: false"),          # not a number
    ("garbage", "battery_charging: false"),                # no "battery: " prefix
    ("battery: 87.5", "battery_charging: maybe"),          # not true/false
    ("battery: I2C bus error", "battery_charging: false"),  # server-side error text
    ("battery: 150", "battery_charging: false"),           # out of range
    ("battery: -1", "battery_charging: false"),
    ("battery: nan", "battery_charging: false"),
    ("battery: inf", "battery_charging: false"),
])
def test_bad_reply_is_unknown_with_one_warning(serve, caplog, battery, charging):
    caplog.set_level(logging.WARNING)
    server = serve(battery=battery, charging=charging)
    assert read_battery(port=server.port) == BatteryStatus.unknown()
    assert len(_warnings(caplog)) == 1


def test_silent_server_times_out_within_the_budget(serve, caplog):
    caplog.set_level(logging.WARNING)
    server = serve(battery=None)
    start = time.monotonic()
    assert read_battery(port=server.port, timeout=0.3) == BatteryStatus.unknown()
    assert time.monotonic() - start < 0.6
    assert len(_warnings(caplog)) == 1


def test_one_timeout_covers_both_commands(serve, caplog):
    """A slow first answer leaves less time for the second, not a fresh second."""
    caplog.set_level(logging.WARNING)
    server = serve(battery=(0.2, "battery: 50"), charging=None)
    start = time.monotonic()
    assert read_battery(port=server.port, timeout=0.4) == BatteryStatus.unknown()
    assert time.monotonic() - start < 0.7
    assert len(_warnings(caplog)) == 1


def test_default_timeout_is_one_second():
    import inspect
    assert inspect.signature(read_battery).parameters["timeout"].default == 1.0
