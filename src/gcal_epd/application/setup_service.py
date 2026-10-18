"""
Calendar setup: the one-time flow that gets feed URLs onto the device.

Serves the setup form, shows its address and PIN on the panel, waits for the
phone, then confirms on the panel. The setup counterpart of display_service,
which does the routine refresh.
"""
import logging

from gcal_epd.config import feeds_file, font_path
from gcal_epd.infrastructure.onboarding.server import FeedSetupServer

log = logging.getLogger(__name__)


def run_onboarding(config: dict, push_display: bool) -> bool:
    """Serve the setup form until feeds are saved. True if they were."""
    server = FeedSetupServer(feeds_file(config))

    log.info("")
    log.info("  Calendar setup — open this on your phone:")
    log.info("      %s", server.url)
    log.info("      PIN: %s", server.pin)
    log.info("")

    if push_display:
        push_setup_screen(config, "setup", url=server.url, pin=server.pin)

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
        img = (render_setup(kwargs["url"], pin=kwargs.get("pin", ""), font_path=font)
               if kind == "setup" else render_setup_success(font_path=font))
        push_to_display(img)
    except Exception as e:
        log.warning("Could not draw the %s screen: %s", kind, e)
