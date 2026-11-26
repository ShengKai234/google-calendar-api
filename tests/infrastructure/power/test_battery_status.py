"""The level drawn on a refresh: parse pisugar-server, and survive its absence.

The server is a real loopback socket. Replies follow pisugar-server
(github.com/PiSugar/pisugar-power-manager-rs): one command per connection,
`battery: <number>` and `battery_charging: true|false`, each line ending
in a newline. On a PiSugar 3 the charging flag is power-plugged and
charging-allowed, already combined by the server.
"""
import logging
import socket
import threading
import time

from PIL import Image

from gcal_epd.domain.battery import BatteryStatus
from gcal_epd.infrastructure.power.pisugar import read_battery_status
from gcal_epd.render.layout import PALETTE


class ScriptedPiSugar:
    """One reply line per connection, like pisugar-server's TCP API.

    `hang` accepts and never answers, so the client hits its own timeout.
    `drop` accepts and closes with no bytes.
    """

    def __init__(self, replies: dict[str, str], *, hang: bool = False, drop: bool = False):
        self.replies = replies
        self.hang = hang
        self.drop = drop
        self.commands: list[str] = []
        self.connections = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._sock = socket.socket()
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(16)
        self.port = self._sock.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        self._sock.settimeout(0.1)
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn: socket.socket) -> None:
        with conn:
            with self._lock:
                self.connections += 1
            if self.hang:
                self._stop.wait(5)
                return
            if self.drop:
                return
            conn.settimeout(1)
            data = b""
            while b"\n" not in data:
                try:
                    chunk = conn.recv(4096)
                except socket.timeout:
                    return
                if not chunk:
                    return
                data += chunk
            cmd = data.decode(errors="replace").split("\n", 1)[0].strip()
            with self._lock:
                self.commands.append(cmd)
            reply = self.replies.get(cmd, "error: unrecognized")
            conn.sendall(reply.encode() + b"\n")

    def close(self) -> None:
        self._stop.set()
        self._sock.close()
        self._thread.join(2)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _warnings(caplog):
    return [r for r in caplog.records if r.levelno >= logging.WARNING]


def _read(server, timeout=1.0):
    return read_battery_status(port=server.port, timeout=timeout)


# --- parsing ----------------------------------------------------------

def test_parses_the_official_battery_line():
    """README example shape: `battery: 87.5`, then charging true/false."""
    replies = {
        "get battery": "battery: 87.5",
        "get battery_charging": "battery_charging: false",
    }
    with ScriptedPiSugar(replies) as server:
        status = _read(server)
        commands = list(server.commands)
    assert status == BatteryStatus(87.5, False)
    assert commands == ["get battery", "get battery_charging"]
    assert status.shown_percent() == 88
    assert not status.is_low(20)


def test_parses_a_charging_level():
    replies = {
        "get battery": "battery: 85",
        "get battery_charging": "battery_charging: true",
    }
    with ScriptedPiSugar(replies) as server:
        status = _read(server)
    assert status == BatteryStatus(85.0, True)
    assert status.shown_percent() == 85
    assert not status.is_low(20)


def test_a_low_level_is_below_the_threshold():
    replies = {
        "get battery": "battery: 15.2",
        "get battery_charging": "battery_charging: false",
    }
    with ScriptedPiSugar(replies) as server:
        status = _read(server)
    assert status == BatteryStatus(15.2, False)
    assert status.shown_percent() == 15
    assert status.is_low(20)


def test_shown_percent_rounds_half_up_and_the_warning_uses_that_number():
    """The mark warns on the integer printed on the glass, not the raw float."""
    assert BatteryStatus(19.5).shown_percent() == 20
    assert not BatteryStatus(19.5).is_low(20)
    assert BatteryStatus(19.4).shown_percent() == 19
    assert BatteryStatus(19.4).is_low(20)
    assert BatteryStatus(20).shown_percent() == 20
    assert not BatteryStatus(20).is_low(20)
    assert BatteryStatus(0).is_low(20)
    assert not BatteryStatus(100).is_low(20)


def test_a_bad_charging_reply_keeps_the_level(caplog):
    replies = {
        "get battery": "battery: 85",
        "get battery_charging": "battery_charging: maybe",
    }
    with ScriptedPiSugar(replies) as server:
        with caplog.at_level(logging.WARNING):
            status = _read(server)
    assert status == BatteryStatus(85.0, None)
    assert _warnings(caplog) == []


