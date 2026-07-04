"""Tests for OpenMeteoRepository — HTTP calls are mocked."""
import json
from io import BytesIO
from unittest.mock import patch, MagicMock

import pytest

from gcal_epd.domain.weather import WeatherInfo
from gcal_epd.infrastructure.open_meteo.repository import OpenMeteoRepository, _WMO_CONDITION


def _fake_response(payload: dict):
    """Return a mock context-manager that yields a readable response."""
    raw = json.dumps(payload).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = raw
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


_CLEAR_PAYLOAD = {
    "current": {
        "temperature_2m": 26.3,
        "relative_humidity_2m": 72,
        "weather_code": 0,
    }
}


@patch("gcal_epd.infrastructure.open_meteo.repository.urllib.request.urlopen")
def test_fetch_weather_returns_weather_info(mock_urlopen):
    mock_urlopen.return_value = _fake_response(_CLEAR_PAYLOAD)
    repo = OpenMeteoRepository(latitude=25.033, longitude=121.565, location="Taipei")
    result = repo.fetch_weather()
    assert isinstance(result, WeatherInfo)


@patch("gcal_epd.infrastructure.open_meteo.repository.urllib.request.urlopen")
def test_fetch_weather_clear_condition(mock_urlopen):
    mock_urlopen.return_value = _fake_response(_CLEAR_PAYLOAD)
    repo = OpenMeteoRepository(latitude=25.033, longitude=121.565, location="Taipei")
    result = repo.fetch_weather()
    assert result.condition == "Clear"
    assert result.temperature == 26.3
    assert result.humidity == 72
    assert result.location == "Taipei"


@patch("gcal_epd.infrastructure.open_meteo.repository.urllib.request.urlopen")
def test_fetch_weather_rain_condition(mock_urlopen):
    payload = {
        "current": {
            "temperature_2m": 18.0,
            "relative_humidity_2m": 95,
            "weather_code": 63,
        }
    }
    mock_urlopen.return_value = _fake_response(payload)
    repo = OpenMeteoRepository(latitude=25.033, longitude=121.565, location="Taipei")
    result = repo.fetch_weather()
    assert result.condition == "Rain"


@patch("gcal_epd.infrastructure.open_meteo.repository.urllib.request.urlopen")
def test_fetch_weather_unknown_code_fallback(mock_urlopen):
    payload = {
        "current": {
            "temperature_2m": 20.0,
            "relative_humidity_2m": 60,
            "weather_code": 999,  # not in the mapping
        }
    }
    mock_urlopen.return_value = _fake_response(payload)
    repo = OpenMeteoRepository(latitude=25.033, longitude=121.565, location="Taipei")
    result = repo.fetch_weather()
    assert result.condition == "Unknown"


@patch("gcal_epd.infrastructure.open_meteo.repository.urllib.request.urlopen")
def test_fetch_weather_network_error_returns_na(mock_urlopen):
    mock_urlopen.side_effect = OSError("network unreachable")
    repo = OpenMeteoRepository(latitude=25.033, longitude=121.565, location="Taipei")
    result = repo.fetch_weather()
    assert result.condition == "N/A"
    assert result.temperature == 0.0
    assert result.humidity == 0


def test_default_location_is_coords():
    repo = OpenMeteoRepository(latitude=25.033, longitude=121.565)
    result_location = repo._location
    assert "25.03" in result_location
    # 121.565 formatted with :.2f is "121.56" in Python (float repr rounds down)
    assert "121.5" in result_location


@pytest.mark.parametrize("code,expected", [
    (0, "Clear"),
    (3, "Overcast"),
    (61, "Light Rain"),
    (95, "Thunderstorm"),
])
def test_wmo_condition_mapping(code, expected):
    assert _WMO_CONDITION[code] == expected
