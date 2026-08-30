"""Tests for domain.weather — WeatherInfo dataclass."""
import dataclasses

from gcal_epd.domain.weather import WeatherInfo


def test_weather_info_fields():
    w = WeatherInfo(temperature=22.5, condition="Clear", humidity=60, location="Taipei")
    assert w.temperature == 22.5
    assert w.condition == "Clear"
    assert w.humidity == 60
    assert w.location == "Taipei"


def test_weather_info_is_dataclass():
    assert dataclasses.is_dataclass(WeatherInfo)


def test_weather_info_equality():
    w1 = WeatherInfo(temperature=20.0, condition="Rain", humidity=80, location="Taipei")
    w2 = WeatherInfo(temperature=20.0, condition="Rain", humidity=80, location="Taipei")
    assert w1 == w2


def test_weather_info_temperature_is_float():
    w = WeatherInfo(temperature=25, condition="Clear", humidity=50, location="Taipei")
    # dataclass does not coerce, but we store whatever is given
    assert isinstance(w.temperature, (int, float))


def test_weather_info_humidity_bounds():
    """Humidity should be representable as 0-100 percent."""
    w = WeatherInfo(temperature=15.0, condition="Foggy", humidity=100, location="Keelung")
    assert 0 <= w.humidity <= 100


def test_precipitation_probability_defaults_to_zero():
    """Sources without a rain forecast must still construct."""
    w = WeatherInfo(temperature=22.5, condition="Clear", humidity=60, location="Taipei")
    assert w.precipitation_probability == 0


def test_precipitation_probability_is_stored():
    w = WeatherInfo(
        temperature=22.5,
        condition="Rain",
        humidity=90,
        location="Taipei",
        precipitation_probability=80,
    )
    assert w.precipitation_probability == 80
