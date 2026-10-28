"""Tests for the wpa_supplicant hotspot — commands and processes are faked."""
import subprocess

import pytest

from gcal_epd.infrastructure.wifi.nmcli import AP_ADDRESS, NmcliError
from gcal_epd.infrastructure.wifi.wpa_hotspot import (
    AP_UP_WAIT,
    HotspotError,
    WpaSupplicantHotspot,
    wpa_config,
)

PASSWORD = "hunter2-very-secret"


class FakeProc:
    def __init__(self, argv, exit_code=None, hangs=False):
        self.argv = argv
        self.returncode = exit_code
        self.hangs = hangs
        self.terminated = self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        if self.hangs and not self.killed:
            raise subprocess.TimeoutExpired(self.argv, timeout)
        return 0


class Rig:
    """Records every command and process; wlan0 becomes an AP after `ap_after` checks."""

    def __init__(self, tmp_path, ap_after=1, wpa_exit=None, nm_state="30 (disconnected)",
                 hangs=False):
        self.calls: list[list[str]] = []
        self.procs: list[FakeProc] = []
        self.ap_after = ap_after
        self.wpa_exit = wpa_exit
        self.nm_state = nm_state
        self.hangs = hangs
        self.t = 0.0
        self.hotspot = WpaSupplicantHotspot(
            run=self.run, popen=self.popen, sleep=self.sleep, clock=lambda: self.t,
            run_dir=tmp_path / "hotspot")

    def run(self, args, timeout):
        self.calls.append(args)
        out = ""
        if args[:2] == ["iw", "dev"]:
            self.ap_after -= 1
            out = "Interface wlan0\n\ttype AP\n" if self.ap_after <= 0 else "\ttype managed\n"
        elif args[:3] == ["nmcli", "-t", "-f"]:
            out = f"GENERAL.STATE:{self.nm_state}\n"
        return subprocess.CompletedProcess(args, 0, out, "")

    def popen(self, argv):
        self.calls.append(argv)
        exit_code = self.wpa_exit if argv[0] == "wpa_supplicant" else None
        proc = FakeProc(argv, exit_code, hangs=self.hangs)
        self.procs.append(proc)
        return proc

    def sleep(self, s):
        self.t += s

    def index(self, *prefix):
        return next(i for i, c in enumerate(self.calls) if c[:len(prefix)] == list(prefix))

    def has(self, *prefix):
        return any(c[:len(prefix)] == list(prefix) for c in self.calls)


# --- config ---

def test_config_offers_wpa_psk_only_with_pmf_off():
    conf = wpa_config("ePaper-Setup-AB12", "abcdefgh23")
    assert "key_mgmt=WPA-PSK\n" in conf
    assert "SHA256" not in conf
    assert "ieee80211w=0" in conf
    assert "mode=2" in conf  # access point
    assert "pairwise=CCMP" in conf and "group=CCMP" in conf


def test_config_carries_the_derived_key_not_the_password():
    # IEEE 802.11i test vector: passphrase "password", SSID "IEEE".
    conf = wpa_config("IEEE", "password")
    assert "psk=f42c6fc52df0ebef9ebb4b90b38a5f902e83fe1b135a70e23aed762e9710a12e" in conf
    assert "ssid=49454545\n" in conf
    assert "password" not in conf


def test_config_cannot_be_broken_by_quotes_or_newlines():
    conf = wpa_config('x"\n}\nnetwork={', 'p"\nkey_mgmt=NONE')
    assert conf.count("network={") == 1
    assert conf.count("key_mgmt=") == 1


# --- start ---

def test_start_takes_wlan0_from_networkmanager_before_running_the_ap(tmp_path):
    rig = Rig(tmp_path)
    rig.hotspot.start("ePaper-Setup-AB12", "abcdefgh23")
    assert rig.index("nmcli", "device", "set", "wlan0", "managed", "no") \
        < rig.index("systemctl", "stop", "wpa_supplicant.service") \
        < rig.index("wpa_supplicant") < rig.index("dnsmasq")
    assert ["ip", "addr", "add", f"{AP_ADDRESS}/24", "dev", "wlan0"] in rig.calls


def test_start_writes_a_root_only_config(tmp_path):
    rig = Rig(tmp_path)
    rig.hotspot.start("ePaper-Setup-AB12", "abcdefgh23")
    conf = tmp_path / "hotspot" / "wpa_supplicant.conf"
    assert conf.stat().st_mode & 0o777 == 0o600
    assert conf.read_text() == wpa_config("ePaper-Setup-AB12", "abcdefgh23")
    wpa = rig.procs[0].argv
    assert wpa[wpa.index("-c") + 1] == str(conf)


