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


class OpenMeteoRepository:
    def __init__(self, latitude: float, longitude: float, location: str = "") -> None:
        self._lat = latitude
        self._lon = longitude
        self._location = location or f"{latitude:.2f},{longitude:.2f}"

    def fetch_weather(self) -> WeatherInfo:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={self._lat}&longitude={self._lon}"
            f"&current=temperature_2m,relative_humidity_2m,weather_code"
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
            )
        except Exception as e:
            log.warning("Could not fetch weather: %s", e)
            return WeatherInfo(temperature=0.0, condition="N/A", humidity=0, location=self._location)
