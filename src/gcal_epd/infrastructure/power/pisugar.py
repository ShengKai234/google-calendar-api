"""
Client for pisugar-server, the PiSugar's own daemon.

The PiSugar 3 keeps an RTC with one wake-up alarm and switches the Pi's
power. We never touch its I2C registers ourselves: pisugar-server owns the
bus and offers a line-based text API on TCP 127.0.0.1:8423 (and a unix
socket). One request per connection keeps this stateless; the server is
local, so a connection costs next to nothing.

Command names, arguments and reply formats are from the official repo,
github.com/PiSugar/pisugar-power-manager-rs:

- README.md, "Unix Domain Socket / Webscoket / TCP" command table:
  `get battery`, `get battery_power_plugged`, `get rtc_time`,
  `get rtc_alarm_time`, `get rtc_alarm_enabled`, `get alarm_repeat`,
  `get model`, `rtc_pi2rtc`, `rtc_rtc2pi`,
  `rtc_alarm_set [ISO8601 time string] [repeat]` with the example
  `rtc_alarm_set 2020-06-26T16:09:34+08:00 127` ("127 (1111111)" = every
  day of the week).
- pisugar-server/src/cmds.rs, `Response::entire_string`: every reply is
  "<command>: <result>", where <result> is the value, "done" for a command
  that returns nothing, or the error text. `get` replies are keyed by the
  name after "get" ("battery: 87.5"). pisugar-server/src/stream.rs ends
  each reply with "\n".
- pisugar-core/src/pisugar3.rs + rtc.rs: the PiSugar 3 alarm stores only
  hour, minute and second (in UTC) plus the weekday repeat mask; the date
  read back is a placeholder. So an alarm is compared by time of day.
- pisugar-core/src/lib.rs `write_alarm`: refused while `auto_power_on` is
  on ("auto_power_on is in conflict with alarm function").
"""
import logging
import socket
from datetime import datetime, timezone
from typing import Callable

log = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8423
TIMEOUT = 5.0           # seconds; the server answers from memory or one I2C read
EVERY_DAY = 0b1111111   # alarm repeat mask: all seven weekdays (README example 127)
_DONE = "done"

Transport = Callable[[str], str]


class PiSugarError(RuntimeError):
    """pisugar-server is unreachable, or answered with an error."""


class TcpTransport:
    """Send one command line to pisugar-server and return its reply line."""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 timeout: float = TIMEOUT,
                 connect: Callable[..., socket.socket] = socket.create_connection) -> None:
        self.address = (host, port)
        self.timeout = timeout
        self._connect = connect

    def __call__(self, command: str) -> str:
        try:
            with self._connect(self.address, timeout=self.timeout) as sock:
                sock.sendall(command.encode() + b"\n")
                data = b""
                while b"\n" not in data:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    data += chunk
        except OSError as e:  # refused, timed out, reset
            raise PiSugarError(f"pisugar-server at {self.address[0]}:{self.address[1]} "
                               f"is not reachable: {e}") from None
        line = data.decode(errors="replace").split("\n", 1)[0].strip()
        if not line:
            raise PiSugarError(f"pisugar-server gave no answer to {command.split()[0]!r}")
        return line


def parse_bool(text: str) -> bool:
    if text in ("true", "false"):
        return text == "true"
    raise PiSugarError(f"expected true or false, got {text!r}")


def parse_time(text: str) -> datetime:
    """The server's ISO 8601 / RFC 3339 times, e.g. 2026-10-19T06:55:00.000+08:00."""
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        raise PiSugarError(f"expected an ISO 8601 time, got {text!r}") from None
    if when.tzinfo is None:
        raise PiSugarError(f"time without a UTC offset: {text!r}")
    return when


def time_of_day_utc(when: datetime) -> tuple[int, int, int]:
    """What the PiSugar 3 alarm really holds: hour, minute, second in UTC."""
    utc = when.astimezone(timezone.utc)
    return utc.hour, utc.minute, utc.second


class PiSugar:
    def __init__(self, transport: Transport | None = None) -> None:
        self._send = transport or TcpTransport()

    # --- plumbing ---------------------------------------------------
    def _request(self, command: str, key: str) -> str:
        """Send `command`; return the result after "<key>: ", or raise."""
        reply = self._send(command)
        prefix = f"{key}: "
        if not reply.startswith(prefix):
            # A parse error comes back without the prefix, with a usage hint.
            raise PiSugarError(f"{command.split()[0]}: unexpected reply {reply!r}")
        return reply[len(prefix):].strip()

    def _get(self, name: str) -> str:
        return self._request(f"get {name}", name)

    def _do(self, command: str) -> None:
        """A command with no value: success is "<command>: done"."""
        name = command.split()[0]
        result = self._request(command, name)
        if result != _DONE:
            raise PiSugarError(f"{name} failed: {result}")

    # --- reads ------------------------------------------------------
    def available(self) -> bool:
        """True if pisugar-server answers; it only runs with a PiSugar fitted."""
        try:
            self.model()
            return True
        except PiSugarError:
            return False

    def model(self) -> str:
        return self._get("model")

    def battery(self) -> float:
        """Charge level in percent."""
        text = self._get("battery")
        try:
            return float(text)
        except ValueError:
            raise PiSugarError(f"battery: {text}") from None

    def power_plugged(self) -> bool:
        return parse_bool(self._get("battery_power_plugged"))

    def rtc_time(self) -> datetime:
        return parse_time(self._get("rtc_time"))

    def alarm_time(self) -> datetime:
        """The alarm; only its time of day is meaningful (see module doc)."""
        return parse_time(self._get("rtc_alarm_time"))

    def alarm_enabled(self) -> bool:
        return parse_bool(self._get("rtc_alarm_enabled"))

    def alarm_repeat(self) -> int:
        text = self._get("alarm_repeat")
        try:
            return int(text)
        except ValueError:
            raise PiSugarError(f"alarm_repeat: {text}") from None

    # --- writes -----------------------------------------------------
    def pi_to_rtc(self) -> None:
        """Write the system clock to the RTC (`rtc_pi2rtc`)."""
        self._do("rtc_pi2rtc")

    def rtc_to_pi(self) -> None:
        """Set the system clock from the RTC (`rtc_rtc2pi`)."""
        self._do("rtc_rtc2pi")

    def set_alarm(self, when: datetime, repeat: int = EVERY_DAY) -> None:
        """Set the one RTC wake-up alarm. `when` must be timezone-aware.

        Seconds only, no fraction: the server parses the argument as a
        chrono DateTime<FixedOffset>, as in the README example.
        """
        if when.tzinfo is None:
            raise ValueError("alarm time must be timezone-aware")
        stamp = when.replace(microsecond=0).isoformat()
        self._do(f"rtc_alarm_set {stamp} {repeat}")

    def set_alarm_verified(self, when: datetime, repeat: int = EVERY_DAY) -> None:
        """Set the alarm, read it back, and raise unless it is what was asked.

        Powering off on an alarm that did not take would leave the Pi off
        for good, so "the server said done" is not enough.
        """
        self.set_alarm(when, repeat)
        got = self.alarm_time()
        if time_of_day_utc(got) != time_of_day_utc(when):
            raise PiSugarError(f"alarm reads back as {got.isoformat()}, "
                               f"not {when.isoformat()}")
        if not self.alarm_enabled():
            raise PiSugarError("alarm reads back as disabled")
        got_repeat = self.alarm_repeat()
        if got_repeat != repeat:
            raise PiSugarError(f"alarm repeat reads back as {got_repeat}, not {repeat}")
