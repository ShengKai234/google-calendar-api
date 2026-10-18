"""
Thin wrapper around NetworkManager's `nmcli`.

Raspberry Pi OS (Bookworm and later) manages Wi-Fi with NetworkManager, so
a hotspot, a scan and a new client connection are each one nmcli call — no
hostapd or dnsmasq to configure. Commands are always passed as argument
lists, never through a shell, so an SSID like `x"; reboot` is just a name.

The Pi Zero W has a single 2.4GHz radio: it is either a hotspot or a client,
never both, and it cannot scan while the hotspot is up. Callers scan first.
"""
import logging
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Callable

log = logging.getLogger(__name__)

DEFAULT_IFNAME = "wlan0"
AP_CONNECTION = "epd-setup-ap"
# Pinned rather than left to NetworkManager, which picks the first free
# 10.42.x.0/24 — the panel's QR must name the address the hotspot really has.
AP_ADDRESS = "10.42.0.1"
AP_PREFIX = 24
_CLIENT_PREFIX = "wifi-"
_WIFI_TYPE = "802-11-wireless"
# nmcli device states below 30 ("disconnected"): 10 unmanaged, 20 unavailable.
_DEVICE_USABLE = 30
RADIO_WAIT = 15  # seconds for wlan0 to become usable once the radio is on

Runner = Callable[[list[str], float], subprocess.CompletedProcess]


class NmcliError(RuntimeError):
    pass


@dataclass(frozen=True)
class Network:
    ssid: str
    signal: int  # 0-100
    secure: bool


