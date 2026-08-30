from dataclasses import dataclass


@dataclass
class CalendarEvent:
    start: str
    title: str
    calendar_name: str
