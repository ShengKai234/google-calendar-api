import datetime
from collections import defaultdict

from PIL import Image, ImageDraw, ImageFont

from calendar_client import CalendarEvent

WIDTH = 800
HEIGHT = 480

C = {
    "black":  (0,   0,   0),
    "white":  (255, 255, 255),
    "green":  (0,   160, 80),
    "blue":   (30,  80,  200),
    "red":    (200, 40,  40),
    "yellow": (210, 170, 0),
    "orange": (220, 110, 0),
}

ACCENT_COLORS = [C["blue"], C["green"], C["red"], C["orange"], C["yellow"]]

HEADER_H = 72
DAY_LABEL_H = 30
EVENT_H = 38
PADDING = 14


def _load_font(font_path: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [font_path] if font_path else []
    candidates += [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
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


def _parse_start(start_str: str) -> tuple[datetime.date, str]:
    if "T" in start_str:
        dt = datetime.datetime.fromisoformat(start_str)
        return dt.date(), dt.strftime("%H:%M")
    return datetime.date.fromisoformat(start_str), ""


def _truncate(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    while text and draw.textlength(text + "…", font=font) > max_width:
        text = text[:-1]
    return text + "…"


def render(
    events: list[CalendarEvent],
    output_path: str = "preview.png",
    font_path: str = "",
) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), C["white"])
    draw = ImageDraw.Draw(img)

    font_xl = _load_font(font_path, 34)
    font_lg = _load_font(font_path, 20)
    font_md = _load_font(font_path, 15)
    font_sm = _load_font(font_path, 12)

    today = datetime.date.today()

    # Header
    draw.rectangle([(0, 0), (WIDTH, HEADER_H)], fill=C["black"])
    draw.text((PADDING, 12), today.strftime("%A, %B %-d"), font=font_xl, fill=C["white"])
    update_str = f"Updated {datetime.datetime.now().strftime('%H:%M')}"
    draw.text((WIDTH - 140, HEADER_H - 22), update_str, font=font_sm, fill=C["white"])

    # Assign accent colors per calendar
    calendar_names = list(dict.fromkeys(e.calendar_name for e in events))
    cal_color = {name: ACCENT_COLORS[i % len(ACCENT_COLORS)] for i, name in enumerate(calendar_names)}

    # Group events by date
    by_day: defaultdict[datetime.date, list[tuple[str, CalendarEvent]]] = defaultdict(list)
    for event in events:
        date, time_str = _parse_start(event.start)
        by_day[date].append((time_str, event))

    # Draw events
    y = HEADER_H + 10
    for date in sorted(by_day.keys()):
        if y + DAY_LABEL_H > HEIGHT:
            break

        if date == today:
            day_label, label_color = "Today", C["red"]
        elif date == today + datetime.timedelta(days=1):
            day_label, label_color = "Tomorrow", C["blue"]
        else:
            day_label, label_color = date.strftime("%A, %-d %b"), C["black"]

        draw.text((PADDING, y), day_label, font=font_lg, fill=label_color)
        y += DAY_LABEL_H

        for time_str, event in by_day[date]:
            if y + EVENT_H > HEIGHT:
                break

            color = cal_color.get(event.calendar_name, C["black"])

            # Left accent bar
            draw.rectangle([(PADDING, y + 4), (PADDING + 4, y + EVENT_H - 6)], fill=color)

            # Time column
            time_display = time_str if time_str else "All day"
            draw.text((PADDING + 12, y + 4), time_display, font=font_md, fill=C["black"])

            # Title
            title_x = PADDING + 78
            title_max_w = WIDTH - title_x - PADDING
            title = _truncate(draw, event.title, font_md, title_max_w)
            draw.text((title_x, y + 4), title, font=font_md, fill=C["black"])

            # Calendar name (small, colored)
            cal_label = _truncate(draw, event.calendar_name, font_sm, title_max_w)
            draw.text((title_x, y + 22), cal_label, font=font_sm, fill=color)

            y += EVENT_H

        y += 8

    img.save(output_path)
    return img
