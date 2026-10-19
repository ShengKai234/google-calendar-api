"""
What the power manager needs from the hardware and the host, as interfaces.

The power service (application/power_service.py) and the setup forms
depend only on these;
the adapters live in infrastructure/power/. A new battery board (Witty Pi,
a Pi 5's own RTC, ...) is a new adapter, with no change to the rules.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from gcal_epd.domain.power_schedule import PowerSchedule


class WakeBoardError(RuntimeError):
    """The board is unreachable, or refused or failed a request."""


@runtime_checkable
class WakeBoard(Protocol):
    """A board with an RTC that cuts the Pi's power and switches it back on.

    `name` is shown in logs and status. `startup_wait` is how long, in
    seconds, to wait at boot for the board's own service to answer (0 if
    there is nothing to wait for).
    """
    name: str
    startup_wait: float

    def available(self) -> bool:
        """True if the board answers; False means there is no board to manage."""
        ...

    def arm(self, when: datetime) -> None:
        """Set the wake-up alarm for `when` (aware) and read it back.

        Raises WakeBoardError unless the board is verified to wake the Pi
        then: powering off on an alarm that did not take is never undone.
        """
        ...

    def rtc_time(self) -> datetime:
        ...

    def rtc_to_system(self) -> None:
        """Set the system clock from the board's RTC."""
        ...

    def system_to_rtc(self) -> None:
        """Write the system clock to the board's RTC."""
        ...

    def report(self, tz) -> list[tuple[str, str]]:
        """(label, value) lines for `status`: battery, alarm, whatever it has."""
        ...


@dataclass(frozen=True)
class Activity:
    """What the Pi is busy with, as far as powering off is concerned."""
    setup: str = ""                         # a setup that is running, "" if none
    refreshing: str = ""                    # a refresh that is running, "" if none
    ssh_sessions: int | None = 0            # None: cannot tell
    last_refresh_end: float | None = None   # CLOCK_MONOTONIC seconds, None if none


@runtime_checkable
class ActivityProbe(Protocol):
    """Answers "is anyone or anything using the Pi?" (systemd, /proc, logind).

    When it cannot tell, it says so in the answer (a "state unknown"
    setup or refresh, ssh_sessions None): the rules then keep the Pi on.
    """
    def activity(self) -> Activity: ...


@runtime_checkable
class HostControl(Protocol):
    """The operating system's clock state and power switch."""
    def ntp_synchronized(self) -> bool | None: ...

    def poweroff(self) -> bool:
        """Start a clean shutdown; False if it could not be started."""
        ...


@runtime_checkable
class ScheduleStore(Protocol):
    """Where the power schedule is kept (the setup forms write, the service reads)."""
    def load(self) -> PowerSchedule:
        """The saved schedule; the default if there is none or it is unreadable."""
        ...

    def save(self, schedule: PowerSchedule) -> None: ...
