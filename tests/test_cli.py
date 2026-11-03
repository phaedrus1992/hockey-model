"""Tests for the thin JSON CLI wrapper."""

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
from seeding import add_game

from hockey_model import cli
from hockey_model.backtest.metrics import calibration
from hockey_model.backtest.runner import BacktestReport, GameRecord, ScoredRun
from hockey_model.cli import CliRuntime
from hockey_model.identity import Catalog
from hockey_model.models import FixedStatModel
from hockey_model.sources.errors import SourceError
from hockey_model.store.db import connect
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


def _store_with_games(path: Path) -> None:
    conn = connect(path)
    add_game(conn, 2015020001, "2015-11-01T00:00", season=20152016)
    add_game(conn, 2015020002, "2015-11-03T00:00", season=20152016, home="BOS", away="TOR")
    add_game(conn, 2015020003, "2015-11-05T00:00", season=20152016, score=(1, 4))
    add_game(conn, 2025020001, "2026-12-01T00:00", state="FUT", season=20262027)
    conn.commit()
    conn.close()


def test_cli_fit_requires_through_season(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOCKEY_MODEL_DB", str(tmp_path / "store.db"))
    assert cli.main(["fit"]) == 2


def test_cli_fit_rejects_unknown_feature(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setenv("HOCKEY_MODEL_DB", str(tmp_path / "store.db"))
    code = cli.main(["fit", "--through-season", "20152016", "--features", "luck"])
    assert code == 2
    assert "luck" in capsys.readouterr().err


def test_cli_fit_with_no_games_says_to_refresh(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setenv("HOCKEY_MODEL_DB", str(tmp_path / "store.db"))
    assert cli.main(["fit", "--through-season", "20152016"]) == 2
    assert "hockey-model refresh" in capsys.readouterr().err


def test_cli_fit_saves_a_fit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    db = tmp_path / "store.db"
    _store_with_games(db)
    monkeypatch.setenv("HOCKEY_MODEL_DB", str(db))
    code = cli.main(["fit", "--through-season", "20152016", "--features", "rest"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["games"] == 3
    assert out["features"] == ["rest"]
    assert out["through_season"] == 20152016
    assert out["diagnostics"]["gradient_norm"] < 1e-6
    assert out["diagnostics"]["stop_reason"].startswith("converged")


def test_cli_fit_with_empty_features_saves_the_elo_alone(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setenv("HOCKEY_MODEL_DB", str(tmp_path / "store.db"))
    code = cli.main(["fit", "--through-season", "20252026", "--features", ""])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert (out["features"], out["elo_weight"], out["intercept"]) == ([], 1.0, 0.0)
    assert out["diagnostics"] is None


def test_cli_game_prints_prediction(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    db = tmp_path / "store.db"
    _store_with_games(db)
    monkeypatch.setenv("HOCKEY_MODEL_DB", str(db))
    assert cli.main(["fit", "--through-season", "20152016"]) == 0
    capsys.readouterr()
    assert cli.main(["game", "2025020001", "--level", "0.9"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["home_win"] + out["away_win"] == pytest.approx(1.0)
    assert out["home_goals"]["level"] == 0.9
    assert out["made_after_start"] is False
    assert isinstance(out["missing"], list)


def test_cli_game_unknown_id(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setenv("HOCKEY_MODEL_DB", str(tmp_path / "store.db"))
    assert cli.main(["game", "123"]) == 2
    err = capsys.readouterr().err
    assert "123" in err
    assert "hockey-model refresh" in err


def test_cli_game_without_a_fit_says_to_fit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    db = tmp_path / "store.db"
    _store_with_games(db)
    monkeypatch.setenv("HOCKEY_MODEL_DB", str(db))
    assert cli.main(["game", "2025020001"]) == 2
    assert "hockey-model fit" in capsys.readouterr().err


def test_cli_backtest_without_games_says_to_refresh(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setenv("HOCKEY_MODEL_DB", str(tmp_path / "store.db"))
    assert cli.main(["backtest"]) == 2
    assert "hockey-model refresh" in capsys.readouterr().err


def _fake_backtest(success: bool) -> object:
    run = ScoredRun("elo", 2, 0.69, 0.25, calibration([0.5, 0.6], [True, False]), None)
    report = BacktestReport(
        ("xg_form",),
        (),
        ("xg_form",),
        ("xg_form",) if success else (),
        {"elo": {"actual": 0.7, "guess": 0.7}},
        (run,),
        success,
        ("note",),
        (),
        {"xg_form": 3},
    )
    record = GameRecord(1, datetime(2026, 1, 1, tzinfo=UTC), "TOR", "BOS", "elo", 0.55, True)
    return lambda conn: (report, [record])


@pytest.mark.parametrize("success", [True, False])
def test_cli_backtest_prints_report_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    success: bool,
) -> None:
    monkeypatch.setenv("HOCKEY_MODEL_DB", str(tmp_path / "store.db"))
    monkeypatch.setattr("hockey_model.store_cli.run_backtest", _fake_backtest(success))
    assert cli.main(["backtest"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["success"] is success
    assert out["live_features"] == (["xg_form"] if success else [])
    assert out["missing_inputs"] == {"xg_form": 3}
    empty_bin = out["runs"][0]["calibration"][0]
    assert empty_bin["count"] == 0
    assert empty_bin["mean_prob"] is None


def test_cli_backtest_writes_games_out(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setenv("HOCKEY_MODEL_DB", str(tmp_path / "store.db"))
    monkeypatch.setattr("hockey_model.store_cli.run_backtest", _fake_backtest(True))
    target = tmp_path / "games.csv"
    assert cli.main(["backtest", "--games-out", str(target)]) == 0
    capsys.readouterr()
    lines = target.read_text().splitlines()
    assert lines[0] == "game_id,start,home,away,run,home_win_prob,home_won"
    assert lines[1].startswith("1,2026-01-01T00:00:00.000000+00:00,TOR,BOS,elo,0.55,True")


def test_cli_backtest_games_out_to_a_bad_path_names_the_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setenv("HOCKEY_MODEL_DB", str(tmp_path / "store.db"))
    monkeypatch.setattr("hockey_model.store_cli.run_backtest", _fake_backtest(True))
    target = tmp_path / "missing-dir" / "games.csv"
    assert cli.main(["backtest", "--games-out", str(target)]) == 2
    err = capsys.readouterr().err
    assert "FileNotFoundError" in err
    assert "check the file path" in err
