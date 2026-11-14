"""The photo-frame window: every screen fits inside it, and lands in it on the panel."""
import datetime
import logging

import pytest
from PIL import Image, ImageChops

from gcal_epd.config import PROJECT_ROOT
from gcal_epd.domain.event import CalendarEvent
from gcal_epd.domain.weather import WeatherInfo
from gcal_epd.render.draw import render, render_setup
from gcal_epd.render.frame import (
    OFFSET_X_RANGE,
    OFFSET_Y_RANGE,
    ORIGIN_X,
    ORIGIN_Y,
    frame_offset,
    to_panel,
)
from gcal_epd.render.layout import (
    BG,
    CONTENT_TOP,
    FRAME_MM,
    HEIGHT,
    PADDING,
    PALETTE,
    PANEL_H,
    PANEL_W,
    PX_PER_MM,
    ROW_H,
    TW_TZ,
    UNDERLINE_DROP,
    WIDTH,
    build_layout,
)
from gcal_epd.render.wifi_screens import render_wifi_connected, render_wifi_setup

# The font the panel really uses, so text is measured as it will be drawn.
FONT = str(PROJECT_ROOT / "assets" / "fonts" / "NotoSansCJKtc-Regular.otf")


def _day(n: int, time: str = "09:00") -> str:
    d = datetime.datetime.now(TW_TZ).date() + datetime.timedelta(days=n)
    return f"{d.isoformat()}T{time}:00"


def _event(start: str, title: str = "Meeting") -> CalendarEvent:
    return CalendarEvent(start=start, title=title, calendar_name="W")


def _weather(location: str = "Taipei", condition: str = "Partly Cloudy") -> WeatherInfo:
    return WeatherInfo(temperature=24, condition=condition, humidity=78,
                       location=location, precipitation_probability=40)


def _content_box(img: Image.Image):
    """Bounding box of everything that is not background."""
    return ImageChops.difference(img.convert("RGB"), Image.new("RGB", img.size, BG)).getbbox()


def _assert_inside_window(img: Image.Image) -> None:
    """Nothing within PADDING of the window's edge, where the mat could hide it."""
    assert img.size == (WIDTH, HEIGHT)
    left, top, right, bottom = _content_box(img)
    assert left >= PADDING and top >= PADDING
    assert right <= WIDTH - PADDING + 1 and bottom <= HEIGHT - PADDING + 1


# --- geometry ---

def test_window_is_the_frame_opening_in_panel_pixels():
    assert (PANEL_W, PANEL_H) == (800, 480)
    assert FRAME_MM == (139, 87)
    assert (WIDTH, HEIGHT) == (139 * PX_PER_MM, 87 * PX_PER_MM) == (695, 435)


def test_window_is_centred_on_the_panel():
    assert (ORIGIN_X, ORIGIN_Y) == (52, 22)
    assert PANEL_W - WIDTH - ORIGIN_X - ORIGIN_X in (0, 1)
    assert PANEL_H - HEIGHT - ORIGIN_Y - ORIGIN_Y in (0, 1)


# --- to_panel ---

def _marked_screen() -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    img.putpixel((0, 0), PALETTE["red"])
    img.putpixel((WIDTH - 1, HEIGHT - 1), PALETTE["green"])
    return img


def test_to_panel_places_the_screen_in_the_window():
    panel = to_panel(_marked_screen())
    assert panel.size == (PANEL_W, PANEL_H)
    assert panel.getpixel((ORIGIN_X, ORIGIN_Y)) == PALETTE["red"]
    assert panel.getpixel((ORIGIN_X + WIDTH - 1, ORIGIN_Y + HEIGHT - 1)) == PALETTE["green"]
    assert _content_box(panel) == (ORIGIN_X, ORIGIN_Y, ORIGIN_X + WIDTH, ORIGIN_Y + HEIGHT)


def test_to_panel_offset_moves_the_window():
    panel = to_panel(_marked_screen(), (5, -3))
    assert panel.getpixel((ORIGIN_X + 5, ORIGIN_Y - 3)) == PALETTE["red"]


def test_to_panel_keeps_a_full_panel_image():
    full = Image.new("RGB", (PANEL_W, PANEL_H), PALETTE["white"])
    assert to_panel(full) is full


def test_to_panel_rejects_other_sizes():
    with pytest.raises(ValueError):
        to_panel(Image.new("RGB", (100, 100), BG))


# --- frame_offset ---

def test_frame_offset_defaults_to_centred():
    assert frame_offset({}) == (0, 0)
    assert frame_offset({"display": {}}) == (0, 0)


