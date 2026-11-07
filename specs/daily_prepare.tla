---------------------------- MODULE daily_prepare ----------------------------
(* A model of the backfill in scripts/daily-prepare.sh and store/refresh_backfill.py.
   Design and mapping to the code: docs/design/daily-prepare-tla.md *)
EXTENDS Naturals, FiniteSets

CONSTANTS
    NWindows,       \* windows in the backfill; window 1 is the newest
    DaysPerWindow,  \* score days in one window
    Budget,         \* attempts one run makes before out_of_time() is true
    MaxFails,       \* MAX_UNIT_FAILURES, scaled down
    AbandonReads,   \* ABANDON_AFTER_FAILED_READS
    AbandonTicks,   \* ticks in ABANDON_MIN_SPAN_DAYS
    RetryTicks,     \* ticks in RETRY_FAILED_AFTER
    OpenDays,       \* days that are not closed: a good read does not complete them
    BrokenScore,    \* score days whose every read fails
    BrokenBox,      \* days whose boxscore read always fails
    OtherBroken     \* TRUE when a source after the NHL steps always fails

Days == 1..(NWindows * DaysPerWindow)
Kinds == {"score", "box"}
Urls == [kind : Kinds, day : Days]
Score(d) == [kind |-> "score", day |-> d]
Box(d) == [kind |-> "box", day |-> d]

ASSUME /\ NWindows >= 1 /\ DaysPerWindow >= 1 /\ Budget >= 1 /\ MaxFails >= 1
       /\ AbandonReads >= 1 /\ AbandonTicks >= 1 /\ RetryTicks >= 1
       /\ OpenDays \subseteq Days /\ BrokenScore \subseteq Days /\ BrokenBox \subseteq Days
       /\ OtherBroken \in BOOLEAN

\* TRUE when a run can read every open day and still have budget for one more unit.
BudgetCovers == Cardinality(OpenDays) < Budget

Min(a, b) == IF a < b THEN a ELSE b

(* The work order of one run. windows() yields window 1 first. In a window, read_days
   takes the days oldest first, then read_boxscores takes the games oldest first. *)
Steps == NWindows * 2 * DaysPerWindow
WindowAt(p) == ((p - 1) \div (2 * DaysPerWindow)) + 1
OffsetAt(p) == (p - 1) % (2 * DaysPerWindow)
KindAt(p) == IF OffsetAt(p) < DaysPerWindow THEN "score" ELSE "box"
DayAt(p) == (NWindows - WindowAt(p)) * DaysPerWindow + (OffsetAt(p) % DaysPerWindow) + 1
UnitAt(p) == [kind |-> KindAt(p), day |-> DayAt(p)]
StageStart(p) == OffsetAt(p) = 0 \/ OffsetAt(p) = DaysPerWindow
BoxStageOf(p) == (WindowAt(p) - 1) * 2 * DaysPerWindow + DaysPerWindow + 1
LastOfWindow(p) == OffsetAt(p) = 2 * DaysPerWindow - 1

VARIABLES
    okRead, streak, span, firstAge, lastAge,  \* source_reads, per URL
    marker,                                   \* the .backfilled file
    calm,                                     \* TRUE: every read that is not broken works
    phase, pc, gaps, noted, due, fails, reads, progress, clean, stopped, errors,  \* one run
    exitCode

store == <<okRead, streak, span, firstAge, lastAge, marker>>
run == <<phase, pc, gaps, noted, due, fails, reads, progress, clean, stopped, errors>>
vars == <<store, calm, run, exitCode>>

\* abandoned_urls(): enough failed reads since the last good read, far enough apart.
Abandoned(u) == streak[u] >= AbandonReads /\ span[u]
\* _day_complete(): a good read after the day closed.
Complete(d) == okRead[Score(d)] /\ d \notin OpenDays
\* games_missing_boxscore(): the score read found a final game with no boxscore.
WantBox(d) == okRead[Score(d)] /\ d \notin OpenDays /\ ~okRead[Box(d)]
\* failed_since(now - RETRY_FAILED_AFTER) in read_boxscores.
RecentFail(u) == streak[u] > 0 /\ lastAge[u] < RetryTicks

