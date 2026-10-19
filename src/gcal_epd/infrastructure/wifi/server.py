"""
Wi-Fi setup form, served on the Pi's own hotspot.

There is no PIN here, unlike the calendar setup form: that one runs on a
shared LAN, but this one is reachable only by joining a hotspot whose
password is shown on the panel. Seeing the panel is the proof of presence.

The radio cannot be a hotspot and a client at once, so submitting the form
drops the phone's connection. The handler only records the request and
answers straight away; the controller does the switch after the reply has
gone out.

The server runs on its own thread, one thread per connection. Browsers
open speculative connections they may never send a request on; served one
at a time, a single idle socket held the real page until the browser gave
up on it. And the controller blocks for ~40 s on every panel refresh — the
form must keep answering through that.
"""
import logging
import secrets
import string
import threading
import time
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from gcal_epd.domain.power_ports import ScheduleStore
from gcal_epd.infrastructure.onboarding.server import validate_feed_url
from gcal_epd.infrastructure.schedule_file import InMemoryScheduleStore
from gcal_epd.infrastructure.web.schedule_form import (
    SCHEDULE_CSS,
    ScheduleFields,
    save_schedule_safely,
)
from gcal_epd.infrastructure.wifi.nmcli import AP_ADDRESS, Network, is_valid_psk

log = logging.getLogger(__name__)

DEFAULT_PORT = 80
_MAX_BODY = 8 * 1024
_IDLE_TIMEOUT = 10  # seconds a connection may sit without sending a request
_MAX_SSID_BYTES = 32
_OTHER = "__other__"
# No 0/o, 1/l/i: the password may have to be typed off the panel.
_PASSWORD_ALPHABET = "".join(c for c in string.ascii_lowercase + string.digits
                             if c not in "0o1li")


def generate_ap_ssid() -> str:
    return f"ePaper-Setup-{secrets.token_hex(2).upper()}"


def generate_ap_password(length: int = 10) -> str:
    return "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))


def parse_feed_links(raw: str) -> list[str]:
    """One link per line, blanks skipped; raise ValueError on a bad one.

    Only the form is checked here — the hotspot has no internet, so whether
    a link really serves a calendar is checked after Wi-Fi joins.
    """
    links = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            links.append(validate_feed_url(line))
        except ValueError as e:
            raise ValueError(f"Calendar link: {e}.") from None
    return links


def validate_credentials(ssid: str, password: str) -> tuple[str, str]:
    """Return the cleaned pair, or raise ValueError explaining what is wrong."""
    if not ssid:
        raise ValueError("Choose a network.")
    if len(ssid.encode("utf-8")) > _MAX_SSID_BYTES:
        raise ValueError("Network names are at most 32 bytes.")
    if password and not is_valid_psk(password):
        raise ValueError("Wi-Fi passwords are 8 to 63 characters.")
    return ssid, password


