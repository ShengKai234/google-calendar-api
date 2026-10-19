"""
Power service for a battery display with a wake-up board (a PiSugar 3).

The Pi is off most of the day. The board's RTC alarm switches it on a few
minutes before each slot of the power schedule; it boots, joins Wi-Fi and
redraws the calendar, and then this sets the alarm for the next wake-up
and powers off. The e-paper keeps its image without power.

Runs at boot as root (deploy/epd-power.service):

    python -m gcal_epd.power_service boot            # clock from RTC, timer drop-in
    python -m gcal_epd.power_service run             # wait for the refresh, then off
    python -m gcal_epd.power_service run --dry-run   # decide, never power off
    python -m gcal_epd.power_service status          # what it sees and would do
    python -m gcal_epd.power_service apply-schedule  # gcal-epd.timer follows the slots

The rules live in domain/power_policy.py, the work in
application/power_service.py; this module is the command line and wiring.
Powering off is refused whenever in doubt (see the policy).
Without a board (none configured, or it does not answer) it does nothing
at all, and the Pi behaves as the always-on display it was before. The
board is picked by [power] board in config.toml (infrastructure/power/boards.py).

To keep a battery Pi on for debugging, create the stay-awake flag on the
boot partition from any computer: an empty file named `epd-stay-awake`.
"""
import argparse
import logging
import sys

from gcal_epd.application.power_service import PowerService
from gcal_epd.config import load_config, power_board, power_timezone, schedule_file
from gcal_epd.infrastructure.power.activity import SystemdActivity
from gcal_epd.infrastructure.power.boards import make_board
from gcal_epd.infrastructure.power.system import System
from gcal_epd.infrastructure.power.timer_dropin import DROPIN, apply_schedule
from gcal_epd.infrastructure.schedule_file import load_schedule

log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Power service for a battery wake-up board")
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="wait for the refresh, set the alarm, power off")
    run_p.add_argument("--dry-run", action="store_true", help="decide, but never power off")
    sub.add_parser("status", help="show the battery, clocks, alarm and decision")
    sub.add_parser("sync-clock", help="set the clock from the RTC, or the RTC from NTP")
    sub.add_parser("apply-schedule", help="make gcal-epd.timer fire at the schedule's slots")
    sub.add_parser("boot", help="sync-clock, then apply-schedule (run at boot)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")  # not at import

    config = load_config()
    tz = power_timezone(config)
    path = schedule_file(config)
    system = System()
    service = PowerService(make_board(power_board(config)), SystemdActivity(system), system,
                           lambda: load_schedule(path), tz)

    if args.command == "status":
        print("\n".join(service.status()))
        return 0
    if args.command in ("sync-clock", "boot"):
        if service.wait_for_board():
            service.sync_clock()
        else:
            log.info("%s does not answer: no RTC to sync with.", service.board.name)
    if args.command in ("apply-schedule", "boot"):
        try:
            apply_schedule(load_schedule(path), tz, system)
        except OSError as e:
            log.error("Could not write %s: %s (run as root)", DROPIN, e)
            return 1
    if args.command == "run":
        service.run(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
