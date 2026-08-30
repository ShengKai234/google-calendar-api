"""Tests for render.draw — verifies PIL Image output and weather widget."""
import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from gcal_epd.domain.event import CalendarEvent
from gcal_epd.domain.weather import WeatherInfo
from gcal_epd.render.draw import render
from gcal_epd.render.layout import WIDTH, HEIGHT


def _event(start: str, title: str = "Meeting", cal: str = "Work") -> CalendarEvent:
    return CalendarEvent(start=start, title=title, calendar_name=cal)


def _today_iso() -> str:
    import datetime
    from gcal_epd.render.layout import TW_TZ
    return datetime.datetime.now(TW_TZ).strftime("%Y-%m-%dT09:00:00")


def test_render_returns_pil_image(tmp_path):
    out = str(tmp_path / "out.png")
    img = render([], output_path=out)
    assert isinstance(img, Image.Image)


def test_render_correct_dimensions(tmp_path):
    out = str(tmp_path / "out.png")
    img = render([], output_path=out)
    assert img.size == (WIDTH, HEIGHT)


def test_render_saves_file(tmp_path):
    out = str(tmp_path / "preview.png")
    render([], output_path=out)
    assert Path(out).exists()


def test_render_with_events(tmp_path):
    events = [_event(_today_iso(), "Standup", "Work")]
    out = str(tmp_path / "out.png")
    img = render(events, output_path=out)
    assert isinstance(img, Image.Image)


def test_render_with_weather(tmp_path):
    weather = WeatherInfo(temperature=25.0, condition="Clear", humidity=60, location="Taipei")
    out = str(tmp_path / "out.png")
    img = render([], weather=weather, output_path=out)
    assert isinstance(img, Image.Image)


def test_render_without_weather(tmp_path):
    out = str(tmp_path / "out.png")
    img = render([], weather=None, output_path=out)
    assert isinstance(img, Image.Image)


def test_render_header_not_white(tmp_path):
    """Header bar should be black, so top-left pixel must not be white."""
    out = str(tmp_path / "out.png")
    img = render([], output_path=out)
    top_left = img.getpixel((0, 0))
    assert top_left != (255, 255, 255), "Header should have a dark background"


def test_render_signature_accepts_weather_kwarg(tmp_path):
    """Smoke-test: render() must accept weather as a keyword argument."""
    import inspect
    sig = inspect.signature(render)
    assert "weather" in sig.parameters


def test_draw_header_with_weather_does_not_raise(tmp_path):
    """Calling render with WeatherInfo must not raise any exception."""
    weather = WeatherInfo(temperature=18.5, condition="Rain", humidity=90, location="Taipei")
    out = str(tmp_path / "out.png")
    render([], weather=weather, output_path=out)  # must not raise


def test_draw_header_without_weather_shows_updated_time(tmp_path):
    """Without weather the header should still render without error."""
    out = str(tmp_path / "out.png")
    render([], weather=None, output_path=out)
