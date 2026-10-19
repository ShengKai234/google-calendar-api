"""Tests for choosing the hotspot strategy."""
import pytest

from gcal_epd.infrastructure.wifi.hotspot import (
    DEFAULT_HOTSPOT,
    HOTSPOTS,
    NetworkManagerHotspot,
    WifiWithHotspot,
    make_wifi,
)
from gcal_epd.infrastructure.wifi.nmcli import NetworkManager
from gcal_epd.infrastructure.wifi.wpa_hotspot import WpaSupplicantHotspot


class Recorder:
    """Stands in for NetworkManager and for a hotspot strategy alike."""

    ifname = "wlan0"

    def __init__(self):
        self.log = []

    def __getattr__(self, name):
        return lambda *args: self.log.append((name, *args))


def test_default_is_the_wpa_supplicant_hotspot():
    """The one an iPhone can join on the Zero W."""
    assert DEFAULT_HOTSPOT == "wpa-supplicant"
    assert isinstance(make_wifi(NetworkManager()).hotspot, WpaSupplicantHotspot)


def test_networkmanager_hotspot_can_still_be_chosen():
    nm = NetworkManager()
    wifi = make_wifi(nm, "networkmanager")
    assert isinstance(wifi.hotspot, NetworkManagerHotspot)
    assert wifi.nm is nm


def test_wpa_supplicant_hotspot_uses_networkmanagers_interface():
    assert make_wifi(NetworkManager(ifname="wlan1")).hotspot.ifname == "wlan1"


def test_unknown_hotspot_is_refused():
    with pytest.raises(KeyError):
        make_wifi(NetworkManager(), "hostapd")


def test_hotspot_calls_go_to_the_strategy_and_the_rest_to_networkmanager():
    nm, hotspot = Recorder(), Recorder()
    wifi = WifiWithHotspot(nm, hotspot)
    wifi.wait_connected(5)
    wifi.scan()
    wifi.saved_wifi_profiles()
    wifi.connect("Home", "pw")
    wifi.start_hotspot("X", "abcdefgh23")
    wifi.resume_hotspot()
    wifi.stop_hotspot()
    wifi.remove_hotspot()
    assert nm.log == [("wait_connected", 5), ("scan",), ("saved_wifi_profiles",),
                      ("connect", "Home", "pw")]
    assert hotspot.log == [("start", "X", "abcdefgh23"), ("resume",), ("stop",), ("remove",)]


@pytest.mark.parametrize("call,expected", [
    (lambda h: h.start("X", "abcdefgh23"), ("start_hotspot", "X", "abcdefgh23")),
    (lambda h: h.resume(), ("resume_hotspot",)),
    (lambda h: h.stop(), ("stop_hotspot",)),
    (lambda h: h.remove(), ("remove_hotspot",)),
])
def test_networkmanager_hotspot_delegates(call, expected):
    nm = Recorder()
    call(NetworkManagerHotspot(nm))
    assert nm.log == [expected]


def test_every_strategy_has_a_name_wifi_setup_accepts():
    assert set(HOTSPOTS) == {"wpa-supplicant", "networkmanager"}
