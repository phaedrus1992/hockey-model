"""Tests for the season plans that the backtest and the experiment registry use.

Covers:
- season_of for dates on both sides of the September boundary
- confirmation_plan: first season, open end, regular season only, cutoff
- in_cohort: season range, game type, cutoff
- scored_label wording
"""

from datetime import UTC, datetime

from hockey_model.game_model.seasons import (
    CONFIRMATION_START,
    SeasonPlan,
    confirmation_plan,
    exploration_plan,
    in_cohort,
    scored_label,
    season_of,
)
from hockey_model.sources.nhl import GameRow


def _game(season: int, game_type: int, start: datetime) -> GameRow:
    """Build one game row for cohort tests."""
    return GameRow(1, season, game_type, start, "TOR", "BOS", "OFF", 3, 2, "REG")


class TestSeasonOf:
    """Test the season a date belongs to."""

    def test_early_season_dates_use_the_previous_year(self):
        """A game in June 2027 belongs to the 2026-27 season."""
        assert season_of(datetime(2027, 6, 1).date()) == 20262027

    def test_late_season_dates_use_the_current_year(self):
        """A game in October 2026 belongs to the 2026-27 season."""
        assert season_of(datetime(2026, 10, 1).date()) == 20262027

    def test_the_boundary_is_september(self):
        """August is the last month of the previous season, September the first of the next."""
        assert season_of(datetime(2026, 8, 31).date()) == 20252026
        assert season_of(datetime(2026, 9, 1).date()) == 20262027


class TestConfirmationPlan:
    """Test the plan a confirmation record scores."""

    def test_the_cohort_starts_at_the_confirmation_season(self):
        """A cutoff inside 2026-27 scores that season onward, not an exploration season."""
        plan = confirmation_plan(datetime(2026, 10, 31, tzinfo=UTC))
        assert plan.scored == (CONFIRMATION_START, 99_999_999)

    def test_an_early_cutoff_still_starts_at_the_confirmation_season(self):
        """The floor keeps a record with an old cutoff from scoring exploration seasons."""
        plan = confirmation_plan(datetime(2020, 1, 1, tzinfo=UTC))
        assert plan.scored[0] == CONFIRMATION_START

    def test_the_cohort_is_regular_season_only(self):
        """Playoff games are outside the confirmation cohort."""
        plan = confirmation_plan(datetime(2026, 10, 31, tzinfo=UTC))
        assert plan.game_types == (2,)

    def test_the_cutoff_is_carried_into_the_plan(self):
        """The plan keeps the record's cutoff so games before it are not scored."""
        cutoff = datetime(2026, 10, 31, tzinfo=UTC)
        assert confirmation_plan(cutoff).cutoff == cutoff

    def test_exploration_plan_covers_every_scoreable_season_through_2025_26(self):
        """Exploration scores every season through 2025-26 that an earlier season can fit on."""
        plan = exploration_plan()
        assert plan.scored == (20162017, 20252026)
        assert plan.game_types is None
        assert plan.cutoff is None

    def test_exploration_starts_after_the_first_fit_season(self):
        """The first scored season needs a season before it to fit on, so it is not 2015-16."""
        plan = exploration_plan()
        assert plan.scored[0] > plan.fit_first


class TestInCohort:
    """Test which games a plan scores."""

    def test_games_outside_the_season_range_are_out(self):
        """A season below the range is not in the cohort."""
        plan = SeasonPlan(scored=(20262027, 20262027))
        assert not in_cohort(_game(20252026, 2, datetime(2025, 11, 1, tzinfo=UTC)), plan)
        assert in_cohort(_game(20262027, 2, datetime(2026, 11, 1, tzinfo=UTC)), plan)

    def test_a_game_type_filter_excludes_playoffs(self):
        """Game type 3 is out when the plan keeps only type 2."""
        plan = SeasonPlan(scored=(20262027, 20262027), game_types=(2,))
        assert not in_cohort(_game(20262027, 3, datetime(2026, 11, 1, tzinfo=UTC)), plan)
        assert in_cohort(_game(20262027, 2, datetime(2026, 11, 1, tzinfo=UTC)), plan)

    def test_games_before_the_cutoff_are_out(self):
        """A plan with a cutoff scores only games that start after it."""
        cutoff = datetime(2026, 10, 31, tzinfo=UTC)
        plan = SeasonPlan(scored=(20262027, 20262027), cutoff=cutoff)
        assert not in_cohort(_game(20262027, 2, datetime(2026, 10, 1, tzinfo=UTC)), plan)
        assert in_cohort(_game(20262027, 2, datetime(2026, 11, 1, tzinfo=UTC)), plan)

    def test_no_cutoff_keeps_every_game_in_the_range(self):
        """A plan without a cutoff scores every game in the season range."""
        plan = SeasonPlan(scored=(20242025, 20252026))
        assert in_cohort(_game(20242025, 3, datetime(2025, 6, 1, tzinfo=UTC)), plan)


class TestScoredLabel:
    """Test the text that names the scored seasons."""

    def test_a_closed_range_is_named(self):
        """A plan with an end season says both ends."""
        assert scored_label(SeasonPlan(scored=(20242025, 20252026))) == (
            "seasons 20242025 to 20252026"
        )

    def test_an_open_end_is_named(self):
        """A confirmation plan says onward instead of a fake end season."""
        plan = confirmation_plan(datetime(2026, 10, 31, tzinfo=UTC))
        assert scored_label(plan) == "seasons from 20262027 onward"
