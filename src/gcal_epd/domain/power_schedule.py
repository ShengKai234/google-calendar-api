"""
When the display is awake: the daily slots of a battery-powered Pi.

To save power the Pi is off most of the day. A PiSugar 3 cuts its power and
turns it back on from its RTC alarm. Each slot is a wall-clock time by which
the panel should show a fresh calendar, so the Pi is woken
`wake_lead_minutes` earlier: enough to boot, join Wi-Fi, fetch and redraw.

Shared by the power manager (sets the alarm) and the setup forms (edit the
slots); neither imports the other.
"""
from dataclasses import dataclass
from datetime import datetime, time, timedelta

DEFAULT_SLOTS = (time(7, 0), time(19, 0))
DEFAULT_WAKE_LEAD = 5   # minutes before a slot; a Zero boots, joins and draws in ~3
MAX_WAKE_LEAD = 60
MAX_SLOTS = 8
MIN_GAP = 30            # minutes between slots, so one wake-up ends before the next


def parse_slot(text: str) -> time:
    """"07:30" -> time(7, 30). Raises ValueError with a message for the form."""
    raw = text.strip()
    hours, sep, minutes = raw.partition(":")
    if not sep or not hours.isdigit() or not minutes.isdigit() or len(minutes) != 2:
        raise ValueError(f"{raw or 'An empty time'} is not a time like 07:00")
    h, m = int(hours), int(minutes)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"{raw} is not a time of day")
    return time(h, m)


def format_slot(slot: time) -> str:
    return f"{slot.hour:02d}:{slot.minute:02d}"


def _minutes(slot: time) -> int:
    return slot.hour * 60 + slot.minute


@dataclass(frozen=True)
class PowerSchedule:
    slots: tuple[time, ...] = DEFAULT_SLOTS
    enabled: bool = True
    wake_lead_minutes: int = DEFAULT_WAKE_LEAD

    def __post_init__(self) -> None:
        slots = tuple(sorted(time(s.hour, s.minute) for s in self.slots))
        if not 1 <= len(slots) <= MAX_SLOTS:
            raise ValueError(f"Set between 1 and {MAX_SLOTS} times")
        mins = [_minutes(s) for s in slots]
        # Gaps around the clock, including last slot -> first slot tomorrow.
        gaps = [b - a for a, b in zip(mins, mins[1:])] + [mins[0] + 1440 - mins[-1]]
        if len(slots) > 1 and min(gaps) < MIN_GAP:
            raise ValueError(f"Times must be at least {MIN_GAP} minutes apart")
        if not 0 <= self.wake_lead_minutes <= MAX_WAKE_LEAD:
            raise ValueError(f"Wake-up lead must be 0-{MAX_WAKE_LEAD} minutes")
        object.__setattr__(self, "slots", slots)

    @property
    def lead(self) -> timedelta:
        return timedelta(minutes=self.wake_lead_minutes)

    def next_slot(self, now: datetime) -> datetime:
        """The first slot strictly after `now`, in `now`'s timezone (aware)."""
        return min(self._candidates(now, timedelta(0)))

    def next_wake(self, now: datetime) -> datetime:
        """When to power the Pi on next: the next slot minus the lead.

        Strictly after `now`, so a Pi woken for 06:55 that is still up at
        06:56 gets tomorrow's or the evening's wake-up, not its own.
        """
        return min(self._candidates(now, self.lead))

    def _candidates(self, now: datetime, lead: timedelta) -> list[datetime]:
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        out = []
        for days in range(3):  # today, tomorrow, and tomorrow's lead wrap
            day = (now + timedelta(days=days)).date()
            for slot in self.slots:
                when = datetime.combine(day, slot, tzinfo=now.tzinfo) - lead
                if when > now:
                    out.append(when)
        return out
