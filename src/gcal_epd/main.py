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
from typing import Callable

from gcal_epd.application.display_service import run as run_display
from gcal_epd.application.setup_service import apply_pending_feeds, run_onboarding
from gcal_epd.config import (
    DATA_DIR,
    DEFAULT_FEEDS_FILE,
    PROJECT_ROOT,
    feeds_file,
    load_config,
    power_board,
)
from gcal_epd.infrastructure.display_mode_file import MODE_FILE, PRIVACY, load_mode
from gcal_epd.infrastructure.fetch_budget import FetchBudget
from gcal_epd.infrastructure.feeds_file import load_feeds, pending_feeds_path, reset_feeds
from gcal_epd.infrastructure.ics.repository import ICSRepository
from gcal_epd.infrastructure.open_meteo.repository import OpenMeteoRepository
from gcal_epd.infrastructure.power.battery import read_battery
from gcal_epd.version import version

log = logging.getLogger(__name__)


def _build_event_repos(config: dict, budget: FetchBudget | None = None,
                       is_private: Callable[[], bool] | None = None) -> list[ICSRepository]:
    """One repository per feed. While `is_private()` (the privacy page is
    on), a bad feed is logged without its calendar's name; each feed asks
    again when it logs, since a press may land mid-download."""
    private = is_private or (lambda: False)
    repos: list[ICSRepository] = []
    for source in config.get("sources", []):
        if source.get("type") != "ics":
            continue
        feeds_path = DATA_DIR / source.get("feeds_file", DEFAULT_FEEDS_FILE)
        for feed in load_feeds(feeds_path):
            url = feed.get("url", "")
            if not url:
                log.warning("Skipping feed with no url: %s",
                            "(name hidden: privacy page)" if private()
                            else feed.get("name", "(unnamed)"))
                continue
            repos.append(ICSRepository(url=url, name=feed.get("name", ""), budget=budget,
                                       hide_name=is_private))
    return repos


def _build_weather_repo(config: dict, budget: FetchBudget | None = None) -> OpenMeteoRepository | None:
    for source in config.get("sources", []):
        if source.get("type") == "open_meteo":
            return OpenMeteoRepository(
                latitude=source["latitude"],
                longitude=source["longitude"],
                location=source.get("location", "Taipei"),
                budget=budget,
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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Fetch calendar feeds and render to e-ink display"
    )
    parser.add_argument("--version", action="version", version=f"gcal-epd {version()}")
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
    args = parser.parse_args(argv)

    # Configured here, not at import, so importing this module (tests, tools)
    # never changes the importer's logging.
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    log.info("gcal-epd %s", version())
    config = load_config()
    # The privacy page (PiSugar button, single press): no events are fetched
    # or drawn, and calendar names stay out of the log.
    mode_file = DATA_DIR / MODE_FILE

    def is_private() -> bool:
        return load_mode(mode_file) == PRIVACY

    privacy = is_private()

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

    event_repos = _build_event_repos(config, is_private=is_private)

    # With no feeds there is nothing to show, so onboarding runs on its own —
    # unless this is the scheduled refresh, which must not wait on a person
    # (its unit has a short timeout; epd-feed-setup.service owns the form).
    needs_setup = (not event_repos or pending_error) and not args.no_setup
    if args.setup or args.reset or needs_setup:
        if not run_onboarding(config, push_display=args.display, error=pending_error):
            log.warning("No calendar feeds configured — rendering an empty calendar.")

    # Start only after onboarding/validation; time spent on a form is not
    # part of the calendar + weather fetch allowance for the ensuing render.
    budget = FetchBudget()
    event_repos = [] if privacy else _build_event_repos(config, budget=budget,
                                                        is_private=is_private)

    run_display(
        event_repos=event_repos,
        weather_repo=_build_weather_repo(config, budget=budget),
        config=config,
        project_root=PROJECT_ROOT,
        push_display=args.display,
        data_dir=DATA_DIR,
        privacy=privacy,
        # Looked at again just before drawing: a press may have switched
        # to the privacy page while the calendars were being fetched.
        is_private=is_private,
        # Mains power ([power] board = "none") has no battery to show.
        battery=None if power_board(config) == "none" else read_battery,
    )


if __name__ == "__main__":
    main()
