from typing import Protocol, runtime_checkable

from gcal_epd.domain.event import CalendarEvent
from gcal_epd.domain.weather import WeatherInfo


@runtime_checkable
class EventRepository(Protocol):
    def fetch_events(self, days_ahead: int, max_results: int) -> list[CalendarEvent]: ...


@runtime_checkable
class WeatherRepository(Protocol):
    def fetch_weather(self) -> WeatherInfo: ...
