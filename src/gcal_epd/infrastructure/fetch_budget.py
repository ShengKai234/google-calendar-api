"""Shared monotonic fetch deadlines, independent of either HTTP library.

Socket read timeouts reset after each read. Even a streaming read can wait
forever for a chunk to fill, so an isolated, killable worker supplies the
hard wall-clock bound. No worker or network operation starts once the shared
refresh budget is exhausted. Spawn also works from the onboarding thread;
no signals, inherited thread locks, or global socket defaults are needed.
"""
import multiprocessing
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
    """Safe transport failure: never transfer exception text containing URLs."""
    def __init__(self, kind: str, status: int | None = None):
        super().__init__(kind)
        self.status = status


class RequestLimit:
    def __init__(self, seconds: float = REQUEST_TIMEOUT,
                 clock: Callable[[], float] = time.monotonic,
                 deadline: float = float("inf")):
        self._clock = clock
        self._end = min(clock() + seconds, deadline)

    def remaining(self) -> float:
        left = self._end - self._clock()
        if left <= 0:
            raise FetchTimeout("request deadline reached")
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
            raise BudgetSpent("refresh fetch budget exhausted")
        return RequestLimit(seconds, clock=self._clock, deadline=self._end)


def _worker(pipe, operation, args, limit):
    try:
        try:
            result = (True, operation(*args, limit))
        except Exception as error:
            # HTTP status is useful for onboarding; error strings and response
            # bodies can contain feed tokens and never cross this boundary.
            status = getattr(getattr(error, "response", None), "status_code", None)
            result = (False, type(error).__name__, status)
        pipe.send(result)
    finally:
        pipe.close()


def run_bounded(operation, args: tuple, limit: RequestLimit) -> bytes:
    """Run one download within its total deadline, then reap its worker.

    The deadline includes process startup, DNS, redirects, headers, and body.
    Parent-side poll prevents a blocked read inside either library from
    consuming the rest of the refresh. The worker streams and checks the
    same absolute monotonic deadline as well.
    """
    limit.remaining()
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    worker = context.Process(target=_worker, args=(sender, operation, args, limit),
                             daemon=True)
    try:
        worker.start()
        sender.close()
        if not receiver.poll(limit.remaining()):
            raise FetchTimeout("request deadline reached")
        result = receiver.recv()
        limit.remaining()
        if result[0]:
            return result[1]
        if result[1] == "FetchTimeout":
            raise FetchTimeout("request deadline reached")
        raise FetchFailure(result[1], result[2])
    except EOFError:
        raise FetchFailure("download worker exited") from None
    finally:
        receiver.close()
        sender.close()
        if worker.pid is not None:
            if worker.is_alive():
                worker.kill()
            worker.join()
        worker.close()
