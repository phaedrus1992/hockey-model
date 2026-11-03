"""Tests for the polite HTTP client. No test touches the network."""

import io
import urllib.request
from email.message import Message
from http.client import HTTPMessage, IncompleteRead
from urllib.error import HTTPError, URLError

import pytest

import hockey_model.sources.http as http_module
from hockey_model.sources.errors import SourceError
from hockey_model.sources.http import HttpClient, _PolicyRedirect, _Refused

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


@pytest.mark.parametrize("retry_after", ["86400", "999999"])
def test_retry_after_is_capped(retry_after: str) -> None:
    clock = FakeClock()
    opener = ScriptedOpener([_http_error(429, retry_after=retry_after), b"body"])
    assert _client(opener, clock).get("nhl", NHL_URL) == b"body"
    assert clock.sleeps == [http_module.MAX_BACKOFF_S]


@pytest.mark.parametrize("retry_after", ["²", "soon", "-3", "9" * 400])
def test_malformed_retry_after_falls_back_to_backoff(retry_after: str) -> None:
    clock = FakeClock()
    opener = ScriptedOpener([_http_error(503, retry_after=retry_after), b"body"])
    assert _client(opener, clock).get("nhl", NHL_URL) == b"body"
    assert clock.sleeps == [1.0]


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


@pytest.mark.parametrize(
    "failure",
    [TimeoutError("read timed out"), ConnectionResetError("reset"), IncompleteRead(b"")],
)
def test_get_retries_failure_while_reading_body(failure: BaseException) -> None:
    clock = FakeClock()
    opener = ScriptedOpener([failure, b"body"])
    assert _client(opener, clock).get("nhl", NHL_URL) == b"body"


def test_get_wraps_read_failure_after_last_retry() -> None:
    clock = FakeClock()
    opener = ScriptedOpener([TimeoutError("slow")] * 4)
    with pytest.raises(SourceError, match="network error"):
        _client(opener, clock).get("nhl", NHL_URL)


def test_get_raises_on_404_without_retry() -> None:
    clock = FakeClock()
    opener = ScriptedOpener([_http_error(404)])
    with pytest.raises(SourceError, match="404"):
        _client(opener, clock).get("nhl", NHL_URL)
    assert len(opener.requests) == 1


def test_get_rejects_unknown_host_before_any_request() -> None:
    opener = ScriptedOpener([])
    with pytest.raises(ValueError, match="no host policy") as info:
        _client(opener, FakeClock()).get("example", "https://example.com/x")
    assert "add it to HOST_POLICIES" in str(info.value)
    assert opener.requests == []


@pytest.mark.parametrize("url", ["http://api-web.nhle.com/x", "ftp://api-web.nhle.com/x"])
def test_get_rejects_non_https_before_any_request(url: str) -> None:
    opener = ScriptedOpener([])
    with pytest.raises(ValueError, match="not https"):
        _client(opener, FakeClock()).get("nhl", url)
    assert opener.requests == []


def test_redirect_to_unlisted_host_is_refused() -> None:
    handler = _PolicyRedirect()
    request = urllib.request.Request(NHL_URL)
    with pytest.raises(_Refused, match="not allowed"):
        handler.redirect_request(
            request, io.BytesIO(), 302, "Found", HTTPMessage(), "https://evil.test/x"
        )


def test_redirect_to_listed_https_host_is_followed() -> None:
    handler = _PolicyRedirect()
    request = urllib.request.Request(NHL_URL)
    redirected = handler.redirect_request(
        request, io.BytesIO(), 302, "Found", HTTPMessage(), "https://api-web.nhle.com/v2/x"
    )
    assert redirected is not None
    assert redirected.full_url == "https://api-web.nhle.com/v2/x"


class _OversizeResponse:
    def __enter__(self) -> _OversizeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return b"x" * size


class _OversizeOpener:
    def open(self, request: urllib.request.Request, timeout: float) -> _OversizeResponse:
        del request, timeout
        return _OversizeResponse()


def test_default_opener_refuses_oversize_body(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http_module, "_OPENER", _OversizeOpener())
    request = urllib.request.Request(NHL_URL)
    with pytest.raises(_Refused, match="larger than"):
        http_module._default_opener(request, 1.0)


def test_source_error_message_names_operation_and_reason() -> None:
    error = SourceError("nhl", NHL_URL, "HTTP 404")
    assert str(error) == f"fetch nhl {NHL_URL}: HTTP 404"
