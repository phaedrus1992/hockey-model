# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Add the typed player, roster, projection, matchup, playoff, and JSON CLI APIs. [feat:types]
- Add the Game input and game_win_probability() for one NHL game's home and away win chance, with a GameModel protocol that a model implements. [feat:api]
- Add an SQLite store at the HOCKEY_MODEL_DB path, which refuses a store made by another schema version. [feat:store]
- Add a polite HTTP client that spaces requests per host and retries rate limits, server errors, and network failures. [feat:sources]
- Add NHL team code maps for ESPN's four renamed codes and the Arizona to Utah franchise history. [feat:sources]
- Python project skeleton: uv, ruff, ty, pytest with coverage and a per-module floor, editorconfig, prek hooks, and CI validation, test, and editorconfig jobs.

[Unreleased]: https://github.com/slackworks/hockey-model/commits/main
