"""
Pillow drawing logic.
Consumes EventRow from layout.py and produces a PIL Image.

The design is dark-theme: a black panel with white type, a bordered header
card, and a three-column event table. Only the seven panel colors are used —
there is no grey available, so hierarchy comes from size and weight.
"""
import datetime

from PIL import Image, ImageDraw, ImageFont

from gcal_epd.domain.event import CalendarEvent
from gcal_epd.domain.weather import WeatherInfo
from gcal_epd.render.layout import (
    ACCENT,
    BG,
    COL_DATE_X,
    COL_TIME_X,
    COL_TITLE_X,
    FG,
    FOOTER_H,
    HEADER_H,
    HEIGHT,
    PADDING,
    PALETTE,
    ROW_H,
    TW_TZ,
    UNDERLINE_DROP,
    WIDTH,
    build_layout,
    format_weekday,
)

_QR_SIZE = 170  # pixels for the QR code block on the setup screen
_QR_QUIET = 10  # white quiet-zone margin around the QR so it stays scannable

# Condition (English, as emitted by the repository) -> which pictogram to draw
_CONDITION_ICON: dict[str, str] = {
    "Clear": "sun",
    "Mainly Clear": "sun_cloud",
    "Partly Cloudy": "sun_cloud",
    "Overcast": "cloud",
    "Foggy": "fog",
    "Icy Fog": "fog",
    "Light Drizzle": "rain",
    "Drizzle": "rain",
    "Heavy Drizzle": "rain",
    "Light Rain": "rain",
    "Rain": "rain",
    "Heavy Rain": "rain",
    "Light Snow": "snow",
    "Snow": "snow",
    "Heavy Snow": "snow",
    "Showers": "rain",
    "Rain Showers": "rain",
    "Heavy Showers": "rain",
    "Thunderstorm": "storm",
}


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
    try:
        return ImageFont.load_default(size)  # Pillow >= 10.1 returns a scalable font
    except TypeError:
        return ImageFont.load_default()


def _text(draw, xy, text, font, fill, anchor="la", bold=0) -> None:
    """Draw text, faking bold with a stroke since only a Regular weight ships."""
    kwargs = dict(font=font, fill=fill)
    if bold:
        kwargs.update(stroke_width=bold, stroke_fill=fill)
    try:
        draw.text(xy, text, anchor=anchor, **kwargs)
    except (ValueError, AttributeError):
        # Bitmap fallback fonts do not support anchors — approximate top-left.
        x, y = xy
        if anchor[0] == "r":
            x -= draw.textlength(text, font=font)
        if anchor[1] == "m":
            y -= font.size // 2 if hasattr(font, "size") else 6
        draw.text((x, y), text, **kwargs)


def _textw(draw: ImageDraw.ImageDraw, text: str, font, bold: int = 0) -> float:
    return draw.textlength(text, font=font) + 2 * bold


def _truncate(draw: ImageDraw.ImageDraw, text: str, font, max_width: float) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    while text and draw.textlength(text + "…", font=font) > max_width:
        text = text[:-1]
    return text + "…"


# --- Weather pictograms -------------------------------------------------
# Drawn from primitives rather than an icon font: chunky solid shapes hold up
# far better than fine glyphs across repeated e-paper refreshes.

def _draw_sun(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, color) -> None:
    """Eight-point star built from two overlapping squares."""
    draw.polygon(
        [(cx - r, cy - r), (cx + r, cy - r), (cx + r, cy + r), (cx - r, cy + r)],
        fill=color,
    )
    d = r * 1.34
    draw.polygon([(cx, cy - d), (cx + d, cy), (cx, cy + d), (cx - d, cy)], fill=color)


def _draw_cloud(draw: ImageDraw.ImageDraw, x: float, y: float, w: float, h: float, color) -> None:
    base_h = h * 0.52
    draw.rounded_rectangle(
        [x, y + h - base_h, x + w, y + h], radius=base_h / 2, fill=color
    )
    for fx, fr, lift in ((0.26, 0.30, 0.15), (0.55, 0.42, 0.34), (0.80, 0.26, 0.10)):
        r = h * fr
        cx = x + w * fx
        cy = y + h - base_h - r * lift
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)


