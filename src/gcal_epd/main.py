"""
Entry point for the calendar: `python -m gcal_epd.main`.

The composition root. It reads the command line, builds the repositories
from config.toml, decides whether this run is setup or a routine refresh,
and hands off to the application layer. The work itself lives elsewhere:
setup in application/setup_service, the refresh in application/
display_service, the feeds file in infrastructure/feeds_file.
"""
import argparse
import logging
import sys

from gcal_epd.application.display_service import run as run_display
from gcal_epd.application.setup_service import apply_pending_feeds, run_onboarding
from gcal_epd.config import DATA_DIR, DEFAULT_FEEDS_FILE, PROJECT_ROOT, feeds_file, load_config
from gcal_epd.infrastructure.feeds_file import load_feeds, pending_feeds_path, reset_feeds
from gcal_epd.infrastructure.ics.repository import ICSRepository
from gcal_epd.infrastructure.open_meteo.repository import OpenMeteoRepository

log = logging.getLogger(__name__)


def _build_event_repos(config: dict) -> list[ICSRepository]:
    repos: list[ICSRepository] = []
    for source in config.get("sources", []):
        if source.get("type") != "ics":
            continue
        feeds_path = DATA_DIR / source.get("feeds_file", DEFAULT_FEEDS_FILE)
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


def _confirm_reset(config: dict, assume_yes: bool = False) -> bool:
    """Confirm, then delete the saved feeds. True if the reset went ahead."""
    feeds_path = feeds_file(config)
    if not feeds_path.exists():
        log.info("Nothing to reset — %s does not exist.", feeds_path.name)
        return True  # fall through to setup anyway

    if not assume_yes:
        if not sys.stdin.isatty():
            log.error(
                "Refusing to reset without confirmation. "
                "Re-run with --yes if you really mean it."
            )
            return False
        answer = input(
            f"Delete {feeds_path.name} and all saved calendar feeds? [y/N] "
        ).strip().lower()
        if answer not in ("y", "yes"):
            return False

    reset_feeds(feeds_path)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch calendar feeds and render to e-ink display"
    )
    parser.add_argument(
        "--display",
        action="store_true",
        help="Push rendered image to e-ink display (Raspberry Pi only)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete saved calendar feeds, then run setup again",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt for --reset",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Serve the calendar setup form even if feeds are already configured",
    )
    parser.add_argument(
        "--no-setup",
        action="store_true",
        help="Never wait on the setup form, even with no feeds (for the timer)",
    )
    args = parser.parse_args()

    # Configured here, not at import, so importing this module (tests, tools)
    # never changes the importer's logging.
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    config = load_config()

    if args.reset and not _confirm_reset(config, assume_yes=args.yes):
        log.info("Reset cancelled — feeds left untouched.")
        return

    # Links typed into the Wi-Fi hotspot form could not be checked offline;
    # check them now, and on failure reopen setup saying why.
    pending_error = ""
    pending = pending_feeds_path(feeds_file(config))
    if pending.exists():
        pending_error = apply_pending_feeds(pending, feeds_file(config))
        if pending_error:
            log.warning("Calendar links from Wi-Fi setup failed: %s", pending_error)

    event_repos = _build_event_repos(config)

    # With no feeds there is nothing to show, so onboarding runs on its own —
    # unless this is the scheduled refresh, which must not wait on a person
    # (its unit has a short timeout; epd-feed-setup.service owns the form).
    needs_setup = (not event_repos or pending_error) and not args.no_setup
    if args.setup or args.reset or needs_setup:
        if run_onboarding(config, push_display=args.display, error=pending_error):
            event_repos = _build_event_repos(config)
        else:
            log.warning("No calendar feeds configured — rendering an empty calendar.")

    run_display(
        event_repos=event_repos,
        weather_repo=_build_weather_repo(config),
        config=config,
        project_root=PROJECT_ROOT,
        push_display=args.display,
        data_dir=DATA_DIR,
    )


if __name__ == "__main__":
    main()
