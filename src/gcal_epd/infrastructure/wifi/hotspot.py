"""
Which program runs the setup hotspot — a strategy, picked at start-up.

NetworkManager scans and joins the home network either way; only the
hotspot differs:

- "wpa-supplicant" (default): our own wpa_supplicant offers WPA2 with the
  WPA-PSK key management only. Works on the Zero W.
- "networkmanager": NetworkManager's hotspot. It also offers WPA-PSK-SHA256
  and has no setting to drop it. The Zero W's firmware then advertises
  something the handshake does not match, and an iPhone gives up after
  message 3/4 — saying the (correct) password is wrong.
"""
from typing import Callable, Protocol

from gcal_epd.infrastructure.wifi.nmcli import Network, NetworkManager


class Hotspot(Protocol):
    def start(self, ssid: str, password: str) -> None: ...
    def resume(self) -> None: ...
    def stop(self) -> None: ...
    def remove(self) -> None: ...


class NetworkManagerHotspot:
    """NetworkManager's own hotspot (the behaviour before the strategy)."""

    def __init__(self, nm: NetworkManager) -> None:
        self._nm = nm

    def start(self, ssid: str, password: str) -> None:
        self._nm.start_hotspot(ssid, password)

    def resume(self) -> None:
        self._nm.resume_hotspot()

    def stop(self) -> None:
        self._nm.stop_hotspot()

    def remove(self) -> None:
        self._nm.remove_hotspot()


class WifiWithHotspot:
    """NetworkManager for the home network, the chosen strategy for the hotspot.

    Has the methods wifi_setup.run calls, so it stands in for NetworkManager.
    """

    def __init__(self, nm: NetworkManager, hotspot: Hotspot) -> None:
        self.nm = nm
        self.hotspot = hotspot

    def wait_connected(self, timeout: float) -> bool:
        return self.nm.wait_connected(timeout)

    def scan(self) -> list[Network]:
        return self.nm.scan()

    def saved_wifi_profiles(self) -> list[str]:
        return self.nm.saved_wifi_profiles()

    def connect(self, ssid: str, password: str) -> None:
        self.nm.connect(ssid, password)

    def start_hotspot(self, ssid: str, password: str) -> None:
        self.hotspot.start(ssid, password)

    def resume_hotspot(self) -> None:
        self.hotspot.resume()

    def stop_hotspot(self) -> None:
        self.hotspot.stop()

    def remove_hotspot(self) -> None:
        self.hotspot.remove()


def _wpa_supplicant(nm: NetworkManager) -> Hotspot:
    from gcal_epd.infrastructure.wifi.wpa_hotspot import WpaSupplicantHotspot
    return WpaSupplicantHotspot(ifname=nm.ifname)


HOTSPOTS: dict[str, Callable[[NetworkManager], Hotspot]] = {
    "wpa-supplicant": _wpa_supplicant,
    "networkmanager": NetworkManagerHotspot,
}
DEFAULT_HOTSPOT = "wpa-supplicant"


def make_wifi(nm: NetworkManager, hotspot: str = DEFAULT_HOTSPOT) -> WifiWithHotspot:
    """`nm` with its hotspot run by the strategy named `hotspot`."""
    return WifiWithHotspot(nm, HOTSPOTS[hotspot](nm))
