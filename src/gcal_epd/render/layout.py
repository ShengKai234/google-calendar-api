"""
Display constants and layout calculation.
Produces structured data (EventRow) from raw CalendarEvent list.
No Pillow dependency — pure geometry and data.
"""
import datetime
from collections import defaultdict
from dataclasses import dataclass

from gcal_epd.domain.event import CalendarEvent

TW_TZ = datetime.timezone(datetime.timedelta(hours=8))

# --- Display geometry ---
WIDTH = 800
HEIGHT = 480
PADDING = 14

HEADER_H = 86        # height of the bordered header card
HEADER_GAP = 8       # gap between header card and the first event row
ROW_H = 34           # one event row
DAY_GAP = 14         # extra space inserted between two different days
FOOTER_H = 28        # reserved strip for the "last updated" line
UNDERLINE_DROP = 14  # title underline offset below the row's vertical centre

# Column origins for the three-column event table
COL_DATE_X = PADDING + 8
COL_TIME_X = 178
COL_TITLE_X = 272

# First row sits below the header card; last row must clear the footer
CONTENT_TOP = PADDING + HEADER_H + HEADER_GAP
CONTENT_BOTTOM = HEIGHT - FOOTER_H

# --- Waveshare 7.3" F 7-color palette ---
# The panel can only show these seven solid colors — there is no grey, so
# visual hierarchy comes from size and weight rather than tint.
PALETTE: dict[str, tuple[int, int, int]] = {
    "black":  (0,   0,   0),
    "white":  (255, 255, 255),
    "green":  (0,   160, 80),
    "blue":   (30,  80,  200),
    "red":    (200, 40,  40),
    "yellow": (210, 170, 0),
    "orange": (220, 110, 0),
}

# --- Semantic roles for the dark theme ---
BG = PALETTE["black"]
FG = PALETTE["white"]
ACCENT = PALETTE["blue"]

# Weekday names, Monday-first to match date.weekday(). Spelled out rather than
# taken from strftime so the panel reads the same whatever locale the Pi has.
WEEKDAY_ABBR = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
WEEKDAY_FULL = [
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
]

ALL_DAY_LABEL = "All day"


@dataclass
class EventRow:
    y: int
    date_str: str
    time_str: str
    title: str


def format_date(date: datetime.date) -> str:
    """08/30 (Sat)"""
    return f"{date.month:02d}/{date.day:02d} ({WEEKDAY_ABBR[date.weekday()]})"


def format_weekday(date: datetime.date) -> str:
    """Saturday"""
    return WEEKDAY_FULL[date.weekday()]


def _parse_start(start_str: str) -> tuple[datetime.date, str]:
    if "T" in start_str:
        dt = datetime.datetime.fromisoformat(start_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TW_TZ)
        else:
            dt = dt.astimezone(TW_TZ)
        return dt.date(), dt.strftime("%H:%M")
    return datetime.date.fromisoformat(start_str), ""


def build_layout(events: list[CalendarEvent]) -> list[EventRow]:
    """Flatten events into positioned rows, grouped by day with a gap between days."""
    by_day: defaultdict[datetime.date, list[tuple[str, CalendarEvent]]] = defaultdict(list)
    for event in events:
        date, time_str = _parse_start(event.start)
        by_day[date].append((time_str, event))

    rows: list[EventRow] = []
    y = CONTENT_TOP

    for i, date in enumerate(sorted(by_day.keys())):
        if i > 0:
            y += DAY_GAP

        # All-day events (no time) sort ahead of timed ones within the same day.
        for time_str, event in sorted(by_day[date], key=lambda pair: pair[0]):
            if y + ROW_H > CONTENT_BOTTOM:
                return rows
            rows.append(EventRow(
                y=y,
                date_str=format_date(date),
                time_str=time_str if time_str else ALL_DAY_LABEL,
                title=event.title,
            ))
            y += ROW_H

    return rows
