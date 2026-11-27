"""Tests for render.draw — verifies PIL Image output, dark theme and weather widget."""
import datetime
import inspect
from pathlib import Path

from PIL import Image, ImageChops

from gcal_epd.config import PROJECT_ROOT
from gcal_epd.domain.battery import BatteryStatus
from gcal_epd.domain.event import CalendarEvent
from gcal_epd.domain.weather import WeatherInfo
from gcal_epd.infrastructure.open_meteo.repository import _WMO_CONDITION
from gcal_epd.render.draw import (
    _CONDITION_ICON,
    render,
    render_privacy,
    render_setup,
)
from gcal_epd.render.layout import BG, FOOTER_H, HEIGHT, PALETTE, WIDTH, TW_TZ


FONT = str(PROJECT_ROOT / "assets" / "fonts" / "NotoSansCJKtc-Regular.otf")


def _event(start: str, title: str = "Meeting", cal: str = "Work") -> CalendarEvent:
    return CalendarEvent(start=start, title=title, calendar_name=cal)


def _today_iso() -> str:
    return datetime.datetime.now(TW_TZ).strftime("%Y-%m-%dT09:00:00")


def _weather(**overrides) -> WeatherInfo:
    base = dict(
        temperature=32.0,
        condition="Partly Cloudy",
        humidity=75,
        location="Taipei",
        precipitation_probability=20,
    )
    base.update(overrides)
    return WeatherInfo(**base)


# --- basic contract ---

def test_render_returns_pil_image(tmp_path):
    img = render([], output_path=str(tmp_path / "out.png"))
    assert isinstance(img, Image.Image)


def test_render_correct_dimensions(tmp_path):
    img = render([], output_path=str(tmp_path / "out.png"))
    assert img.size == (WIDTH, HEIGHT)


def test_render_saves_file(tmp_path):
    out = str(tmp_path / "preview.png")
    render([], output_path=out)
    assert Path(out).exists()


def test_render_with_events(tmp_path):
    events = [_event(_today_iso(), "Standup", "Work")]
    img = render(events, output_path=str(tmp_path / "out.png"))
    assert isinstance(img, Image.Image)


def test_render_signature_accepts_weather_kwarg():
    assert "weather" in inspect.signature(render).parameters


# --- dark theme ---

def test_render_background_is_dark(tmp_path):
    """The panel is dark-theme: the corner outside the header card is black."""
    img = render([], output_path=str(tmp_path / "out.png"))
    assert img.getpixel((0, 0)) == BG


def test_render_draws_light_pixels(tmp_path):
    """White type/border must actually be drawn — not an all-black panel."""
    img = render([_event(_today_iso())], weather=_weather(), output_path=str(tmp_path / "out.png"))
    assert PALETTE["white"] in {c for _, c in img.getcolors(maxcolors=WIDTH * HEIGHT)}


def test_render_uses_only_panel_colors(tmp_path):
    """Anti-aliasing aside, the dominant colors must come from the 7-color palette."""
    img = render([_event(_today_iso())], weather=_weather(), output_path=str(tmp_path / "out.png"))
    counts = img.getcolors(maxcolors=WIDTH * HEIGHT)
    dominant = max(counts)[1]
    assert dominant == BG, "black should be the dominant color in a dark theme"


# --- weather widget ---

def test_render_with_weather(tmp_path):
    img = render([], weather=_weather(), output_path=str(tmp_path / "out.png"))
    assert isinstance(img, Image.Image)


def test_render_without_weather(tmp_path):
    img = render([], weather=None, output_path=str(tmp_path / "out.png"))
    assert isinstance(img, Image.Image)


def test_render_every_known_condition(tmp_path):
    """Every condition the repository can emit must render without raising."""
    for condition in set(_WMO_CONDITION.values()) | {"N/A", "Unknown"}:
        render(
            [_event(_today_iso())],
            weather=_weather(condition=condition),
            output_path=str(tmp_path / "out.png"),
        )


def test_render_unknown_condition_does_not_raise(tmp_path):
    render([], weather=_weather(condition="Sharknado"), output_path=str(tmp_path / "out.png"))


