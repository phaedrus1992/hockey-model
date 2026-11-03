"""Tests for the thin JSON CLI wrapper."""

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from hockey_model import cli
from hockey_model.cli import CliRuntime
from hockey_model.identity import Catalog
from hockey_model.models import FixedStatModel
from hockey_model.sources.errors import SourceError
from hockey_model.types import Player, Projection, Roster, Slot, Standing

PLAYER_PROJECTION = Projection(0.4, 0.1, 0.7, 0.8)


def _player(canonical_id: str, name: str = "A Player", *, yahoo_id: str | None = None) -> Player:
    return Player(canonical_id, yahoo_id, None, name, frozenset({Slot.C}), "TOR")


class Joint:
    def project_total(
        self, players: Sequence[Player], stat: str, horizon_games: int, level: float
    ) -> Projection:
        return Projection(float(len(players)), 0.0, 2.0, level)


class Game:
    def win_probabilities(self, home: Roster, away: Roster) -> tuple[float, float]:
        return 0.6, 0.4

    def expected_goals(self, team: Roster, level: float) -> Projection:
        return Projection(3.0, 1.0, 5.0, level)


class Playoffs:
    def playoff_odds(
        self, team_code: str, standings: Sequence[Standing], level: float
    ) -> Projection:
        return Projection(0.7, 0.5, 0.9, level)


def _runtime(players: tuple[Player, ...]) -> CliRuntime:
    table = {(player.canonical_id, "goals"): PLAYER_PROJECTION for player in players}
    return CliRuntime(
        Catalog(players),
        FixedStatModel(table),
        Joint(),
        Game(),
        Playoffs(),
        (Standing("TOR", 10, 12, 5, 8),),
    )


def _write_roster(path: Path, player_id: str) -> None:
    path.write_text(
        json.dumps(
            {
                "name": player_id,
                "players": [
                    {
                        "canonical_id": player_id,
                        "full_name": player_id,
                        "eligible": ["C"],
                        "team_code": "TOR",
                    }
                ],
                "slots": {player_id: "C"},
            }
        )
    )


def test_player_subcommand_prints_projection_json(capsys: pytest.CaptureFixture[str]) -> None:
    runtime = _runtime((_player("p-a"),))
    assert cli.main(["player", "goals", "p-a"], runtime) == 0
    output = json.loads(capsys.readouterr().out)
    assert output == {"high": 0.7, "level": 0.8, "low": 0.1, "point": 0.4}


def test_ambiguous_name_exits_two_and_names_candidates(
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = _runtime((_player("p-a", "Sam Smith"), _player("p-b", "Sam Smith")))
    assert cli.main(["player", "goals", "Sam Smith"], runtime) == 2
    error = capsys.readouterr().err
    assert "p-a" in error and "p-b" in error


def test_unknown_subcommand_exits_two(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["nonsense"]) == 2
    assert "invalid choice" in capsys.readouterr().err


def test_known_command_without_runtime_exits_two(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["player", "goals", "p-a"]) == 2
    assert "no models are configured" in capsys.readouterr().err


def test_player_subcommand_resolves_numeric_string_id(capsys: pytest.CaptureFixture[str]) -> None:
    player = _player("p-a", yahoo_id="123")
    assert cli.main(["player", "goals", "123"], _runtime((player,))) == 0
    assert json.loads(capsys.readouterr().out)["point"] == 0.4


def test_team_matchup_and_playoff_commands_print_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    player = _player("p-a")
    runtime = _runtime((player,))
    home = tmp_path / "home.json"
    away = tmp_path / "away.json"
    _write_roster(home, "p-a")
    _write_roster(away, "p-b")

    assert cli.main(["team", "goals", str(home)], runtime) == 0
    assert json.loads(capsys.readouterr().out)["total"]["point"] == 1.0
    assert cli.main(["matchup", str(home), str(away)], runtime) == 0
    assert json.loads(capsys.readouterr().out)["home_win"] == 0.6
    assert cli.main(["playoffs", "TOR"], runtime) == 0
    assert json.loads(capsys.readouterr().out)["point"] == 0.7


def test_bad_roster_file_exits_two(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("[]")
    assert cli.main(["team", "goals", str(bad)], _runtime((_player("p-a"),))) == 2
    assert "root must be" in capsys.readouterr().err


@pytest.mark.parametrize(
    "change",
    [
        {"slots": []},
        {"players": "not-an-array"},
        {"players": [{"canonical_id": None, "full_name": "x", "eligible": ["C"]}]},
        {"players": [{"canonical_id": "x", "full_name": [], "eligible": ["C"]}]},
        {"players": [{"canonical_id": "x", "full_name": "x", "eligible": ["C"], "nhl_id": True}]},
    ],
)
def test_malformed_roster_fields_exit_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], change: dict[str, object]
) -> None:
    roster = {"name": "bad", "players": [], "slots": None} | change
    path = tmp_path / "bad-fields.json"
    path.write_text(json.dumps(roster))
    assert cli.main(["team", "goals", str(path)], _runtime((_player("p-a"),))) == 2
    assert "invalid roster fields" in capsys.readouterr().err


def test_roster_property_parses_valid_dicts(tmp_path: Path) -> None:
    for name, cid, fname in [
        ("team-a", "p-1", "Player One"),
        ("team-b", "p-2", "Player Two"),
        ("team-c", "p-3", "Player Three"),
    ]:
        roster = {
            "name": name,
            "players": [{"canonical_id": cid, "full_name": fname, "eligible": ["C"]}],
            "slots": None,
        }
        path = tmp_path / f"{cid}.json"
        path.write_text(json.dumps(roster))
        result = cli._roster(path)
        assert isinstance(result, Roster)
        assert result.name == name


def test_empty_player_reference_exits_two(capsys: pytest.CaptureFixture[str]) -> None:
    runtime = _runtime((_player("p-a"),))
    assert cli.main(["player", "goals", ""], runtime) == 2
    assert "must not be empty" in capsys.readouterr().err


class _RefreshClient:
    """Stands in for HttpClient: every request fails, so each source reports an error."""

    def get(self, source: str, url: str) -> bytes:
        raise SourceError(source, url, "HTTP 503")


def test_cli_refresh_requires_db_env(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("HOCKEY_MODEL_DB", raising=False)
    assert cli.main(["refresh"]) == 2
    assert "HOCKEY_MODEL_DB" in capsys.readouterr().err


def test_cli_refresh_exits_one_on_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setenv("HOCKEY_MODEL_DB", str(tmp_path / "store.db"))
    monkeypatch.setattr("hockey_model.store_cli.HttpClient", _RefreshClient)
    code = cli.main(["refresh", "--backfill-from", "2026-01-10"])
    report = json.loads(capsys.readouterr().out)
    assert code == 1
    assert report["errors"]
    assert report["errors"][0]["type"] == "SourceError"
    assert report["credits"] == []


def test_cli_refresh_rejects_bad_backfill_date(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOCKEY_MODEL_DB", str(tmp_path / "store.db"))
    assert cli.main(["refresh", "--backfill-from", "yesterday"]) == 2
