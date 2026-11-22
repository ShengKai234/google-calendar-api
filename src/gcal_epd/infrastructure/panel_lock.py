"""
One process drives the panel at a time.

The timer's refresh, the setup screens and the PiSugar button actions all
draw on the same SPI panel; two at once fail with "GPIO busy". systemd
ordering keeps the units started together apart, but a button press can
come at any moment, so every push takes this lock first.

The lock file lives in the data directory, which both the app's user and
root (the Wi-Fi setup) can write. Whoever comes first creates it; flock
works on a read-only descriptor, so the other can still lock it.
"""
import fcntl
import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

log = logging.getLogger(__name__)

PANEL_LOCK = "panel.lock"
WAIT = 60        # seconds: one full refresh of the panel takes 15-30 s
POLL = 0.5


class PanelBusy(RuntimeError):
    """Another process kept the panel for longer than the wait."""


@contextmanager
def panel_lock(path: Path, wait: float = WAIT,
               clock: Callable[[], float] = time.monotonic,
               sleep: Callable[[float], None] = time.sleep) -> Iterator[None]:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_CREAT, 0o644)
    except OSError as e:
        # Better a drawing that may collide than a panel never drawn.
        log.warning("No panel lock (%s); drawing without it.", e)
        yield
        return
    try:
        deadline = clock() + wait
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if clock() >= deadline:
                    raise PanelBusy(f"the panel was still in use after {wait:.0f} s") from None
                sleep(POLL)
        yield
    finally:
        os.close(fd)  # releases the lock