\* A unit is done when a read worked or when it is a known gap. No later run undoes it.
Done(u) == okRead[u] \/ Abandoned(u)
ScoreDone(d) == Done(Score(d))
\* A box is needed only for a final game, and the score read finds the game.
BoxDone(d) == ~WantBox(d) \/ Abandoned(Box(d))
WindowDays(k) == {d \in Days : (NWindows - k) * DaysPerWindow < d
                                /\ d <= (NWindows - k + 1) * DaysPerWindow}
WindowDone(k) == \A d \in WindowDays(k) : ScoreDone(d) /\ BoxDone(d)

Broken(u) == IF u.kind = "score" THEN u.day \in BrokenScore ELSE u.day \in BrokenBox

RunIdle == /\ phase = "idle" /\ pc = 1 /\ gaps = {} /\ noted = {} /\ due = {}
           /\ fails = 0 /\ reads = 0 /\ ~progress /\ clean /\ ~stopped /\ ~errors

Init == /\ okRead = [u \in Urls |-> FALSE]
        /\ streak = [u \in Urls |-> 0]
        /\ span = [u \in Urls |-> FALSE]
        /\ firstAge = [u \in Urls |-> 0]
        /\ lastAge = [u \in Urls |-> 0]
        /\ marker = FALSE
        /\ calm = FALSE
        /\ phase = "idle" /\ pc = 1 /\ gaps = {} /\ noted = {} /\ due = {}
        /\ fails = 0 /\ reads = 0 /\ progress = FALSE
        /\ clean = TRUE /\ stopped = FALSE /\ errors = FALSE
        /\ exitCode = 0

TypeOK ==
    /\ okRead \in [Urls -> BOOLEAN]
    /\ streak \in [Urls -> 0..AbandonReads]
    /\ span \in [Urls -> BOOLEAN]
    /\ firstAge \in [Urls -> 0..AbandonTicks]
    /\ lastAge \in [Urls -> 0..RetryTicks]
    /\ marker \in BOOLEAN /\ calm \in BOOLEAN
    /\ phase \in {"idle", "nhl", "other", "finish"}
    /\ pc \in 1..(Steps + 1)
    /\ gaps \subseteq Urls /\ noted \subseteq Urls /\ due \subseteq Days
    /\ fails \in 0..MaxFails /\ reads \in 0..Budget /\ progress \in BOOLEAN
    /\ clean \in BOOLEAN /\ stopped \in BOOLEAN /\ errors \in BOOLEAN
    /\ exitCode \in {0, 1, 75}

(* Time passes only between runs. One tick is ABANDON_MIN_SPAN_DAYS. A run takes much less
   time than one tick, so every read of a run has the same time. *)
Tick ==
    /\ phase = "idle"
    /\ firstAge' = [u \in Urls |-> IF streak[u] > 0
                                   THEN Min(firstAge[u] + 1, AbandonTicks) ELSE 0]
    /\ lastAge' = [u \in Urls |-> IF streak[u] > 0
                                  THEN Min(lastAge[u] + 1, RetryTicks) ELSE 0]
    /\ UNCHANGED <<okRead, streak, span, marker, calm, run, exitCode>>

GoCalm ==
    /\ ~calm
    /\ calm' = TRUE
    /\ UNCHANGED <<store, run, exitCode>>

(* daily-prepare.sh runs a backfill only while the marker is missing. score_gaps() and
   read_boxscores() read the gaps before any read of this run, and note them. *)
StartRun ==
    /\ phase = "idle" /\ ~marker
    /\ phase' = "nhl"
    /\ gaps' = {u \in Urls : Abandoned(u)}
    /\ noted' = {u \in Urls : Abandoned(u)}
    \* In calm weather a re-read resolves every game, so no day is due again.
    /\ \E D \in SUBSET {d \in Days : okRead[Score(d)]} : due' = IF calm THEN {} ELSE D
    /\ UNCHANGED <<store, calm, pc, fails, reads, progress, clean, stopped, errors,
                   exitCode>>

