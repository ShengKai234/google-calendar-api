import argparse
import logging
import sys
import tomllib
from pathlib import Path

from gcal_epd.application.display_service import run as run_display
from gcal_epd.infrastructure.ics.repository import ICSRepository
from gcal_epd.infrastructure.onboarding.server import FeedSetupServer, reset_feeds
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


def _feeds_path(config: dict) -> Path:
    for source in config.get("sources", []):
        if source.get("type") == "ics":
            return _PROJECT_ROOT / source.get("feeds_file", "ics_feeds.toml")
    return _PROJECT_ROOT / "ics_feeds.toml"


def run_onboarding(config: dict, push_display: bool) -> bool:
    """Serve the setup form, showing the address and PIN on the panel."""
    feeds_path = _feeds_path(config)
    server = FeedSetupServer(feeds_path)

    log.info("")
    log.info("  Calendar setup — open this on your phone:")
    log.info("      %s", server.url)
    log.info("      PIN: %s", server.pin)
    log.info("")

    if push_display:
        _push_screen(config, "setup", url=server.url, pin=server.pin)

    saved = server.serve_until_configured()
    if saved and push_display:
        _push_screen(config, "success")
    return saved


def _push_screen(config: dict, kind: str, **kwargs) -> None:
    """Draw a setup screen to the panel; never fatal if the panel is absent."""
    display_cfg = config.get("display", {})
    raw_font = display_cfg.get("font_path", "")
    font_path = (str(_PROJECT_ROOT / raw_font)
                 if raw_font and not raw_font.startswith("/") else raw_font)
    try:
        from gcal_epd.epd import push_to_display
        from gcal_epd.render.draw import render_setup, render_setup_success
        img = (render_setup(kwargs["url"], pin=kwargs.get("pin", ""), font_path=font_path)
               if kind == "setup" else render_setup_success(font_path=font_path))
        push_to_display(img)
    except Exception as e:
        log.warning("Could not draw the %s screen: %s", kind, e)


def _confirm_reset(config: dict, assume_yes: bool = False) -> bool:
    """Confirm, then delete the saved feeds. True if the reset went ahead."""
    feeds_path = _feeds_path(config)
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
    args = parser.parse_args()

    config = load_config()

    if args.reset and not _confirm_reset(config, assume_yes=args.yes):
        log.info("Reset cancelled — feeds left untouched.")
        return

    event_repos = _build_event_repos(config)

    # With no feeds there is nothing to show, so onboarding runs on its own.
    if args.setup or args.reset or not event_repos:
        if run_onboarding(config, push_display=args.display):
            event_repos = _build_event_repos(config)
        else:
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
