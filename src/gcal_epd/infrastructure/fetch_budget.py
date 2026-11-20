"""Shared monotonic fetch deadlines, independent of either HTTP library.

HTTP runs in the caller, with finite socket timeouts and streaming checks.
A scoped POSIX alarm protects the refresh main thread even while a library
buffers a chunk or reads headers. Only DNS (which has no socket timeout)
runs in a daemon thread; an unresolved lookup cannot delay interpreter exit.
Threaded onboarding keeps the same socket limits and per-chunk checks.
"""
from contextlib import contextmanager
import signal
import socket
import threading
import time
from typing import Callable

CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 30.0
REQUEST_TIMEOUT = 40.0
REFRESH_BUDGET = 90.0


class FetchTimeout(TimeoutError):
    """The complete request, including its body, exceeded its deadline."""


class BudgetSpent(FetchTimeout):
    """The refresh has no fetch time left."""


class FetchFailure(Exception):
    """A short, URL-free explanation suitable for logs and onboarding."""


class RequestLimit:
    def __init__(self, seconds: float = REQUEST_TIMEOUT,
                 clock: Callable[[], float] = time.monotonic,
                 deadline: float = float("inf")):
        self._clock = clock
        now = clock()
        self.seconds = min(seconds, deadline - now)
        self._end = min(now + seconds, deadline)

    def remaining(self) -> float:
        left = self._end - self._clock()
        if left <= 0:
            raise FetchTimeout(f"timed out after {self.seconds:g} s") from None
        return left

    @property
    def connect_timeout(self) -> float:
        return min(CONNECT_TIMEOUT, self.remaining())

    @property
    def read_timeout(self) -> float:
        return min(READ_TIMEOUT, self.remaining())


class FetchBudget:
    def __init__(self, seconds: float = REFRESH_BUDGET,
                 clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._end = clock() + seconds

    def request(self, seconds: float = REQUEST_TIMEOUT) -> RequestLimit:
        left = self._end - self._clock()
        if left <= 0:
            raise BudgetSpent("refresh fetch budget exhausted") from None
        return RequestLimit(seconds, clock=self._clock, deadline=self._end)


_dns_state = threading.local()
_dns_lock = threading.Lock()
_dns_users = 0
_resolver = socket.getaddrinfo


def _resolve(*args, **kwargs):
    limit = getattr(_dns_state, "limit", None)
    resolver = _resolver
    if limit is None:
        return resolver(*args, **kwargs)
    done = threading.Event()
    result = []

    def lookup():
        try:
            result.append(resolver(*args, **kwargs))
        except Exception:
            result.append(None)  # resolver errors can include private input
        finally:
            done.set()

    wait = limit.connect_timeout
    # getaddrinfo cannot be cancelled. Keep the caller bounded without joining
    # it; a resolver that never returns can leave one daemon thread per lookup
    # until process exit.
    threading.Thread(target=lookup, name="fetch-dns", daemon=True).start()
    if not done.wait(wait):
        raise FetchTimeout(f"DNS lookup timed out after {wait:g} s") from None
    limit.remaining()
    if not result or result[0] is None:
        raise FetchFailure("DNS lookup failed") from None
    return result[0]


@contextmanager
def _dns_scope(limit):
    # The dispatcher uses thread-local deadlines; unrelated HTTP/server
    # threads retain normal resolver behavior. Concurrent fetch scopes share
    # the hook and the last one restores it, including on exceptions.
    global _dns_users, _resolver
    previous = getattr(_dns_state, "limit", None)
    with _dns_lock:
        if not _dns_users:
            _resolver = socket.getaddrinfo
            socket.getaddrinfo = _resolve
        _dns_users += 1
    _dns_state.limit = limit
    try:
        yield
    finally:
        _dns_state.limit = previous
        with _dns_lock:
            _dns_users -= 1
            if not _dns_users and socket.getaddrinfo is _resolve:
                socket.getaddrinfo = _resolver


@contextmanager
def _alarm_scope(limit):
    main = threading.current_thread() is threading.main_thread()
    if not main or not hasattr(signal, "setitimer"):
        yield
        return
    old_handler = signal.getsignal(signal.SIGALRM)
    old_timer = signal.getitimer(signal.ITIMER_REAL)
    started = limit._clock()
    left = limit.remaining()
    if old_timer[0] > 0:
        left = min(left, old_timer[0])

    def expired(*args):
        raise FetchTimeout(f"timed out after {limit.seconds:g} s") from None

    try:
        signal.signal(signal.SIGALRM, expired)
        signal.setitimer(signal.ITIMER_REAL, left)
        yield
    finally:
        # Disarm our deadline before restoring the caller's signal handler.
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)
        if old_timer[0] > 0:
            remaining = max(0.000001, old_timer[0] - (limit._clock() - started))
            signal.setitimer(signal.ITIMER_REAL, remaining, old_timer[1])


@contextmanager
def request_scope(limit: RequestLimit):
    """Protect a direct HTTP call without starting a download worker.

    The refresh runs on the main thread, where SIGALRM can interrupt a
    buffered read (per-chunk checks alone cannot do that). In a threaded
    validation caller, the connect/read socket timeouts bound stalled I/O and
    the whole-request deadline is checked between streamed chunks. A peer that
    continuously sends data can therefore outlast that deadline in a threaded
    caller. DNS alone needs a daemon thread because getaddrinfo has no timeout;
    an uninterruptible resolver can leave that daemon alive until process exit.
    """
    limit.remaining()
    # Install/remove the DNS hook outside our alarm's lifetime, so a deadline
    # cannot interrupt the resolver reference-count update halfway through.
    with _dns_scope(limit):
        with _alarm_scope(limit):
            limit.remaining()
            yield
            limit.remaining()
