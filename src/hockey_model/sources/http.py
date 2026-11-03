"""Polite HTTP fetches: one request at a time per host, with bounded retries."""

import time
import urllib.request
from collections.abc import Callable
from importlib.metadata import version
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

from hockey_model.sources.errors import SourceError
from hockey_model.sources.policy import HOST_POLICIES

Opener = Callable[[urllib.request.Request, float], bytes]

TIMEOUT_S = 30.0
MAX_BACKOFF_S = 30.0


def _default_opener(request: urllib.request.Request, timeout: float) -> bytes:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body: bytes = response.read()
    return body


def _user_agent() -> str:
    return f"hockey-model/{version('hockey-model')}"


def _is_retryable_status(code: int) -> bool:
    return code == 429 or code >= 500


def _backoff_s(attempt: int, retry_after: str | None) -> float:
    if retry_after is not None and retry_after.strip().isdigit():
        return float(retry_after)
    return min(2.0**attempt, MAX_BACKOFF_S)


class HttpClient:
    """Fetch URLs from known hosts, spacing requests and retrying transient failures."""

    def __init__(
        self,
        opener: Opener | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._opener: Opener = _default_opener if opener is None else opener
        self._clock = clock
        self._sleep = sleep
        self._last_start: dict[str, float] = {}

    def get(self, source: str, url: str) -> bytes:
        """Return the response body, or raise ``SourceError`` once retries run out."""
        host = urlsplit(url).hostname or ""
        policy = HOST_POLICIES.get(host)
        if policy is None:
            raise SourceError(source, url, f"no host policy for {host!r}; add it to HOST_POLICIES")
        request = urllib.request.Request(url, headers={"User-Agent": _user_agent()})
        attempts = policy.max_retries + 1
        reason = "no attempt made"
        for attempt in range(attempts):
            self._wait_for_host(host, policy.min_interval_s)
            try:
                return self._opener(request, TIMEOUT_S)
            except HTTPError as exc:
                if not _is_retryable_status(exc.code):
                    raise SourceError(source, url, f"HTTP {exc.code}") from exc
                reason = f"HTTP {exc.code}"
                delay = _backoff_s(attempt, exc.headers.get("Retry-After"))
            except URLError as exc:
                reason = f"network error {exc.reason}"
                delay = _backoff_s(attempt, None)
            if attempt < attempts - 1:
                self._sleep(delay)
        raise SourceError(source, url, f"{reason} after {attempts} attempts")

    def _wait_for_host(self, host: str, min_interval_s: float) -> None:
        last = self._last_start.get(host)
        if last is not None:
            remaining = min_interval_s - (self._clock() - last)
            if remaining > 0:
                self._sleep(remaining)
        self._last_start[host] = self._clock()
