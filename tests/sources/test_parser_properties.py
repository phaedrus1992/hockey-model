"""Property tests: a parser raises only its named errors, whatever the input is."""

import copy
import csv
import io
import json
from pathlib import Path
from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from hockey_model.sources.daily_faceoff import parse_starters
from hockey_model.sources.espn import parse_injuries, parse_scoreboard_starters
from hockey_model.sources.moneypuck import parse_goalie_games, parse_team_games
from hockey_model.sources.nhl import parse_boxscore, parse_score_day
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
