"""
When a battery display may power off: the rules, as one pure function.

The power service (application/power_service.py) gathers a Snapshot of
the Pi and asks decide(); nothing here touches the hardware, so every rule
is tested on its own (tests/domain/test_power_policy.py).

Powering off is the risky step, so it is refused whenever in doubt: a
person may be setting the display up or logged in, a refresh may be
drawing. The alarm itself is checked by the service before it powers off.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

from gcal_epd.domain.power_schedule import PowerSchedule

GRACE = 120            # seconds to stay up after the refresh, for a quick SSH check
AWAKE_CAP = 900        # give up on a refresh this long after waking, to save battery
MIN_OFF = 180          # never power off for a wake-up closer than this: shutdown
                       # takes ~30 s on a Zero, and a missed alarm waits a day


def _hm(when: datetime) -> str:
    return when.strftime("%H:%M")


@dataclass(frozen=True)
class Snapshot:
    """Everything the decision depends on, gathered at one moment."""
    now: datetime                 # aware, in the schedule's timezone
    boot: datetime                # when this boot began
    schedule: PowerSchedule
    board: bool = True            # the wake-up board answers
    stay_awake: bool = False      # the flag file exists
    setup: str = ""               # a setup that is running, "" if none
    refreshing: str = ""          # a refresh that is running, "" if none
    ssh_sessions: int | None = 0  # None: cannot tell
    last_refresh: datetime | None = None  # when a refresh last finished


@dataclass(frozen=True)
class Decision:
    power_off: bool
    reason: str
    final: bool = False  # nothing to manage on this Pi: stop watching


def decide(s: Snapshot) -> Decision:
    """Whether to power off now, and why. Pure, so every rule is testable.

    The reasons to stay on come first, in order of who would be hurt: no
    board (nothing could switch the Pi back on), the user's choices, a
    person at the display, a refresh drawing. Only then the timing.
    """
    if not s.board:
        return Decision(False, "no wake-up board answers: nothing could switch "
                               "this Pi back on, so it stays always on", final=True)
    if not s.schedule.enabled:
        return Decision(False, "the power schedule is turned off")
    if s.stay_awake:
        return Decision(False, "the stay-awake flag exists")
    if s.setup:
        return Decision(False, f"{s.setup} is running: someone is setting up")
    if s.ssh_sessions is None:
        return Decision(False, "cannot tell whether someone is logged in over SSH")
    if s.ssh_sessions:
        return Decision(False, f"{s.ssh_sessions} SSH session(s) open")
    if s.refreshing:
        return Decision(False, f"{s.refreshing} is running")

    schedule, now = s.schedule, s.now
    wake = schedule.next_wake(now)
    if wake - now < timedelta(seconds=MIN_OFF):
        return Decision(False, f"the next wake-up ({_hm(wake)}) is too close to power "
                               f"off for; staying on for that refresh")

    # Inside a wake-up window (between a wake-up and its slot) the refresh
    # must be one for this slot: one that ended after the window opened.
    # Outside, any refresh since boot will do.
    slot = schedule.next_slot(now)
    in_window = schedule.lead and slot - now <= schedule.lead
    required = max(s.boot, slot - schedule.lead) if in_window else s.boot
    deadline = required + timedelta(seconds=AWAKE_CAP)
    if in_window:
        deadline = max(deadline, slot)  # never give up before the timer's refresh

    if s.last_refresh is not None and s.last_refresh >= required:
        done = s.last_refresh + timedelta(seconds=GRACE)
        if now >= done:
            return Decision(True, f"the refresh finished at {_hm(s.last_refresh)}")
        return Decision(False, f"the refresh finished; grace period until {_hm(done)}")
    if now >= deadline:
        return Decision(True, f"no refresh finished since {_hm(required)}; "
                              f"giving up to save the battery")
    return Decision(False, f"waiting for the refresh (gives up at {_hm(deadline)})")
