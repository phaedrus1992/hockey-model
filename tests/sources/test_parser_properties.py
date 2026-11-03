"""Property tests: a parser raises only its named errors, whatever the input is."""

import copy
import csv
import io
import json
import re
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from hockey_model.sources.daily_faceoff import parse_starters
from hockey_model.sources.espn import parse_injuries, parse_scoreboard_starters
from hockey_model.sources.moneypuck import parse_goalie_games, parse_team_games
from hockey_model.sources.nhl import parse_boxscore, parse_score_day
from hockey_model.sources.payload import utc_field
from hockey_model.sources.shape_errors import SourceParseError, SourceShapeError

FIXTURES = Path(__file__).parent.parent / "fixtures"
NAMED_ERRORS = (SourceParseError, SourceShapeError)
SLOW = settings(max_examples=60, deadline=None, suppress_health_check=list(HealthCheck))

JSON_VALUES = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=True) | st.text(max_size=8),
    lambda children: (
        st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=8), children, max_size=4)
    ),
    max_leaves=12,
)


def load(name: str) -> object:
    return json.loads((FIXTURES / name).read_text())


def containers(value: object, path: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    """Return the path to every dict key and list index in ``value``."""
    found: list[tuple[object, ...]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            found.append((*path, key))
            found.extend(containers(item, (*path, key)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.append((*path, index))
            found.extend(containers(item, (*path, index)))
    return found


def replaced(payload: object, path: tuple[object, ...], new: object) -> object:
    """Return a copy of ``payload`` with the value at ``path`` replaced by ``new``."""
    result = copy.deepcopy(payload)
    target: Any = result
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = new
    return result


def only_named_errors(parse, payload: object) -> None:
    try:
        result = parse(payload)
    except NAMED_ERRORS:
        return
    assert result is not None


@given(JSON_VALUES)
def test_nhl_parsers_reject_any_json_with_a_named_error(value: object) -> None:
    only_named_errors(parse_score_day, value)
    only_named_errors(parse_boxscore, value)


@given(JSON_VALUES)
def test_espn_parsers_reject_any_json_with_a_named_error(value: object) -> None:
    only_named_errors(parse_scoreboard_starters, value)
    only_named_errors(parse_injuries, value)


@SLOW
@given(st.data())
def test_a_changed_fixture_never_escapes_as_an_unnamed_error(data: st.DataObject) -> None:
    cases = [
        (parse_score_day, "nhl/score_2026-01-10.json"),
        (parse_boxscore, "nhl/boxscore_2025020709.json"),
        (parse_scoreboard_starters, "espn/scoreboard_20261103.json"),
        (parse_injuries, "espn/injuries.json"),
    ]
    parse, name = data.draw(st.sampled_from(cases))
    payload = load(name)
    path = data.draw(st.sampled_from(containers(payload)))
    only_named_errors(parse, replaced(payload, path, data.draw(JSON_VALUES)))


@given(st.text(max_size=200))
def test_daily_faceoff_rejects_any_text_with_a_named_error(text: str) -> None:
    only_named_errors(parse_starters, text)


@given(JSON_VALUES)
def test_daily_faceoff_rejects_any_embedded_json_with_a_named_error(value: object) -> None:
    page = f'<script id="__NEXT_DATA__">{json.dumps(value, allow_nan=True)}</script>'
    only_named_errors(parse_starters, page)


@given(st.text(max_size=300))
def test_moneypuck_team_parser_rejects_any_text_with_a_named_error(text: str) -> None:
    only_named_errors(parse_team_games, text)


@given(st.binary(max_size=300))
def test_moneypuck_goalie_parser_rejects_any_bytes_with_a_named_error(data: bytes) -> None:
    only_named_errors(parse_goalie_games, data)


@SLOW
@given(st.data())
def test_moneypuck_team_rows_do_not_depend_on_column_order(data: st.DataObject) -> None:
    text = (FIXTURES / "moneypuck" / "all_teams_sample.csv").read_text()
    rows = list(csv.reader(io.StringIO(text)))
    order = data.draw(st.permutations(range(len(rows[0]))))
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    for row in rows:
        writer.writerow([row[i] for i in order])
    assert parse_team_games(out.getvalue()) == parse_team_games(text)


def test_the_property_helpers_find_paths_in_a_fixture() -> None:
    assert len(containers(load("espn/scoreboard_20261103.json"))) > 100


def _box_with_toi(toi: str) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(
        (FIXTURES / "nhl" / "boxscore_2025020709.json").read_text()
    )
    payload["playerByGameStats"]["homeTeam"]["forwards"][0]["toi"] = toi
    return payload


@given(minutes=st.integers(0, 999), seconds=st.integers(0, 59))
def test_time_on_ice_is_minutes_times_sixty_plus_seconds(minutes: int, seconds: int) -> None:
    rows = parse_boxscore(_box_with_toi(f"{minutes}:{seconds:02d}"))
    assert rows.skaters[0].toi_seconds == 60 * minutes + seconds


@given(minutes=st.integers(0, 999), seconds=st.integers(60, 99))
def test_time_on_ice_with_sixty_or_more_seconds_is_rejected(minutes: int, seconds: int) -> None:
    with pytest.raises(SourceParseError, match="MM:SS"):
        parse_boxscore(_box_with_toi(f"{minutes}:{seconds}"))


_MOMENTS = st.datetimes(
    min_value=datetime(1990, 1, 1), max_value=datetime(2100, 1, 1), timezones=st.just(UTC)
)
_OFFSETS = st.integers(-14 * 60, 14 * 60).map(lambda m: timezone(timedelta(minutes=m)))


@given(moment=_MOMENTS, offset=_OFFSETS)
def test_utc_field_returns_the_same_instant_in_utc(moment: datetime, offset: timezone) -> None:
    local = moment.astimezone(offset)
    found = utc_field("nhl", {"d": local.isoformat()}, "d", "a game")
    assert found == moment
    assert found.utcoffset() == timedelta(0)


@given(moment=st.datetimes(min_value=datetime(1990, 1, 1), max_value=datetime(2100, 1, 1)))
def test_utc_field_rejects_a_time_with_no_zone(moment: datetime) -> None:
    with pytest.raises(SourceParseError, match="no timezone"):
        utc_field("nhl", {"d": moment.isoformat()}, "d", "a game")


def _team_text_with(**changes: str) -> str:
    text = (FIXTURES / "moneypuck" / "all_teams_sample.csv").read_text()
    lines = text.splitlines()
    header = lines[0].split(",")
    for index, line in enumerate(lines[1:], start=1):
        cells = line.split(",")
        if cells[header.index("situation")] != "all":
            continue
        for column, value in changes.items():
            cells[header.index(column)] = value
        lines[index] = ",".join(cells)
        break
    return "\n".join(lines) + "\n"


@given(value=st.floats(min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False))
def test_a_moneypuck_number_written_with_repr_reads_back_exactly(value: float) -> None:
    rows = parse_team_games(_team_text_with(xGoalsFor=repr(value)))
    assert rows[0].xg_for == value


@given(text=st.text(max_size=12).filter(lambda t: not re.fullmatch(r"[0-9.eE+-]+", t)))
def test_a_moneypuck_number_with_other_characters_is_rejected(text: str) -> None:
    if "," in text or "\n" in text or "\r" in text or '"' in text:
        return
    with pytest.raises(NAMED_ERRORS):
        parse_team_games(_team_text_with(xGoalsFor=text))