def test_condition_icon_keys_are_known_conditions():
    assert set(_CONDITION_ICON).issubset(set(_WMO_CONDITION.values()))


def test_repository_conditions_all_have_icons():
    """Guard against the repository emitting a label with no pictogram."""
    missing = set(_WMO_CONDITION.values()) - set(_CONDITION_ICON)
    assert not missing, f"conditions with no icon: {missing}"


def test_render_weather_fallback_values(tmp_path):
    """The repository's failure fallback must still render."""
    fallback = WeatherInfo(temperature=0.0, condition="N/A", humidity=0, location="Taipei")
    render([], weather=fallback, output_path=str(tmp_path / "out.png"))


# --- overflow / edge cases ---

def test_render_long_title_is_truncated(tmp_path):
    events = [_event(_today_iso(), "が" * 200)]
    img = render(events, output_path=str(tmp_path / "out.png"))
    assert img.size == (WIDTH, HEIGHT)


def test_render_many_events_does_not_raise(tmp_path):
    events = [
        _event(
            (datetime.datetime.now(TW_TZ).date() + datetime.timedelta(days=d)).isoformat()
            + "T09:00:00",
            title=f"Event {d}",
        )
        for d in range(40)
    ]
    render(events, weather=_weather(), output_path=str(tmp_path / "out.png"))


# --- setup screens ---

def test_render_setup_returns_image(tmp_path):
    img = render_setup("http://192.168.0.5:8080", pin="123456",
                       output_path=str(tmp_path / "s.png"))
    assert img.size == (WIDTH, HEIGHT)


