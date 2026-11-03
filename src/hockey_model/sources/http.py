"""Polite HTTP fetches: one request at a time per host, with bounded retries."""

import logging
import re
import time
import urllib.request
from collections.abc import Callable
from http.client import HTTPException, HTTPMessage
from importlib.metadata import PackageNotFoundError, version
from typing import IO
from urllib.error import HTTPError
from urllib.parse import urlsplit

from hockey_model.sources.errors import SourceError
from hockey_model.sources.policy import HOST_POLICIES, HostPolicy
from hockey_model.types import HockeyModelError

Opener = Callable[[urllib.request.Request, float], bytes]

_LOG = logging.getLogger(__name__)
TIMEOUT_S = 30.0
MAX_BACKOFF_S = 30.0
# A response larger than this is refused rather than read into memory.
MAX_BODY_BYTES = 64 * 1024 * 1024
# ASCII digits only. str.isdigit() also accepts characters that float() rejects.
_RETRY_AFTER = re.compile(r"[0-9]{1,6}")


class _Refused(Exception):
    """A response the client will not accept: a redirect off the allowlist, or too large."""


class _PolicyRedirect(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only to a host on the allowlist, over https."""

    def redirect_request(  # noqa: PLR0913  # the base class fixes this signature
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        try:
            _policy_for(newurl)
        except (ValueError, HockeyModelError) as exc:
            raise _Refused(f"redirect to {newurl!r} is not allowed: {exc}") from exc
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_PolicyRedirect)


def _default_opener(request: urllib.request.Request, timeout: float) -> bytes:
    with _OPENER.open(request, timeout=timeout) as response:
        body: bytes = response.read(MAX_BODY_BYTES + 1)
    if len(body) > MAX_BODY_BYTES:
        raise _Refused(f"response is larger than {MAX_BODY_BYTES} bytes; raise MAX_BODY_BYTES")
    return body


def _policy_for(url: str) -> HostPolicy:
    """Return the host policy for ``url``, or raise ``ValueError`` naming the fix."""
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise ValueError(f"fetch {url!r}: scheme {parts.scheme!r} is not https; use https")
    host = parts.hostname or ""
    policy = HOST_POLICIES.get(host)
    if policy is None:
        raise ValueError(f"fetch {url!r}: no host policy for {host!r}; add it to HOST_POLICIES")
    return policy


def _user_agent() -> str:
    try:
        package_version = version("hockey-model")
    except PackageNotFoundError as exc:
        raise HockeyModelError(
            "read package version: hockey-model is not installed; run uv sync"
        ) from exc
    return f"hockey-model/{package_version}"


def _is_retryable_status(code: int) -> bool:
    return code == 429 or code >= 500


def _backoff_s(attempt: int, retry_after: str | None) -> float:
    if retry_after is not None and _RETRY_AFTER.fullmatch(retry_after.strip()):
        return min(float(retry_after.strip()), MAX_BACKOFF_S)
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
        """Return the response body, or raise ``SourceError`` once retries run out.

        Raises ``ValueError`` for a URL that is not https or whose host has no policy.
        """
        policy = _policy_for(url)
        host = urlsplit(url).hostname or ""
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
            except _Refused as exc:
                raise SourceError(source, url, str(exc)) from exc
            except (OSError, HTTPException) as exc:
                reason = f"network error {exc}"
                delay = _backoff_s(attempt, None)
            if attempt < attempts - 1:
                _LOG.debug("retry %s %s after attempt %d: %s", source, url, attempt + 1, reason)
                self._sleep(delay)
        raise SourceError(source, url, f"{reason} after {attempts} attempts")

    def _wait_for_host(self, host: str, min_interval_s: float) -> None:
        last = self._last_start.get(host)
        if last is not None:
            remaining = min_interval_s - (self._clock() - last)
            if remaining > 0:
                self._sleep(remaining)
        self._last_start[host] = self._clock()
