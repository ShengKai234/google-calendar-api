import argparse
import logging
import tomllib
from pathlib import Path

from gcal_epd.application.display_service import run as run_display
from gcal_epd.infrastructure.ics.repository import ICSRepository
from gcal_epd.infrastructure.open_meteo.repository import OpenMeteoRepository

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_EXAMPLE_FEEDS = "ics_feeds.example.toml"


def load_config(path: str = "config.toml") -> dict:
    with open(_PROJECT_ROOT / path, "rb") as f:
        return tomllib.load(f)


def load_feeds(feeds_path: Path) -> list[dict]:
    """Read feed definitions from the gitignored feeds file.

    Feed URLs are bearer tokens, so they live outside the tracked config
    rather than in config.toml.
    """
    try:
        with open(feeds_path, "rb") as f:
            return tomllib.load(f).get("feed", [])
    except FileNotFoundError:
        log.error(
            "Calendar feed file not found: %s\n"
            "Copy %s to %s and fill in your feed URLs.",
            feeds_path.name, _EXAMPLE_FEEDS, feeds_path.name,
        )
        return []
    except tomllib.TOMLDecodeError as e:
        log.error("Could not parse %s: %s", feeds_path.name, e)
        return []


def _build_event_repos(config: dict) -> list[ICSRepository]:
    repos: list[ICSRepository] = []
    for source in config.get("sources", []):
        if source.get("type") != "ics":
            continue
        feeds_path = _PROJECT_ROOT / source.get("feeds_file", "ics_feeds.toml")
        for feed in load_feeds(feeds_path):
            url = feed.get("url", "")
            if not url:
                log.warning("Skipping feed with no url: %s", feed.get("name", "(unnamed)"))
                continue
            repos.append(ICSRepository(url=url, name=feed.get("name", "")))
    return repos


def _build_weather_repo(config: dict) -> OpenMeteoRepository | None:
    for source in config.get("sources", []):
        if source.get("type") == "open_meteo":
            return OpenMeteoRepository(
                latitude=source["latitude"],
                longitude=source["longitude"],
                location=source.get("location", "Taipei"),
            )
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch calendar feeds and render to e-ink display"
    )
    parser.add_argument(
        "--display",
        action="store_true",
        help="Push rendered image to e-ink display (Raspberry Pi only)",
    )
    args = parser.parse_args()

    config = load_config()
    event_repos = _build_event_repos(config)
    if not event_repos:
        log.warning("No calendar feeds configured — rendering an empty calendar.")

    run_display(
        event_repos=event_repos,
        weather_repo=_build_weather_repo(config),
        config=config,
        project_root=_PROJECT_ROOT,
        push_display=args.display,
    )


if __name__ == "__main__":
    main()
