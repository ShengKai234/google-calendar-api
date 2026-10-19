"""
One-time onboarding server.

The device holds no secret to show; the *user* holds one — a feed URL far
too long to type on a machine with no keyboard. So the Pi briefly serves a
form on the LAN, shows its own address and a PIN on the panel, and the user
pastes the URL from their phone.

The address on screen is the Pi's own, not a secret. The PIN is what stops
anyone else on the same network from writing feeds during the window.
"""
import logging
import re
import secrets
import socket
import time
from dataclasses import dataclass
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlsplit

from gcal_epd.domain.power_schedule import PowerSchedule, format_slot, parse_slot
from gcal_epd.infrastructure.feeds_file import write_feeds_file

log = logging.getLogger(__name__)

DEFAULT_PORT = 8080
DEFAULT_TIMEOUT = 600  # seconds before the window closes on its own
_ALLOWED_SCHEMES = ("webcal", "webcals", "http", "https")
_MAX_BODY = 64 * 1024


def detect_lan_ip() -> str:
    """The address a phone on the same network can reach.

    Opening a UDP socket sends no traffic; it only asks the routing table
    which local address would be used, which beats hostname lookups that
    resolve to 127.0.0.1 on a headless Pi.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def generate_pin() -> str:
    return f"{secrets.randbelow(1000000):06d}"


def validate_feed_url(url: str) -> str:
    """Return the cleaned URL, or raise ValueError explaining what is wrong."""
    url = url.strip()
    if not url:
        raise ValueError("empty URL")
    parts = urlsplit(url)
    if parts.scheme not in _ALLOWED_SCHEMES:
        raise ValueError(
            f"URL must start with {' , '.join(s + '://' for s in _ALLOWED_SCHEMES)}"
        )
    if not parts.netloc:
        raise ValueError("URL has no host")
    return url


def probe_feed(url: str, timeout: int = 20) -> int:
    """Fetch and parse a feed, returning its upcoming event count.

    Raises if the feed cannot be reached or parsed, so a typo is caught
    here rather than showing up as a silently empty calendar later. Note
    a *reachable* calendar may legitimately have zero upcoming events, so
    the count alone can never stand in for success.
    """
    from gcal_epd.infrastructure.ics.repository import ICSRepository, events_from_ics

    repo = ICSRepository(url=url, timeout=timeout)
    return len(events_from_ics(repo.fetch_raw(), days_ahead=365, max_results=1000))


def inspect_feed(url: str, timeout: int = 20) -> tuple[int, str]:
    """Return (upcoming event count, "") if the feed works, else (0, problem).

    The problem names only the host — it goes on the panel and the form,
    and the full URL is a bearer token.
    """
    import requests

    from gcal_epd.infrastructure.ics.repository import (
        ICSRepository,
        events_from_ics,
        normalize_feed_url,
    )

    host = urlsplit(normalize_feed_url(url)).netloc or "that link"
    try:
        raw = ICSRepository(url=url, timeout=timeout).fetch_raw()
    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else "an error"
        return 0, f"The calendar at {host} answered {code}."
    except Exception:
        return 0, f"Could not download the calendar from {host}."
    try:
        return len(events_from_ics(raw, days_ahead=365, max_results=1000)), ""
    except Exception:
        return 0, f"The link at {host} is not a calendar (iCal) file."


def check_feed(url: str, timeout: int = 20) -> str:
    """"" if the feed downloads and parses, else what went wrong."""
    return inspect_feed(url, timeout)[1]


# --- wake-up times, shared by this form and the Wi-Fi hotspot form ----------

SaveSchedule = Callable[[PowerSchedule], None]

_SCHEDULE_HTML = """<fieldset class="wake"><legend>Display wake-up times</legend>
<input type="hidden" name="schedule" value="1">
<div class="slots">{inputs}</div>
<label class="check"><input type="checkbox" name="enabled" value="1"{checked}>
Turn off between updates to save battery</label>
<small>The display wakes a few minutes before each time to refresh the
calendar, and is off in between.</small></fieldset>"""


@dataclass
class ScheduleFields:
    """The wake-up section of a form: the times as typed, and the checkbox.

    Every time input shares the field name "slot", and any number of them
    is accepted (blanks ignored), so adding an "Add time" button later is
    a page-only change. The hidden "schedule" field marks a form that has
    the section: without it, an unticked checkbox and a missing section
    would look the same.
    """
    slots: list[str]
    enabled: bool

    @classmethod
    def of(cls, schedule: PowerSchedule) -> "ScheduleFields":
        return cls([format_slot(s) for s in schedule.slots], schedule.enabled)

    @classmethod
    def from_form(cls, form: dict[str, list[str]]) -> "ScheduleFields | None":
        """The section as submitted, or None if the form had none."""
        if "schedule" not in form:
            return None
        return cls([s.strip() for s in form.get("slot", [])], "enabled" in form)

    def to_schedule(self, current: PowerSchedule) -> PowerSchedule:
        """Raise ValueError, with a message for the form, if the times are wrong.

        The wake-up lead is not on the form, so it is kept from `current`.
        """
        return PowerSchedule(slots=tuple(parse_slot(s) for s in self.slots if s),
                             enabled=self.enabled,
                             wake_lead_minutes=current.wake_lead_minutes)

    def html(self) -> str:
        slots = self.slots or [""]  # always somewhere to type a time
        inputs = "".join(
            f'<input type="time" name="slot" aria-label="Wake-up time {i}"'
            f' value="{escape(s)}">' for i, s in enumerate(slots, 1))
        return _SCHEDULE_HTML.format(inputs=inputs,
                                     checked=" checked" if self.enabled else "")


# Rules for the section above, for the <style> of a page that shows it.
SCHEDULE_CSS = """fieldset.wake{border:1px solid #8888;border-radius:8px;margin:1.5rem 0 0;
padding:.4rem 1rem 1rem}
legend{font-weight:600;padding:0 .3rem}
.slots{display:flex;flex-wrap:wrap;gap:.5rem;margin-top:.3rem}
.slots input{flex:1 1 7rem;width:auto}
label.check{display:flex;gap:.5rem;align-items:center;font-weight:400}
label.check input{width:auto;margin:0}"""


def save_schedule_safely(save: SaveSchedule, schedule: PowerSchedule) -> bool:
    """Save the times; a failure is logged, never fatal to the rest of setup."""
    try:
        save(schedule)
    except Exception as e:  # a full disk, a broken config.toml

        log.warning("Could not save the wake-up times: %s", e)
        return False
    log.info("Saved wake-up times %s (%s).",
             ", ".join(format_slot(s) for s in schedule.slots),
             "power off between" if schedule.enabled else "always on")
    return True


_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Calendar Setup</title><style>
:root{{color-scheme:light dark}}
body{{font:16px/1.5 system-ui,-apple-system,sans-serif;margin:0;padding:24px;
max-width:34rem;margin-inline:auto}}
h1{{font-size:1.3rem;margin:0 0 .25rem}}
p.sub{{margin:0 0 1.5rem;opacity:.7}}
label{{display:block;margin:1rem 0 .3rem;font-weight:600}}
input,textarea{{width:100%;box-sizing:border-box;padding:.6rem;font-size:16px;
border:1px solid #8888;border-radius:8px;background:transparent;color:inherit;
font-family:inherit}}
textarea{{min-height:7rem;font-family:ui-monospace,monospace;font-size:14px}}
small{{opacity:.7;display:block;margin-top:.3rem}}
button{{margin-top:1.5rem;width:100%;padding:.8rem;font-size:1rem;font-weight:600;
border:0;border-radius:8px;background:#2563eb;color:#fff}}
.msg{{padding:.8rem 1rem;border-radius:8px;margin-bottom:1rem}}
.err{{background:#fee2e2;color:#991b1b}}
.ok{{background:#dcfce7;color:#166534}}
@media(prefers-color-scheme:dark){{.err{{background:#7f1d1d;color:#fecaca}}
.ok{{background:#14532d;color:#bbf7d0}}}}
{schedule_css}
</style></head><body>
<h1>Calendar Setup</h1>
<p class="sub">Paste your calendar feed links below.</p>
{message}
<form method="post">
<label for="pin">PIN shown on the display</label>
<input id="pin" name="pin" inputmode="numeric" pattern="[0-9]*" autocomplete="off"
 required value="{pin_value}">
<label for="urls">Feed URLs — one per line</label>
<textarea id="urls" name="urls" required
 placeholder="webcal://p1-caldav.icloud.com/published/2/...
https://calendar.google.com/calendar/ical/.../basic.ics">{urls_value}</textarea>
<small>Apple: Calendar &rsaquo; right-click calendar &rsaquo; Share &rsaquo; Public Calendar.
Google: Settings &rsaquo; calendar &rsaquo; Integrate calendar &rsaquo; secret iCal address.</small>
{schedule}
<button type="submit">Save and show my calendar</button>
</form></body></html>"""

