"""Tests for domain.repositories — Protocol structural typing."""
from gcal_epd.domain.event import CalendarEvent
from gcal_epd.domain.weather import WeatherInfo
from gcal_epd.domain.repositories import EventRepository, WeatherRepository


class _StubEventRepo:
    def fetch_events(self, days_ahead: int, max_results: int) -> list[CalendarEvent]:
        return [CalendarEvent(start="2024-01-15", title="Stub", calendar_name="Cal")]


class _StubWeatherRepo:
    def fetch_weather(self) -> WeatherInfo:
        return WeatherInfo(temperature=20.0, condition="Clear", humidity=55, location="Test")


class _BadRepo:
    """Does not implement the required methods."""
    pass


def test_event_repo_protocol_satisfied():
    repo = _StubEventRepo()
    assert isinstance(repo, EventRepository)


def test_weather_repo_protocol_satisfied():
    repo = _StubWeatherRepo()
    assert isinstance(repo, WeatherRepository)


def test_bad_repo_fails_event_protocol():
    bad = _BadRepo()
    assert not isinstance(bad, EventRepository)


def test_bad_repo_fails_weather_protocol():
    bad = _BadRepo()
    assert not isinstance(bad, WeatherRepository)


def test_event_repo_returns_list():
    repo = _StubEventRepo()
    result = repo.fetch_events(days_ahead=7, max_results=10)
    assert isinstance(result, list)
    assert all(isinstance(e, CalendarEvent) for e in result)


def test_weather_repo_returns_weather_info():
    repo = _StubWeatherRepo()
    result = repo.fetch_weather()
    assert isinstance(result, WeatherInfo)
