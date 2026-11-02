"""JSON command-line wrapper over the public Python API."""

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Never

from hockey_model.identity import Catalog
from hockey_model.matchup import matchup, playoff_probability
from hockey_model.models import JointModel, MatchupModel, StandingsModel, StatModel
from hockey_model.projections import project_player, project_team
from hockey_model.types import (
    HockeyModelError,
    ModelNotConfiguredError,
    Player,
    Roster,
    Slot,
    Standing,
)


@dataclass(frozen=True, slots=True)
class CliRuntime:
    """Models and catalog supplied by an embedding application to the CLI."""

    catalog: Catalog
    stat_model: StatModel
    joint_model: JointModel
    matchup_model: MatchupModel
    standings_model: StandingsModel
    standings: tuple[Standing, ...]


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        self.print_usage(sys.stderr)
        raise ValueError(message)


def _add_projection_options(parser: argparse.ArgumentParser, *, horizon: bool) -> None:
    if horizon:
        parser.add_argument("--horizon-games", type=int, default=1)
    parser.add_argument("--level", type=float, default=0.8)


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="hockey-model", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    player = commands.add_parser("player", help="project one player statistic")
    player.add_argument("stat")
    player.add_argument("ref")
    _add_projection_options(player, horizon=True)

    team = commands.add_parser("team", help="project one roster statistic")
    team.add_argument("stat")
    team.add_argument("roster_file", type=Path)
    _add_projection_options(team, horizon=True)

    game = commands.add_parser("matchup", help="project a matchup between roster files")
    game.add_argument("home_file", type=Path)
    game.add_argument("away_file", type=Path)
    _add_projection_options(game, horizon=False)

    playoffs = commands.add_parser("playoffs", help="project a team's playoff probability")
    playoffs.add_argument("team_code")
    _add_projection_options(playoffs, horizon=False)
    return parser


def _player(data: object) -> Player:
    if not isinstance(data, dict):
        raise ValueError("each roster player must be a JSON object")
    return Player(
        canonical_id=str(data["canonical_id"]),
        yahoo_id=None if data.get("yahoo_id") is None else str(data["yahoo_id"]),
        nhl_id=None if data.get("nhl_id") is None else int(data["nhl_id"]),
        full_name=str(data["full_name"]),
        eligible=frozenset(Slot(value) for value in data["eligible"]),
        team_code=None if data.get("team_code") is None else str(data["team_code"]),
    )


def _roster(path: Path) -> Roster:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"read roster {path}: {exc}; provide a readable JSON roster") from exc
    if not isinstance(data, dict):
        raise ValueError(f"read roster {path}: root must be a JSON object")
    try:
        players = tuple(_player(item) for item in data["players"])
        raw_slots = data.get("slots")
        slots = (
            None if raw_slots is None else {key: Slot(value) for key, value in raw_slots.items()}
        )
        return Roster(str(data["name"]), players, slots)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"read roster {path}: invalid roster fields: {exc}") from exc


def _ref(value: str) -> str | int:
    return int(value) if value.isdecimal() else value


def _run(args: argparse.Namespace, runtime: CliRuntime) -> object:
    if args.command == "player":
        player = runtime.catalog.resolve(_ref(args.ref))
        return project_player(
            player,
            args.stat,
            runtime.stat_model,
            horizon_games=args.horizon_games,
            level=args.level,
        )
    if args.command == "team":
        return project_team(
            _roster(args.roster_file),
            args.stat,
            runtime.stat_model,
            runtime.joint_model,
            horizon_games=args.horizon_games,
            level=args.level,
        )
    if args.command == "matchup":
        return matchup(
            _roster(args.home_file),
            _roster(args.away_file),
            runtime.matchup_model,
            args.level,
        )
    return playoff_probability(
        args.team_code, runtime.standings, runtime.standings_model, args.level
    )


def _json_default(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    raise TypeError(f"cannot serialize {type(value).__name__}")


def main(argv: Sequence[str] | None = None, runtime: CliRuntime | None = None) -> int:
    """Run the JSON CLI, returning zero on success and two for caller errors."""
    try:
        args = _parser().parse_args(argv)
        if runtime is None:
            raise ModelNotConfiguredError(
                "run CLI command: no models are configured; "
                "embed CliRuntime with data-backed models"
            )
        print(json.dumps(_run(args, runtime), default=_json_default, sort_keys=True))
    except (HockeyModelError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0
