from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
from tenacity import (
    RetryCallState,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config.settings import get_settings
from app.utils.dates import parse_datetime, utcnow

log = logging.getLogger(__name__)

RETRY_STATUSES = {429, 500, 502, 503, 504}
# Longer Retry-After values mean a quota is exhausted (e.g. a daily budget); retrying in-process is pointless.
MAX_RETRY_WAIT_SECONDS = 300.0


class HttpFetchError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class RobotsDisallowed(HttpFetchError):
    pass


class _Retryable(Exception):
    def __init__(self, response: httpx.Response | None, retry_after: float | None):
        super().__init__(f"retryable http failure: {response.status_code if response else 'transport'}")
        self.response = response
        self.retry_after = retry_after


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        when = parse_datetime(value)
        return max(0.0, (when - utcnow()).total_seconds()) if when else None


class PoliteHttpClient:
    """Sequential HTTP client: per-host spacing, retry with Retry-After, optional robots.txt checks."""

    def __init__(
        self,
        *,
        timeout: float | None = None,
        max_retries: int | None = None,
        default_headers: dict[str, str] | None = None,
        min_interval: float = 0.0,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        client: httpx.Client | None = None,
    ):
        settings = get_settings()
        self._timeout = timeout or settings.http_timeout_seconds
        self._max_retries = settings.http_max_retries if max_retries is None else max_retries
        self._default_min_interval = min_interval
        self._host_intervals: dict[str, float] = {}
        self._last_request: dict[str, float] = {}
        self._sleep = sleep
        self._monotonic = monotonic
        self._robots: dict[str, RobotFileParser | None] = {}
        headers = {"User-Agent": settings.user_agent, **(default_headers or {})}
        self._client = client or httpx.Client(headers=headers, timeout=self._timeout, follow_redirects=True)
        self.user_agent = headers["User-Agent"]

    def set_min_interval(self, host: str, seconds: float) -> None:
        self._host_intervals[host] = seconds

    def pace(self, key: str, seconds: float) -> None:
        """Block until `seconds` have passed since the previous call with the same key."""
        self._host_intervals[key] = seconds
        self._throttle(key)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PoliteHttpClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _throttle(self, host: str) -> None:
        interval = self._host_intervals.get(host, self._default_min_interval)
        last = self._last_request.get(host)
        if interval and last is not None:
            wait = interval - (self._monotonic() - last)
            if wait > 0:
                self._sleep(wait)
        self._last_request[host] = self._monotonic()

    def _wait(self, state: RetryCallState) -> float:
        exc = state.outcome.exception() if state.outcome else None
        if isinstance(exc, _Retryable) and exc.retry_after is not None:
            return min(exc.retry_after, MAX_RETRY_WAIT_SECONDS)
        return wait_exponential(multiplier=1, min=1, max=60)(state)

    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        respect_robots: bool = False,
        raise_for_status: bool = True,
        ok_statuses: set[int] | None = None,
        should_retry: Callable[[httpx.Response], float | None] | None = None,
    ) -> httpx.Response:
        host = urlparse(url).netloc
        if respect_robots and not self.robots_allowed(url):
            raise RobotsDisallowed(f"robots.txt disallows fetching {url}")

        def attempt() -> httpx.Response:
            self._throttle(host)
            try:
                response = self._client.request(method, url, params=params, headers=headers)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                raise _Retryable(None, None) from exc
            if response.status_code in RETRY_STATUSES:
                retry_after = parse_retry_after(response.headers.get("Retry-After"))
                if retry_after is None or retry_after <= MAX_RETRY_WAIT_SECONDS:
                    raise _Retryable(response, retry_after)
            elif should_retry is not None:
                wait = should_retry(response)
                if wait is not None and wait <= MAX_RETRY_WAIT_SECONDS:
                    raise _Retryable(response, wait)
            return response

        retrying = Retrying(
            retry=retry_if_exception_type(_Retryable),
            stop=stop_after_attempt(self._max_retries + 1),
            wait=self._wait,
            sleep=self._sleep,
            before_sleep=lambda s: log.warning("retrying http request", extra={"url": url, "attempt": s.attempt_number}),
            reraise=False,
        )
        try:
            response = retrying(attempt)
        except Exception as exc:
            cause = exc.last_attempt.exception() if hasattr(exc, "last_attempt") else exc
            status = cause.response.status_code if isinstance(cause, _Retryable) and cause.response else None
            raise HttpFetchError(f"{method} {url} failed after retries ({cause})", status) from exc

        if raise_for_status and response.status_code >= 400 and response.status_code not in (ok_statuses or set()):
            raise HttpFetchError(f"{method} {url} returned {response.status_code}", response.status_code)
        return response

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def get_json(self, url: str, **kwargs: Any) -> Any:
        return self.get(url, **kwargs).json()

    def robots_allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._robots:
            parser: RobotFileParser | None = RobotFileParser()
            try:
                response = self._client.get(f"{origin}/robots.txt")
                if response.status_code == 200:
                    parser.parse(response.text.splitlines())
                elif response.status_code in (401, 403):
                    parser.disallow_all = True
                else:
                    parser = None  # no robots.txt means no restrictions
            except httpx.HTTPError:
                # Unreachable robots.txt: fail closed.
                parser.disallow_all = True
            self._robots[origin] = parser
        parser = self._robots[origin]
        return True if parser is None else parser.can_fetch(self.user_agent, url)

    def crawl_delay(self, url: str) -> float | None:
        parsed = urlparse(url)
        self.robots_allowed(url)
        parser = self._robots.get(f"{parsed.scheme}://{parsed.netloc}")
        if parser is None:
            return None
        delay = parser.crawl_delay(self.user_agent)
        return float(delay) if delay is not None else None
