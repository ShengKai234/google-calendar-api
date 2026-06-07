"""
Display constants and layout calculation.
Produces structured data (DayBlock / EventRow) from raw CalendarEvent list.
No Pillow dependency — pure geometry and data.
"""
import datetime
from collections import defaultdict
from dataclasses import dataclass, field

from gcal_epd.calendar_client import CalendarEvent

# --- Display geometry ---
WIDTH = 800
HEIGHT = 480
HEADER_H = 72
DAY_LABEL_H = 30
EVENT_H = 38
PADDING = 14

# --- Waveshare 7.3" F 7-color palette ---
PALETTE: dict[str, tuple[int, int, int]] = {
    "black":  (0,   0,   0),
    "white":  (255, 255, 255),
    "green":  (0,   160, 80),
    "blue":   (30,  80,  200),
    "red":    (200, 40,  40),
    "yellow": (210, 170, 0),
    "orange": (220, 110, 0),
}

ACCENT_COLORS: list[tuple[int, int, int]] = [
    PALETTE["blue"],
    PALETTE["green"],
    PALETTE["red"],
    PALETTE["orange"],
    PALETTE["yellow"],
]


@dataclass
class EventRow:
    y: int
    time_str: str
    title: str
    calendar_name: str
    accent_color: tuple[int, int, int]


@dataclass
class DayBlock:
    y: int
    label: str
    label_color: tuple[int, int, int]
    rows: list[EventRow] = field(default_factory=list)


def _parse_start(start_str: str) -> tuple[datetime.date, str]:
    if "T" in start_str:
        dt = datetime.datetime.fromisoformat(start_str)
        return dt.date(), dt.strftime("%H:%M")
    return datetime.date.fromisoformat(start_str), ""


def _assign_cal_colors(events: list[CalendarEvent]) -> dict[str, tuple[int, int, int]]:
    names = list(dict.fromkeys(e.calendar_name for e in events))
    return {name: ACCENT_COLORS[i % len(ACCENT_COLORS)] for i, name in enumerate(names)}


def build_layout(events: list[CalendarEvent]) -> list[DayBlock]:
    today = datetime.date.today()
    cal_color = _assign_cal_colors(events)

    by_day: defaultdict[datetime.date, list[tuple[str, CalendarEvent]]] = defaultdict(list)
    for event in events:
        date, time_str = _parse_start(event.start)
        by_day[date].append((time_str, event))

    blocks: list[DayBlock] = []
    y = HEADER_H + 10

    for date in sorted(by_day.keys()):
        if y + DAY_LABEL_H > HEIGHT:
            break

        if date == today:
            label, label_color = "Today", PALETTE["red"]
        elif date == today + datetime.timedelta(days=1):
            label, label_color = "Tomorrow", PALETTE["blue"]
        else:
            label, label_color = date.strftime("%A, %-d %b"), PALETTE["black"]

        block = DayBlock(y=y, label=label, label_color=label_color)
        y += DAY_LABEL_H

        for time_str, event in by_day[date]:
            if y + EVENT_H > HEIGHT:
                break
            block.rows.append(EventRow(
                y=y,
                time_str=time_str if time_str else "All day",
                title=event.title,
                calendar_name=event.calendar_name,
                accent_color=cal_color.get(event.calendar_name, PALETTE["black"]),
            ))
            y += EVENT_H

        blocks.append(block)
        y += 8

    return blocks
