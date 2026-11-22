"""
What the PiSugar's custom button does: `python -m gcal_epd.buttons <action>`.

    single press   privacy   switch between the calendar and the privacy
                             page (date and weather, no events)
    double press   refresh   redraw what is showing now: the calendar, or
                             the privacy page while that is on

pisugar-server notices the press and runs, as root, only
`systemctl start --no-block epd-button@<action>.service`
(deploy/epd-button@.service); that unit runs this module as the app's own
user. Starting a unit that is already running does nothing, so a second
press during an action is absorbed. `power_manager buttons` (run by
install.sh) tells pisugar-server these commands.

The PiSugar's power button is separate and keeps its own job: click and
hold to switch the Pi on, long press to switch it off.
"""
import argparse
import logging
from pathlib import Path

from gcal_epd.infrastructure.panel_lock import PANEL_LOCK, panel_lock

log = logging.getLogger(__name__)

# gesture -> action
GESTURES = {"single": "privacy", "double": "refresh"}


def command(action: str) -> str:
    """What pisugar-server runs for an action: one plain command, since it
    joins words with single spaces and loses any quoting."""
    return f"systemctl start --no-block epd-button@{action}.service"


def commands() -> dict[str, str]:
    """gesture -> the command pisugar-server runs for it."""
    return {gesture: command(action) for gesture, action in GESTURES.items()}


def refresh() -> None:
    """The timer's refresh, without its update check: a press redraws now."""
    from gcal_epd import main as app
    app.main(["--display", "--no-setup"])


def mode_file() -> Path:
    from gcal_epd.config import DATA_DIR
    from gcal_epd.infrastructure.display_mode_file import MODE_FILE
    return DATA_DIR / MODE_FILE


def privacy() -> None:
    """Show the other page, then draw it. A double press never undoes the
    privacy page: only this does.

    The switch takes the panel lock: a refresh looks at the mode and draws
    in one hold of it, so the switch lands before that look or after the
    push, never between them (review 56-1). The redraw takes it again."""
    from gcal_epd.infrastructure import display_mode_file as dm
    path = mode_file()
    with panel_lock(path.parent / PANEL_LOCK):
        page = dm.toggle(path)
    log.info("Button: showing the %s page.", page)
    refresh()


ACTIONS = {"privacy": privacy, "refresh": refresh}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a PiSugar button action")
    parser.add_argument("action", choices=sorted(ACTIONS))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")  # not at import
    ACTIONS[args.action]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