def test_start_serves_dhcp_on_the_pinned_subnet(tmp_path):
    rig = Rig(tmp_path)
    rig.hotspot.start("X", "abcdefgh23")
    dnsmasq = rig.procs[1].argv
    assert "--interface=wlan0" in dnsmasq
    assert any(a.startswith("--dhcp-range=10.42.0.") for a in dnsmasq)


def test_password_never_reaches_a_command_line(tmp_path):
    """Command lines are visible to every local user through ps."""
    rig = Rig(tmp_path)
    rig.hotspot.start("X", PASSWORD)
    rig.hotspot.stop()
    assert not any(PASSWORD in a for c in rig.calls for a in c)


def test_start_waits_for_the_interface_to_become_an_ap(tmp_path):
    rig = Rig(tmp_path, ap_after=3)
    rig.hotspot.start("X", "abcdefgh23")
    assert rig.t == 2  # two one-second waits
    assert len(rig.procs) == 2  # dnsmasq only once the AP is up


def test_start_fails_and_hands_wlan0_back_when_wpa_supplicant_exits(tmp_path):
    rig = Rig(tmp_path, wpa_exit=255)
    with pytest.raises(HotspotError):
        rig.hotspot.start("X", "abcdefgh23")
    assert rig.has("nmcli", "device", "set", "wlan0", "managed", "yes")
    assert rig.has("systemctl", "start", "wpa_supplicant.service")
    assert not rig.has("dnsmasq")


def test_start_gives_up_at_the_deadline(tmp_path):
    rig = Rig(tmp_path, ap_after=10**6)
    with pytest.raises(HotspotError, match="did not become an access point"):
        rig.hotspot.start("X", "abcdefgh23")
    assert rig.t >= AP_UP_WAIT
    assert rig.procs[0].terminated


def test_hotspot_error_is_an_nmcli_error():
    """wifi_setup.run handles both hotspots' failures the same way."""
    assert issubclass(HotspotError, NmcliError)


# --- stop / resume / remove ---

def test_stop_ends_both_processes_and_hands_wlan0_back(tmp_path):
    rig = Rig(tmp_path)
    rig.hotspot.start("X", "abcdefgh23")
    rig.calls.clear()
    rig.hotspot.stop()
    assert all(p.terminated for p in rig.procs)
    assert rig.index("systemctl", "start", "wpa_supplicant.service") \
        < rig.index("nmcli", "device", "set", "wlan0", "managed", "yes") \
        < rig.index("nmcli", "-t", "-f", "GENERAL.STATE")


def test_stop_waits_for_networkmanager_to_take_wlan0_back(tmp_path):
    rig = Rig(tmp_path)
    rig.hotspot.start("X", "abcdefgh23")
    rig.nm_state = "20 (unavailable)"
    t0 = rig.t
    rig.hotspot.stop()  # gives up quietly; the next connect reports the failure
    assert rig.t - t0 >= 20


def test_stop_kills_a_process_that_will_not_end(tmp_path):
    rig = Rig(tmp_path, hangs=True)
    rig.hotspot.start("X", "abcdefgh23")
    rig.hotspot.stop()
    assert all(p.killed for p in rig.procs)


def test_stop_before_start_touches_nothing(tmp_path):
    rig = Rig(tmp_path)
    rig.hotspot.stop()
    rig.hotspot.remove()
    assert rig.calls == []


def test_resume_brings_back_the_same_hotspot(tmp_path):
    rig = Rig(tmp_path)
    rig.hotspot.start("ePaper-Setup-AB12", "abcdefgh23")
    rig.hotspot.stop()
    conf = tmp_path / "hotspot" / "wpa_supplicant.conf"
    conf.write_text("stale")
    rig.hotspot.resume()
    assert conf.read_text() == wpa_config("ePaper-Setup-AB12", "abcdefgh23")
    assert len(rig.procs) == 4


def test_resume_before_start_is_an_error(tmp_path):
    with pytest.raises(HotspotError):
        Rig(tmp_path).hotspot.resume()


def test_remove_deletes_the_config(tmp_path):
    rig = Rig(tmp_path)
    rig.hotspot.start("X", "abcdefgh23")
    rig.hotspot.remove()
    assert not (tmp_path / "hotspot" / "wpa_supplicant.conf").exists()
