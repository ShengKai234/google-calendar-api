import datetime
import logging

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.service_account import Credentials

from gcal_epd.domain.event import CalendarEvent

log = logging.getLogger(__name__)


class GoogleCalendarRepository:
    def __init__(self, creds: Credentials, calendar_ids: list[str]) -> None:
        self._creds = creds
        self._calendar_ids = calendar_ids

    def fetch_events(self, days_ahead: int, max_results: int) -> list[CalendarEvent]:
        service = build("calendar", "v3", credentials=self._creds)
        now = datetime.datetime.now(datetime.timezone.utc)
        end_time = now + datetime.timedelta(days=days_ahead)

        events: list[CalendarEvent] = []
        for cal_id in self._calendar_ids:
            try:
                cal_info = service.calendars().get(calendarId=cal_id).execute()
                calendar_name = cal_info.get("summary", cal_id)
                items = (
                    service.events()
                    .list(
                        calendarId=cal_id,
                        timeMin=now.isoformat(),
                        timeMax=end_time.isoformat(),
                        maxResults=max_results,
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

    def check_access(self, calendar_id: str) -> bool:
        try:
            service = build("calendar", "v3", credentials=self._creds)
            service.events().list(calendarId=calendar_id, maxResults=1).execute()
            return True
        except HttpError:
            return False
