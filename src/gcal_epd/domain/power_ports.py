"""
What the power manager needs from the hardware and the host, as interfaces.

The power service (application/power_service.py) depends only on these;
the adapters live in infrastructure/power/. A new battery board (Witty Pi,
a Pi 5's own RTC, ...) is a new adapter, with no change to the rules.
"""
from datetime import datetime
from typing import Protocol, runtime_checkable


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
