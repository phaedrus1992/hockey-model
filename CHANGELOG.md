# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Add the typed player, roster, projection, matchup, playoff, and JSON CLI APIs. [feat:types]
- Add the Game input and game_win_probability() for one NHL game's home and away win chance, with a GameModel protocol that a model implements. Game rejects a team code that is not an NHL code. [feat:api]
- Add an SQLite store at the HOCKEY_MODEL_DB path, which refuses a store made by another schema version. [feat:store]
- Add a polite HTTP client that spaces requests per host and retries rate limits, server errors, and network failures. A response body that takes more than 120 s fails with a named error. [feat:sources]
- Add NHL team code maps for ESPN's four renamed codes and the Arizona to Utah franchise history. [feat:sources]
- Add NHL API score-day and boxscore reads, and store them as dated reads that keep earlier reads. [feat:sources]
- Add MoneyPuck team and goalie game-by-game reads (expected goals), stored as dated reads that keep earlier values. Data from MoneyPuck.com. [feat:sources]
- Add ESPN probable starting goalie and injury reads, and Daily Faceoff starting goalie reads, stored as dated reads. [feat:sources]
- Add `hockey-model refresh`, which reads every source into the store, keeps each source failure apart, and exits 1 when a source failed. [feat:store]
- Add as-of reads of the store and starting goalie resolution: the goalie on the game, the boxscore starter after puck drop, the first confirmed read, the newest likely read, then the goalie with the most recent starts. [feat:store]
- Add the NHL Elo (K 8, home advantage 28, log-margin scaling, same as sportsbettr without the market shrink) and the game features: expected-goals form, goalie goals saved above expected, and rest. [feat:model]
- Add the logistic game model: `hockey-model fit` fits and saves the weights, and `hockey-model game GAME_ID` prints the win chances, expected goals with a Poisson interval, and the missing inputs. [feat:model]
- Add backtest scores: log loss, Brier score, a ten-bin calibration table, and a block bootstrap interval for a mean. [feat:backtest]
- Add `hockey-model backtest`, a walk-forward backtest that refits before each scored season, tests all features together against the results-only Elo, and writes per-game predictions with `--games-out`. [feat:backtest]
- Add mutation testing with mutmut: `uv run mutmut run` mutates the parsers and the rate math, and an advisory CI job reports the survivors without failing the build. [chore:test]
- Python project skeleton: uv, ruff, ty, pytest with coverage and a per-module floor, editorconfig, prek hooks, and CI validation, test, and editorconfig jobs.
- Certify each logistic fit by the gradient of the penalized loss and save its diagnostics (iterations, objective, gradient, conditioning, penalty, scaling, stop reason) with the fit. A clipped step no longer counts as convergence. [feat:model]
- Add the November 2026 backtest report. The joint test passed with expected-goals form and rest, and the guess run vetoed goalie goals saved above expected. [docs:backtest]
- Add `hockey-model backtest --candidates attempt`, which replaces the expected-goals form with a shot-attempt form for the leak test. [feat:backtest]

### Changed

- Record the DraftKings comparison in the README, the backtest report, and the run report. The model is level with the line in 2024-25 and worse in 2025-26, and it fails the blend gate. [docs:backtest]
- Move the store to schema version 2, which adds MoneyPuck shot-attempt counts. A version 1 store is refused, so rebuild it on a new path with `hockey-model refresh --backfill-from 2014-10-01`. [feat:store]

### Fixed

- Read a failed NHL score day again on the next refresh, for 30 days. A day that failed and was followed by a good day was never read again, so its games were missing from the Elo and the fit. [fix:store]
- Refuse a boxscore that does not have exactly one starting goalie for each team. A boxscore without a goalie made the next refresh stop with a database error. [fix:sources]
- Read MoneyPuck numbers as plain ASCII decimals. A value such as 1_0 or a non-ASCII digit was accepted. [fix:sources]
- Refuse an ESPN return date that is not text, and a saved fit with an unknown feature or a weight that is not finite. [fix:sources]
- Match an injury name to the goalies of its own team only. [fix:model]
- Print the type and message of an unexpected failure in the store commands. [fix:cli]
- Note in the backtest report that the goalie guess run has no injury history. [fix:backtest]
- Allow an hour for the MoneyPuck team file, which is about 130 MB, instead of 15 minutes. [fix:sources]

[Unreleased]: https://github.com/slackworks/hockey-model/commits/main