_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Wi-Fi Setup</title><style>
:root{{color-scheme:light dark}}
body{{font:16px/1.5 system-ui,-apple-system,sans-serif;margin:0;padding:24px;
max-width:34rem;margin-inline:auto}}
h1{{font-size:1.3rem;margin:0 0 .25rem}}
p.sub{{margin:0 0 1.5rem;opacity:.7}}
label{{display:block;margin:1rem 0 .3rem;font-weight:600}}
input,select,textarea{{width:100%;box-sizing:border-box;padding:.6rem;font-size:16px;
border:1px solid #8888;border-radius:8px;background:transparent;color:inherit;
font-family:inherit}}
small{{opacity:.7;display:block;margin-top:.3rem}}
button{{margin-top:1.5rem;width:100%;padding:.8rem;font-size:1rem;font-weight:600;
border:0;border-radius:8px;background:#2563eb;color:#fff}}
.msg{{padding:.8rem 1rem;border-radius:8px;margin-bottom:1rem}}
.err{{background:#fee2e2;color:#991b1b}}
@media(prefers-color-scheme:dark){{.err{{background:#7f1d1d;color:#fecaca}}}}
{schedule_css}
</style></head><body>
<h1>Wi-Fi Setup</h1>
<p class="sub">Choose the network this display should join.</p>
{message}
<form method="post">
<label for="ssid">Network</label>
<select id="ssid" name="ssid">{options}
<option value="{other}">Other (hidden network)…</option></select>
<label for="other_ssid">Hidden network name</label>
<input id="other_ssid" name="other_ssid" autocomplete="off" autocapitalize="off"
 value="{other_value}">
<small>Only needed when "Other" is selected. Only 2.4GHz networks work.</small>
<label for="password">Password</label>
<input id="password" name="password" type="password" autocomplete="off">
<small>Leave empty for an open network.</small>
<label for="feeds">Calendar links (optional)</label>
<textarea id="feeds" name="feeds" rows="4" autocomplete="off" autocapitalize="off"
 placeholder="webcal://p1-caldav.icloud.com/published/2/...">{feeds_value}</textarea>
<small>One per line. Checked once the display is online — if one fails, the
display shows a QR to fix it. Leave empty to keep the current calendars.</small>
{schedule}
<button type="submit">Connect</button>
</form></body></html>"""

_CONNECTING = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Wi-Fi Setup</title><style>
body{{font:16px/1.5 system-ui,-apple-system,sans-serif;margin:0;padding:24px;
max-width:34rem;margin-inline:auto;text-align:center}}
h1{{font-size:1.4rem}}
</style></head><body><h1>Connecting to {ssid}…</h1>
<p>This hotspot is closing now, so your phone will disconnect.
Watch the display.</p>
<p>If it cannot connect, the hotspot comes back with an error on the
display — rejoin it and reload this page to try again.</p>
<p>{feeds_note}</p>
</body></html>"""


class _Handler(BaseHTTPRequestHandler):
    server_version = "gcal-epd"
    timeout = _IDLE_TIMEOUT  # drop speculative connections that never send

    def log_message(self, fmt, *args):
        pass  # keep request lines (and anything in them) out of the journal

    def _send(self, body: str, status: int = 200) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _page(self, error: str = "", selected: str = "", other: str = "",
              feeds: str = "", times: ScheduleFields | None = None,
              status: int = 200) -> None:
        options = []
        for net in self.server.networks:
            mark = "" if net.secure else " (open)"
            sel = " selected" if net.ssid == selected else ""
            options.append(f'<option value="{escape(net.ssid)}"{sel}>'
                           f'{escape(net.ssid)}{mark}</option>')
        message = f'<div class="msg err">{escape(error)}</div>' if error else ""
        times = times or ScheduleFields.of(self.server.schedule)
        self._send(_PAGE.format(message=message, options="".join(options),
                                other=_OTHER, other_value=escape(other),
                                feeds_value=escape(feeds), schedule=times.html(),
                                schedule_css=SCHEDULE_CSS), status)

    def do_GET(self) -> None:
        # Any path gets the form: phones probing for a captive portal land here.
        self.server.last_activity = time.monotonic()
        self._page(error=self.server.error)

    def do_POST(self) -> None:
        self.server.last_activity = time.monotonic()
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > _MAX_BODY:
            self._page("Request was empty or too large.", status=400)
            return

        form = parse_qs(self.rfile.read(length).decode("utf-8", "replace"),
                        keep_blank_values=True)
        choice = (form.get("ssid") or [""])[0]
        other = (form.get("other_ssid") or [""])[0].strip()
        password = (form.get("password") or [""])[0]
        raw_feeds = (form.get("feeds") or [""])[0]
        times = ScheduleFields.from_form(form)
        ssid = other if choice == _OTHER else choice

        try:
            ssid, password = validate_credentials(ssid, password)
            feeds = parse_feed_links(raw_feeds)
            schedule = times.to_schedule(self.server.schedule) if times else None
        except ValueError as e:
            # The password is never sent back: it is retyped, like any login form.
            self._page(str(e), selected=choice, other=other, feeds=raw_feeds,
                       times=times, status=400)
            return

        # Saved now, not after the join: the times do not depend on the
        # network (or the calendar links), and a failed join reloads the
        # form, which should show what was just chosen.
        if schedule is not None and save_schedule_safely(self.server.schedule_store,
                                                         schedule):
            self.server.schedule = schedule

        note = (f"Then {len(feeds)} calendar link(s) will be checked and the "
                "calendar shown." if feeds else
                "Then the display shows a QR to add your calendars, if none are set up.")
        self._send(_CONNECTING.format(ssid=escape(ssid), feeds_note=note))
        with self.server.lock:
            self.server.pending = (ssid, password, feeds)
        self.server.submitted.set()
        log.info("Wi-Fi setup: received credentials for %r", ssid)


class WifiSetupServer:
    """The form, served in the background; the controller polls for a submission."""

    def __init__(self, networks: list[Network], port: int = DEFAULT_PORT,
                 schedule_store: ScheduleStore | None = None) -> None:
        self.port = port
        self._httpd = ThreadingHTTPServer(("0.0.0.0", port), _Handler)
        self._httpd.daemon_threads = True
        self._httpd.networks = list(networks)
        # Where the wake-up times are kept; the form starts from what it holds.
        self._httpd.schedule_store = schedule_store or InMemoryScheduleStore()
        self._httpd.schedule = self._httpd.schedule_store.load()
        self._httpd.error = ""
        self._httpd.pending = None
        self._httpd.lock = threading.Lock()
        self._httpd.submitted = threading.Event()
        self._httpd.last_activity = float("-inf")
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                         kwargs={"poll_interval": 0.5}, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        return f"http://{AP_ADDRESS}" + ("" if self.port == 80 else f":{self.port}")

    @property
    def last_activity(self) -> float:
        return self._httpd.last_activity

    def set_networks(self, networks: list[Network]) -> None:
        self._httpd.networks = list(networks)

    def set_error(self, error: str) -> None:
        self._httpd.error = error

    def handle_once(self) -> None:
        """Wait up to a second for a submission; requests are served meanwhile."""
        self._httpd.submitted.wait(1)

    def take_pending(self) -> tuple[str, str, list[str]] | None:
        with self._httpd.lock:
            pending, self._httpd.pending = self._httpd.pending, None
            self._httpd.submitted.clear()
        return pending

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
