"""Tests for the polite HTTP client. No test touches the network."""

import urllib.request
from email.message import Message
from urllib.error import HTTPError, URLError

import pytest

from hockey_model.sources.errors import SourceError
from hockey_model.sources.http import HttpClient

NHL_URL = "https://api-web.nhle.com/v1/schedule/now"


class FakeClock:
    """A clock that advances only when the fake sleep runs."""

    def __init__(self, now: float = 0.0) -> None:
        self.now = now
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class ScriptedOpener:
    """Return or raise the scripted outcomes in order, and record each request."""

    def __init__(self, outcomes: list[bytes | BaseException]) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[urllib.request.Request] = []

    def __call__(self, request: urllib.request.Request, timeout: float) -> bytes:
        del timeout
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _http_error(code: int, retry_after: str | None = None) -> HTTPError:
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return HTTPError(NHL_URL, code, f"status {code}", headers, None)


def _client(opener: ScriptedOpener, clock: FakeClock) -> HttpClient:
    return HttpClient(opener=opener, clock=clock, sleep=clock.sleep)


def test_get_sends_user_agent() -> None:
    opener = ScriptedOpener([b"ok"])
    _client(opener, FakeClock()).get("nhl", NHL_URL)
    user_agent = opener.requests[0].get_header("User-agent")
    assert user_agent is not None
    assert user_agent.startswith("hockey-model/")


def test_get_returns_body() -> None:
    opener = ScriptedOpener([b"payload"])
    assert _client(opener, FakeClock()).get("nhl", NHL_URL) == b"payload"


def test_get_spaces_requests_per_host() -> None:
    clock = FakeClock(now=0.0)
    opener = ScriptedOpener([b"a", b"b"])
    client = _client(opener, clock)
    client.get("nhl", NHL_URL)
    clock.now = 0.1
    client.get("nhl", NHL_URL)
    assert clock.sleeps == [pytest.approx(0.4)]


def test_get_retries_429_with_retry_after() -> None:
    clock = FakeClock()
    opener = ScriptedOpener([_http_error(429, retry_after="7"), b"body"])
    assert _client(opener, clock).get("nhl", NHL_URL) == b"body"
    assert 7.0 in clock.sleeps


def test_get_raises_after_last_retry() -> None:
    clock = FakeClock()
    opener = ScriptedOpener([_http_error(503)] * 4)
    with pytest.raises(SourceError, match="503") as info:
        _client(opener, clock).get("nhl", NHL_URL)
    assert info.value.source == "nhl"
    assert info.value.url == NHL_URL
    assert len(opener.requests) == 4


def test_get_retries_network_error_then_succeeds() -> None:
    clock = FakeClock()
    opener = ScriptedOpener([URLError("reset"), b"body"])
    assert _client(opener, clock).get("nhl", NHL_URL) == b"body"
    assert 1.0 in clock.sleeps


def test_get_raises_on_404_without_retry() -> None:
    clock = FakeClock()
    opener = ScriptedOpener([_http_error(404)])
    with pytest.raises(SourceError, match="404"):
        _client(opener, clock).get("nhl", NHL_URL)
    assert len(opener.requests) == 1


def test_get_rejects_unknown_host() -> None:
    opener = ScriptedOpener([])
    with pytest.raises(SourceError, match="no host policy") as info:
        _client(opener, FakeClock()).get("example", "https://example.com/x")
    assert info.value.reason.startswith("no host policy")
    assert opener.requests == []


def test_source_error_message_names_operation_and_fix() -> None:
    error = SourceError("nhl", NHL_URL, "HTTP 404")
    assert str(error) == (f"fetch nhl {NHL_URL}: HTTP 404; the stored data stays in use")
