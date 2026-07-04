import argparse
import logging
import tomllib
from pathlib import Path

from googleapiclient.errors import HttpError

from gcal_epd.infrastructure.google_calendar.auth import get_credentials
from gcal_epd.infrastructure.google_calendar.repository import GoogleCalendarRepository
from gcal_epd.infrastructure.open_meteo.repository import OpenMeteoRepository
from gcal_epd.application.display_service import run as run_display

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent.parent


def load_config(path: str = "config.toml") -> dict:
    with open(_PROJECT_ROOT / path, "rb") as f:
        return tomllib.load(f)


def _build_event_repos(config: dict) -> list[GoogleCalendarRepository]:
    repos = []
    for source in config.get("sources", []):
        if source["type"] == "google_calendar":
            sa_file = str(_PROJECT_ROOT / source["service_account_file"])
            creds = get_credentials(sa_file)
            repos.append(GoogleCalendarRepository(creds, source.get("calendar_ids", [])))
    return repos


def _build_weather_repo(config: dict) -> OpenMeteoRepository | None:
    for source in config.get("sources", []):
        if source["type"] == "open_meteo":
            return OpenMeteoRepository(
                latitude=source["latitude"],
                longitude=source["longitude"],
                location=source.get("location", "Taipei"),
            )
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Google Calendar and render to e-ink display")
    parser.add_argument("--display", action="store_true", help="Push rendered image to e-ink display (Raspberry Pi only)")
    parser.add_argument("--setup", action="store_true", help="Run one-time calendar sharing setup")
    parser.add_argument("--email", help="Google Calendar email to use during setup (skips interactive prompt)")
    args = parser.parse_args()

    config = load_config()
    config_path = _PROJECT_ROOT / "config.toml"

    gcal_sources = [s for s in config.get("sources", []) if s["type"] == "google_calendar"]
    calendar_ids = [cid for s in gcal_sources for cid in s.get("calendar_ids", [])]

    if args.setup or not calendar_ids:
        from gcal_epd.infrastructure.google_calendar.setup import run_setup
        run_setup(config, config_path, display=args.display, email=args.email)
        config = load_config()

    try:
        event_repos = _build_event_repos(config)
        weather_repo = _build_weather_repo(config)
        run_display(
            event_repos=event_repos,
            weather_repo=weather_repo,
            config=config,
            project_root=_PROJECT_ROOT,
            push_display=args.display,
        )
    except HttpError as error:
        log.error("API error: %s", error)


if __name__ == "__main__":
    main()
