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
- Python project skeleton: uv, ruff, ty, pytest with coverage and a per-module floor, editorconfig, prek hooks, and CI validation, test, and editorconfig jobs.

[Unreleased]: https://github.com/slackworks/hockey-model/commits/main
