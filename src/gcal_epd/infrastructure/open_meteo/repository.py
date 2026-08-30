import json
import logging
import urllib.request

from gcal_epd.domain.weather import WeatherInfo

log = logging.getLogger(__name__)

_WMO_CONDITION: dict[int, str] = {
    0: "Clear",
    1: "Mainly Clear", 2: "Partly Cloudy", 3: "Overcast",
    45: "Foggy", 48: "Icy Fog",
    51: "Light Drizzle", 53: "Drizzle", 55: "Heavy Drizzle",
    61: "Light Rain", 63: "Rain", 65: "Heavy Rain",
    71: "Light Snow", 73: "Snow", 75: "Heavy Snow",
    80: "Showers", 81: "Rain Showers", 82: "Heavy Showers",
    95: "Thunderstorm", 96: "Thunderstorm", 99: "Thunderstorm",
}


def _current_precipitation_probability(data: dict) -> int:
    """Pick the hourly rain chance for the hour reported by `current`.

    Both series are local time (timezone=auto), so matching on the
    "YYYY-MM-DDTHH" prefix lines them up. Returns 0 when unavailable.
    """
    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []
    values = hourly.get("precipitation_probability") or []
    now = (data.get("current") or {}).get("time", "")
    if not (times and values and now):
        return 0
    for i, stamp in enumerate(times):
        if stamp[:13] == now[:13] and i < len(values):
            return int(values[i] or 0)
    return 0


class OpenMeteoRepository:
    def __init__(self, latitude: float, longitude: float, location: str = "") -> None:
        self._lat = latitude
        self._lon = longitude
        self._location = location or f"{latitude:.2f},{longitude:.2f}"

    def fetch_weather(self) -> WeatherInfo:
        # precipitation_probability is only published on the hourly series, so
        # it is requested alongside `current` and matched to the current hour.
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={self._lat}&longitude={self._lon}"
            f"&current=temperature_2m,relative_humidity_2m,weather_code"
            f"&hourly=precipitation_probability"
            f"&forecast_days=1&timezone=auto"
            f"&temperature_unit=celsius"
        )
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
            current = data["current"]
            code = current.get("weather_code", 0)
            return WeatherInfo(
                temperature=current["temperature_2m"],
                condition=_WMO_CONDITION.get(code, "Unknown"),
                humidity=current["relative_humidity_2m"],
                location=self._location,
                precipitation_probability=_current_precipitation_probability(data),
            )
        except Exception as e:
            log.warning("Could not fetch weather: %s", e)
            return WeatherInfo(temperature=0.0, condition="N/A", humidity=0, location=self._location)
