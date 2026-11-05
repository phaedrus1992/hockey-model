# hockey-model

Player stat and game prediction interfaces for hockey. The package gives data
and model adapters one typed API for player identity, NHL or fantasy rosters,
stat projections, matchups, and playoff likelihood.

## Python API

Resolve names strictly through a catalog. Full-name matching ignores case and
accents; ambiguous names raise an error that lists canonical IDs.

```python
from hockey_model import Catalog

catalog = Catalog(players_from_your_source)
player = catalog.resolve("Zdeno Chara")
```

Project a player stat with an implementation of `StatModel`:

```python
from hockey_model import project_player

goals = project_player(player, "goals", stat_model)
print(goals.point, goals.low, goals.high, goals.level)
```

Use the same `Roster` type for fantasy and NHL teams. Team uncertainty comes
from a `JointModel`, not from adding player intervals.

```python
from hockey_model import Roster, Slot, project_team

roster = Roster(
    "my roster",
    tuple(players),
    {player.canonical_id: Slot.C for player in players},
)
team_goals = project_team(roster, "goals", stat_model, joint_model)
```

Match any two rosters with a `MatchupModel`:

```python
from hockey_model import matchup

result = matchup(home_roster, away_roster, matchup_model)
print(result.home_win, result.away_win)
```

The player, team, and matchup model protocols contain no production model or
data-source choice. An embedding application supplies those adapters.
`FixedStatModel` is available for deterministic examples and tests.
The NHL game win model is the one model that ships (see below).

## NHL game win model

`game_win_probability()` returns the win chance of each side of one NHL game, the expected goals of each side with an interval, and the inputs that were missing.
The model reads only the local store and makes no network request.

```python
from datetime import UTC, datetime

from hockey_model import Game, game_win_probability
from hockey_model.game_model.logistic import ELO_ONLY
from hockey_model.game_model.nhl_model import NhlGameModel
from hockey_model.store.db import connect

conn = connect(path_to_store)
model = NhlGameModel(conn, ELO_ONLY)
game = Game(2026020236, "TOR", "UTA", datetime(2026, 11, 4, 0, 0, tzinfo=UTC))
result = game_win_probability(game, model)
print(result.home_win, result.away_win, result.made_after_start)
for gap in result.missing:
    print(gap.kind, gap.team, gap.note)
```

The model is the results-only Elo of sportsbettr plus three features: MoneyPuck expected-goals form, the starting goalie's goals saved above expected, and rest days.
A fitted logistic regression sets the weights.
`made_after_start` is true when the prediction time is at or after the puck drop.
A caller must never treat such a result as a pregame read.
The starting goalie comes from the first confirmed ESPN or Daily Faceoff read, then the newest likely read, then the goalie with the most recent starts.
The result lists a goalie that no source confirmed.

The model uses no price data.
It does not say whether the model beats a betting market.
The backtest (below) scores it against game results and the results-only Elo only.

### The store

All data sits in one SQLite file.
Set `HOCKEY_MODEL_DB` to its path.
An unset or empty variable is an error that names it.

```text
HOCKEY_MODEL_DB=~/.cache/hockey-model/store.db hockey-model refresh --backfill-from 2014-10-01
HOCKEY_MODEL_DB=~/.cache/hockey-model/store.db hockey-model fit --through-season 20252026
HOCKEY_MODEL_DB=~/.cache/hockey-model/store.db hockey-model game 2026020236
HOCKEY_MODEL_DB=~/.cache/hockey-model/store.db hockey-model backtest --games-out games.csv
```

- `refresh` reads every source and appends each read with its fetch time. It exits 1 when a source failed, and it prints what each source wrote, the errors, and the credits. The first backfill makes about 16,000 NHL requests at two a second, so it takes hours. Run it again after an error: it skips what it already has.
- `fit --through-season YYYYYYYY [--features a,b]` fits the weights on every game from the 2015-16 season through that season and saves the fit. `--features ""` saves the Elo alone.
- `game GAME_ID [--level L]` prints the prediction of one stored game with the newest fit.
- `backtest [--games-out PATH] [--candidates {xg,attempt}]` runs the walk-forward backtest and prints a JSON report. `--games-out` writes one CSV row for each scored game and run. `--candidates attempt` replaces `xg_form` with the shot-attempt form, the leak test in #77.

### Data sources

| Source | Data |
| --- | --- |
| NHL API (`api-web.nhle.com`) | Schedule, results, boxscores, and the actual starting goalie |
| MoneyPuck CSV files | Expected goals for each team game and each goalie game |
| ESPN (`site.api.espn.com`, unofficial) | Probable starting goalies and injuries |
| Daily Faceoff (`dailyfaceoff.com/starting-goalies`) | Starting goalies |

Data from MoneyPuck.com.
MoneyPuck allows its data for non-commercial use only, and asks for credit wherever the data is shown.
hockey-model downloads only the CSV and ZIP files that the MoneyPuck data page lists, and every output that uses them carries the credit.
Read the MoneyPuck terms before any commercial use.
ESPN does not support its endpoints, so hockey-model fetches them sparingly.
The HTTP client waits between requests to one host, retries rate limits, and sends the user agent `hockey-model/<version>`.

### Backtest result

The November 2026 backtest scored 2,792 games from the 2024-25 and 2025-26 seasons.
The joint test passed: the live model beats the results-only Elo on log loss, 0.6763 against 0.6876.
The 95% interval of the difference is -0.0144 to -0.0083.
The live features are expected-goals form and rest.
The guess run vetoed goalie goals saved above expected.
MoneyPuck's expected-goals model may have trained on the scored games, so the gain may look larger than it was.
Issue #77 tests this with a form built from shot-attempt counts.
A reviewer then scored the model against the last pre-game DraftKings line on matched regular season games.
The model is level with the line in 2024-25 (0.6633 against 0.6604) and worse in 2025-26 (0.6911 against 0.6826, interval +0.0035 to +0.0140).
The model does not pass the blend gate for betting.
The full report is in [docs/backtest/2026-11-nhl-game-model.md](docs/backtest/2026-11-nhl-game-model.md).

### Experiment registry

Each experiment is one JSON record in `experiments/`.
A record states the hypothesis, the data cutoff, the baseline, the cohort, the
minimum games, the promotion criterion, and the failure outcome.
A record is frozen once registered: only `status` and `result` may change, and
`hockey-model experiments check` compares the record with the commit that
registered it.

An exploration record scores the seasons through 2025-26 and can run as many
times as you like.
A confirmation record scores only games after its cutoff in the 2026-27 regular
season and later, and it runs once.
The run refuses when the cohort holds fewer games than the record requires.
A run whose interval is wider than the effect the record expected is
inconclusive, not rejected.

```text
hockey-model experiments check
hockey-model experiments run 0001-v1-forward-test --games-out games.csv
```

The per-game CSV of a confirmation run is committed under
`experiments/results/`, and the record stores its SHA-256 hash.

## CLI

The player, team, matchup, and playoff commands wrap the same calls and print
JSON. The installed command reports that models are unconfigured until an
embedding application provides `CliRuntime`; it does not hide a second model
stack inside the CLI. The store commands above need no `CliRuntime`.

```text
hockey-model player goals PLAYER_ID
hockey-model team goals roster.json
hockey-model matchup home.json away.json
hockey-model playoffs TEAM_CODE
```

Roster files are JSON objects with `name`, `players`, and optional `slots`.
Player objects use the public `Player` field names, and slot values use the
public `Slot` values.

## Develop

```text
uv sync --locked
uv run pytest
prek install
```

See `AGENTS.md` for the commands and rules.
