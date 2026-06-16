"""
One-time setup flow: show QR code, wait for calendar sharing, update config.
"""
import logging
import time
import tomllib
from pathlib import Path

import tomli_w

from gcal_epd.auth import get_credentials, get_service_account_email
from gcal_epd.calendar_client import check_calendar_access

log = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_POLL_INTERVAL = 30  # seconds between access checks
_POLL_TIMEOUT = 600  # 10 minutes


def run_setup(config: dict, config_path: Path, display: bool = False, email: str | None = None) -> None:
    """
    Interactive setup:
      1. Show QR code + service account email on e-paper and terminal
      2. Wait for user to share their Google Calendar
      3. Poll until access is confirmed
      4. Save calendar_id to config.toml
    """
    sa_file = str(_PROJECT_ROOT / config["auth"]["service_account_file"])
    sa_email = get_service_account_email(sa_file)
    creds = get_credentials(sa_file)

    # Render setup screen to e-paper (Pi only)
    if display:
        _push_setup_screen(sa_email, config)

    # Print to terminal as well
    _print_setup_instructions(sa_email)

    user_email = email or input("Enter your Google Calendar email address: ").strip()
    if not user_email:
        raise ValueError("Email cannot be empty.")

    print(f"\nPolling for calendar access every {_POLL_INTERVAL}s (up to {_POLL_TIMEOUT // 60} min)...")
    print("Share your calendar then wait — checking", end="", flush=True)

    deadline = time.monotonic() + _POLL_TIMEOUT
    while time.monotonic() < deadline:
        if check_calendar_access(creds, user_email):
            print(" ✓")
            break
        print(".", end="", flush=True)
        time.sleep(_POLL_INTERVAL)
    else:
        raise TimeoutError(
            f"\nCalendar access not granted within {_POLL_TIMEOUT // 60} minutes.\n"
            "Make sure you shared the correct calendar with:\n"
            f"  {sa_email}"
        )

    _save_calendar_ids(config_path, [user_email])
    log.info("Saved calendar_ids to %s", config_path)

    if display:
        _push_success_screen(config)

    print(f"\nSetup complete! Calendar '{user_email}' is now connected.")


def _push_setup_screen(sa_email: str, config: dict) -> None:
    try:
        from gcal_epd.epd import push_to_display
        from gcal_epd.render.draw import render_setup
        display_cfg = config.get("display", {})
        font_path = _resolve_font(display_cfg)
        img = render_setup(sa_email, font_path=font_path)
        push_to_display(img)
    except Exception as e:
        log.warning("Could not push setup screen to display: %s", e)


def _push_success_screen(config: dict) -> None:
    try:
        from gcal_epd.epd import push_to_display
        from gcal_epd.render.draw import render_setup_success
        display_cfg = config.get("display", {})
        font_path = _resolve_font(display_cfg)
        img = render_setup_success(font_path=font_path)
        push_to_display(img)
    except Exception as e:
        log.warning("Could not push success screen to display: %s", e)


def _resolve_font(display_cfg: dict) -> str:
    raw = display_cfg.get("font_path", "")
    if raw and not raw.startswith("/"):
        return str(_PROJECT_ROOT / raw)
    return raw


def _save_calendar_ids(config_path: Path, calendar_ids: list[str]) -> None:
    with open(config_path, "rb") as f:
        config = tomllib.load(f)
    config["calendar"]["calendar_ids"] = calendar_ids
    with open(config_path, "wb") as f:
        tomli_w.dump(config, f)


def _print_setup_instructions(sa_email: str) -> None:
    try:
        import qrcode
        qr = qrcode.QRCode(border=2)
        qr.add_data(sa_email)
        qr.make(fit=True)
        print("\nScan to copy the service account email:\n")
        qr.print_ascii(invert=True)
    except ImportError:
        pass

    print("\n" + "=" * 62)
    print("  Google Calendar Setup")
    print("=" * 62)
    print(f"\n  Share your calendar with this service account email:\n")
    print(f"    {sa_email}\n")
    print("  Steps:")
    print("    1. Open Google Calendar (calendar.google.com)")
    print("    2. Settings > My Calendars > [your calendar name]")
    print("    3. Share with specific people & groups")
    print("    4. Add the email above")
    print("    5. Set permission: 'See all event details'")
    print("    6. Save\n")
    print("=" * 62 + "\n")
