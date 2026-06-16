"""
Pillow drawing logic.
Consumes DayBlock / EventRow from layout.py and produces a PIL Image.
"""
import datetime

from PIL import Image, ImageDraw, ImageFont

from gcal_epd.calendar_client import CalendarEvent
from gcal_epd.render.layout import (
    HEADER_H,
    PADDING,
    PALETTE,
    TW_TZ,
    WIDTH,
    HEIGHT,
    build_layout,
)

_QR_SIZE = 190  # pixels for the QR code block on the setup screen


def _load_font(font_path: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [font_path] if font_path else []
    candidates += [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
    ]
    for path in candidates:
        if not path:
            continue
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _truncate(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    while text and draw.textlength(text + "…", font=font) > max_width:
        text = text[:-1]
    return text + "…"


def _draw_header(draw: ImageDraw.ImageDraw, fonts: dict) -> None:
    now_tw = datetime.datetime.now(TW_TZ)
    draw.rectangle([(0, 0), (WIDTH, HEADER_H)], fill=PALETTE["black"])
    draw.text(
        (PADDING, 12),
        now_tw.strftime("%A, %B %-d"),
        font=fonts["xl"],
        fill=PALETTE["white"],
    )
    draw.text(
        (WIDTH - 140, HEADER_H - 22),
        f"Updated {now_tw.strftime('%H:%M')}",
        font=fonts["sm"],
        fill=PALETTE["white"],
    )


def render(
    events: list[CalendarEvent],
    output_path: str = "preview.png",
    font_path: str = "",
) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), PALETTE["white"])
    draw = ImageDraw.Draw(img)

    fonts = {
        "xl": _load_font(font_path, 34),
        "lg": _load_font(font_path, 20),
        "md": _load_font(font_path, 15),
        "sm": _load_font(font_path, 12),
    }

    _draw_header(draw, fonts)

    title_x = PADDING + 78
    title_max_w = WIDTH - title_x - PADDING

    for block in build_layout(events):
        draw.text((PADDING, block.y), block.label, font=fonts["lg"], fill=block.label_color)

        for row in block.rows:
            draw.rectangle(
                [(PADDING, row.y + 4), (PADDING + 4, row.y + 30)],
                fill=row.accent_color,
            )
            draw.text((PADDING + 12, row.y + 4), row.time_str, font=fonts["md"], fill=PALETTE["black"])
            draw.text(
                (title_x, row.y + 4),
                _truncate(draw, row.title, fonts["md"], title_max_w),
                font=fonts["md"],
                fill=PALETTE["black"],
            )
            draw.text(
                (title_x, row.y + 22),
                _truncate(draw, row.calendar_name, fonts["sm"], title_max_w),
                font=fonts["sm"],
                fill=row.accent_color,
            )

    img.save(output_path)
    return img


def render_setup(
    service_account_email: str,
    output_path: str = "",
    font_path: str = "",
) -> Image.Image:
    """Render the one-time calendar sharing setup screen."""
    img = Image.new("RGB", (WIDTH, HEIGHT), PALETTE["white"])
    draw = ImageDraw.Draw(img)

    fonts = {
        "xl": _load_font(font_path, 34),
        "lg": _load_font(font_path, 22),
        "md": _load_font(font_path, 15),
        "sm": _load_font(font_path, 12),
    }

    # Header
    draw.rectangle([(0, 0), (WIDTH, HEADER_H)], fill=PALETTE["black"])
    draw.text((PADDING, 14), "Calendar Setup", font=fonts["xl"], fill=PALETTE["white"])

    content_y = HEADER_H + 20
    text_x = PADDING + _QR_SIZE + 24

    # QR code (encodes the service account email as plain text for easy copy)
    import qrcode
    qr = qrcode.QRCode(box_size=4, border=2)
    qr.add_data(service_account_email)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color=PALETTE["black"], back_color=PALETTE["white"]).convert("RGB")
    qr_img = qr_img.resize((_QR_SIZE, _QR_SIZE), Image.NEAREST)
    img.paste(qr_img, (PADDING, content_y))

    # Right-side instructions
    y = content_y
    draw.text((text_x, y), "Share your Google Calendar", font=fonts["lg"], fill=PALETTE["black"])
    y += 28
    draw.text((text_x, y), "with this service account:", font=fonts["md"], fill=PALETTE["black"])
    y += 26

    # Email (may be long — wrap at 42 chars)
    email = service_account_email
    mid = email.find("@")
    if mid > 0 and draw.textlength(email, font=fonts["sm"]) > WIDTH - text_x - PADDING:
        draw.text((text_x, y), email[:mid + 1], font=fonts["sm"], fill=PALETTE["blue"])
        draw.text((text_x, y + 16), email[mid + 1:], font=fonts["sm"], fill=PALETTE["blue"])
        y += 36
    else:
        draw.text((text_x, y), email, font=fonts["sm"], fill=PALETTE["blue"])
        y += 20

    y += 12
    steps = [
        "1. Open Google Calendar on your phone",
        "2. Settings > My Calendars > [Calendar name]",
        "3. Share with specific people & groups",
        "4. Add the email above",
        "5. Permission: See all event details",
        "6. Scan the QR code to copy the email",
    ]
    for step in steps:
        draw.text((text_x, y), step, font=fonts["sm"], fill=PALETTE["black"])
        y += 19

    if output_path:
        img.save(output_path)
    return img


def render_setup_success(output_path: str = "", font_path: str = "") -> Image.Image:
    """Brief success screen shown after calendar access is confirmed."""
    img = Image.new("RGB", (WIDTH, HEIGHT), PALETTE["white"])
    draw = ImageDraw.Draw(img)

    fonts = {
        "xl": _load_font(font_path, 48),
        "lg": _load_font(font_path, 24),
    }

    draw.rectangle([(0, 0), (WIDTH, HEADER_H)], fill=PALETTE["green"])
    draw.text((PADDING, 14), "Connected!", font=fonts["xl"], fill=PALETTE["white"])
    draw.text((PADDING, HEADER_H + 40), "Calendar access granted. Fetching events...", font=fonts["lg"], fill=PALETTE["black"])

    if output_path:
        img.save(output_path)
    return img
