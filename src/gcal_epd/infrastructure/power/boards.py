"""
Which wake-up board this Pi has, from [power] board in config.toml.

    board = "auto"      # the PiSugar 3 if pisugar-server is installed, else none
    board = "pisugar3"
    board = "none"      # mains power: always on, the timer refreshes

A new board is one adapter implementing WakeBoard (domain/power_ports.py)
and one entry in BOARDS.
"""
import shutil
from datetime import datetime
from typing import Callable

from gcal_epd.domain.power_ports import WakeBoard, WakeBoardError
from gcal_epd.infrastructure.power.pisugar import PiSugar3Board

DEFAULT_BOARD = "auto"


class NullBoard:
    """No board: nothing can switch the Pi back on, so it never powers off."""
    name = "no wake-up board"
    startup_wait = 0

    def available(self) -> bool:
        return False

    def arm(self, when: datetime) -> None:
        raise WakeBoardError("there is no wake-up board")

    def rtc_time(self) -> datetime:
        raise WakeBoardError("there is no RTC")

    def rtc_to_system(self) -> None:
        raise WakeBoardError("there is no RTC")

    def system_to_rtc(self) -> None:
        raise WakeBoardError("there is no RTC")

    def report(self, tz) -> list[tuple[str, str]]:
        return []


def _pisugar3(which: Callable[[str], str | None]) -> WakeBoard:
    # Not installed: do not hold up Wi-Fi setup at every boot waiting for it.
    return PiSugar3Board(startup_wait=15 if which("pisugar-server") else 0)


def _auto(which: Callable[[str], str | None]) -> WakeBoard:
    return _pisugar3(which) if which("pisugar-server") else NullBoard()


BOARDS: dict[str, Callable[[Callable[[str], str | None]], WakeBoard]] = {
    "auto": _auto,
    "pisugar3": _pisugar3,
    "none": lambda which: NullBoard(),
}


def make_board(name: str = DEFAULT_BOARD,
               which: Callable[[str], str | None] = shutil.which) -> WakeBoard:
    try:
        factory = BOARDS[name]
    except KeyError:
        raise ValueError(f"Unknown [power] board {name!r}; "
                         f"choose one of {', '.join(BOARDS)}") from None
    return factory(which)
