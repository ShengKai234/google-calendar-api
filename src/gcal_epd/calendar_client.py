import datetime
import logging
from dataclasses import dataclass

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

log = logging.getLogger(__name__)


@dataclass
class CalendarEvent:
    start: str
    title: str
    calendar_name: str


def fetch_events(
    creds: Credentials,
    include_access_roles: list[str],
    days_ahead: int,
    max_results_per_calendar: int,
) -> list[CalendarEvent]:
    service = build("calendar", "v3", credentials=creds)

    all_calendars = service.calendarList().list().execute().get("items", [])
    selected = [c for c in all_calendars if c.get("accessRole") in include_access_roles]

    log.info("Calendars: %s", [c["summary"] for c in selected])

    now = datetime.datetime.now(datetime.timezone.utc)
    end_time = now + datetime.timedelta(days=days_ahead)

    events: list[CalendarEvent] = []
    for calendar in selected:
        items = (
            service.events()
            .list(
                calendarId=calendar["id"],
                timeMin=now.isoformat(),
                timeMax=end_time.isoformat(),
                maxResults=max_results_per_calendar,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
            .get("items", [])
        )
        for item in items:
            events.append(CalendarEvent(
                start=item["start"].get("dateTime", item["start"].get("date")),
                title=item.get("summary", "(no title)"),
                calendar_name=calendar["summary"],
            ))

    events.sort(key=lambda e: e.start)
    return events
