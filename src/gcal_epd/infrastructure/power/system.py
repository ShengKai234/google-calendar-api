"""
What the rest of the Pi is doing: systemd units, logins, processes.

The power manager may only cut the power when nothing is going on, and
each question it asks is answered here by one systemd tool or by /proc.
Commands go through an injected runner as argument lists, never a shell.
A tool that fails answers "cannot tell" (None) rather than raising: the
caller decides what is safe when it does not know.
"""
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

Runner = Callable[[list[str], float], subprocess.CompletedProcess]

# Oneshot units sit in "activating" while their command runs; a unit with
# no RemainAfterExit drops straight back to "inactive" (or "failed").
_BUSY_STATES = {"activating", "deactivating", "reloading"}


def _run(args: list[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


@dataclass(frozen=True)
class UnitState:
    active_state: str
    # CLOCK_MONOTONIC seconds when the main process last exited; None if it
    # never ran this boot (also when a Condition= skipped it).
    last_exit: float | None
    # A job is pending: e.g. a timer fired and the start job waits for the
    # units it is ordered After=, while the unit is still "inactive".
    queued: bool = False

    @property
    def busy(self) -> bool:
        return self.active_state in _BUSY_STATES


def parse_properties(text: str) -> dict[str, str]:
    """`systemctl show` / `loginctl show-session` output: one key=value per line."""
    props = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            props[key] = value
    return props


USEC_INFINITY = 2**64 - 1


def unit_object_path(unit: str) -> str:
    """A unit's D-Bus object path, escaped as systemd does (sd_bus_path_encode):
    every byte but [A-Za-z0-9] becomes _xx, as does a leading digit."""
    label = "".join(
        chr(b) if (chr(b).isascii() and chr(b).isalnum() and not (i == 0 and chr(b).isdigit()))
        else f"_{b:02x}"
        for i, b in enumerate(unit.encode()))
    return f"/org/freedesktop/systemd1/unit/{label or '_'}"


class System:
    def __init__(self, run: Runner = _run, proc: Path = Path("/proc")) -> None:
        self._run = run
        self._proc = proc

    def _cmd(self, *args: str, timeout: float = 15) -> str | None:
        """stdout of a command, or None (logged) if it failed."""
        try:
            result = self._run(list(args), timeout)
        except (OSError, subprocess.TimeoutExpired) as e:
            log.warning("%s failed: %s", " ".join(args[:2]), e)
            return None
        if result.returncode != 0:
            log.warning("%s failed: %s", " ".join(args), (result.stderr or "").strip())
            return None
        return result.stdout

    # --- systemd units ----------------------------------------------
    def unit_state(self, unit: str) -> UnitState | None:
        out = self._cmd("systemctl", "show", unit, "-p", "ActiveState",
                        "-p", "ExecMainExitTimestampMonotonic", "-p", "Job")
        if out is None:
            return None
        props = parse_properties(out)
        try:
            exit_us = int(props.get("ExecMainExitTimestampMonotonic", "0") or 0)
        except ValueError:
            exit_us = 0
        job = props.get("Job", "")
        return UnitState(props.get("ActiveState", "unknown"),
                         exit_us / 1e6 if exit_us else None,
                         queued=job.isdigit() and job != "0")

    def timer_next(self, unit: str) -> float | None:
        """When `unit` (a timer) next fires, in Unix seconds; None if it is not
        scheduled, not installed, or systemd cannot tell.

        Asked over D-Bus, which answers in microseconds: `systemctl show`
        prints this property as a date in the local format whatever
        --timestamp says (systemd 257), so it cannot be parsed (issue #48).
        """
        out = self._cmd("busctl", "get-property", "org.freedesktop.systemd1",
                        unit_object_path(unit), "org.freedesktop.systemd1.Timer",
                        "NextElapseUSecRealtime")
        if out is None:
            return None
        kind, _, value = out.strip().partition(" ")
        if kind != "t" or not value.isdigit():
            return None
        usec = int(value)
        # 0: never; UINT64_MAX (infinity): not loaded, or its service is running.
        if usec == 0 or usec >= USEC_INFINITY:
            return None
        return usec / 1e6

    # --- clock ------------------------------------------------------
    def ntp_synchronized(self) -> bool | None:
        out = self._cmd("timedatectl", "show", "-p", "NTPSynchronized", "--value")
        if out is None:
            return None
        return out.strip() == "yes"

    # --- people -----------------------------------------------------
    def remote_sessions(self) -> int | None:
        """Open SSH (remote) login sessions, or None if logind cannot tell.

        Asked from logind rather than utmp (`who`): logind registers every
        PAM session with whether it is remote, and utmp is on its way out
        of current distributions.
        """
        out = self._cmd("loginctl", "list-sessions", "--no-legend")
        if out is None:
            return None
        count = 0
        for line in out.splitlines():
            fields = line.split()
            if not fields:
                continue
            info = self._cmd("loginctl", "show-session", fields[0],
                             "-p", "Remote", "-p", "Service", "-p", "State")
            if info is None:
                return None
            props = parse_properties(info)
            remote = props.get("Remote") == "yes" or props.get("Service", "").startswith("sshd")
            if remote and props.get("State") != "closing":
                count += 1
        return count

    # --- processes --------------------------------------------------
    def command_lines(self) -> list[list[str]]:
        """argv of every process, from /proc/<pid>/cmdline.

        Catches what systemd units do not: a refresh or the Wi-Fi setup run
        by hand over SSH, or under systemd-run with a transient unit name.
        """
        lines = []
        try:
            entries = list(self._proc.iterdir())
        except OSError as e:
            log.warning("Cannot list %s: %s", self._proc, e)
            return lines
        for entry in entries:
            if not entry.name.isdigit():
                continue
            try:
                raw = (entry / "cmdline").read_bytes()
            except OSError:
                continue  # exited meanwhile, or a kernel thread
            if raw:
                lines.append([a.decode(errors="replace") for a in raw.rstrip(b"\0").split(b"\0")])
        return lines

    # --- actions ----------------------------------------------------
    def daemon_reload(self) -> bool:
        return self._cmd("systemctl", "daemon-reload", timeout=60) is not None

    def try_restart(self, unit: str) -> bool:
        """Restart `unit` if it is running; leave a stopped unit stopped."""
        return self._cmd("systemctl", "try-restart", unit, timeout=60) is not None

    def poweroff(self) -> bool:
        return self._cmd("systemctl", "poweroff", timeout=60) is not None
