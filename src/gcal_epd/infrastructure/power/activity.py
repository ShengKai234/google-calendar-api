"""
What the Pi is busy with, asked of systemd, logind and /proc.

The systemd adapter for ActivityProbe (domain/power_ports.py). The unit
and module names of this app live here, not in the power rules.
"""
import time
from typing import Callable

from gcal_epd.domain.power_ports import Activity
from gcal_epd.infrastructure.power.system import System

# The PiSugar button's actions (deploy/epd-button@.service) redraw the
# panel too: the Pi stays on while one runs, and grace counts from its end.
BUTTON_UNITS = ("epd-button@refresh.service", "epd-button@privacy.service")
REFRESH_UNITS = ("gcal-epd.service", "epd-feed-setup.service") + BUTTON_UNITS
SETUP_UNITS = ("epd-wifi-setup.service",)
UPDATE_UNIT = "epd-update.service"


def classify_processes(argvs: list[list[str]]) -> tuple[str, str]:
    """(setup, refresh) found among running processes, "" for none."""
    setup = refresh = ""
    for argv in argvs:
        if "gcal_epd.wifi_setup" in argv:
            setup = "Wi-Fi setup (gcal_epd.wifi_setup)"
        elif "gcal_epd.main" in argv:
            if "--setup" in argv:
                setup = setup or "calendar setup (gcal_epd.main --setup)"
            else:
                refresh = "a calendar refresh (gcal_epd.main)"
    return setup, refresh


class SystemdActivity:
    def __init__(self, system: System,
                 monotonic: Callable[[], float] = time.monotonic) -> None:
        self.system = system
        self._monotonic = monotonic
        # When a refresh was last seen running. systemd unloads a template
        # instance (epd-button@...) once it ends and nothing refers to it,
        # and its exit time goes with it; the grace then counts from here,
        # at most one poll before the real end.
        self._seen_refreshing: float | None = None

    def activity(self) -> Activity:
        setup = refreshing = queued = ""
        last_end = last_any = None

        def ended(state):
            nonlocal last_any
            if state.last_exit is not None:
                last_any = max(last_any or state.last_exit, state.last_exit)

        for unit in SETUP_UNITS:
            state = self.system.unit_state(unit)
            if state is None:
                setup = f"{unit} (state unknown)"
                continue
            if state.busy:
                setup = unit
            ended(state)
        for unit in REFRESH_UNITS:
            state = self.system.unit_state(unit)
            if state is None:
                refreshing = f"{unit} (state unknown)"
                continue
            if state.busy:
                refreshing = unit
            elif state.queued:
                # Behind the update check, which runs first: about to start.
                queued = queued or unit
            if state.last_exit is not None:
                last_end = max(last_end or state.last_exit, state.last_exit)
            ended(state)
        # Over-the-air updates (installed releases only). Each refresh
        # queues a check that runs before it; while its start job waits in
        # the queue the service is still "inactive".
        state = self.system.unit_state(UPDATE_UNIT)
        updating = ""
        if state is None:
            updating = f"{UPDATE_UNIT} (state unknown)"
        else:
            if state.busy:
                updating = UPDATE_UNIT
            elif state.queued:
                queued = queued or UPDATE_UNIT
            ended(state)
        proc_setup, proc_refresh = classify_processes(self.system.command_lines())
        if refreshing or proc_refresh:
            self._seen_refreshing = self._monotonic()
        if self._seen_refreshing is not None:
            last_end = max(last_end or self._seen_refreshing, self._seen_refreshing)
            last_any = max(last_any or self._seen_refreshing, self._seen_refreshing)
        return Activity(setup=setup or proc_setup,
                        refreshing=refreshing or proc_refresh,
                        ssh_sessions=self.system.remote_sessions(),
                        last_refresh_end=last_end,
                        updating=updating,
                        queued=queued,
                        last_activity_end=last_any)
