from dataclasses import dataclass


@dataclass
class WeatherInfo:
    temperature: float    # celsius
    condition: str        # "Clear", "Cloudy", "Rain", etc.
    humidity: int         # percent
    location: str         # label for display