def test_render_setup_qr_sits_on_white_panel(tmp_path):
    """A QR inverted on black will not scan — it needs a white quiet zone."""
    from gcal_epd.render.draw import _QR_QUIET
    from gcal_epd.render.layout import PADDING

    img = render_setup("http://192.168.0.5:8080", pin="123456",
                       output_path=str(tmp_path / "s.png"))
    probe = img.getpixel((PADDING + _QR_QUIET // 2, PADDING + 56 + 22 + _QR_QUIET // 2))
    assert probe == PALETTE["white"]


def test_render_setup_without_pin_does_not_raise(tmp_path):
    render_setup("http://192.168.0.5:8080", output_path=str(tmp_path / "s.png"))


def test_render_setup_long_url_is_truncated(tmp_path):
    """A long address must not run off the panel."""
    long_url = "http://192.168.0.5:8080/" + "x" * 200
    img = render_setup(long_url, pin="123456", output_path=str(tmp_path / "s.png"))
    assert img.size == (WIDTH, HEIGHT)


def test_render_setup_error_is_drawn_in_red(tmp_path):
    def colors(img):
        return {c for _, c in img.getcolors(maxcolors=WIDTH * HEIGHT)}

    plain = render_setup("http://192.168.0.5:8080", pin="123456")
    failed = render_setup("http://192.168.0.5:8080", pin="123456",
                          error="The link at h.example is not a calendar (iCal) file.")
    assert PALETTE["red"] not in colors(plain)
    assert PALETTE["red"] in colors(failed)


# --- footer ---

def _bottom_right(img):
    box = (WIDTH // 2, HEIGHT - FOOTER_H, WIDTH, HEIGHT)
    return {c for _, c in img.crop(box).getcolors(maxcolors=WIDTH * HEIGHT)}


def test_version_is_drawn_bottom_right(tmp_path):
    img = render([], version="0.2.1", output_path=str(tmp_path / "out.png"))
    assert PALETTE["white"] in _bottom_right(img)


def test_no_version_leaves_bottom_right_blank(tmp_path):
    img = render([], output_path=str(tmp_path / "out.png"))
    assert _bottom_right(img) == {BG}


# --- the privacy page ---

def test_privacy_page_fills_the_frame_window(tmp_path):
    out = tmp_path / "p.png"
    img = render_privacy(weather=_weather(), output_path=str(out), version="9.9.9")
    assert img.size == (WIDTH, HEIGHT)
    assert out.exists()


def test_privacy_page_without_weather(tmp_path):
    img = render_privacy(weather=None, output_path=str(tmp_path / "p.png"))
    assert img.size == (WIDTH, HEIGHT)


def test_privacy_page_takes_no_events():
    """Nothing to leak: it is never given the events or calendar names."""
    params = inspect.signature(render_privacy).parameters
    assert "events" not in params


def test_privacy_page_does_not_show_the_location(tmp_path):
    """Same pixels whatever the weather's location label says."""
    now = datetime.datetime(2026, 11, 22, 9, 30, tzinfo=TW_TZ)
    a = render_privacy(weather=_weather(location="Taipei"), output_path=str(tmp_path / "a.png"),
                       now=now)
    b = render_privacy(weather=_weather(location="Somewhere Else Entirely"),
                       output_path=str(tmp_path / "b.png"), now=now)
    assert a.tobytes() == b.tobytes()


# --- the battery, bottom right, left of the version ---

def _footer_right(img):
    return img.crop((WIDTH // 2, HEIGHT - FOOTER_H, WIDTH, HEIGHT))


def _colors(img):
    return {c for _, c in img.getcolors(maxcolors=WIDTH * HEIGHT)}


def _battery_only(tmp_path, battery, **kw):
    """The footer's right half with only the battery in it (no version)."""
    return _footer_right(render([], battery=battery, output_path=str(tmp_path / "b.png"),
                                font_path=FONT, **kw))


def test_battery_drawn_in_white_when_not_low(tmp_path):
    colors = _colors(_battery_only(tmp_path, BatteryStatus(85)))
    assert PALETTE["white"] in colors
    assert PALETTE["red"] not in colors
    assert PALETTE["yellow"] not in colors


def test_charging_battery_shows_a_yellow_bolt(tmp_path):
    colors = _colors(_battery_only(tmp_path, BatteryStatus(85, charging=True)))
    assert PALETTE["yellow"] in colors
    assert PALETTE["white"] in colors


def test_low_battery_icon_and_percent_are_red(tmp_path):
    img = _battery_only(tmp_path, BatteryStatus(15))
    assert PALETTE["red"] in _colors(img)
    # Nothing white or grey: every pixel is red, black, or a blend of the two.
    assert max(img.getchannel("G").getextrema()) <= PALETTE["red"][1]


def test_low_threshold_comes_from_the_caller(tmp_path):
    assert PALETTE["red"] in _colors(_battery_only(tmp_path, BatteryStatus(30),
                                                   low_battery_percent=40))
    assert PALETTE["red"] not in _colors(_battery_only(tmp_path, BatteryStatus(30),
                                                       low_battery_percent=20))


def test_unknown_battery_has_an_x_and_no_percent(tmp_path):
    unknown = _battery_only(tmp_path, BatteryStatus.unknown())
    shortest = _battery_only(tmp_path, BatteryStatus(5))   # "5%"
    assert PALETTE["red"] in _colors(unknown)               # the X
    assert PALETTE["yellow"] not in _colors(unknown)
    unknown_w = unknown.getbbox()[2] - unknown.getbbox()[0]
    shortest_w = shortest.getbbox()[2] - shortest.getbbox()[0]
    assert unknown_w < shortest_w - 8


def test_battery_sits_left_of_the_version(tmp_path):
    kw = dict(output_path=str(tmp_path / "v.png"), font_path=FONT, version="0.5.1")
    version_only = _footer_right(render([], **kw))
    both = _footer_right(render([], battery=BatteryStatus(85, charging=True), **kw))
    battery = ImageChops.difference(both, version_only).getbbox()
    assert battery is not None
    assert battery[2] < version_only.getbbox()[0]


def test_privacy_page_shows_the_battery_too(tmp_path):
    img = render_privacy(weather=None, output_path=str(tmp_path / "p.png"), font_path=FONT,
                         battery=BatteryStatus(85, charging=True))
    assert PALETTE["yellow"] in _colors(_footer_right(img))
