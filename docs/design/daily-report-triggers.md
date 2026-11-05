# Daily report triggers

## Problem

The daily report must be published before the first puck drop of each game day, with the goalie starters as fresh as possible.
A report published after puck drop is useless for scoring, because a reader drops every prediction made after the start.
GitHub Actions schedules run in UTC, and a scheduled run can start late.

## Game day

A game day is the Eastern date that the NHL schedule and score feed use.
A 7 pm ET slate starts after midnight UTC for much of the season, so a UTC date splits one night's games across two reports.
Every day-level key uses the Eastern game day: the report date, the release tag, the store read, and the gate.
Every game start stays a UTC instant.
`src/hockey_model/game_day.py` holds the time zone and the day window.

## Trigger hours

The report for a game day runs at the last top-of-hour slot before its first puck drop, moved earlier as described below.
A trigger fires at minute `TRIGGER_MINUTE_UTC` of each hour in `TRIGGER_HOURS_UTC` in `src/hockey_model/report_trigger.py`, and the workflow cron lists the same minute and hours.

Options:

1. Every two hours, all day. This is simple, but a trigger can be up to two hours before the puck drop, and half the triggers can never be the last one for any game day.
2. Every hour, all day. This gives the freshest starters, but most triggers can never be the last one.
3. Every hour, only at the hours that hold a first puck drop's last trigger. This gives the freshest starters with the fewest runs.

The choice is option 3.

The trigger minute is not :00.
GitHub delays and drops scheduled runs most at the top of the hour, and many workflows also use :15, :30, and :45.
Each trigger is the top-of-hour slot of the hourly grid, moved earlier to `TRIGGER_MINUTE_UTC` of the hour before it.
The move is `REPORT_LEAD`, the minutes left in the hour after the trigger minute.
A trigger is due when waiting for the next trigger would leave no more than `REPORT_LEAD` before the first puck drop.
So the report runs at the moved slot, never later than the old top-of-hour slot, and a delayed run has that much more time.
A minute just before :45 keeps that margin near what a :45 trigger gives, without the :45 queue.

`scripts/trigger_hours.py` reads the season schedule and prints the hours that the first puck drops need.
For the 2026-27 regular season, a single international game in the morning needs one hour by itself.
Every other game day needs an hour in the afternoon or the evening, UTC.
The script MUST be run again each season, and again when the playoff schedule comes out.
A game day whose last trigger hour is not in the list still gets a report at its next trigger, as a late run.

## Two runs per game day

The slow work does not fit between a trigger and the puck drop.
The fit and the backtest each take minutes or more on a full store.

1. `daily-prepare.yml` runs once each morning, before the first trigger hour. It refreshes every source, fits the model, and runs the backtest.
2. `daily-report.yml` runs at each trigger. When the trigger is due, it refreshes only the schedule, the goalie sources, and the injuries, then predicts and publishes.

When the morning run did not finish, the report run fails and says so.
It does not do the morning work itself, because that work takes about an hour and the report run must finish in minutes before the puck drop.
The operator runs the `daily-prepare` workflow for the day, then runs the report again.
Both workflows share one concurrency group, because both write the cached store.

## Actions cost

The repository is public, and GitHub-hosted runners on public repositories have no minute charge.
A trigger that is not due runs one short gate job.
The numbers for one month are in the pull request that added this design.
