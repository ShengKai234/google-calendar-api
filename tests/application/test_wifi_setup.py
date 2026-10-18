"""Tests for the Wi-Fi setup controller, with NetworkManager and the form faked."""
import pytest

from gcal_epd import wifi_setup
from gcal_epd.infrastructure.wifi.nmcli import Network, NmcliError


class FakeNM:
    def __init__(self, online_at_boot=False, connect_ok=True, saved=(),
                 online_on_retry=False):
        self.online_at_boot = online_at_boot
        self.connect_ok = connect_ok
        self.saved = list(saved)
        self.online_on_retry = online_on_retry
        self.log: list = []
        self._waits = 0

    def wait_connected(self, timeout):
        self._waits += 1
        self.log.append(("wait", timeout))
        return self.online_at_boot if self._waits == 1 else self.online_on_retry

    def scan(self):
        self.log.append("scan")
        return [Network("Home", 70, True)]

    def start_hotspot(self, ssid, password):
        self.log.append("start_hotspot")

    def resume_hotspot(self):
        self.log.append("resume_hotspot")

    def stop_hotspot(self):
        self.log.append("stop_hotspot")

    def remove_hotspot(self):
        self.log.append("remove_hotspot")

    def saved_wifi_profiles(self):
        return self.saved

    def connect(self, ssid, password):
        self.log.append(("connect", ssid))
        if not self.connect_ok:
            self.connect_ok = True  # second attempt succeeds
            raise NmcliError("Secrets were required")


class FakeServer:
    """Feeds scripted requests, one per loop iteration.

    None = idle, "get" = the form was loaded, (ssid, password) = a submission.
    """

    url = "http://10.42.0.1"

    def __init__(self, submissions, clock):
        self.submissions = list(submissions)
        self.clock = clock
        self.pending = None
        self.error = ""
        self.last_activity = float("-inf")
        self.closed = False
        self.networks = None

    def handle_once(self):
        self.clock.t += 1
        if not self.submissions:
            raise KeyboardInterrupt  # end of script
        item = self.submissions.pop(0)
        if item == "get":
            self.last_activity = self.clock.t  # someone loaded the form
        elif item is not None:
            self.pending = item
            self.last_activity = self.clock.t

    def take_pending(self):
        p, self.pending = self.pending, None
        return p

    def set_error(self, e):
        self.error = e

    def set_networks(self, n):
        self.networks = n

    def close(self):
        self.closed = True


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def _run(nm, submissions, **kw):
    clock = Clock()
    screens = []
    holder = {}

    def factory(networks):
        holder["server"] = FakeServer(submissions, clock)
        return holder["server"]

    result = wifi_setup.run(nm, factory, lambda kind, **a: screens.append((kind, a)),
                            clock=clock, sleep=lambda s: None, **kw)
    return result, screens, holder.get("server")


def test_already_online_skips_the_hotspot():
    nm = FakeNM(online_at_boot=True)
    result, screens, server = _run(nm, [])
    assert result == "online"
    assert "start_hotspot" not in nm.log
    assert screens == [] and server is None


def test_force_starts_hotspot_even_when_online():
    nm = FakeNM(online_at_boot=True)
    result, _, _ = _run(nm, [("Home", "correct-horse")], force=True)
    assert result == "joined"
    assert "start_hotspot" in nm.log


def test_scans_before_taking_the_radio():
    nm = FakeNM()
    _run(nm, [("Home", "correct-horse")])
    assert nm.log.index("scan") < nm.log.index("start_hotspot")


def test_successful_join_shows_connected_and_cleans_up():
    nm = FakeNM()
    result, screens, server = _run(nm, [None, ("Home", "correct-horse")])
    assert result == "joined"
    assert [k for k, _ in screens] == ["ap", "connected"]
    assert nm.log.index("stop_hotspot") < nm.log.index(("connect", "Home"))
    assert nm.log[-1] == "remove_hotspot"
    assert server.closed


def test_wrong_password_brings_the_same_hotspot_back():
    nm = FakeNM(connect_ok=False)
    result, screens, server = _run(nm, [("Home", "wrong-pass"), ("Home", "right-pass")])
    assert result == "joined"
    assert "resume_hotspot" in nm.log
    assert [k for k, _ in screens] == ["ap", "ap", "connected"]
    assert "Could not join Home" in screens[1][1]["error"]
    # Same hotspot credentials, so the phone can rejoin on its own.
    assert screens[0][1]["ap_password"] == screens[1][1]["ap_password"]
    assert "Could not join Home" in server.error


def test_cancel_still_removes_hotspot():
    nm = FakeNM()
    result, _, server = _run(nm, [None, None])
    assert result == "cancelled"
    assert nm.log[-1] == "remove_hotspot"
    assert server.closed


def test_retries_saved_networks_when_idle():
    nm = FakeNM(saved=["preconfigured"], online_on_retry=True)
    result, screens, _ = _run(nm, [None] * 10, retry_interval=5, idle_grace=0)
    assert result == "joined"
    assert "stop_hotspot" in nm.log
    assert screens[-1][0] == "connected"


def test_failed_retry_rescans_and_resumes_hotspot():
    nm = FakeNM(saved=["preconfigured"], online_on_retry=False)
    _, _, server = _run(nm, [None] * 8, retry_interval=5, idle_grace=0)
    assert nm.log.count("scan") >= 2
    assert "resume_hotspot" in nm.log
    assert server.networks is not None


def test_no_retry_without_saved_networks():
    nm = FakeNM(saved=[])
    _run(nm, [None] * 10, retry_interval=5, idle_grace=0)
    assert "stop_hotspot" not in nm.log


def test_no_retry_while_someone_is_using_the_form():
    nm = FakeNM(saved=["preconfigured"], online_on_retry=True)
    result, _, _ = _run(nm, ["get"] * 6, retry_interval=2, idle_grace=30)
    assert result == "cancelled"
    assert "stop_hotspot" not in nm.log


# --- hand-over to the calendar ---

UNITS = ["gcal-epd.service", "epd-feed-setup.service"]


@pytest.mark.parametrize("result", ["online", "joined"])
def test_start_units_once_there_is_a_network(result):
    """Booting straight onto a known network must still refresh the panel."""
    calls = []
    wifi_setup.start_units(result, UNITS, run=lambda cmd, check: calls.append(cmd))
    assert calls == [["systemctl", "start", "--no-block", u] for u in UNITS]


def test_start_units_not_when_cancelled():
    calls = []
    wifi_setup.start_units("cancelled", UNITS, run=lambda cmd, check: calls.append(cmd))
    assert calls == []
