"""Tests for the nmcli wrapper — nmcli itself is replaced by a fake runner."""
import subprocess

import pytest

from gcal_epd.infrastructure.wifi.nmcli import (
    AP_ADDRESS,
    AP_CONNECTION,
    NetworkManager,
    NmcliError,
    is_valid_psk,
    split_terse,
)

PASSWORD = "hunter2-very-secret"


class FakeNmcli:
    """Records each command; answers from a list of (prefix, rc, stdout, stderr)."""

    def __init__(self, rules=()):
        self.calls: list[list[str]] = []
        self.rules = list(rules)

    def __call__(self, args, timeout):
        self.calls.append(args)
        for prefix, rc, out, err in self.rules:
            if args[1:1 + len(prefix)] == list(prefix):
                return subprocess.CompletedProcess(args, rc, out, err)
        return subprocess.CompletedProcess(args, 0, "", "")

    def called(self, *prefix):
        return [c for c in self.calls if c[1:1 + len(prefix)] == list(prefix)]


def _nm(fake, **kw):
    return NetworkManager(run=fake, sleep=lambda s: None, **kw)


# --- parsing ---

def test_split_terse_plain():
    assert split_terse("Home:80:WPA2") == ["Home", "80", "WPA2"]


def test_split_terse_unescapes_colon_and_backslash():
    assert split_terse(r"a\:b\\c:42:") == ["a:b\\c", "42", ""]


@pytest.mark.parametrize("pw,ok", [
    ("", False), ("short", False), ("12345678", True), ("x" * 63, True),
    ("x" * 64, False), ("ab" * 32, True),  # 64 hex digits is a raw key
])
def test_is_valid_psk(pw, ok):
    assert is_valid_psk(pw) is ok


# --- state ---

def test_is_connected_to_a_real_network():
    fake = FakeNmcli([(("-t", "-f"), 0,
                       "GENERAL.STATE:100 (connected)\nGENERAL.CONNECTION:Home\n", "")])
    assert _nm(fake).is_connected()


def test_is_connected_false_while_serving_the_hotspot():
    """The radio reports 'connected' as an AP too — that is not online."""
    fake = FakeNmcli([(("-t", "-f"), 0,
                       f"GENERAL.STATE:100 (connected)\nGENERAL.CONNECTION:{AP_CONNECTION}\n", "")])
    assert not _nm(fake).is_connected()


def test_is_connected_false_when_disconnected():
    fake = FakeNmcli([(("-t", "-f"), 0,
                       "GENERAL.STATE:30 (disconnected)\nGENERAL.CONNECTION:\n", "")])
    assert not _nm(fake).is_connected()


def test_is_connected_false_when_nmcli_fails():
    fake = FakeNmcli([(("-t", "-f"), 10, "", "Error: Device 'wlan0' not found.")])
    assert not _nm(fake).is_connected()


def test_wait_connected_gives_up_at_the_deadline():
    t = [0.0]
    fake = FakeNmcli([(("-t", "-f"), 0, "GENERAL.STATE:30 (disconnected)\n", "")])
    nm = NetworkManager(run=fake, sleep=lambda s: t.__setitem__(0, t[0] + s),
                        clock=lambda: t[0])
    assert not nm.wait_connected(10, poll=2)
    assert t[0] >= 10


def test_scan_dedupes_sorts_and_skips_hidden():
    out = "Home:40:WPA2\nHome:70:WPA2\n:90:WPA2\nCafe:55:\nOffice\\:5F:20:WPA1 WPA2\n"
    fake = FakeNmcli([(("-t", "-f", "SSID,SIGNAL,SECURITY"), 0, out, "")])
    nets = _nm(fake).scan()
    assert [n.ssid for n in nets] == ["Home", "Cafe", "Office:5F"]
    assert nets[0].signal == 70
    assert nets[1].secure is False


def test_scan_failure_returns_empty():
    fake = FakeNmcli([(("-t", "-f", "SSID,SIGNAL,SECURITY"), 1, "", "boom")])
    assert _nm(fake).scan() == []