def _draw_droplet(draw: ImageDraw.ImageDraw, cx: float, cy: float, size: float, color) -> None:
    r = size * 0.36
    by = cy + size * 0.16
    draw.ellipse([cx - r, by - r, cx + r, by + r], fill=color)
    draw.polygon(
        [(cx, cy - size * 0.50), (cx - r * 0.98, by + r * 0.12), (cx + r * 0.98, by + r * 0.12)],
        fill=color,
    )


def _draw_umbrella(draw: ImageDraw.ImageDraw, cx: float, cy: float, size: float, color) -> None:
    r = size * 0.48
    top = cy - size * 0.16
    stroke = max(2, int(size * 0.11))
    draw.pieslice([cx - r, top - r, cx + r, top + r], 180, 360, fill=color)
    draw.line([(cx, top), (cx, cy + size * 0.36)], fill=color, width=stroke)
    hr = size * 0.16
    draw.arc(
        [cx - hr * 2, cy + size * 0.36 - hr, cx, cy + size * 0.36 + hr],
        0, 90, fill=color, width=stroke,
    )


def _draw_weather_icon(draw: ImageDraw.ImageDraw, kind: str, x: float, y: float, size: float) -> None:
    """Draw `kind` into a `size`-square box with its top-left at (x, y)."""
    cx, cy = x + size / 2, y + size / 2
    if kind == "sun":
        _draw_sun(draw, cx, cy, size * 0.30, PALETTE["yellow"])
        return
    if kind == "sun_cloud":
        _draw_sun(draw, x + size * 0.34, y + size * 0.30, size * 0.24, PALETTE["yellow"])
        _draw_cloud(draw, x + size * 0.10, y + size * 0.40, size * 0.86, size * 0.46, FG)
        return
    if kind == "cloud":
        _draw_cloud(draw, x + size * 0.06, y + size * 0.26, size * 0.88, size * 0.50, FG)
        return
    if kind in ("rain", "storm"):
        _draw_cloud(draw, x + size * 0.06, y + size * 0.16, size * 0.88, size * 0.46, FG)
        if kind == "storm":
            bx, by = cx, y + size * 0.66
            draw.polygon(
                [(bx + size * 0.06, by), (bx - size * 0.12, by + size * 0.20),
                 (bx, by + size * 0.20), (bx - size * 0.06, by + size * 0.36),
                 (bx + size * 0.16, by + size * 0.14), (bx + size * 0.03, by + size * 0.14)],
                fill=PALETTE["yellow"],
            )
        else:
            for fx in (0.30, 0.55, 0.80):
                _draw_droplet(draw, x + size * fx, y + size * 0.80, size * 0.24, ACCENT)
        return
    if kind == "snow":
        _draw_cloud(draw, x + size * 0.06, y + size * 0.16, size * 0.88, size * 0.46, FG)
        for fx in (0.30, 0.55, 0.80):
            r = size * 0.06
            sx, sy = x + size * fx, y + size * 0.80
            draw.ellipse([sx - r, sy - r, sx + r, sy + r], fill=FG)
        return
    if kind == "fog":
        _draw_cloud(draw, x + size * 0.06, y + size * 0.14, size * 0.88, size * 0.42, FG)
        for i, fy in enumerate((0.70, 0.84)):
            inset = size * (0.10 + 0.08 * i)
            draw.line(
                [(x + inset, y + size * fy), (x + size - inset, y + size * fy)],
                fill=FG, width=max(2, int(size * 0.07)),
            )
        return
    # Unknown condition — leave the icon slot empty rather than guessing.


