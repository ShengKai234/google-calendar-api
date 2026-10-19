"""Tests for picking the hotspot strategy on wifi_setup's command line."""
import signal

import pytest

from gcal_epd import wifi_setup
from gcal_epd.infrastructure.wifi.hotspot import NetworkManagerHotspot
from gcal_epd.infrastructure.wifi.wpa_hotspot import WpaSupplicantHotspot


@pytest.fixture
def started(monkeypatch):
    """Run main() with the setup loop replaced; return what it was given."""
    seen = {}

    def fake_run(wifi, *args, **kwargs):
        seen["wifi"] = wifi
        seen["sigterm"] = signal.getsignal(signal.SIGTERM)
        return "online"

    monkeypatch.setattr(wifi_setup, "run", fake_run)
    monkeypatch.setattr(wifi_setup.NetworkManager, "available", staticmethod(lambda: True))
    monkeypatch.setattr(signal, "signal", lambda *a: seen.setdefault("handler", a))

    def start(*argv):
        monkeypatch.setattr("sys.argv", ["wifi_setup", *argv])
        wifi_setup.main()
        return seen
    return start


def test_wpa_supplicant_hotspot_by_default(started):
    assert isinstance(started()["wifi"].hotspot, WpaSupplicantHotspot)


def test_networkmanager_hotspot_on_request(started):
    seen = started("--hotspot", "networkmanager")
    assert isinstance(seen["wifi"].hotspot, NetworkManagerHotspot)


def test_unknown_hotspot_is_a_usage_error(started):
    with pytest.raises(SystemExit):
        started("--hotspot", "hostapd")


def test_systemctl_stop_ends_setup_like_ctrl_c(started):
    """So the hotspot comes down and wlan0 goes back to NetworkManager."""
    signum, handler = started()["handler"]
    assert signum == signal.SIGTERM
    with pytest.raises(KeyboardInterrupt):
        handler(signum, None)