_DONE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Calendar Setup</title><style>
body{{font:16px/1.5 system-ui,-apple-system,sans-serif;margin:0;padding:24px;
max-width:34rem;margin-inline:auto;text-align:center}}
h1{{font-size:1.4rem}} ul{{text-align:left;display:inline-block}}
</style></head><body><h1>Connected</h1>
<p>{summary}</p><ul>{items}</ul>
<p>{schedule}</p>
<p>You can close this page — the display is updating now.</p>
</body></html>"""


class _Handler(BaseHTTPRequestHandler):
    server_version = "gcal-epd"

    # --- plumbing ---------------------------------------------------
    def log_message(self, fmt, *args):
        # Default logging writes the request line to stderr; a URL could
        # end up there via a query string, so route it nowhere.
        pass

    def _send(self, body: str, status: int = 200) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _page(self, message: str = "", pin: str = "", urls: str = "",
              times: ScheduleFields | None = None, status: int = 200) -> None:
        times = times or ScheduleFields.of(self.server.schedule)
        self._send(_PAGE.format(message=message, pin_value=escape(pin),
                                urls_value=escape(urls), schedule=times.html(),
                                schedule_css=SCHEDULE_CSS), status)

    # --- routes -----------------------------------------------------
    def do_GET(self) -> None:
        if urlsplit(self.path).path != "/":
            self._send("<h1>Not found</h1>", 404)
            return
        notice = self.server.notice
        self._page(f'<div class="msg err">{escape(notice)}</div>' if notice else "")

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > _MAX_BODY:
            self._page('<div class="msg err">Request was empty or too large.</div>',
                       status=400)
            return

        # Blank values kept, so a cleared time input comes back as a box to fill.
        form = parse_qs(self.rfile.read(length).decode("utf-8", "replace"),
                        keep_blank_values=True)
        pin = (form.get("pin") or [""])[0].strip()
        raw_urls = (form.get("urls") or [""])[0]
        times = ScheduleFields.from_form(form)

        if not secrets.compare_digest(pin, self.server.pin):
            log.warning("Onboarding: rejected a submission with a wrong PIN.")
            self._page('<div class="msg err">That PIN does not match the '
                       'display. Check the screen and try again.</div>',
                       urls=raw_urls, times=times, status=403)
            return

        urls, errors = [], []  # errors are HTML, escaped as they are added
        for line in raw_urls.splitlines():
            if not line.strip():
                continue
            try:
                urls.append(validate_feed_url(line))
            except ValueError as e:
                errors.append(f"{escape(line.strip()[:40])}… — {escape(str(e))}")
        if not urls:
            errors.append("No feed URLs given.")
        schedule = None
        if times is not None:
            try:
                schedule = times.to_schedule(self.server.schedule)
            except ValueError as e:
                errors.append(f"Wake-up times: {escape(str(e))}.")
        if errors:
            self._page('<div class="msg err">' + "<br>".join(errors) + "</div>",
                       pin=pin, urls=raw_urls, times=times, status=400)
            return

        # Probe before saving, so a bad URL fails here rather than showing
        # up as a mysteriously empty calendar later.
        feeds, results, failures = [], [], []
        for url in urls:
            host = urlsplit(url).netloc
            count, problem = inspect_feed(url)
            if problem:
                failures.append(problem)
                continue
            feeds.append({"url": url})
            results.append(f"<li>{escape(host)} — {count} event(s) found</li>")

        if failures:
            self._page('<div class="msg err">' +
                       "<br>".join(escape(f) for f in failures) +
                       " Check the link and try again.</div>",
                       pin=pin, urls=raw_urls, times=times, status=400)
            return

        write_feeds_file(self.server.feeds_path, feeds)
        log.info("Onboarding: saved %d feed(s) to %s",
                 len(feeds), self.server.feeds_path.name)
        wake_note = ""
        if schedule is not None:
            if save_schedule_safely(self.server.save_schedule, schedule):
                self.server.schedule = schedule
                wake_note = "Wake-up times: " + ", ".join(
                    format_slot(s) for s in schedule.slots) + "."
            else:
                wake_note = "The wake-up times could not be saved."
        self._send(_DONE.format(
            summary=f"Saved {len(feeds)} calendar feed(s).",
            items="".join(results), schedule=escape(wake_note)))
        self.server.configured = True


class FeedSetupServer:
    """Serves the setup form until feeds are saved or the window closes."""

    def __init__(self, feeds_path, port: int = DEFAULT_PORT,
                 pin: str | None = None, timeout: int = DEFAULT_TIMEOUT,
                 notice: str = "", schedule: PowerSchedule | None = None,
                 save_schedule: SaveSchedule = lambda schedule: None) -> None:
        self.feeds_path = Path(feeds_path)
        self.notice = notice  # shown on the form, e.g. why setup reopened
        # The wake-up times the form starts from, and where a new set goes;
        # the caller knows the file, the server only the function.
        self.schedule = schedule or PowerSchedule()
        self.save_schedule = save_schedule
        self.port = port
        self.pin = pin or generate_pin()
        self.timeout = timeout
        self.ip = detect_lan_ip()

    @property
    def url(self) -> str:
        return f"http://{self.ip}:{self.port}"

    def serve_until_configured(self) -> bool:
        """Run the form. True if feeds were saved, False if the window closed."""
        httpd = ThreadingHTTPServer(("0.0.0.0", self.port), _Handler)
        httpd.pin = self.pin
        httpd.feeds_path = self.feeds_path
        httpd.notice = self.notice
        httpd.schedule = self.schedule
        httpd.save_schedule = self.save_schedule
        httpd.configured = False
        httpd.timeout = 1

        log.info("Setup form: %s  (PIN %s)", self.url, self.pin)
        deadline = time.monotonic() + self.timeout
        try:
            while not httpd.configured and time.monotonic() < deadline:
                httpd.handle_request()
        except KeyboardInterrupt:
            log.info("Setup cancelled.")
        finally:
            httpd.server_close()

        if not httpd.configured:
            log.warning("Setup window closed after %ds with no feeds saved.",
                        self.timeout)
        return httpd.configured