def test_a_level_above_full_is_not_a_reading(caplog):
    replies = {"get battery": "battery: 250"}
    with ScriptedPiSugar(replies) as server:
        with caplog.at_level(logging.WARNING):
            status = _read(server)
        assert server.connections == 1  # do not ask charging after a bad level
    assert status is None
    assert len(_warnings(caplog)) == 1
    assert _warnings(caplog)[0].exc_info is None


# --- unreachable and garbage ------------------------------------------

def test_garbage_is_one_warning_and_no_reading(caplog):
    replies = {"get battery": "nope"}
    with ScriptedPiSugar(replies) as server:
        with caplog.at_level(logging.WARNING):
            status = _read(server)
        assert server.connections == 1
    assert status is None
    warnings = _warnings(caplog)
    assert len(warnings) == 1
    assert "Battery level unavailable" in warnings[0].getMessage()
    assert warnings[0].exc_info is None


def test_a_non_numeric_level_is_unavailable(caplog):
    replies = {"get battery": "battery: banana"}
    with ScriptedPiSugar(replies) as server:
        with caplog.at_level(logging.WARNING):
            assert _read(server) is None
    assert len(_warnings(caplog)) == 1


def test_a_closed_connection_is_unavailable(caplog):
    with ScriptedPiSugar({}, drop=True) as server:
        with caplog.at_level(logging.WARNING):
            assert _read(server) is None
    assert len(_warnings(caplog)) == 1


def test_unreachable_port_returns_none_quickly(caplog):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    started = time.monotonic()
    with caplog.at_level(logging.WARNING):
        status = read_battery_status(port=port, timeout=1)
    elapsed = time.monotonic() - started
    assert status is None
    assert elapsed < 0.5
    assert len(_warnings(caplog)) == 1


def test_a_silent_server_times_out_without_a_second_command(caplog):
    with ScriptedPiSugar({}, hang=True) as server:
        started = time.monotonic()
        with caplog.at_level(logging.WARNING):
            status = read_battery_status(port=server.port, timeout=0.4)
        elapsed = time.monotonic() - started
        connections = server.connections
    assert status is None
    assert connections == 1
    assert 0.3 <= elapsed < 1.5
    assert len(_warnings(caplog)) == 1
    assert _warnings(caplog)[0].exc_info is None


# --- the refresh still draws ------------------------------------------

def test_a_refresh_draws_a_low_battery_read_from_the_socket(tmp_path, monkeypatch):
    from gcal_epd.application import display_service
    from gcal_epd.config import PROJECT_ROOT

    config = {"display": {
        "output_path": "preview.png",
        "font_path": "assets/fonts/NotoSansCJKtc-Regular.otf",
        "low_battery_percent": 20,
    }}
    replies = {
        "get battery": "battery: 15",
        "get battery_charging": "battery_charging: false",
    }
    with ScriptedPiSugar(replies) as server:
        monkeypatch.setattr(
            display_service, "read_battery_status",
            lambda: read_battery_status(port=server.port, timeout=1),
        )
        display_service.run(
            event_repos=[], weather_repo=None, config=config,
            project_root=PROJECT_ROOT, data_dir=tmp_path,
        )
    img = Image.open(tmp_path / "preview.png")
    colors = {c for _, c in img.getcolors(maxcolors=img.size[0] * img.size[1])}
    assert PALETTE["red"] in colors


def test_a_refresh_still_saves_the_page_when_pisugar_is_down(tmp_path, monkeypatch, caplog):
    from gcal_epd.application import display_service
    from gcal_epd.config import PROJECT_ROOT

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    config = {"display": {"output_path": "preview.png", "font_path": ""}}
    monkeypatch.setattr(
        display_service, "read_battery_status",
        lambda: read_battery_status(port=port, timeout=1),
    )
    with caplog.at_level(logging.WARNING):
        display_service.run(
            event_repos=[], weather_repo=None, config=config,
            project_root=PROJECT_ROOT, data_dir=tmp_path,
        )
    img = Image.open(tmp_path / "preview.png")
    assert img.size[0] > 0
    colors = {c for _, c in img.getcolors(maxcolors=img.size[0] * img.size[1])}
    assert PALETTE["red"] not in colors
    assert len(_warnings(caplog)) == 1
