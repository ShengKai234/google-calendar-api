"""
Setup hotspot run by our own wpa_supplicant, offering WPA-PSK only.

NetworkManager's hotspot offers WPA-PSK and WPA-PSK-SHA256 together, with
no setting to drop the second. On the Zero W the Wi-Fi firmware builds the
beacon itself, and an iPhone drops out right after message 3/4 of the
handshake, reporting a wrong password although the password matched
(found on hardware; see hotspot.py). With WPA-PSK alone it joins.

While the hotspot is up NetworkManager is told to leave wlan0 alone, and the
system wpa_supplicant is stopped; both are handed wlan0 back when it goes
down, so scanning and joining the home network work as before. DHCP comes
from dnsmasq, the same program NetworkManager's hotspot uses, at the same
pinned address — the panel's QR names it.
"""
import hashlib
import logging
import subprocess
import time
from pathlib import Path
from typing import Callable

from gcal_epd.infrastructure.wifi.nmcli import AP_ADDRESS, AP_PREFIX, DEFAULT_IFNAME, NmcliError

log = logging.getLogger(__name__)

RUN_DIR = Path("/run/epd-hotspot")
CHANNEL_FREQ = 2412      # channel 1; the Zero W has 2.4GHz only
DHCP_RANGE = ("10.42.0.10", "10.42.0.254")
AP_UP_WAIT = 20          # seconds for the interface to turn into an AP
NM_BACK_WAIT = 20        # seconds for NetworkManager to take wlan0 back
_DEVICE_USABLE = 30      # nmcli device state "disconnected"; below is unusable
_STOP_WAIT = 5

Runner = Callable[[list[str], float], subprocess.CompletedProcess]


class HotspotError(NmcliError):
    """The hotspot did not come up. An NmcliError, as NetworkManager's is."""


def _run(args: list[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def wpa_config(ssid: str, password: str, frequency: int = CHANNEL_FREQ) -> str:
    """wpa_supplicant.conf for a WPA2 AP with the WPA-PSK key management only.

    The SSID goes in as hex and the password as its derived key, so no
    character in either can break out of the file's quoting.
    """
    psk = hashlib.pbkdf2_hmac("sha1", password.encode(), ssid.encode(), 4096, 32)
    return (
        "network={\n"
        f"  ssid={ssid.encode().hex()}\n"
        "  mode=2\n"
        f"  frequency={frequency}\n"
        "  key_mgmt=WPA-PSK\n"
        "  proto=RSN\n"
        "  pairwise=CCMP\n"
        "  group=CCMP\n"
        "  ieee80211w=0\n"
        f"  psk={psk.hex()}\n"
        "}\n"
    )


class WpaSupplicantHotspot:
    def __init__(self, ifname: str = DEFAULT_IFNAME, run: Runner = _run,
                 popen: Callable[..., subprocess.Popen] = subprocess.Popen,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic,
                 run_dir: Path = RUN_DIR) -> None:
        self.ifname = ifname
        self._run = run
        self._popen = popen
        self._sleep = sleep
        self._clock = clock
        self._run_dir = run_dir
        self._creds: tuple[str, str] | None = None
        self._procs: list[subprocess.Popen] = []
        self._holding = False  # wlan0 taken from NetworkManager

    @property
    def _conf(self) -> Path:
        return self._run_dir / "wpa_supplicant.conf"

    # --- Hotspot strategy ---------------------------------------------
    def start(self, ssid: str, password: str) -> None:
        self.remove()
        self._creds = (ssid, password)
        self._up()

    def resume(self) -> None:
        """Bring the same hotspot back, so a phone that joined once rejoins."""
        if self._creds is None:
            raise HotspotError("no hotspot to resume")
        self._up()

    def stop(self) -> None:
        self._down()

    def remove(self) -> None:
        self._down()
        self._conf.unlink(missing_ok=True)

    # --- plumbing -----------------------------------------------------
    def _cmd(self, *args: str, timeout: float = 15) -> subprocess.CompletedProcess | None:
        """Run a command; failures are logged, the AP check below decides."""
        try:
            result = self._run(list(args), timeout)
        except (OSError, subprocess.TimeoutExpired) as e:
            log.warning("%s failed: %s", args[0], e)
            return None
        if result.returncode != 0:
            log.warning("%s failed: %s", " ".join(args), result.stderr.strip())
        return result

    def _up(self) -> None:
        ssid, password = self._creds
        self._run_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._conf.touch(mode=0o600)  # holds the key: root only, before writing
        self._conf.write_text(wpa_config(ssid, password))

        self._holding = True
        self._cmd("nmcli", "device", "set", self.ifname, "managed", "no")
        self._cmd("systemctl", "stop", "wpa_supplicant.service")
        self._cmd("rfkill", "unblock", "wifi")
        self._cmd("ip", "link", "set", self.ifname, "up")
        self._cmd("ip", "addr", "flush", "dev", self.ifname)
        self._cmd("ip", "addr", "add", f"{AP_ADDRESS}/{AP_PREFIX}", "dev", self.ifname)

        wpa = self._popen(["wpa_supplicant", "-i", self.ifname, "-D", "nl80211",
                           "-c", str(self._conf)])
        self._procs.append(wpa)
        if not self._wait_ap(wpa):
            self._down()
            raise HotspotError(f"{self.ifname} did not become an access point "
                               f"within {AP_UP_WAIT}s")

        self._procs.append(self._popen([
            # Options as NetworkManager runs it for its own hotspot.
            "dnsmasq", "--keep-in-foreground", "--conf-file=/dev/null",
            f"--pid-file={self._run_dir / 'dnsmasq.pid'}",
            f"--interface={self.ifname}", "--bind-interfaces", "--except-interface=lo",
            "--port=0",  # DHCP only, as NetworkManager's hotspot had no upstream DNS either
            f"--dhcp-range={DHCP_RANGE[0]},{DHCP_RANGE[1]},1h", "--dhcp-authoritative",
            f"--dhcp-leasefile={self._run_dir / 'dnsmasq.leases'}",
        ]))

    def _wait_ap(self, wpa: subprocess.Popen) -> bool:
        deadline = self._clock() + AP_UP_WAIT
        while True:
            if wpa.poll() is not None:
                log.warning("wpa_supplicant exited with %s", wpa.returncode)
                return False
            info = self._cmd("iw", "dev", self.ifname, "info")
            if info is not None and "type AP" in info.stdout:
                return True
            if self._clock() >= deadline:
                return False
            self._sleep(1)

    def _down(self) -> None:
        for proc in reversed(self._procs):
            proc.terminate()
            try:
                proc.wait(_STOP_WAIT)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        self._procs = []
        if not self._holding:
            return
        self._cmd("ip", "addr", "flush", "dev", self.ifname)
        self._cmd("systemctl", "start", "wpa_supplicant.service")
        self._cmd("nmcli", "device", "set", self.ifname, "managed", "yes")
        self._holding = False
        self._wait_nm()

    def _wait_nm(self) -> None:
        """Wait until NetworkManager can scan and join on wlan0 again."""
        deadline = self._clock() + NM_BACK_WAIT
        while True:
            out = self._cmd("nmcli", "-t", "-f", "GENERAL.STATE", "device", "show",
                            self.ifname)
            state = out.stdout.partition(":")[2].split()[:1] if out else []
            if state and state[0].isdigit() and int(state[0]) >= _DEVICE_USABLE:
                return
            if self._clock() >= deadline:
                log.warning("NetworkManager has not taken %s back after %ss",
                            self.ifname, NM_BACK_WAIT)
                return
            self._sleep(1)
