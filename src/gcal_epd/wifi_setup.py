"""
Wi-Fi setup over a hotspot, for a display that has no network yet.

Runs at boot as root (deploy/epd-wifi-setup.service). If NetworkManager
joins a saved network on its own, this exits at once. Otherwise the Pi
becomes a hotspot, the panel shows how to join it, and the phone picks the
home network from a form. A wrong password brings the same hotspot back.

While waiting it periodically drops the hotspot to retry saved networks,
so a router that was simply slower to boot than the Pi does not leave the
display stuck in setup — but never while someone is using the form.

    sudo .venv/bin/python -m gcal_epd.wifi_setup --display          # as at boot

To change networks over SSH, run it detached — the SSH session drops with
the Wi-Fi and would take a foreground process down with it:

    sudo systemd-run --working-directory=$PWD \\
        $PWD/.venv/bin/python -m gcal_epd.wifi_setup --display --force
"""
import argparse
import logging
import subprocess
import sys
import time
from typing import Callable

from gcal_epd.infrastructure.wifi.nmcli import NetworkManager, NmcliError
from gcal_epd.infrastructure.wifi.server import (
    DEFAULT_PORT,
    WifiSetupServer,
    generate_ap_password,
    generate_ap_ssid,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

BOOT_WAIT = 60        # seconds to let NetworkManager join a saved network
RETRY_INTERVAL = 300  # how often to retry saved networks while in setup
RETRY_WAIT = 45       # how long each retry gets
IDLE_GRACE = 120      # never retry within this long of a form request
_FLUSH_DELAY = 2      # let the "connecting" page reach the phone first

Push = Callable[..., None]


def run(nm: NetworkManager, server_factory: Callable[[list], WifiSetupServer],
        push: Push, *, force: bool = False, boot_wait: float = BOOT_WAIT,
        retry_interval: float = RETRY_INTERVAL, retry_wait: float = RETRY_WAIT,
        idle_grace: float = IDLE_GRACE, clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep) -> str:
    """Return "online" (already connected), "joined" (set up here) or "cancelled"."""
    if not force and nm.wait_connected(boot_wait):
        log.info("Wi-Fi already connected — no setup needed.")
        return "online"

    networks = nm.scan()  # must happen before the hotspot takes the radio
    ap_ssid, ap_password = generate_ap_ssid(), generate_ap_password()
    server = server_factory(networks)
    try:
        nm.start_hotspot(ap_ssid, ap_password)
        log.info("Hotspot %s is up — setup form at %s", ap_ssid, server.url)
        push("ap", ap_ssid=ap_ssid, ap_password=ap_password, url=server.url)

        next_retry = clock() + retry_interval
        while True:
            server.handle_once()

            creds = server.take_pending()
            if creds:
                ssid, password = creds
                sleep(_FLUSH_DELAY)
                nm.stop_hotspot()
                try:
                    nm.connect(ssid, password)
                except NmcliError as e:
                    log.warning("Could not join %r: %s", ssid, e)
                    error = f"Could not join {ssid}. Check the password and try again."
                    server.set_error(error)
                    nm.resume_hotspot()
                    push("ap", ap_ssid=ap_ssid, ap_password=ap_password,
                         url=server.url, error=error)
                    next_retry = clock() + retry_interval
                    continue
                log.info("Joined %r.", ssid)
                push("connected", ssid=ssid)
                return "joined"

            now = clock()
            if (retry_interval and now >= next_retry
                    and now - server.last_activity >= idle_grace
                    and nm.saved_wifi_profiles()):
                log.info("Retrying saved networks...")
                nm.stop_hotspot()
                if nm.wait_connected(retry_wait):
                    log.info("A saved network came back.")
                    push("connected", ssid="your saved network")
                    return "joined"
                server.set_networks(nm.scan())  # the radio is free to scan now
                nm.resume_hotspot()
                next_retry = clock() + retry_interval
    except KeyboardInterrupt:
        log.info("Wi-Fi setup cancelled.")
        return "cancelled"
    finally:
        server.close()
        nm.remove_hotspot()


def _make_push(display: bool) -> Push:
    """Draw a setup screen to the panel; never fatal if the panel is absent."""
    def push(kind: str, **kwargs) -> None:
        if not display:
            return
        try:
            from gcal_epd.epd import push_to_display
            from gcal_epd.main import _PROJECT_ROOT, load_config
            from gcal_epd.render.wifi_screens import render_wifi_connected, render_wifi_setup

            raw_font = load_config().get("display", {}).get("font_path", "")
            font_path = (str(_PROJECT_ROOT / raw_font)
                         if raw_font and not raw_font.startswith("/") else raw_font)
            if kind == "ap":
                img = render_wifi_setup(kwargs["ap_ssid"], kwargs["ap_password"],
                                        kwargs["url"], error=kwargs.get("error", ""),
                                        font_path=font_path)
            else:
                img = render_wifi_connected(kwargs["ssid"], font_path=font_path)
            push_to_display(img)
        except Exception as e:
            log.warning("Could not draw the Wi-Fi %s screen: %s", kind, e)
    return push


def start_units(result: str, units: list[str], run=subprocess.run) -> None:
    """Hand over to the calendar once there is a network, however it came.

    Started on "online" as well as "joined": a display that boots straight
    onto a known network would otherwise sit blank until the next timer
    run, and never show the calendar setup form at all.
    """
    if result not in ("online", "joined"):
        return
    for unit in units:
        # --no-block: these units are ordered after this one, so waiting
        # for them here would deadlock.
        run(["systemctl", "start", "--no-block", unit], check=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Set up Wi-Fi through a hotspot")
    parser.add_argument("--display", action="store_true",
                        help="Show hotspot details on the e-ink display")
    parser.add_argument("--force", action="store_true",
                        help="Start the hotspot even if Wi-Fi is already connected")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--start-unit", metavar="UNIT", action="append", default=[],
                        help="systemd unit to start once Wi-Fi is up (repeatable)")
    args = parser.parse_args()

    if not NetworkManager.available():
        log.error("nmcli not found — Wi-Fi setup needs NetworkManager "
                  "(Raspberry Pi OS Bookworm or later).")
        sys.exit(1)

    result = run(NetworkManager(),
                 lambda networks: WifiSetupServer(networks, port=args.port),
                 _make_push(args.display), force=args.force)

    start_units(result, args.start_unit)
    if result == "cancelled":
        sys.exit(130)


if __name__ == "__main__":
    main()