def test_frame_offset_reads_display_table():
    assert frame_offset({"display": {"frame_offset_px": [4, -2]}}) == (4, -2)


def test_frame_offset_limits_keep_the_window_on_the_panel():
    assert OFFSET_X_RANGE == (-52, 53)
    assert OFFSET_Y_RANGE == (-22, 23)
    for x, y in [(-52, -22), (53, 23)]:
        offset = frame_offset({"display": {"frame_offset_px": [x, y]}})
        assert offset == (x, y)
        to_panel(Image.new("RGB", (WIDTH, HEIGHT), BG), offset)  # fits


@pytest.mark.parametrize("raw", [
    [54, 0], [0, -23], [1], [1, 2, 3], ["1", 2], [1.5, 0], [True, 0], "3,4", 7,
])
def test_frame_offset_ignores_unusable_values(raw, caplog):
    with caplog.at_level(logging.WARNING):
        assert frame_offset({"display": {"frame_offset_px": raw}}) == (0, 0)
    assert "frame_offset_px" in caplog.text


# --- every screen fits inside the window ---

def test_calendar_fits_inside_window(tmp_path):
    events = [_event(_day(d % 7, f"{8 + d % 10:02d}:30"),
                     "很長的標題 Design review: e-paper frame layout v2 " * 2)
              for d in range(30)]
    img = render(events, weather=_weather("Taipei City, Taiwan (Asia/Taipei)"),
                 output_path=str(tmp_path / "p.png"), font_path=FONT, version="10.20.30")
    _assert_inside_window(img)


def test_calendar_setup_fits_inside_window():
    img = render_setup("http://192.168.100.123:8080/setup/" + "x" * 200, pin="482193",
                       font_path=FONT, error="Could not read " + "y" * 200)
    _assert_inside_window(img)


@pytest.mark.parametrize("password", ["abcdefgh23", "mmmmmmmmmm", "WWWWWWWWWW"])
def test_wifi_setup_fits_inside_window(password):
    """Wide generated passwords shrink to fit the column rather than run off the window."""
    img = render_wifi_setup("ePaper-Setup-" + "X" * 80, password, "http://10.42.0.1:8080",
                            error="Could not join " + "Y" * 120 + ".", font_path=FONT)
    _assert_inside_window(img)


def test_wifi_connected_fits_inside_window():
    _assert_inside_window(render_wifi_connected("Home-" + "Z" * 100, font_path=FONT))


# --- the calendar keeps its rows and spacing in the smaller window ---

def test_nine_rows_fit_across_three_days():
    events = [_event(_day(d, f"{9 + i:02d}:00")) for d in range(3) for i in range(3)]
    assert len(build_layout(events)) == 9


def test_eight_rows_fit_across_seven_days():
    days = [0, 0, 1, 2, 3, 4, 5, 6]   # 8 rows, 6 day gaps
    events = [_event(_day(d, f"{9 + i:02d}:00")) for i, d in enumerate(days)]
    rows = build_layout(events)
    assert len(rows) == 8
    assert rows[0].y == CONTENT_TOP


def test_footer_clears_the_last_row(tmp_path, monkeypatch):
    """The footer starts below the lowest pixel of the last row (descenders included)."""
    import gcal_epd.render.draw as draw_mod

    events = [_event(_day(d % 3, f"{9 + d:02d}:00"), "Weekly sync gjpqy") for d in range(12)]
    full = render(events, output_path=str(tmp_path / "a.png"), font_path=FONT, version="0.3.1")
    monkeypatch.setattr(draw_mod, "_draw_footer", lambda *a, **k: None)
    rows_only = render(events, output_path=str(tmp_path / "b.png"), font_path=FONT)

    rows_bottom = _content_box(rows_only)[3]
    footer_top = ImageChops.difference(full, rows_only).getbbox()[1]
    assert footer_top > rows_bottom


def _header_has_sun(img: Image.Image) -> bool:
    header = img.crop((0, 0, WIDTH, CONTENT_TOP))
    return PALETTE["yellow"] in {c for _, c in header.getcolors(maxcolors=WIDTH * HEIGHT)}


def test_weather_icon_drawn_beside_a_short_location(tmp_path):
    img = render([], weather=_weather("Taipei"), output_path=str(tmp_path / "p.png"),
                 font_path=FONT)
    assert _header_has_sun(img)


def test_long_location_drops_the_icon_instead_of_overlapping(tmp_path):
    img = render([], weather=_weather("Taipei City, Taiwan (Asia/Taipei) " * 3),
                 output_path=str(tmp_path / "p.png"), font_path=FONT)
    assert not _header_has_sun(img)
    _assert_inside_window(img)
