"""An in-memory pisugar-server speaking the same text protocol as the real one.

Replies follow pisugar-server/src/cmds.rs: "<name>: <value>", "<name>: done",
or "<name>: <error>". The PiSugar 3 alarm keeps only a UTC time of day.
"""
from datetime import datetime, timedelta, timezone

from gcal_epd.infrastructure.power.pisugar import PiSugarError

UTC = timezone.utc


class FakePiSugarServer:
    def __init__(self, *, up=True, battery=87.5, plugged=False,
                 rtc=datetime(2026, 10, 19, 22, 55, 3, tzinfo=UTC), server_offset=8):
        self.up = up
        self.battery = battery
        self.plugged = plugged
        self.rtc = rtc
        self.offset = timezone(timedelta(hours=server_offset))  # the Pi's local zone
        self.alarm = (0, 0, 0)          # UTC h, m, s
        self.alarm_enabled = False
        self.repeat = 0
        self.auto_power_on = False
        self.drop_alarm = False         # accept rtc_alarm_set but store nothing
        self.errors: dict[str, str] = {}  # command name -> error text
        self.commands: list[str] = []
        self.system_time_set = None

    def __call__(self, command: str) -> str:
        if not self.up:
            raise PiSugarError("pisugar-server at 127.0.0.1:8423 is not reachable: refused")
        self.commands.append(command)
        parts = command.split(" ")
        if parts[0] == "get":
            name = parts[1]
            if name in self.errors:
                return f"{name}: {self.errors[name]}"
            return f"{name}: {self._get(name)}"
        name = parts[0]
        if name in self.errors:
            return f"{name}: {self.errors[name]}"
        if name == "rtc_alarm_set":
            if len(parts) != 3:
                return "error: the following required arguments were not provided\n" \
                       "Hint: use 'help rtc_alarm_set' for usage"
            if self.auto_power_on:
                return f"{name}: auto_power_on is in conflict with alarm function"
            when = datetime.fromisoformat(parts[1]).astimezone(UTC)
            if not self.drop_alarm:
                self.alarm = (when.hour, when.minute, when.second)
                self.alarm_enabled = True
                self.repeat = int(parts[2])
            return f"{name}: done"
        if name == "rtc_pi2rtc":
            return f"{name}: done"
        if name == "rtc_rtc2pi":
            self.system_time_set = self.rtc
            return f"{name}: done"
        return f"error: unrecognized subcommand '{name}'\nHint: use 'help'"

    def _get(self, name: str) -> str:
        if name == "model":
            return "PiSugar 3"
        if name == "battery":
            return str(self.battery)
        if name == "battery_power_plugged":
            return "true" if self.plugged else "false"
        if name == "rtc_time":
            return self.rtc.astimezone(self.offset).isoformat(timespec="milliseconds")
        if name == "rtc_alarm_time":
            h, m, s = self.alarm
            # The date is a placeholder (2000-01-01 in pisugar-core), shown in local time.
            return datetime(2000, 1, 1, h, m, s, tzinfo=UTC).astimezone(self.offset) \
                .isoformat(timespec="milliseconds")
        if name == "rtc_alarm_enabled":
            return "true" if self.alarm_enabled else "false"
        if name == "alarm_repeat":
            return str(self.repeat)
        return "unknown"
