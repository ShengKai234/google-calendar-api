"""Tests for the systemd / logind / /proc probes — commands are faked."""
import subprocess

import pytest

from gcal_epd.infrastructure.power.system import System, UnitState, parse_properties


class Runner:
    """Answers commands from a table keyed by the argv prefix."""

    def __init__(self, table=None, fail=()):
        self.table = table or {}
        self.fail = fail
        self.calls = []

    def __call__(self, args, timeout):
        self.calls.append(args)
        key = tuple(args)
        for prefix in self.fail:
            if key[:len(prefix)] == prefix:
                return subprocess.CompletedProcess(args, 1, "", "Failed to connect to bus")
        for prefix, out in self.table.items():
            if key[:len(prefix)] == prefix:
                if isinstance(out, BaseException):
                    raise out
                return subprocess.CompletedProcess(args, 0, out, "")
        return subprocess.CompletedProcess(args, 0, "", "")


def test_parse_properties():
    assert parse_properties("A=1\nB=x=y\n\nnoise") == {"A": "1", "B": "x=y"}


def test_unit_state_running_oneshot():
    run = Runner({("systemctl", "show", "gcal-epd.service"):
                  "ActiveState=activating\nExecMainExitTimestampMonotonic=0\n"})
    state = System(run=run).unit_state("gcal-epd.service")
    assert state == UnitState("activating", None)
    assert state.busy
    assert run.calls[0] == ["systemctl", "show", "gcal-epd.service", "-p", "ActiveState",
                            "-p", "ExecMainExitTimestampMonotonic", "-p", "Job"]


@pytest.mark.parametrize("job, queued", [("Job=635\n", True), ("Job=\n", False),
                                         ("Job=0\n", False), ("", False)])
def test_unit_state_sees_a_pending_job(job, queued):
    # A timer that fired queues a start job; until it runs (After= other
    # units) the service is still "inactive" (issue #48, review 48-1).
    run = Runner({("systemctl", "show"):
                  "ActiveState=inactive\nExecMainExitTimestampMonotonic=0\n" + job})
    assert System(run=run).unit_state("epd-update.service").queued is queued


def test_unit_state_finished():
    run = Runner({("systemctl", "show"):
                  "ActiveState=inactive\nExecMainExitTimestampMonotonic=95500000\n"})
    state = System(run=run).unit_state("gcal-epd.service")
    assert state == UnitState("inactive", 95.5)
    assert not state.busy


@pytest.mark.parametrize("state", ["failed", "inactive", "active"])
def test_unit_state_not_busy(state):
    assert not UnitState(state, None).busy


def test_unit_state_unknown_when_systemctl_fails():
    assert System(run=Runner(fail=[("systemctl",)])).unit_state("x.service") is None


def test_unit_state_unknown_when_systemctl_hangs():
    run = Runner({("systemctl",): subprocess.TimeoutExpired("systemctl", 15)})
    assert System(run=run).unit_state("x.service") is None


@pytest.mark.parametrize("out,expected", [("yes\n", True), ("no\n", False)])
def test_ntp_synchronized(out, expected):
    run = Runner({("timedatectl", "show", "-p", "NTPSynchronized", "--value"): out})
    assert System(run=run).ntp_synchronized() is expected


def test_ntp_unknown():
    assert System(run=Runner(fail=[("timedatectl",)])).ntp_synchronized() is None


SESSIONS = "c1 1000 admin - 1234 user tty1 no -\n7 1000 admin - 2345 user pts/0 no -\n"


def test_remote_sessions_counts_ssh_only():
    run = Runner({
        ("loginctl", "list-sessions"): SESSIONS,
        ("loginctl", "show-session", "c1"): "Remote=no\nService=login\nState=active\n",
        ("loginctl", "show-session", "7"): "Remote=yes\nService=sshd\nState=active\n",
    })
    assert System(run=run).remote_sessions() == 1