def _draw_header(
    draw: ImageDraw.ImageDraw,
    fonts: dict,
    now: datetime.datetime,
    weather: WeatherInfo | None,
) -> None:
    top = PADDING
    bottom = PADDING + HEADER_H
    draw.rounded_rectangle(
        [(PADDING, top), (WIDTH - PADDING, bottom)],
        radius=14, outline=FG, width=2,
    )

    mid = (top + bottom) / 2
    upper_y = top + HEADER_H * 0.34
    lower_y = top + HEADER_H * 0.70

    # --- Left: big date, then weekday over location ---
    date_x = PADDING + 20
    date_str = f"{now.month:02d}/{now.day:02d}"
    _text(draw, (date_x, mid), date_str, fonts["date"], FG, anchor="lm", bold=2)

    meta_x = date_x + _textw(draw, date_str, fonts["date"], bold=2) + 18
    has_location = bool(weather and weather.location)
    # With no location beneath it, the weekday centres on the card instead.
    _text(
        draw,
        (meta_x, upper_y if has_location else mid),
        format_weekday(now.date()),
        fonts["weekday"], FG, anchor="lm",
    )
    if has_location:
        _text(draw, (meta_x, lower_y), weather.location, fonts["location"], FG, anchor="lm")

    if not weather:
        return

    # --- Right: condition line over humidity / rain-chance line ---
    right = WIDTH - PADDING - 20
    line1 = f"{weather.temperature:.0f}°C {weather.condition}"
    w1 = _textw(draw, line1, fonts["temp"], bold=1)

    icon_s = 24
    gap = 5
    hum = f"{weather.humidity}%"
    pop = f"{weather.precipitation_probability}%"
    w2 = (
        icon_s + gap + _textw(draw, hum, fonts["metric"])
        + 18
        + icon_s + gap + _textw(draw, pop, fonts["metric"])
    )

    block_w = max(w1, w2)
    _text(draw, (right, upper_y), line1, fonts["temp"], FG, anchor="rm", bold=1)

    x = right - w2
    _draw_droplet(draw, x + icon_s / 2, lower_y, icon_s, ACCENT)
    x += icon_s + gap
    _text(draw, (x, lower_y), hum, fonts["metric"], FG, anchor="lm")
    x += _textw(draw, hum, fonts["metric"]) + 18
    _draw_umbrella(draw, x + icon_s / 2, lower_y, icon_s, ACCENT)
    x += icon_s + gap
    _text(draw, (x, lower_y), pop, fonts["metric"], FG, anchor="lm")

    icon_size = 54
    icon_x = right - block_w - 14 - icon_size
    if icon_x > meta_x + 40:  # only if it will not collide with the date block
        kind = _CONDITION_ICON.get(weather.condition, "")
        if kind:
            _draw_weather_icon(draw, kind, icon_x, mid - icon_size / 2, icon_size)


def _draw_footer(draw: ImageDraw.ImageDraw, fonts: dict, now: datetime.datetime) -> None:
    _text(
        draw,
        (COL_DATE_X, HEIGHT - FOOTER_H / 2 - 2),
        f"Updated {now.strftime('%H:%M')}",
        fonts["footer"],
        FG,
        anchor="lm",
    )


def render(
    events: list[CalendarEvent],
    weather: WeatherInfo | None = None,
    output_path: str = "preview.png",
    font_path: str = "",
) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)
    now = datetime.datetime.now(TW_TZ)

    fonts = {
        "date": _load_font(font_path, 50),
        "weekday": _load_font(font_path, 24),
        "location": _load_font(font_path, 19),
        "temp": _load_font(font_path, 23),
        "metric": _load_font(font_path, 21),
        "row": _load_font(font_path, 21),
        "title": _load_font(font_path, 23),
        "footer": _load_font(font_path, 14),
    }

    _draw_header(draw, fonts, now, weather)

    title_max_w = WIDTH - COL_TITLE_X - PADDING - 8
    for row in build_layout(events):
        mid = row.y + ROW_H / 2
        _text(draw, (COL_DATE_X, mid), row.date_str, fonts["row"], FG, anchor="lm")
        _text(draw, (COL_TIME_X, mid), row.time_str, fonts["row"], FG, anchor="lm")

        title = _truncate(draw, row.title, fonts["title"], title_max_w)
        _text(draw, (COL_TITLE_X, mid), title, fonts["title"], FG, anchor="lm")

        underline_w = draw.textlength(title, font=fonts["title"])
        underline_y = mid + UNDERLINE_DROP
        draw.line(
            [(COL_TITLE_X, underline_y), (COL_TITLE_X + underline_w, underline_y)],
            fill=FG, width=1,
        )

    _draw_footer(draw, fonts, now)

    img.save(output_path)
    return img


