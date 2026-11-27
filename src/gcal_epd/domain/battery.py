"""The PiSugar's charge, as the footer shows it."""
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class BatteryStatus:
    """`percent` is None when the battery could not be read."""
    percent: float | None
    charging: bool = False

    @classmethod
    def unknown(cls) -> "BatteryStatus":
        return cls(None)

    @property
    def known(self) -> bool:
        return self.percent is not None

    @property
    def shown_percent(self) -> int | None:
        """The whole number on the panel, rounded half up (87.5 -> 88)."""
        return None if self.percent is None else math.floor(self.percent + 0.5)

    def is_low(self, threshold: int) -> bool:
        """Below `threshold` as shown, so the colour always matches the number."""
        return self.known and self.shown_percent < threshold
