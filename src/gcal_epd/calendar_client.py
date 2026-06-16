import datetime
import logging
from dataclasses import dataclass

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

log = logging.getLogger(__name__)


@dataclass
class CalendarEvent:
    start: str
    title: str
    calendar_name: str


def fetch_events(
    creds: Credentials,
    calendar_ids: list[str],
    days_ahead: int,
    max_results_per_calendar: int,
) -> list[CalendarEvent]:
    service = build("calendar", "v3", credentials=creds)

    now = datetime.datetime.now(datetime.timezone.utc)
    end_time = now + datetime.timedelta(days=days_ahead)

    events: list[CalendarEvent] = []
    for cal_id in calendar_ids:
        try:
            cal_info = service.calendars().get(calendarId=cal_id).execute()
            calendar_name = cal_info.get("summary", cal_id)

            items = (
                service.events()
                .list(
                    calendarId=cal_id,
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
                    calendar_name=calendar_name,
                ))

        except HttpError as e:
            log.warning("Could not access calendar %s: %s", cal_id, e)

    events.sort(key=lambda e: e.start)
    return events


def check_calendar_access(creds: Credentials, calendar_id: str) -> bool:
    """Return True if the service account can read the given calendar."""
    try:
        service = build("calendar", "v3", credentials=creds)
        service.events().list(calendarId=calendar_id, maxResults=1).execute()
        return True
    except HttpError:
        return False
