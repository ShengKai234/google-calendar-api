"""Tests for OpenMeteoRepository — HTTP calls are mocked."""
import json
from io import BytesIO
from unittest.mock import patch, MagicMock

import pytest

from gcal_epd.domain.weather import WeatherInfo
from gcal_epd.infrastructure.open_meteo.repository import (
    OpenMeteoRepository,
    _WMO_CONDITION,
    _current_precipitation_probability,
)


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


# --- precipitation probability ---

_POP_PAYLOAD = {
    "current": {
        "time": "2026-08-30T15:00",
        "temperature_2m": 32.0,
        "relative_humidity_2m": 75,
        "weather_code": 2,
    },
    "hourly": {
        "time": ["2026-08-30T13:00", "2026-08-30T14:00", "2026-08-30T15:00", "2026-08-30T16:00"],
        "precipitation_probability": [5, 10, 20, 45],
    },
}


def test_precipitation_matches_the_current_hour():
    assert _current_precipitation_probability(_POP_PAYLOAD) == 20


def test_precipitation_ignores_minutes_when_matching():
    payload = {**_POP_PAYLOAD, "current": {**_POP_PAYLOAD["current"], "time": "2026-08-30T15:45"}}
    assert _current_precipitation_probability(payload) == 20


def test_precipitation_missing_hourly_returns_zero():
    assert _current_precipitation_probability(_CLEAR_PAYLOAD) == 0


def test_precipitation_no_matching_hour_returns_zero():
    payload = {**_POP_PAYLOAD, "current": {**_POP_PAYLOAD["current"], "time": "2026-08-31T04:00"}}
    assert _current_precipitation_probability(payload) == 0


def test_precipitation_null_value_returns_zero():
    payload = {
        "current": {"time": "2026-08-30T15:00"},
        "hourly": {
            "time": ["2026-08-30T15:00"],
            "precipitation_probability": [None],
        },
    }
    assert _current_precipitation_probability(payload) == 0


def test_precipitation_shorter_values_array_returns_zero():
    payload = {
        "current": {"time": "2026-08-30T16:00"},
        "hourly": {
            "time": ["2026-08-30T15:00", "2026-08-30T16:00"],
            "precipitation_probability": [10],  # truncated series
        },
    }
    assert _current_precipitation_probability(payload) == 0


@patch("gcal_epd.infrastructure.open_meteo.repository.urllib.request.urlopen")
def test_fetch_weather_includes_precipitation(mock_urlopen):
    mock_urlopen.return_value = _fake_response(_POP_PAYLOAD)
    repo = OpenMeteoRepository(latitude=25.033, longitude=121.565, location="Taipei")
    result = repo.fetch_weather()
    assert result.precipitation_probability == 20


@patch("gcal_epd.infrastructure.open_meteo.repository.urllib.request.urlopen")
def test_fetch_weather_without_hourly_defaults_to_zero(mock_urlopen):
    mock_urlopen.return_value = _fake_response(_CLEAR_PAYLOAD)
    repo = OpenMeteoRepository(latitude=25.033, longitude=121.565, location="Taipei")
    result = repo.fetch_weather()
    assert result.precipitation_probability == 0


@patch("gcal_epd.infrastructure.open_meteo.repository.urllib.request.urlopen")
def test_fetch_weather_requests_hourly_precipitation(mock_urlopen):
    mock_urlopen.return_value = _fake_response(_POP_PAYLOAD)
    repo = OpenMeteoRepository(latitude=25.033, longitude=121.565, location="Taipei")
    repo.fetch_weather()
    url = mock_urlopen.call_args[0][0]
    assert "hourly=precipitation_probability" in url
    assert "timezone=auto" in url
