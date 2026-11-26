"""
The battery level for the footer, from pisugar-server (see pisugar.py).

Asked once per refresh: `get battery` ("battery: 87.5") and
`get battery_charging` ("battery_charging: true"). Both share one short
time budget, so a missing or stuck daemon costs the refresh at most about
that long. Anything that goes wrong is one warning and an unknown status:
the calendar is drawn either way.
"""
import logging
import math
import time
from typing import Callable

from gcal_epd.domain.battery import BatteryStatus
from gcal_epd.infrastructure.power.pisugar import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    PiSugar,
    PiSugarError,
    TcpTransport,
)

log = logging.getLogger(__name__)

TIMEOUT = 1.0  # seconds, for both commands together


def read_battery(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 timeout: float = TIMEOUT,
                 clock: Callable[[], float] = time.monotonic) -> BatteryStatus:
    deadline = clock() + timeout

    def send(command: str) -> str:
        left = deadline - clock()
        if left <= 0:
            raise PiSugarError(f"no time left for {command!r}")
        return TcpTransport(host, port, timeout=left)(command)

    sugar = PiSugar(send)
    try:
        percent = sugar.battery()
        charging = sugar.battery_charging()
    except PiSugarError as e:
        log.warning("Battery level unreadable: %s", e)
        return BatteryStatus.unknown()
    if not (math.isfinite(percent) and 0 <= percent <= 100):
        log.warning("Battery level unreadable: %r is not a percentage", percent)
        return BatteryStatus.unknown()
    return BatteryStatus(percent, charging=charging)
