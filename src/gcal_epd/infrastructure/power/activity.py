"""
What the Pi is busy with, asked of systemd, logind and /proc.

The systemd adapter for ActivityProbe (domain/power_ports.py). The unit
and module names of this app live here, not in the power rules.
"""
from gcal_epd.domain.power_ports import Activity
from gcal_epd.infrastructure.power.system import System

REFRESH_UNITS = ("gcal-epd.service", "epd-feed-setup.service")
SETUP_UNITS = ("epd-wifi-setup.service",)


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
    def __init__(self, system: System) -> None:
        self.system = system

    def activity(self) -> Activity:
        setup = refreshing = ""
        for unit in SETUP_UNITS:
            state = self.system.unit_state(unit)
            if state is None:
                setup = f"{unit} (state unknown)"
            elif state.busy:
                setup = unit
        last_end = None
        for unit in REFRESH_UNITS:
            state = self.system.unit_state(unit)
            if state is None:
                refreshing = f"{unit} (state unknown)"
                continue
            if state.busy:
                refreshing = unit
            if state.last_exit is not None:
                last_end = max(last_end or state.last_exit, state.last_exit)
        proc_setup, proc_refresh = classify_processes(self.system.command_lines())
        return Activity(setup=setup or proc_setup,
                        refreshing=refreshing or proc_refresh,
                        ssh_sessions=self.system.remote_sessions(),
                        last_refresh_end=last_end)
