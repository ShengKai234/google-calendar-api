import argparse
import logging
import tomllib
from pathlib import Path

from googleapiclient.errors import HttpError

from gcal_epd.auth import get_credentials
from gcal_epd.calendar_client import fetch_events
from gcal_epd.render.draw import render

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

# Config is always loaded relative to the project root (two levels above this file)
_PROJECT_ROOT = Path(__file__).parent.parent.parent


def load_config(path: str = "config.toml") -> dict:
    with open(_PROJECT_ROOT / path, "rb") as f:
        return tomllib.load(f)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Google Calendar and render to e-ink display")
    parser.add_argument("--display", action="store_true", help="Push rendered image to e-ink display (Raspberry Pi only)")
    args = parser.parse_args()

    config = load_config()

    creds = get_credentials(
        credentials_file=str(_PROJECT_ROOT / config["auth"]["credentials_file"]),
        token_file=str(_PROJECT_ROOT / config["auth"]["token_file"]),
    )

    try:
        events = fetch_events(
            creds=creds,
            include_access_roles=config["calendar"]["include_access_roles"],
            days_ahead=config["calendar"]["days_ahead"],
            max_results_per_calendar=config["calendar"]["max_results_per_calendar"],
        )

        if not events:
            log.info("No upcoming events found.")
            return

        log.info("\nUpcoming events (next %d days):", config["calendar"]["days_ahead"])
        for event in events:
            log.info("  %s  [%s]  %s", event.start, event.calendar_name, event.title)

        display_cfg = config.get("display", {})
        output_path = str(_PROJECT_ROOT / display_cfg.get("output_path", "preview.png"))
        raw_font = display_cfg.get("font_path", "")
        font_path = str(_PROJECT_ROOT / raw_font) if raw_font and not raw_font.startswith("/") else raw_font

        img = render(events, output_path=output_path, font_path=font_path)
        log.info("Preview saved to %s", output_path)

        if args.display:
            from gcal_epd.epd import push_to_display
            push_to_display(img)

    except HttpError as error:
        log.error("API error: %s", error)


if __name__ == "__main__":
    main()