def test_remote_sessions_ignores_closing():
    run = Runner({
        ("loginctl", "list-sessions"): "7 1000 admin - 2345 user pts/0 no -\n",
        ("loginctl", "show-session", "7"): "Remote=yes\nService=sshd\nState=closing\n",
    })
    assert System(run=run).remote_sessions() == 0


def test_remote_sessions_none():
    assert System(run=Runner({("loginctl", "list-sessions"): ""})).remote_sessions() == 0


def test_remote_sessions_unknown_when_loginctl_fails():
    assert System(run=Runner(fail=[("loginctl",)])).remote_sessions() is None
    run = Runner({("loginctl", "list-sessions"): SESSIONS},
                 fail=[("loginctl", "show-session")])
    assert System(run=run).remote_sessions() is None


def test_command_lines(tmp_path):
    for pid, cmdline in (("1", b"/sbin/init\0"), ("42", b"python\0-m\0gcal_epd.main\0"),
                         ("43", b"")):
        (tmp_path / pid).mkdir()
        (tmp_path / pid / "cmdline").write_bytes(cmdline)
    (tmp_path / "self").mkdir()
    (tmp_path / "99").mkdir()  # exited: no cmdline
    lines = System(proc=tmp_path).command_lines()
    assert sorted(lines) == [["/sbin/init"], ["python", "-m", "gcal_epd.main"]]


def test_command_lines_without_proc(tmp_path):
    assert System(proc=tmp_path / "missing").command_lines() == []


def test_actions():
    run = Runner()
    system = System(run=run)
    assert system.daemon_reload() and system.try_restart("gcal-epd.timer") and system.poweroff()
    assert run.calls == [["systemctl", "daemon-reload"],
                         ["systemctl", "try-restart", "gcal-epd.timer"],
                         ["systemctl", "poweroff"]]


def test_poweroff_failure_is_reported():
    assert not System(run=Runner(fail=[("systemctl",)])).poweroff()


TIMER_PROPERTY = ["org.freedesktop.systemd1.Timer", "NextElapseUSecRealtime"]


def test_timer_next_reads_microseconds_over_dbus():
    # busctl prints the property as a number whatever the locale or the
    # systemd version (`t <microseconds since the epoch>`).
    run = Runner({("busctl",): "t 1795129200000000\n"})
    assert System(run=run).timer_next("epd-update.timer") == 1795129200.0
    assert run.calls[0] == ["busctl", "get-property", "org.freedesktop.systemd1",
                            "/org/freedesktop/systemd1/unit/epd_2dupdate_2etimer",
                            *TIMER_PROPERTY]


def test_timer_next_does_not_depend_on_systemctl_timestamp_format():
    # systemd 257 ignores --timestamp=unix for this property and prints a
    # date (issue #48); whatever systemctl says, the answer comes from D-Bus.
    run = Runner({("systemctl",): "NextElapseUSecRealtime=Fri 2026-11-20 19:01:00 CST\n",
                  ("busctl",): "t 1795172460000000\n"})
    assert System(run=run).timer_next("epd-update.timer") == 1795172460.0


@pytest.mark.parametrize("unit, path", [
    ("epd-update.timer", "/org/freedesktop/systemd1/unit/epd_2dupdate_2etimer"),
    ("gcal-epd.timer", "/org/freedesktop/systemd1/unit/gcal_2depd_2etimer"),
    ("2x.timer", "/org/freedesktop/systemd1/unit/_32x_2etimer"),
])
def test_timer_next_escapes_the_unit_object_path(unit, path):
    run = Runner({("busctl",): "t 1\n"})
    System(run=run).timer_next(unit)
    assert run.calls[0][3] == path


@pytest.mark.parametrize("out", [
    "t 0\n",                         # never elapses
    "t 18446744073709551615\n",      # infinity: not installed, or its service is running
    "", "t\n", "t x\n", "s \"x\"\n",
])
def test_timer_next_none_when_not_scheduled(out):
    assert System(run=Runner({("busctl",): out})).timer_next("t.timer") is None


def test_timer_next_none_when_busctl_fails():
    assert System(run=Runner(fail=[("busctl",)])).timer_next("t.timer") is None
