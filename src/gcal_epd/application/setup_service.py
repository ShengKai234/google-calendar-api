"""
Calendar setup: the one-time flow that gets feed URLs onto the device.

Serves the setup form, shows its address and PIN on the panel, waits for the
phone, then confirms on the panel. The setup counterpart of display_service,
which does the routine refresh.
"""
import logging
from pathlib import Path

from gcal_epd.config import feeds_file, font_path
from gcal_epd.infrastructure.feeds_file import load_feeds, write_feeds_file
from gcal_epd.infrastructure.onboarding.server import FeedSetupServer, check_feed

log = logging.getLogger(__name__)


def run_onboarding(config: dict, push_display: bool, error: str = "") -> bool:
    """Serve the setup form until feeds are saved. True if they were.

    `error` says why setup reopened; it is shown on the panel and the form.
    """
    server = FeedSetupServer(feeds_file(config), notice=error)

    log.info("")
    log.info("  Calendar setup — open this on your phone:")
    log.info("      %s", server.url)
    log.info("      PIN: %s", server.pin)
    log.info("")

    if push_display:
        push_setup_screen(config, "setup", url=server.url, pin=server.pin, error=error)

    saved = server.serve_until_configured()
    if saved and push_display:
        push_setup_screen(config, "success")
    return saved


def push_setup_screen(config: dict, kind: str, **kwargs) -> None:
    """Draw a setup screen to the panel; never fatal if the panel is absent."""
    font = font_path(config)
    try:
        from gcal_epd.epd import push_to_display
        from gcal_epd.render.draw import render_setup, render_setup_success
        img = (render_setup(kwargs["url"], pin=kwargs.get("pin", ""), font_path=font,
                            error=kwargs.get("error", ""))
               if kind == "setup" else render_setup_success(font_path=font))
        push_to_display(img)
    except Exception as e:
        log.warning("Could not draw the %s screen: %s", kind, e)


def apply_pending_feeds(pending_path: Path, feeds_path: Path, check=check_feed) -> str:
    """Check links parked by the Wi-Fi form; save them as the feeds if all work.

    Returns "" on success, else the first problem. The pending file is
    removed either way — kept, a broken link would be retried at every
    boot instead of the user being asked for a new one — and feeds that
    worked before are never replaced by ones that do not.
    """
    pending_path = Path(pending_path)
    try:
        urls = [f["url"] for f in load_feeds(pending_path) if f.get("url")]
    finally:
        pending_path.unlink(missing_ok=True)

    if not urls:
        return "No calendar links were received. Enter them again."
    for url in urls:
        problem = check(url)
        if problem:
            return problem
    write_feeds_file(feeds_path, [{"url": u} for u in urls])
    log.info("Saved %d feed(s) from Wi-Fi setup to %s", len(urls), Path(feeds_path).name)
    return ""
