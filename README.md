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

The model protocols deliberately contain no production model or data-source
choice. An embedding application supplies those adapters. `FixedStatModel` is
available for deterministic examples and tests.

## CLI

The `hockey-model` command wraps the same calls and prints JSON. The installed
command reports that models are unconfigured until an embedding application
provides `CliRuntime`; it does not hide a second model stack inside the CLI.

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
