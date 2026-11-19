"""
iCalendar (.ics) feed repository.

Reads a published calendar feed — Apple iCloud, Google, or any server that
exposes an .ics URL. Unlike the Calendar API, a feed ships recurring events
as RRULE rules rather than individual occurrences, so they are expanded
client-side before being handed to the domain.
"""
import datetime
import logging
import time
from urllib.parse import urlsplit

import icalendar
import recurring_ical_events
import requests

from gcal_epd.domain.event import CalendarEvent
from gcal_epd.infrastructure import fetch_budget

log = logging.getLogger(__name__)

# requests/urllib3 logs the full request line at DEBUG level, which would put
# the feed token straight into the systemd journal whenever debug logging is
# on. A feed URL is a bearer token, so hold that logger above DEBUG no matter
# what level the application selects.
logging.getLogger("urllib3.connectionpool").setLevel(logging.INFO)

DEFAULT_TIMEOUT = fetch_budget.REQUEST_TIMEOUT
_USER_AGENT = "gcal-epd/1.0"


def normalize_feed_url(url: str) -> str:
    """webcal:// is plain https:// — the scheme only tells the OS to subscribe."""
    for scheme in ("webcal://", "webcals://"):
        if url.startswith(scheme):
            return "https://" + url[len(scheme):]
    return url


def events_from_ics(
    raw: bytes,
    days_ahead: int,
    max_results: int,
    name: str = "",
    now: datetime.datetime | None = None,
) -> list[CalendarEvent]:
    """Parse feed bytes into the events falling in the next `days_ahead` days.

    Split out from the HTTP fetch so it can be exercised directly against
    fixture feeds. `now` is injectable to keep recurrence tests deterministic.
    """
    calendar = icalendar.Calendar.from_ical(raw)

    # The feed names itself unless the config overrides it.
    calendar_name = name or str(calendar.get("X-WR-CALNAME") or "") or "Calendar"

    window_start = now or datetime.datetime.now(datetime.timezone.utc)
    window_end = window_start + datetime.timedelta(days=days_ahead)
    occurrences = recurring_ical_events.of(calendar).between(window_start, window_end)

    events: list[CalendarEvent] = []
    for occurrence in occurrences:
        if str(occurrence.get("STATUS", "")).upper() == "CANCELLED":
            continue
        dtstart = occurrence.get("DTSTART")
        if dtstart is None:
            continue
        events.append(CalendarEvent(
            # date -> "YYYY-MM-DD" (all-day), datetime -> ISO 8601. A naive
            # datetime keeps no offset, so the render layer applies the
            # display timezone — as the Calendar API path did.
            start=dtstart.dt.isoformat(),
            title=str(occurrence.get("SUMMARY") or "(no title)"),
            calendar_name=calendar_name,
        ))

    # ISO strings sort chronologically, and a bare date sorts ahead of any
    # time on the same day — so all-day events lead their day.
    events.sort(key=lambda e: e.start)
    return events[:max_results]


def _download(url: str, limit: fetch_budget.RequestLimit) -> bytes:
    response = requests.get(
        url, timeout=(limit.connect_timeout, limit.read_timeout),
        headers={"User-Agent": _USER_AGENT}, stream=True,
    )
    try:
        limit.remaining()
        response.raise_for_status()
        chunks = []
        for chunk in response.iter_content(chunk_size=64 * 1024):
            limit.remaining()
            chunks.append(chunk)
        limit.remaining()
        return b"".join(chunks)
    finally:
        response.close()


class ICSRepository:
    """Fetches one .ics feed. Satisfies the EventRepository protocol."""

    def __init__(self, url: str, name: str = "", timeout: float = DEFAULT_TIMEOUT,
                 *, budget: fetch_budget.FetchBudget | None = None,
                 clock=time.monotonic) -> None:
        self._url = normalize_feed_url(url)
        self._name = name
        self._timeout = timeout
        self._budget = budget
        self._clock = clock

    @property
    def _log_label(self) -> str:
        """A safe label for logs.

        The feed URL embeds a private token and these logs land in the
        systemd journal, so a feed is only ever identified by name and host.
        """
        host = urlsplit(self._url).hostname or "unknown host"
        return f"{self._name or 'feed'} ({host})"

    def fetch_raw(self) -> bytes:
        """Fetch the feed, raising on failure.

        fetch_events deliberately swallows errors so one dead feed cannot
        take the whole render down. Callers that need to *know* whether a
        feed works — onboarding, validating a URL a user just typed — use
        this instead, because "no events" and "unreachable" are different
        answers and an empty calendar is perfectly legitimate.
        """
        limit = (self._budget.request(self._timeout) if self._budget is not None
                 else fetch_budget.RequestLimit(self._timeout, self._clock))
        try:
            return fetch_budget.run_bounded(_download, (self._url,), limit)
        except fetch_budget.FetchFailure as error:
            if error.status is not None:
                response = requests.Response()
                response.status_code = error.status
                raise requests.HTTPError(f"HTTP {error.status}", response=response) from None
            raise

    def fetch_events(self, days_ahead: int, max_results: int) -> list[CalendarEvent]:
        try:
            raw = self.fetch_raw()
        except fetch_budget.BudgetSpent:
            log.warning("Skipping %s: refresh fetch budget exhausted", self._log_label)
            return []
        except Exception as e:
            log.warning("Could not reach %s (%s)", self._log_label, type(e).__name__)
            return []

        try:
            return events_from_ics(
                raw,
                days_ahead=days_ahead,
                max_results=max_results,
                name=self._name,
            )
        except Exception as e:
            log.warning("Could not parse %s (%s)", self._log_label, type(e).__name__)
            return []