def render_setup(
    setup_url: str,
    pin: str = "",
    output_path: str = "",
    font_path: str = "",
) -> Image.Image:
    """Render the one-time setup screen.

    The QR carries this device's own LAN address, not a secret — it is only
    a shortcut so the phone does not have to type an IP.
    """
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)

    fonts = {
        "xl": _load_font(font_path, 32),
        "lg": _load_font(font_path, 21),
        "url": _load_font(font_path, 20),
        "pin": _load_font(font_path, 40),
        "md": _load_font(font_path, 15),
        "sm": _load_font(font_path, 13),
    }

    draw.rounded_rectangle(
        [(PADDING, PADDING), (WIDTH - PADDING, PADDING + 56)],
        radius=14, outline=FG, width=2,
    )
    _text(draw, (PADDING + 20, PADDING + 28), "Calendar Setup", fonts["xl"], FG,
          anchor="lm", bold=1)

    content_y = PADDING + 56 + 22
    text_x = PADDING + _QR_SIZE + 2 * _QR_QUIET + 26

    # QR of the setup URL, on its own white panel so it still scans.
    import qrcode
    qr = qrcode.QRCode(box_size=4, border=2)
    qr.add_data(setup_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color=PALETTE["black"],
                           back_color=PALETTE["white"]).convert("RGB")
    qr_img = qr_img.resize((_QR_SIZE, _QR_SIZE), Image.NEAREST)
    draw.rectangle(
        [
            (PADDING, content_y),
            (PADDING + _QR_SIZE + 2 * _QR_QUIET, content_y + _QR_SIZE + 2 * _QR_QUIET),
        ],
        fill=PALETTE["white"],
    )
    img.paste(qr_img, (PADDING + _QR_QUIET, content_y + _QR_QUIET))

    y = content_y
    _text(draw, (text_x, y), "Scan with your phone,", fonts["lg"], FG)
    y += 28
    _text(draw, (text_x, y), "or open this address:", fonts["md"], FG)
    y += 26
    _text(draw, (text_x, y), _truncate(draw, setup_url, fonts["url"],
                                       WIDTH - text_x - PADDING),
          fonts["url"], PALETTE["yellow"])
    y += 34

    if pin:
        y += 6
        _text(draw, (text_x, y), "PIN", fonts["md"], FG)
        y += 22
        _text(draw, (text_x, y), pin, fonts["pin"], PALETTE["green"], bold=1)
        y += 62

    for line in (
        "Paste your calendar feed links",
        "into the form, then enter the PIN.",
        "This screen closes once saved.",
    ):
        _text(draw, (text_x, y), line, fonts["sm"], FG)
        y += 19

    if output_path:
        img.save(output_path)
    return img


def render_setup_success(output_path: str = "", font_path: str = "") -> Image.Image:
    """Brief success screen shown after calendar access is confirmed."""
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)

    fonts = {
        "xl": _load_font(font_path, 44),
        "lg": _load_font(font_path, 22),
    }

    draw.rounded_rectangle(
        [(PADDING, PADDING), (WIDTH - PADDING, PADDING + HEADER_H)],
        radius=14, outline=PALETTE["green"], width=3,
    )
    _text(
        draw,
        (PADDING + 20, PADDING + HEADER_H / 2),
        "Connected!",
        fonts["xl"],
        PALETTE["green"],
        anchor="lm",
        bold=1,
    )
    _text(
        draw,
        (PADDING + 20, PADDING + HEADER_H + 44),
        "Calendar feeds saved. Fetching events...",
        fonts["lg"],
        FG,
    )

    if output_path:
        img.save(output_path)
    return img
