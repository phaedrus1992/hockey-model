"""Typed field readers for parsed JSON, so a changed source shape fails with a named error."""

import json
from collections.abc import Mapping
from datetime import UTC, datetime

from hockey_model.sources.http import HttpClient
from hockey_model.sources.shape_errors import SourceParseError


def as_mapping(source: str, value: object, where: str) -> Mapping[str, object]:
    """Return ``value`` as a mapping, or raise naming ``where``."""
    if not isinstance(value, Mapping):
        raise SourceParseError(source, f"{where} must be an object, got {type(value).__name__}")
    return value


def as_list(source: str, value: object, where: str) -> list[object]:
    """Return ``value`` as a list, or raise naming ``where``."""
    if not isinstance(value, list):
        raise SourceParseError(source, f"{where} must be a list, got {type(value).__name__}")
    return value


def field(source: str, obj: Mapping[str, object], key: str, where: str) -> object:
    """Return ``obj[key]``, or raise naming the missing key."""
    if key not in obj:
        raise SourceParseError(source, f"{where} has no {key!r} field")
    return obj[key]


def int_field(source: str, obj: Mapping[str, object], key: str, where: str) -> int:
    """Return an integer field. A bool is not an integer here."""
    value = field(source, obj, key, where)
    if isinstance(value, bool) or not isinstance(value, int):
        raise SourceParseError(source, f"{where} field {key!r} must be an integer, got {value!r}")
    return value


def str_field(source: str, obj: Mapping[str, object], key: str, where: str) -> str:
    """Return a non-empty string field."""
    value = field(source, obj, key, where)
    if not isinstance(value, str) or not value:
        raise SourceParseError(source, f"{where} field {key!r} must be a string, got {value!r}")
    return value


def utc_field(source: str, obj: Mapping[str, object], key: str, where: str) -> datetime:
    """Return an ISO 8601 field as a timezone-aware UTC datetime."""
    text = str_field(source, obj, key, where)
    try:
        moment = datetime.fromisoformat(text)
    except ValueError as exc:
        raise SourceParseError(source, f"{where} field {key!r} is not ISO 8601: {text!r}") from exc
    if moment.tzinfo is None:
        raise SourceParseError(source, f"{where} field {key!r} has no timezone: {text!r}")
    return moment.astimezone(UTC)


def get_json_text(source: str, text: str | bytes, where: str) -> object:
    """Parse JSON text, or raise naming ``where``."""
    try:
        return json.loads(text)
    except ValueError as exc:
        raise SourceParseError(source, f"{where} is not valid JSON: {exc}") from exc


def get_json(client: HttpClient, source: str, url: str) -> object:
    """Fetch ``url`` and parse the body as JSON."""
    return get_json_text(source, client.get(source, url), url)
