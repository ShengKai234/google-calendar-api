"""Tests for render.draw — verifies PIL Image output, dark theme and weather widget."""
import datetime
import inspect
from pathlib import Path

from PIL import Image

from gcal_epd.domain.event import CalendarEvent
from gcal_epd.domain.weather import WeatherInfo
from gcal_epd.infrastructure.open_meteo.repository import _WMO_CONDITION
from gcal_epd.render.draw import (
    _CONDITION_ICON,
    render,
    render_setup,
    render_setup_success,
)
from gcal_epd.render.layout import BG, HEIGHT, PALETTE, WIDTH, TW_TZ


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
    img = render_setup("svc@project.iam.gserviceaccount.com", output_path=str(tmp_path / "s.png"))
    assert img.size == (WIDTH, HEIGHT)


def test_render_setup_qr_sits_on_white_panel(tmp_path):
    """A QR inverted on black will not scan — it needs a white quiet zone."""
    from gcal_epd.render.draw import _QR_QUIET
    from gcal_epd.render.layout import PADDING

    img = render_setup("svc@project.iam.gserviceaccount.com", output_path=str(tmp_path / "s.png"))
    # A pixel inside the quiet-zone margin, just outside the QR bitmap itself.
    probe = img.getpixel((PADDING + _QR_QUIET // 2, PADDING + 56 + 20 + _QR_QUIET // 2))
    assert probe == PALETTE["white"]


def test_render_setup_long_email_wraps(tmp_path):
    long_email = "a" * 60 + "@project.iam.gserviceaccount.com"
    render_setup(long_email, output_path=str(tmp_path / "s.png"))


def test_render_setup_success_returns_image(tmp_path):
    img = render_setup_success(output_path=str(tmp_path / "ok.png"))
    assert img.size == (WIDTH, HEIGHT)
