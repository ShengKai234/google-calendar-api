"""
What the PiSugar's custom button does: `python -m gcal_epd.buttons <action>`.

    double press   refresh   redraw the calendar now

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

# gesture -> action
GESTURES = {"double": "refresh"}


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


ACTIONS = {"refresh": refresh}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a PiSugar button action")
    parser.add_argument("action", choices=sorted(ACTIONS))
    args = parser.parse_args(argv)
    ACTIONS[args.action]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
