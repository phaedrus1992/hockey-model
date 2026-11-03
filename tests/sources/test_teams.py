"""Tests for the NHL team code maps across sources and seasons."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from hockey_model.sources.shape_errors import SourceParseError, SourceShapeError
from hockey_model.sources.teams import (
    NHL_TEAM_CODES,
    franchise,
    from_daily_faceoff,
    from_espn,
    from_moneypuck,
)

ESPN_RENAMED = {"LAK", "NJD", "SJS", "TBL", "ARI"}


def test_nhl_team_codes_has_32_current_teams_plus_arizona() -> None:
    assert len(NHL_TEAM_CODES) == 33
    assert "ARI" in NHL_TEAM_CODES
    assert "UTA" in NHL_TEAM_CODES


@pytest.mark.parametrize(
    ("code", "expected"),
    [("ARI", "UTA"), ("UTA", "UTA"), ("TOR", "TOR")],
)
def test_franchise_maps_arizona_to_utah(code: str, expected: str) -> None:
    assert franchise(code) == expected


@pytest.mark.parametrize(
    ("espn", "nhl"),
    [("LA", "LAK"), ("NJ", "NJD"), ("SJ", "SJS"), ("TB", "TBL")],
)
def test_from_espn_maps_renamed_codes(espn: str, nhl: str) -> None:
    assert from_espn(espn) == nhl


@given(st.sampled_from(sorted(NHL_TEAM_CODES - ESPN_RENAMED)))
def test_from_espn_keeps_unchanged_codes(code: str) -> None:
    assert from_espn(code) == code


def test_from_espn_rejects_unknown_code_and_names_it() -> None:
    with pytest.raises(SourceShapeError, match="UTAH") as info:
        from_espn("UTAH")
    assert "add it to sources/teams.py" in str(info.value)


def test_franchise_rejects_unknown_code() -> None:
    with pytest.raises(SourceShapeError, match="UTAH"):
        franchise("UTAH")


@given(st.text(max_size=8))
def test_from_espn_returns_known_code_or_raises_shape_error(code: str) -> None:
    try:
        result = from_espn(code)
    except SourceShapeError:
        return
    assert result in NHL_TEAM_CODES


def test_a_shape_error_keeps_its_source_and_value() -> None:
    error = SourceShapeError("espn", "XXX")
    assert (error.source, error.value) == ("espn", "XXX")
    assert str(error) == "map espn team code 'XXX': unknown code; add it to sources/teams.py"
    parse = SourceParseError("nhl", "field 'id' is missing")
    assert (parse.source, parse.detail) == ("nhl", "field 'id' is missing")
    assert str(parse) == "read nhl data: field 'id' is missing"


@pytest.mark.parametrize(
    ("call", "source"),
    [
        (franchise, "franchise"),
        (from_espn, "espn"),
        (from_moneypuck, "moneypuck"),
        (from_daily_faceoff, "daily_faceoff"),
    ],
)
def test_each_map_names_its_source_in_the_error(call, source: str) -> None:
    with pytest.raises(SourceShapeError) as caught:
        call("QQQ")
    assert (caught.value.source, caught.value.value) == (source, "QQQ")