def test_saved_wifi_profiles_excludes_hotspot_and_other_types():
    out = (f"preconfigured:802-11-wireless\n{AP_CONNECTION}:802-11-wireless\n"
           "lo:loopback\nWired:802-3-ethernet\n")
    fake = FakeNmcli([(("-t", "-f", "NAME,TYPE"), 0, out, "")])
    assert _nm(fake).saved_wifi_profiles() == ["preconfigured"]


# --- radio ---

def _state(code):
    return (("-t", "-f", "GENERAL.STATE"), 0, f"GENERAL.STATE:{code}\n", "")


def test_radio_on_unblocks_rfkill_and_turns_networkmanagers_radio_on():
    """A card with no Wi-Fi set up has the radio off at both levels."""
    fake = FakeNmcli([_state("30 (disconnected)")])
    assert _nm(fake).radio_on()
    assert ["rfkill", "unblock", "wifi"] in fake.calls
    assert fake.called("radio", "wifi", "on")


def test_radio_on_waits_until_the_interface_leaves_unavailable():
    states = iter(["20 (unavailable)", "20 (unavailable)", "30 (disconnected)"])

    def run(args, timeout):
        if args[1:4] == ["-t", "-f", "GENERAL.STATE"]:
            return subprocess.CompletedProcess(args, 0, f"GENERAL.STATE:{next(states)}\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    slept = []
    assert NetworkManager(run=run, sleep=slept.append).radio_on()
    assert len(slept) == 2


def test_radio_on_gives_up_at_the_deadline():
    t = [0.0]
    fake = FakeNmcli([_state("20 (unavailable)")])
    nm = NetworkManager(run=fake, sleep=lambda s: t.__setitem__(0, t[0] + s),
                        clock=lambda: t[0])
    assert not nm.radio_on(timeout=5)
    assert t[0] >= 5


def test_radio_on_goes_ahead_when_rfkill_or_nmcli_fail():
    """Missing rfkill or a refused radio command must not stop the hotspot try."""
    def run(args, timeout):
        if args[0] == "rfkill":
            raise FileNotFoundError("rfkill")
        return subprocess.CompletedProcess(args, 4, "", "Error: not authorized")

    assert NetworkManager(run=run, sleep=lambda s: None).radio_on()


@pytest.mark.parametrize("use", [
    lambda nm: nm.wait_connected(0),
    lambda nm: nm.scan(),
    lambda nm: nm.start_hotspot("X", "abcdefgh23"),
    lambda nm: nm.resume_hotspot(),
    lambda nm: nm.connect("Home", PASSWORD),
], ids=["wait_connected", "scan", "start_hotspot", "resume_hotspot", "connect"])
def test_every_use_of_the_radio_turns_it_on_first(use):
    """Pi OS can block Wi-Fi again during boot, so once is not enough."""
    fake = FakeNmcli()
    use(_nm(fake))
    radio = ["nmcli", "radio", "wifi", "on"]
    first_other = next(c for c in fake.calls if c[0] != "rfkill" and c != radio
                       and c[1:4] != ["-t", "-f", "GENERAL.STATE"])
    assert fake.calls.index(radio) < fake.calls.index(first_other)


# --- hotspot ---

def test_start_hotspot_pins_address_and_disables_autoconnect():
    fake = FakeNmcli()
    _nm(fake).start_hotspot("ePaper-Setup-AB12", "abcdefgh23")
    add = fake.called("connection", "add")[0]
    assert add[add.index("ssid") + 1] == "ePaper-Setup-AB12"
    assert add[add.index("con-name") + 1] == AP_CONNECTION
    assert add[add.index("802-11-wireless.mode") + 1] == "ap"
    assert add[add.index("ipv4.method") + 1] == "shared"
    assert add[add.index("ipv4.addresses") + 1] == f"{AP_ADDRESS}/24"
    assert add[add.index("connection.autoconnect") + 1] == "no"
    assert fake.called("connection", "up", AP_CONNECTION)


def test_start_hotspot_is_wpa2_aes_with_pmf_off():
    """On Trixie the Zero W's AP only comes up with PMF off (found on hardware);
    turning PMF off must not cost the encryption."""
    fake = FakeNmcli()
    _nm(fake).start_hotspot("X", "abcdefgh23")
    add = fake.called("connection", "add")[0]
    assert add[add.index("wifi-sec.pmf") + 1] == "disable"
    assert add[add.index("wifi-sec.key-mgmt") + 1] == "wpa-psk"
    assert add[add.index("wifi-sec.pairwise") + 1] == "ccmp"


def test_start_hotspot_refuses_when_another_interface_has_the_subnet():
    """NetworkManager would accept the clash and routing would break quietly."""
    out = ("GENERAL.DEVICE:wlan0\nGENERAL.DEVICE:usb0\n"
           "IP4.ADDRESS[1]:10.42.0.1/24\nGENERAL.DEVICE:lo\nIP4.ADDRESS[1]:127.0.0.1/8\n")
    fake = FakeNmcli([(("-t", "-f", "GENERAL.DEVICE,IP4.ADDRESS"), 0, out, "")])
    with pytest.raises(NmcliError, match="usb0 already uses 10.42.0.1/24"):
        _nm(fake).start_hotspot("X", "abcdefgh23")
    assert not fake.called("connection", "add")


def test_start_hotspot_ignores_its_own_interface_and_other_subnets():
    out = ("GENERAL.DEVICE:wlan0\nIP4.ADDRESS[1]:10.42.0.1/24\n"
           "GENERAL.DEVICE:eth0\nIP4.ADDRESS[1]:192.168.1.20/24\n")
    fake = FakeNmcli([(("-t", "-f", "GENERAL.DEVICE,IP4.ADDRESS"), 0, out, "")])
    _nm(fake).start_hotspot("X", "abcdefgh23")
    assert fake.called("connection", "up", AP_CONNECTION)


def test_start_hotspot_removes_profile_when_it_will_not_come_up():
    fake = FakeNmcli([(("connection", "up"), 4, "", "Error: activation failed")])
    with pytest.raises(NmcliError):
        _nm(fake).start_hotspot("X", "abcdefgh23")
    deletes = fake.called("connection", "delete", AP_CONNECTION)
    assert len(deletes) == 2  # stale profile before, failed profile after


def test_hotspot_error_does_not_leak_password():
    fake = FakeNmcli([(("connection", "add"), 4, "", "Error: radio blocked")])
    with pytest.raises(NmcliError) as e:
        _nm(fake).start_hotspot("X", PASSWORD)
    assert PASSWORD not in str(e.value)
    assert "radio blocked" in str(e.value)


# --- client ---

def test_connect_adds_wpa_profile_and_brings_it_up():
    fake = FakeNmcli()
    _nm(fake).connect("Home", PASSWORD)
    add = fake.called("connection", "add")[0]
    assert add[add.index("ssid") + 1] == "Home"
    assert add[add.index("wifi-sec.psk") + 1] == PASSWORD
    assert fake.called("--wait", "30", "connection", "up", "wifi-Home")


def test_connect_open_network_has_no_security():
    fake = FakeNmcli()
    _nm(fake).connect("Cafe", "")
    add = fake.called("connection", "add")[0]
    assert "wifi-sec.key-mgmt" not in add


def test_connect_passes_hostile_ssid_as_one_argument():
    """No shell is involved, so an SSID cannot inject a command."""
    fake = FakeNmcli()
    _nm(fake).connect('x"; reboot #', PASSWORD)
    add = fake.called("connection", "add")[0]
    assert 'x"; reboot #' in add


def test_connect_failure_removes_profile_and_hides_password():
    fake = FakeNmcli([(("--wait",), 4, "", "Error: Secrets were required")])
    with pytest.raises(NmcliError) as e:
        _nm(fake).connect("Home", PASSWORD)
    assert PASSWORD not in str(e.value)
    deletes = fake.called("connection", "delete", "wifi-Home")
    assert len(deletes) == 2  # stale profile before, failed profile after
