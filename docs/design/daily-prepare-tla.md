# Daily prepare state machine: TLA+ model

Tracks issue #169.

## Problem

`scripts/daily-prepare.sh` keeps state across runs.
The first run backfills the store one year at a time, newest year first, under a time budget.
A stopped run exits 75 and writes no marker.
The next run resumes, because refresh skips what it already read.
A complete backfill writes `$HOCKEY_MODEL_DB.backfilled`.
Each later run reads the day's data and writes `prepared-DATE`.

The tests check single runs.
No test checks the ordering rules across runs.
Two rules carry most of the risk:

- The marker must exist only when every window is read.
- A resumed run must not lose a window that an earlier run finished.

## Options

1. Model the windows, the budget stop, the abandoned-URL rule, and the marker in TLA+. Check it with TLC in CI.
2. Model the store and its cache too.
3. Add more property tests only.

## Choice

Option 1.
The cross-run rules are where example tests miss a bug.
Option 3 already exists in part (hypothesis), and it cannot state a rule across runs.
Option 2 needs the store and the branch-scoped cache, which is too large for one change.

## What the code does (checked in source)

- `store/refresh_backfill.py`: `windows(first, last)` yields 365-day windows, newest first.
  The loop stops at the first window that reports `stopped`.
  `complete` is true only when every window read was `clean`.
- `store/refresh_nhl.py`: a read returns `clean=False, stopped=True` when a run stops early (three failures in a row, or the time ran out).
  A stopped read is never clean, so an early stop always leaves `complete` false.
- `store/source_reads.py` and the `abandoned_urls` check: a URL that fails twice, 12 hours apart, is abandoned and named in the notes.
  This is a per-URL threshold.
  The run-stop threshold (three in a row) is a separate per-run threshold.
  The spec models both.

## Model scope

Constants kept small for TLC: 3 windows, a budget of 2 reads per run, and 2 failures before a URL is abandoned.

State: the set of done windows, the marker, the abandoned URLs, the notes, and the exit code of the last run.

Actions:

1. Start a run. Take windows newest first.
2. Read a window. It is clean, unclean (failed reads, not stopped), or stopped (budget or three failures).
3. Stop the run at the first stopped window.
4. Abandon a URL after its second failure.
5. Write the marker when every window is clean.
6. Exit 75 when the run stops before the last window.

## Invariants

- `MarkerOnlyWhenComplete`: the marker exists only when every window is done.
- `DoneStaysDone`: a window marked done is not unmarked by a later run.
- `StoppedIsNotComplete`: a run that stopped never writes the marker.
- `AbandonedIsNamed`: an abandoned URL always has a note.
- `ExitCodeMatchesMarker`: exit 75 if and only if the run stopped with no marker.

## Mapping

The mapping from spec to code stays manual.
Each invariant names the function it models in its comment.
This note is the map.

## Verification plan

- Pin the TLA+ tools jar by SHA-256.
- Put the spec at `specs/daily_prepare.tla`, with `specs/daily_prepare.cfg` beside it.
- Add one CI job that runs TLC and fails on any violated invariant.
  The job uses an action pinned by SHA, with a version comment.
- Break test: remove the stop guard on the marker, run TLC, and confirm it reports `MarkerOnlyWhenComplete`.
  Restore the guard, and confirm TLC passes.

## Steps after go

1. Write the spec and its `.cfg`. Run TLC locally.
2. Run the break test for each invariant.
3. Add the pinned CI job.
4. Add the TLC command to `AGENTS.md` under Commands.
5. Update this note if the model changes.

## Non-goals

- The HTTP calls and the game model.
- A proof that the Python code matches the spec.
