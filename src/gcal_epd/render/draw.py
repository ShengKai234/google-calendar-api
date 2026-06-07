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
