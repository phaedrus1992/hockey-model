"""The walk-forward backtest of the NHL game model against game results.

The backtest uses no price data. It scores the model against the results of the games, a
home win rate, and the results-only Elo.
"""

import csv
import math
import sqlite3
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import datetime
from pathlib import Path

from hockey_model.backtest.metrics import (
    CalibrationBin,
    block_bootstrap_mean_ci,
    brier,
    calibration,
    log_loss,
    per_game_log_loss,
)
from hockey_model.game_model.features import FEATURES, GoalieMode
from hockey_model.game_model.logistic import LogisticFit, fit_logistic, predict_logistic
from hockey_model.game_model.seasons import DEFAULT_PLAN, SeasonPlan
from hockey_model.game_model.training import TrainingRow, training_rows
from hockey_model.sources.moneypuck import MONEYPUCK_CREDIT
from hockey_model.store.timestamps import iso_utc
from hockey_model.types import HockeyModelError

MONEYPUCK_LEAK_NOTE = (
    "The MoneyPuck expected-goals model is today's model. MoneyPuck possibly trained it on "
    "games after the scored seasons, so results that use MoneyPuck data may look better than "
    "they would have then."
)
GOALIE_FEATURE = "goalie_gsax"
GUESS_EQUALS_ACTUAL_NOTE = (
    "No tested feature reads the starting goalie, so the actual run and the guess run are the "
    "same by construction. The equal scores do not show that a wrong goalie costs nothing."
)
INJURY_HISTORY_NOTE = (
    "The store has no ESPN injury history before it began to keep injury reads, so the goalie "
    "guess run never leaves out an injured goalie. The live model does."
)
MONEYPUCK_FEATURES = frozenset({"xg_form", "goalie_gsax"})
ELO = "elo"
HOME_RATE = "home_rate"
MODEL_ACTUAL = "model_actual"
MODEL_GUESS = "model_guess"
RECORDED_RUNS = (ELO, MODEL_ACTUAL, MODEL_GUESS)
# A feature is vetoed only when it is worse by more than rounding error.
VETO_TOLERANCE = 1e-9


@dataclass(frozen=True, slots=True)
class ScoredRun:
    """The scores of one way of predicting the scored games."""

    name: str
    games: int
    log_loss: float
    brier: float
    calibration: tuple[CalibrationBin, ...]
    diff_vs_elo_ci: tuple[float, float] | None


@dataclass(frozen=True, slots=True)
class GameRecord:
    """One predicted game, for scoring against a line outside hockey-model."""

    game_id: int
    start: datetime
    home: str
    away: str
    run: str
    home_win_prob: float
    home_won: bool


@dataclass(frozen=True, slots=True)
class BacktestReport:
    """The result of one backtest."""

    candidate_features: tuple[str, ...]
    vetoed: tuple[str, ...]
    tested_features: tuple[str, ...]
    live_features: tuple[str, ...]
    validation: Mapping[str, Mapping[str, float]]
    runs: tuple[ScoredRun, ...]
    success: bool
    notes: tuple[str, ...]
    credits: tuple[str, ...]
    # Scored games, with the goalie who started, that had each kind of missing input.
    missing_inputs: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class _Scored:
    """The probabilities that each run gave for one scored game."""

    row: TrainingRow
    by_run: Mapping[str, float]


def _in(rows: Sequence[TrainingRow], low: int, high: int) -> list[TrainingRow]:
    return [r for r in rows if low <= r.game.season <= high]


def _wins(rows: Sequence[TrainingRow]) -> list[bool]:
    return [r.home_won for r in rows]


def _fit(rows: Sequence[TrainingRow], features: Sequence[str]) -> LogisticFit:
    return fit_logistic([r.features for r in rows], _wins(rows), features)


def _loss(fit: LogisticFit, rows: Sequence[TrainingRow]) -> float:
    return log_loss([predict_logistic(fit, r.features) for r in rows], _wins(rows))


def _validate(
    actual: Sequence[TrainingRow], guess: Sequence[TrainingRow], plan: SeasonPlan
) -> tuple[dict[str, dict[str, float]], tuple[str, ...]]:
    """Score the Elo alone and the Elo plus each feature on the validation seasons.

    Each fit uses the training seasons with the goalie who started. It is scored with that
    goalie ("actual") and with the guessed goalie ("guess"). A feature is vetoed when its
    guess score is worse than the Elo alone.
    """
    train = _in(actual, *plan.select_train)
    validate_actual = _in(actual, *plan.select_validate)
    validate_guess = _in(guess, *plan.select_validate)
    if not train or not validate_actual:
        raise HockeyModelError(
            f"backtest: no games in the selection seasons {plan.select_train} and "
            f"{plan.select_validate}; run `hockey-model refresh --backfill-from 2014-10-01`"
        )
    validation: dict[str, dict[str, float]] = {}
    for name, features in [(ELO, ()), *[(f"{ELO}+{f}", (f,)) for f in FEATURES]]:
        fit = _fit(train, features)
        validation[name] = {
            "actual": _loss(fit, validate_actual),
            "guess": _loss(fit, validate_guess),
        }
    baseline = validation[ELO]["guess"]
    vetoed = tuple(
        f for f in FEATURES if validation[f"{ELO}+{f}"]["guess"] > baseline + VETO_TOLERANCE
    )
    return validation, vetoed


