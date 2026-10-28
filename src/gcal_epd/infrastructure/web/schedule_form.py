"""
The wake-up times section of a setup form, shared by both forms.

The calendar setup form (onboarding/server.py, on the LAN) and the Wi-Fi
hotspot form (wifi/server.py) render, parse and save it the same way.
A settings page or an "Add time" button changes only this module.
"""
import logging
from dataclasses import dataclass
from html import escape

from gcal_epd.domain.power_ports import ScheduleStore
from gcal_epd.domain.power_schedule import PowerSchedule, format_slot, parse_slot

log = logging.getLogger(__name__)


_SCHEDULE_HTML = """<fieldset class="wake"><legend>Display wake-up times</legend>
<input type="hidden" name="schedule" value="1">
<div class="slots">{inputs}</div>
<label class="check"><input type="checkbox" name="enabled" value="1"{checked}>
Turn off between updates to save battery</label>
<small>The display wakes a few minutes before each time to refresh the
calendar, and is off in between.</small></fieldset>"""


@dataclass
class ScheduleFields:
    """The wake-up section of a form: the times as typed, and the checkbox.

    Every time input shares the field name "slot", and any number of them
    is accepted (blanks ignored), so adding an "Add time" button later is
    a page-only change. The hidden "schedule" field marks a form that has
    the section: without it, an unticked checkbox and a missing section
    would look the same.
    """
    slots: list[str]
    enabled: bool

    @classmethod
    def of(cls, schedule: PowerSchedule) -> "ScheduleFields":
        return cls([format_slot(s) for s in schedule.slots], schedule.enabled)

    @classmethod
    def from_form(cls, form: dict[str, list[str]]) -> "ScheduleFields | None":
        """The section as submitted, or None if the form had none."""
        if "schedule" not in form:
            return None
        return cls([s.strip() for s in form.get("slot", [])], "enabled" in form)

    def to_schedule(self, current: PowerSchedule) -> PowerSchedule:
        """Raise ValueError, with a message for the form, if the times are wrong.

        The wake-up lead is not on the form, so it is kept from `current`.
        """
        return PowerSchedule(slots=tuple(parse_slot(s) for s in self.slots if s),
                             enabled=self.enabled,
                             wake_lead_minutes=current.wake_lead_minutes)

    def html(self) -> str:
        slots = self.slots or [""]  # always somewhere to type a time
        inputs = "".join(
            f'<input type="time" name="slot" aria-label="Wake-up time {i}"'
            f' value="{escape(s)}">' for i, s in enumerate(slots, 1))
        return _SCHEDULE_HTML.format(inputs=inputs,
                                     checked=" checked" if self.enabled else "")


# Rules for the section above, for the <style> of a page that shows it.
SCHEDULE_CSS = """fieldset.wake{border:1px solid #8888;border-radius:8px;margin:1.5rem 0 0;
padding:.4rem 1rem 1rem}
legend{font-weight:600;padding:0 .3rem}
.slots{display:flex;flex-wrap:wrap;gap:.5rem;margin-top:.3rem}
.slots input{flex:1 1 7rem;width:auto}
label.check{display:flex;gap:.5rem;align-items:center;font-weight:400}
label.check input{width:auto;margin:0}"""


def save_schedule_safely(store: ScheduleStore, schedule: PowerSchedule) -> bool:
    """Save the times; a failure is logged, never fatal to the rest of setup."""
    try:
        store.save(schedule)
    except Exception as e:  # a full disk, a broken config.toml
        log.warning("Could not save the wake-up times: %s", e)
        return False
    log.info("Saved wake-up times %s (%s).",
             ", ".join(format_slot(s) for s in schedule.slots),
             "power off between" if schedule.enabled else "always on")
    return True
