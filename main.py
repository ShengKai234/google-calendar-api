import logging
import tomllib

from googleapiclient.errors import HttpError

from auth import get_credentials
from calendar_client import fetch_events

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


def load_config(path: str = "config.toml") -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def main() -> None:
    config = load_config()

    creds = get_credentials(
        credentials_file=config["auth"]["credentials_file"],
        token_file=config["auth"]["token_file"],
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
            print(f"  {event.start}  [{event.calendar_name}]  {event.title}")

    except HttpError as error:
        log.error("API error: %s", error)


if __name__ == "__main__":
    main()
