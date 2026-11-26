"""One PiSugar reading for the page."""
from dataclasses import dataclass


@dataclass(frozen=True)
class BatteryStatus:
    """Charge in percent, and whether the pack is taking a charge.

    `charging` is None when that part of the reply could not be read; the
    level is still worth showing. The percent is the server's number
    (pisugar-server answers `battery: 87.5`), not yet rounded for the glass.
    """
    percent: float
    charging: bool | None = None

    def shown_percent(self) -> int:
        """The integer printed next to the mark, half up, clamped to 0..100."""
        clamped = min(100.0, max(0.0, self.percent))
        return int(clamped + 0.5)

    def is_low(self, threshold: float) -> bool:
        """Warn when the percent on the glass is below `threshold`."""
        return self.shown_percent() < threshold