\* run.attempt(): one read in one transaction. It records the result in source_reads.
\* A read finishes a unit for good when it works and the unit had no good read before.
\* An open day never finishes, because the next run reads it again.
Attempt(u, ok) ==
    /\ reads' = reads + 1
    /\ progress' = (progress \/ (ok /\ ~okRead[u]
                                 /\ (u.kind = "box" \/ u.day \notin OpenDays)))
    /\ okRead' = [okRead EXCEPT ![u] = @ \/ ok]
    /\ IF ok
       THEN /\ streak' = [streak EXCEPT ![u] = 0]
            /\ span' = [span EXCEPT ![u] = FALSE]
            /\ firstAge' = [firstAge EXCEPT ![u] = 0]
            /\ lastAge' = [lastAge EXCEPT ![u] = 0]
       ELSE /\ streak' = [streak EXCEPT ![u] = Min(@ + 1, AbandonReads)]
            /\ span' = [span EXCEPT ![u] = IF streak[u] = 0 THEN FALSE
                                           ELSE @ \/ firstAge[u] >= AbandonTicks]
            /\ firstAge' = [firstAge EXCEPT ![u] = IF streak[u] = 0 THEN 0 ELSE @]
            /\ lastAge' = [lastAge EXCEPT ![u] = 0]

Outcomes(u) == IF Broken(u) THEN {FALSE} ELSE IF calm THEN {TRUE} ELSE BOOLEAN

\* Move to the next unit. A stop jumps to the box stage of the window, or ends the NHL steps.
Advance(stopNow, failsNext) ==
    /\ pc' = IF stopNow /\ KindAt(pc) = "score" THEN BoxStageOf(pc)
             ELSE IF stopNow THEN Steps + 1
             ELSE IF stopped /\ LastOfWindow(pc) THEN Steps + 1
             ELSE pc + 1
    /\ fails' = failsNext

\* One loop pass of read_days().
ScoreStep ==
    LET u == UnitAt(pc)
        f == IF StageStart(pc) THEN 0 ELSE fails
    IN \/ /\ f >= MaxFails
          /\ stopped' = TRUE /\ clean' = FALSE
          /\ Advance(TRUE, f)
          /\ UNCHANGED <<store, reads, progress, errors>>
       \/ /\ f < MaxFails
          /\ u \in gaps \/ (u.day \notin due /\ Complete(u.day))
          /\ Advance(FALSE, 0)
          /\ UNCHANGED <<store, reads, progress, errors, clean, stopped>>
       \/ /\ f < MaxFails
          /\ ~(u \in gaps \/ (u.day \notin due /\ Complete(u.day)))
          /\ reads >= Budget
          /\ stopped' = TRUE /\ clean' = FALSE
          /\ Advance(TRUE, f)
          /\ UNCHANGED <<store, reads, progress, errors>>
       \/ /\ f < MaxFails
          /\ ~(u \in gaps \/ (u.day \notin due /\ Complete(u.day)))
          /\ reads < Budget
          /\ \E ok \in Outcomes(u) :
                /\ Attempt(u, ok)
                /\ clean' = (clean /\ ok)
                /\ errors' = (errors \/ ~ok)
                /\ Advance(FALSE, IF ok THEN 0 ELSE Min(f + 1, MaxFails))
          /\ UNCHANGED <<marker, stopped>>

\* One loop pass of read_boxscores(). A game that is not waiting is not in its list.
BoxStep ==
    LET u == UnitAt(pc)
        f == IF StageStart(pc) THEN 0 ELSE fails
    IN \/ /\ ~WantBox(u.day) \/ u \in gaps
          /\ Advance(FALSE, f)
          /\ UNCHANGED <<store, reads, progress, errors, clean, stopped>>
       \/ /\ WantBox(u.day) /\ u \notin gaps
          /\ f >= MaxFails \/ reads >= Budget
          /\ stopped' = TRUE /\ clean' = FALSE
          /\ Advance(TRUE, f)
          /\ UNCHANGED <<store, reads, progress, errors>>
       \/ /\ WantBox(u.day) /\ u \notin gaps
          /\ f < MaxFails /\ reads < Budget
          /\ RecentFail(u)
          /\ clean' = FALSE
          /\ Advance(FALSE, f)
          /\ UNCHANGED <<store, reads, progress, errors, stopped>>
       \/ /\ WantBox(u.day) /\ u \notin gaps
          /\ f < MaxFails /\ reads < Budget
          /\ ~RecentFail(u)
          /\ \E ok \in Outcomes(u) :
                /\ Attempt(u, ok)
                /\ clean' = (clean /\ ok)
                /\ errors' = (errors \/ ~ok)
                /\ Advance(FALSE, IF ok THEN 0 ELSE Min(f + 1, MaxFails))
          /\ UNCHANGED <<marker, stopped>>

