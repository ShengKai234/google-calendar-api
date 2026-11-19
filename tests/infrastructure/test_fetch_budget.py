"""Bounded network fetching: fake transports and a controllable monotonic clock."""
import json
import socket
import signal
from unittest.mock import MagicMock

import pytest

from gcal_epd.infrastructure import fetch_budget as fb
from gcal_epd.infrastructure.ics import repository as ics
from gcal_epd.infrastructure.open_meteo import repository as meteo


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture(autouse=True)
def no_processes(monkeypatch):
    import multiprocessing
    def forbidden(*args, **kwargs):
        raise AssertionError("HTTP downloads must not start a subprocess")
    monkeypatch.setattr(multiprocessing, "get_context", forbidden)


class Response:
    __slots__ = ("clock", "chunks", "elapsed", "closed", "status_code")
    def __init__(self, clock, chunks=(), elapsed=0):
        self.clock, self.chunks, self.elapsed = clock, list(chunks), elapsed
        self.closed = False
        self.status_code = 200

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        for chunk in self.chunks:
            self.clock.now += self.elapsed
            yield chunk

    def read1(self, size):
        self.clock.now += self.elapsed
        return self.chunks.pop(0) if self.chunks else b""

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


ICS = (b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:1\r\n"
       b"DTSTART;VALUE=DATE:20991231\r\nSUMMARY:Saved event\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
WEATHER = json.dumps({"current": {"temperature_2m": 23, "relative_humidity_2m": 50}}).encode()
URL = "https://calendar.example.test/private-placeholder/calendar.ics?token=placeholder"


def test_requests_receives_connect_read_limits(clock, monkeypatch):
    response = Response(clock, [ICS])
    get = MagicMock(return_value=response)
    monkeypatch.setattr(ics.requests, "get", get)
    assert ics.ICSRepository(URL, clock=clock).fetch_raw() == ICS
    assert get.call_args.kwargs["timeout"] == (10, 30)
    assert get.call_args.kwargs["stream"] is True
    assert response.closed


def test_urllib_uses_timeout_and_public_stream_only(clock, monkeypatch):
    response = Response(clock, [WEATHER])
    open_ = MagicMock(return_value=response)
    monkeypatch.setattr(meteo.urllib.request, "urlopen", open_)
    assert meteo.OpenMeteoRepository(0, 0, clock=clock).fetch_weather().temperature == 23
    assert open_.call_args.kwargs["timeout"] == 10
    assert response.closed


@pytest.mark.parametrize("kind", ["ics", "weather"])
def test_slow_drip_body_hits_whole_request_cap(kind, clock, monkeypatch):
    response = Response(clock, [b"x"] * 100, elapsed=9)
    if kind == "ics":
        monkeypatch.setattr(ics.requests, "get", MagicMock(return_value=response))
        with pytest.raises(fb.FetchTimeout):
            ics.ICSRepository(URL, clock=clock).fetch_raw()
    else:
        monkeypatch.setattr(meteo.urllib.request, "urlopen", MagicMock(return_value=response))
        assert meteo.OpenMeteoRepository(0, 0, clock=clock).fetch_weather().condition == "N/A"
    assert clock.now < 60, "streaming must stop near the cap, not consume the full body"
    assert response.closed


def test_all_sources_share_budget_and_keep_earlier_results(clock, monkeypatch, caplog):
    budget = fb.FetchBudget(clock=clock)
    responses = [Response(clock, [ICS], elapsed=10), Response(clock, [b"x"] * 100, elapsed=10),
                 Response(clock, [b"x"] * 100, elapsed=10)]
    get = MagicMock(side_effect=responses)
    open_ = MagicMock()
    monkeypatch.setattr(ics.requests, "get", get)
    monkeypatch.setattr(meteo.urllib.request, "urlopen", open_)
    repos = [ics.ICSRepository(URL, name=name, budget=budget) for name in ("Good", "Slow", "Last", "Skipped")]
    events = [event for repo in repos for event in repo.fetch_events(40000, 10)]
    assert [event.title for event in events] == ["Saved event"]
    assert get.call_count == 3
    assert get.call_args.kwargs["timeout"] == (10, 30)
    assert meteo.OpenMeteoRepository(0, 0, budget=budget).fetch_weather().condition == "N/A"
    open_.assert_not_called()
    assert "Skipped (calendar.example.test)" in caplog.text
    assert "api.open-meteo.com" in caplog.text
    assert "budget" in caplog.text.lower()
    if URL in caplog.text or "private-placeholder" in caplog.text:
        pytest.fail("unsafe feed diagnostic", pytrace=False)


@pytest.mark.parametrize("kind", ["ics", "weather"])
def test_request_limits_shrink_to_remaining_budget(kind, clock, monkeypatch):
    budget = fb.FetchBudget(clock=clock)
    clock.now = 86
    response = Response(clock, [ICS if kind == "ics" else WEATHER])
    if kind == "ics":
        get = MagicMock(return_value=response)
        monkeypatch.setattr(ics.requests, "get", get)
        assert ics.ICSRepository(URL, budget=budget).fetch_raw() == ICS
        assert get.call_args.kwargs["timeout"] == (4, 4)
    else:
        open_ = MagicMock(return_value=response)
        monkeypatch.setattr(meteo.urllib.request, "urlopen", open_)
        assert meteo.OpenMeteoRepository(0, 0, budget=budget).fetch_weather().temperature == 23
        assert open_.call_args.kwargs["timeout"] == 4


@pytest.mark.parametrize("failure", [OSError(URL), ValueError(URL)], ids=["network", "invalid"])
def test_errors_containing_urls_are_not_logged(failure, clock, monkeypatch, caplog):
    monkeypatch.setattr(ics.requests, "get", MagicMock(side_effect=failure))
    assert ics.ICSRepository(URL, name="Home", clock=clock).fetch_events(14, 10) == []
    assert "Home (calendar.example.test)" in caplog.text
    if URL in caplog.text or "private-placeholder" in caplog.text:
        pytest.fail("unsafe feed diagnostic", pytrace=False)


def test_parse_errors_containing_feed_content_are_not_logged(clock, monkeypatch, caplog):
    monkeypatch.setattr(ics.requests, "get", MagicMock(return_value=Response(clock, [ICS])))
    monkeypatch.setattr(ics, "events_from_ics", MagicMock(side_effect=ValueError(URL)))
    assert ics.ICSRepository(URL, clock=clock).fetch_events(14, 10) == []
    if URL in caplog.text or "private-placeholder" in caplog.text:
        pytest.fail("unsafe feed diagnostic", pytrace=False)


def test_host_label_excludes_userinfo():
    assert ics.ICSRepository("https://placeholder:placeholder@calendar.example.test/a")._log_label == "feed (calendar.example.test)"


def test_budget_absolute_deadline_cannot_move_during_request_creation():
    class TickingClock:
        def __init__(self):
            self.now = 0
        def __call__(self):
            self.now += 1
            return self.now
    clock = TickingClock()
    budget = fb.FetchBudget(seconds=3, clock=clock)
    limit = budget.request()
    # At time 4 the absolute refresh deadline is spent, even if constructing
    # the request itself took time after the initial remaining-time check.
    with pytest.raises(fb.FetchTimeout):
        limit.remaining()


def test_weather_exception_text_is_not_logged(clock, monkeypatch, caplog):
    monkeypatch.setattr(meteo.urllib.request, "urlopen", MagicMock(side_effect=OSError(URL)))
    assert meteo.OpenMeteoRepository(0, 0, clock=clock).fetch_weather().condition == "N/A"
    if URL in caplog.text:
        pytest.fail("unsafe feed diagnostic", pytrace=False)


def test_direct_fetch_raw_errors_have_safe_useful_messages(clock, monkeypatch):
    monkeypatch.setattr(ics.requests, "get", MagicMock(side_effect=ics.requests.ReadTimeout(URL)))
    with pytest.raises(fb.FetchFailure) as caught:
        ics.ICSRepository(URL, clock=clock).fetch_raw()
    message = str(caught.value)
    if URL in message:
        pytest.fail("fetch_raw exposed a feed URL", pytrace=False)
    assert "timed out" in message and "40" in message


def test_http_failure_is_url_free_and_preserves_onboarding_status(clock, monkeypatch):
    response = Response(clock)
    response.status_code = 404
    monkeypatch.setattr(ics.requests, "get", MagicMock(return_value=response))
    with pytest.raises(ics.requests.HTTPError) as caught:
        ics.ICSRepository(URL, clock=clock).fetch_raw()
    error = caught.value
    if URL in str(error) or getattr(error.response, "url", None):
        pytest.fail("HTTP failure exposed a feed URL", pytrace=False)
    assert str(error) == "HTTP 404" and error.response.status_code == 404
    assert error.__suppress_context__
    assert response.closed


def test_expired_request_does_not_start_http(clock, monkeypatch):
    get = MagicMock()
    monkeypatch.setattr(ics.requests, "get", get)
    with pytest.raises(fb.FetchTimeout):
        ics.ICSRepository(URL, timeout=0, clock=clock).fetch_raw()
    get.assert_not_called()


def test_stream_yields_bounded_chunks(clock, monkeypatch):
    response = Response(clock, [ICS])
    get = MagicMock(return_value=response)
    monkeypatch.setattr(ics.requests, "get", get)
    assert ics.ICSRepository(URL, clock=clock).fetch_raw() == ICS
    get.assert_called_once()


def test_refresh_deadline_is_armed_and_restored_without_sleep(clock, monkeypatch):
    calls = []
    handler = object()
    monkeypatch.setattr(signal, "getsignal", lambda sig: handler)
    monkeypatch.setattr(signal, "getitimer", lambda which: (0, 0))
    monkeypatch.setattr(signal, "signal", lambda *args: calls.append(("handler", args)))
    monkeypatch.setattr(signal, "setitimer", lambda *args: calls.append(("timer", args)))
    limit = fb.RequestLimit(seconds=4, clock=clock)
    with fb.request_scope(limit):
        installed = next(args[1] for what, args in calls if what == "handler")
        with pytest.raises(fb.FetchTimeout):
            installed(None, None)
    assert ("timer", (signal.ITIMER_REAL, 4)) in calls
    assert calls[-1] == ("handler", (signal.SIGALRM, handler))
    assert ("timer", (signal.ITIMER_REAL, 0)) in calls


def test_dns_timeout_uses_only_daemon_thread_and_restores_resolver(clock, monkeypatch):
    from types import SimpleNamespace
    threads = []
    class Event:
        def wait(self, timeout):
            clock.now += timeout
            return False
        def set(self):
            pass
    class Thread:
        def __init__(self, **kwargs):
            threads.append(kwargs)
        def start(self):
            pass  # unresolved DNS: fake time advances only in Event.wait
    monkeypatch.setattr(fb, "dns_threading", SimpleNamespace(Event=Event, Thread=Thread))
    resolver = socket.getaddrinfo
    with fb.request_scope(fb.RequestLimit(seconds=4, clock=clock)):
        with pytest.raises(fb.FetchTimeout):
            socket.getaddrinfo("calendar.example.test", 443)
    assert socket.getaddrinfo is resolver
    assert len(threads) == 1 and threads[0]["daemon"] is True
    assert clock.now == 4
