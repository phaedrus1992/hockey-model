# ESPN fixtures

Captured on 2026-11-03 with one request each.

- `scoreboard_20261103.json` and `scoreboard_20261104.json`: the scoreboard for two days with games not started. They hold `Confirmed` and `Expected` goalies and the `TB`, `NJ`, `LA`, and `SJ` codes.
- `injuries.json`: the injury list. The athlete `links`, `headshot`, and team `logos` keys and the `longComment` text are removed to cut the file size. No parser reads them.
