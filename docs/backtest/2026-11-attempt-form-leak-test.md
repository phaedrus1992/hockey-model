# Attempt-form leak test: frozen protocol

This document fixes the test and the decision rule before the run. It answers issue #77.

## Question

The first backtest scored the model with `xg_form`, a form built from MoneyPuck expected goals.
MoneyPuck's expected-goals model may have trained on the scored games.
This test replaces `xg_form` with a form built from raw shot-attempt counts, which have no model behind them.

## Hypothesis

The gain over Elo comes from the shot-attempt share as much as from the expected-goals share.

## Fixed inputs

- Candidate set: `attempt_form`, `goalie_gsax`, `rest`. Only `xg_form` is replaced.
- `attempt_form` is the Corsi share: `shotAttemptsFor / (shotAttemptsFor + shotAttemptsAgainst)`, averaged over the same last 10 games as `xg_form`.
- Everything else is unchanged: the seasons, the refit before each scored season, the guess veto, and the success rule.
- The joint test stays one test. The v1 success rule does not change.
- The scored seasons do not pick between the two forms.

## Reference

The first run gave a model minus Elo log-loss difference of -0.0113, with CI -0.0144 to -0.0083, on 2,792 games (2024-25 and 2025-26).

## Decision rule

Let `d` be the model minus Elo log-loss difference of the attempt run, on the same games.
Let `d_xg` be the difference of the xG run on the rebuilt store, which must match -0.0113.

- Recovers most: `d <= (2/3) * d_xg`. The xG gain is real.
- Collapses: `d > (1/3) * d_xg`. The leak did the work.
- Between the two: the result is inconclusive and is reported as such.

The rule applies to the point estimate.
The CI is reported next to it and does not change the call.

## Not in scope

- Fenwick counts (`unblockedShotAttemptsFor` and `unblockedShotAttemptsAgainst`) are stored, but no feature uses them in this run.
- `goalie_gsax` still uses MoneyPuck expected goals. A collapse therefore cannot be read as the whole leak, because that feature may carry the same leak.
- The Vince comparison against the DraftKings no-vig line runs outside this repository.