def _run(args: list[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def split_terse(line: str) -> list[str]:
    """Split one line of `nmcli -t` output.

    Terse mode separates fields with ':' and escapes a literal ':' or '\\'
    inside a field with a backslash — SSIDs can contain either.
    """
    fields, current, escaped = [], [], False
    for ch in line:
        if escaped:
            current.append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(ch)
    fields.append("".join(current))
    return fields


def is_valid_psk(password: str) -> bool:
    """WPA2-Personal takes 8-63 characters, or exactly 64 hex digits."""
    if len(password) == 64:
        return all(c in "0123456789abcdefABCDEF" for c in password)
    return 8 <= len(password) <= 63


class NetworkManager:
    def __init__(self, ifname: str = DEFAULT_IFNAME, run: Runner = _run,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.ifname = ifname
        self._run = run
        self._sleep = sleep
        self._clock = clock

    @staticmethod
    def available() -> bool:
        return shutil.which("nmcli") is not None

    # --- plumbing ---------------------------------------------------
    def _nmcli(self, *args: str, timeout: float = 30, secret: bool = False) -> str:
        """Run nmcli and return stdout, raising NmcliError on failure.

        With secret=True the arguments carry a password, so the error text
        keeps only nmcli's own message, never the command line.
        """
        cmd = ["nmcli", *args]
        try:
            result = self._run(cmd, timeout)
        except subprocess.TimeoutExpired:
            raise NmcliError(f"nmcli {args[0]} timed out") from None
        if result.returncode != 0:
            what = "nmcli" if secret else " ".join(cmd)
            raise NmcliError(f"{what} failed: {result.stderr.strip()}")
        return result.stdout

    # --- radio ------------------------------------------------------
    def radio_on(self, timeout: float = RADIO_WAIT) -> bool:
        """Turn the Wi-Fi radio on; True once wlan0 is usable, or cannot tell.

        Until a Wi-Fi country is set through Pi OS's own tools (Imager,
        raspi-config), Wi-Fi is rfkill-blocked and NetworkManager keeps its
        radio off (WirelessEnabled=false in its state file). Either one leaves
        wlan0 "unavailable": a scan finds nothing and the hotspot fails with
        "No suitable device found". Pi OS can also block Wi-Fi again during
        boot, so this runs before each use of the radio, not once. Failures
        are logged, not raised: the step that needs the radio reports them.
        """
        try:
            result = self._run(["rfkill", "unblock", "wifi"], 10)
            if result.returncode != 0:
                log.warning("rfkill unblock wifi failed: %s", result.stderr.strip())
        except (OSError, subprocess.TimeoutExpired) as e:
            log.warning("rfkill unblock wifi failed: %s", e)
        try:
            self._nmcli("radio", "wifi", "on")
        except NmcliError as e:
            log.warning("Could not turn the Wi-Fi radio on: %s", e)

        deadline = self._clock() + timeout
        while True:
            state = self._device_state()
            if state is None or state >= _DEVICE_USABLE:
                return True
            if self._clock() >= deadline:
                log.warning("%s still unavailable %ss after turning the radio on",
                            self.ifname, timeout)
                return False
            self._sleep(1)

    def _device_state(self) -> int | None:
        """nmcli's numeric state of the interface, or None if it cannot tell."""
        try:
            out = self._nmcli("-t", "-f", "GENERAL.STATE", "device", "show", self.ifname)
        except NmcliError:
            return None
        for line in out.splitlines():
            key, _, value = line.partition(":")
            if key == "GENERAL.STATE":
                try:
                    return int(value.split()[0])
                except (ValueError, IndexError):
                    return None
        return None

    # --- state ------------------------------------------------------
    def is_connected(self) -> bool:
        """True when the radio is joined to a real network, not our hotspot."""
        try:
            out = self._nmcli("-t", "-f", "GENERAL.STATE,GENERAL.CONNECTION",
                              "device", "show", self.ifname)
        except NmcliError:
            return False
        info = {}
        for line in out.splitlines():
            key, _, value = line.partition(":")
            info[key] = value
        state = info.get("GENERAL.STATE", "")
        connection = info.get("GENERAL.CONNECTION", "")
        return state.startswith("100") and connection not in ("", AP_CONNECTION)

    def wait_connected(self, timeout: float, poll: float = 2) -> bool:
        self.radio_on()  # a saved network cannot be joined with the radio off
        deadline = self._clock() + timeout
        while True:
            if self.is_connected():
                return True
            if self._clock() >= deadline:
                return False
            self._sleep(poll)

    def scan(self) -> list[Network]:
        """Visible networks, strongest first, one entry per SSID."""
        self.radio_on()
        try:
            out = self._nmcli("-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi",
                              "list", "ifname", self.ifname, "--rescan", "yes",
                              timeout=45)
        except NmcliError as e:
            log.warning("Wi-Fi scan failed: %s", e)
            return []
        best: dict[str, Network] = {}
        for line in out.splitlines():
            fields = split_terse(line)
            if len(fields) < 3 or not fields[0]:
                continue  # hidden networks broadcast no SSID
            try:
                signal = int(fields[1])
            except ValueError:
                signal = 0
            net = Network(fields[0], signal, fields[2] not in ("", "--"))
            if net.ssid not in best or signal > best[net.ssid].signal:
                best[net.ssid] = net
        return sorted(best.values(), key=lambda n: -n.signal)

    def saved_wifi_profiles(self) -> list[str]:
        """Client Wi-Fi profiles NetworkManager could fall back to."""
        try:
            out = self._nmcli("-t", "-f", "NAME,TYPE", "connection", "show")
        except NmcliError:
            return []
        names = []
        for line in out.splitlines():
            fields = split_terse(line)
            if len(fields) >= 2 and fields[1] == _WIFI_TYPE and fields[0] != AP_CONNECTION:
                names.append(fields[0])
        return names

    # --- hotspot ----------------------------------------------------
    def start_hotspot(self, ssid: str, password: str) -> None:
        """Bring up a WPA2 hotspot on AP_ADDRESS, serving DHCP to phones.

        Built with `connection add` instead of `device wifi hotspot` so the
        address is fixed. NetworkManager would not refuse an address another
        interface already uses — routing would just break quietly — so that
        is checked first and fails here with a clear message.
        """
        self.radio_on()
        self._check_ap_subnet_free()
        self.remove_hotspot()
        self._nmcli(
            "connection", "add", "type", "wifi", "ifname", self.ifname,
            "con-name", AP_CONNECTION, "ssid", ssid,
            # Never pick the hotspot on its own at boot over a real network.
            "connection.autoconnect", "no",
            "802-11-wireless.mode", "ap", "802-11-wireless.band", "bg",
            # WPA2-AES only: the Zero W's brcmfmac AP fails on mixed WPA/TKIP.
            "wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.proto", "rsn",
            "wifi-sec.pairwise", "ccmp", "wifi-sec.group", "ccmp",
            "wifi-sec.psk", password,
            "ipv4.method", "shared", "ipv4.addresses", f"{AP_ADDRESS}/{AP_PREFIX}",
            "ipv6.method", "disabled",
            secret=True,
        )
        try:
            self._nmcli("connection", "up", AP_CONNECTION)
        except NmcliError:
            self.remove_hotspot()
            raise

    def _check_ap_subnet_free(self) -> None:
        """Raise if another interface already sits on the hotspot's subnet."""
        try:
            out = self._nmcli("-t", "-f", "GENERAL.DEVICE,IP4.ADDRESS", "device", "show")
        except NmcliError:
            return  # cannot tell; let activation decide
        subnet = AP_ADDRESS.rsplit(".", 1)[0] + "."
        device = ""
        for line in out.splitlines():
            key, _, value = line.partition(":")
            if key == "GENERAL.DEVICE":
                device = value
            elif key.startswith("IP4.ADDRESS") and value.startswith(subnet) \
                    and device != self.ifname:
                raise NmcliError(
                    f"{device} already uses {value}, the hotspot's subnet. "
                    f"Free {subnet}0/{AP_PREFIX} on {device} first."
                )

    def resume_hotspot(self) -> None:
        """Bring the same hotspot back, so a phone that joined once rejoins."""
        self.radio_on()
        self._nmcli("connection", "up", AP_CONNECTION)

    def stop_hotspot(self) -> None:
        try:
            self._nmcli("connection", "down", AP_CONNECTION)
        except NmcliError:
            pass  # already down

    def remove_hotspot(self) -> None:
        try:
            self._nmcli("connection", "delete", AP_CONNECTION)
        except NmcliError:
            pass  # never created

    # --- client -----------------------------------------------------
    def connect(self, ssid: str, password: str, timeout: int = 30) -> None:
        """Save a client profile for `ssid` and join it, or raise NmcliError.

        The password goes on nmcli's argument list. That is visible to other
        local users through `ps` for the moment it runs; this is a
        single-user appliance and the call runs as root, so it is accepted
        here rather than hand-writing NetworkManager keyfiles.
        """
        self.radio_on()
        name = _CLIENT_PREFIX + ssid
        try:
            self._nmcli("connection", "delete", name)  # replace a stale password
        except NmcliError:
            pass

        args = ["connection", "add", "type", "wifi", "ifname", self.ifname,
                "con-name", name, "ssid", ssid, "connection.autoconnect", "yes"]
        if password:
            args += ["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", password]
        self._nmcli(*args, secret=True)

        try:
            self._nmcli("--wait", str(timeout), "connection", "up", name,
                        timeout=timeout + 15)
        except NmcliError:
            # A profile with a wrong password would be retried at every boot.
            try:
                self._nmcli("connection", "delete", name)
            except NmcliError:
                pass
            raise