NhlStep ==
    /\ phase = "nhl" /\ pc <= Steps
    /\ IF KindAt(pc) = "score" THEN ScoreStep ELSE BoxStep
    /\ UNCHANGED <<calm, phase, gaps, noted, due, exitCode>>

\* nhl() adds an error when the budget stopped the run before it finished one unit.
EndNhl ==
    /\ phase = "nhl" /\ pc = Steps + 1
    /\ phase' = "other"
    /\ errors' = (errors \/ (stopped /\ ~progress /\ reads >= Budget))
    /\ UNCHANGED <<store, calm, pc, gaps, noted, due, fails, reads, progress, clean, stopped,
                   exitCode>>

\* MoneyPuck, ESPN, and Daily Faceoff run after the NHL steps. A failure sets refresh exit 1.
OtherSources ==
    /\ phase = "other"
    /\ \E e \in (IF calm /\ ~OtherBroken THEN {FALSE}
                 ELSE IF OtherBroken THEN {TRUE} ELSE BOOLEAN) :
          errors' = (errors \/ e)
    /\ phase' = "finish"
    /\ UNCHANGED <<store, calm, pc, gaps, noted, due, fails, reads, progress, clean, stopped,
                   exitCode>>

\* The backfill branch of daily-prepare.sh: refresh_rc, then backfill_complete.
Finish ==
    /\ phase = "finish"
    /\ exitCode' = IF errors THEN 1 ELSE IF clean THEN 0 ELSE 75
    /\ marker' = (~errors /\ clean)
    /\ phase' = "idle" /\ pc' = 1 /\ gaps' = {} /\ noted' = {} /\ due' = {}
    /\ fails' = 0 /\ reads' = 0 /\ progress' = FALSE
    /\ clean' = TRUE /\ stopped' = FALSE /\ errors' = FALSE
    /\ UNCHANGED <<okRead, streak, span, firstAge, lastAge, calm>>

Next == Tick \/ GoCalm \/ StartRun \/ NhlStep \/ EndNhl \/ OtherSources \/ Finish

Fairness == /\ WF_vars(GoCalm) /\ WF_vars(StartRun) /\ SF_vars(Tick)
            /\ WF_vars(NhlStep) /\ WF_vars(EndNhl) /\ WF_vars(OtherSources)
            /\ WF_vars(Finish)

Spec == Init /\ [][Next]_vars /\ Fairness

-----------------------------------------------------------------------------
\* Safety

MarkerOnlyWhenComplete == marker => \A k \in 1..NWindows : WindowDone(k)

AbandonedIsNoted == phase /= "idle" => gaps \subseteq noted

DoneStaysDone == [][\A u \in Urls : Done(u) => Done(u)']_vars

ScoreRead(d) == phase = "nhl" /\ reads' = reads + 1 /\ UnitAt(pc) = Score(d)
NoRereadOfCompleteDay == [][\A d \in Days : ScoreRead(d) => (~Complete(d) \/ d \in due)]_vars

Finishing == phase = "finish" /\ phase' = "idle"
StoppedNeverMarks == [][Finishing /\ (stopped \/ errors) => ~marker']_vars
ExitCodeRule == [][Finishing => /\ (exitCode' = 1 <=> errors)
                                 /\ (exitCode' = 75 => ~marker' /\ ~clean)
                                 /\ (exitCode' = 0 => marker')]_vars

\* A run that the budget stops with no finished unit exits 1, not 75.
StallExitsOne == [][Finishing /\ stopped /\ ~progress /\ reads >= Budget
                     => exitCode' = 1]_vars

\* Liveness

\* A budget that covers the open days lets the backfill finish.
BackfillFinishes == BudgetCovers => <>marker

\* A budget that is too small ends in exit 1 instead of in endless exit 75.
FinishesOrFails == <>(marker \/ exitCode = 1)
=============================================================================