def _score_seasons(
    actual: Sequence[TrainingRow],
    guess: Sequence[TrainingRow],
    tested: Sequence[str],
    plan: SeasonPlan,
) -> list[_Scored]:
    """Fit before each scored season on all earlier seasons, then score that season once."""
    by_game = {r.game.game_id: r for r in guess}
    scored: list[_Scored] = []
    for season in sorted({r.game.season for r in _in(actual, *plan.scored)}):
        fit_rows = _in(actual, plan.fit_first, season - 1)
        if not fit_rows:
            raise HockeyModelError(
                f"backtest: no games to fit before season {season}; "
                "run `hockey-model refresh --backfill-from 2014-10-01`"
            )
        fit = _fit(fit_rows, tested)
        home_rate = sum(_wins(fit_rows)) / len(fit_rows)
        for row in _in(actual, season, season):
            scored.append(
                _Scored(
                    row,
                    {
                        ELO: 1.0 / (1.0 + math.exp(-row.features.elo_logit)),
                        HOME_RATE: home_rate,
                        MODEL_ACTUAL: predict_logistic(fit, row.features),
                        MODEL_GUESS: predict_logistic(fit, by_game[row.game.game_id].features),
                    },
                )
            )
    return scored


def _scored_run(name: str, games: Sequence[_Scored], elo_losses: Sequence[float]) -> ScoredRun:
    probs = [g.by_run[name] for g in games]
    wins = [g.row.home_won for g in games]
    ci = None
    if name != ELO:
        diffs = [a - b for a, b in zip(per_game_log_loss(probs, wins), elo_losses, strict=True)]
        ci = block_bootstrap_mean_ci(diffs)
    return ScoredRun(
        name, len(games), log_loss(probs, wins), brier(probs, wins), calibration(probs, wins), ci
    )


def _records(games: Sequence[_Scored]) -> list[GameRecord]:
    return [
        GameRecord(
            g.row.game.game_id,
            g.row.game.start,
            g.row.game.home,
            g.row.game.away,
            run,
            g.by_run[run],
            g.row.home_won,
        )
        for run in RECORDED_RUNS
        for g in games
    ]


def _missing_counts(games: Sequence[_Scored]) -> dict[str, int]:
    """Count the scored games that had each kind of missing input."""
    counts: Counter[str] = Counter()
    for game in games:
        counts.update({m.kind.value for m in game.row.features.missing})
    return dict(sorted(counts.items()))


def _notes(tested: Sequence[str], vetoed: Sequence[str], success: bool) -> tuple[str, ...]:
    notes = [f"{len(FEATURES)} candidate features were tested together as one joint test."]
    if vetoed:
        notes.append(f"The guess run vetoed: {', '.join(vetoed)}.")
    if not success:
        notes.append("The joint test failed, so the Elo alone ships.")
    if MONEYPUCK_FEATURES & set(tested):
        notes.append(MONEYPUCK_LEAK_NOTE)
    if GOALIE_FEATURE not in tested:
        notes.append(GUESS_EQUALS_ACTUAL_NOTE)
    notes.append(INJURY_HISTORY_NOTE)
    return tuple(notes)


def run_backtest(
    conn: sqlite3.Connection, plan: SeasonPlan = DEFAULT_PLAN
) -> tuple[BacktestReport, list[GameRecord]]:
    """Run the walk-forward backtest on the stored games.

    Success is one test: the 95th percentile of the block-bootstrap interval of the
    per-game log loss of the model minus that of the Elo, with the goalie who started,
    is below zero. The guess run never changes success.
    """
    first, last = plan.fit_first, plan.scored[1]
    actual = training_rows(conn, first, last, GoalieMode.ACTUAL, plan.burn_in)
    guess = training_rows(conn, first, last, GoalieMode.GUESS, plan.burn_in)
    validation, vetoed = _validate(actual, guess, plan)
    tested = tuple(f for f in FEATURES if f not in vetoed)
    games = _score_seasons(actual, guess, tested, plan)
    if not games:
        raise HockeyModelError(
            f"backtest: no games in the scored seasons {plan.scored}; "
            "run `hockey-model refresh --backfill-from 2014-10-01`"
        )
    wins = [g.row.home_won for g in games]
    elo_losses = per_game_log_loss([g.by_run[ELO] for g in games], wins)
    runs = tuple(
        _scored_run(name, games, elo_losses) for name in (HOME_RATE, ELO, MODEL_ACTUAL, MODEL_GUESS)
    )
    model = next(r for r in runs if r.name == MODEL_ACTUAL)
    success = model.diff_vs_elo_ci is not None and model.diff_vs_elo_ci[1] < 0.0
    uses_moneypuck = bool(MONEYPUCK_FEATURES & set(tested))
    report = BacktestReport(
        candidate_features=FEATURES,
        vetoed=vetoed,
        tested_features=tested,
        live_features=tested if success else (),
        validation=validation,
        runs=runs,
        success=success,
        notes=_notes(tested, vetoed, success),
        credits=(MONEYPUCK_CREDIT,) if uses_moneypuck else (),
        missing_inputs=_missing_counts(games),
    )
    return report, _records(games)


def write_game_records(path: Path, records: Sequence[GameRecord]) -> None:
    """Write one CSV row for each record. The ``start`` column is ISO 8601 UTC."""
    names = [f.name for f in fields(GameRecord)]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(names)
        for record in records:
            writer.writerow(
                [
                    iso_utc(record.start) if name == "start" else getattr(record, name)
                    for name in names
                ]
            )
