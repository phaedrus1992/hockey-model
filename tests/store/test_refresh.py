"""Tests for refresh. A fake client serves the fixtures by URL, so no test uses the network."""

import copy
import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from hockey_model.sources.errors import SourceError
from hockey_model.sources.http import HttpClient
from hockey_model.sources.moneypuck import MONEYPUCK_CREDIT, TEAM_GAMES_URL, goalie_games_url
from hockey_model.store.db import connect
from hockey_model.store.refresh import refresh
from hockey_model.store.refresh_other import current_season_start
from hockey_model.store.source_reads import record_read

FIXTURES = Path(__file__).parent.parent / "fixtures"
NOW = datetime(2026, 1, 10, 10, 0, tzinfo=UTC)
SCORE_URL = "https://api-web.nhle.com/v1/score/"
BOX_URL = "https://api-web.nhle.com/v1/gamecenter/"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class FakeClient(HttpClient):
    """Serve the fixtures by URL and record every request."""

    def __init__(self, overrides: dict[str, bytes | Exception] | None = None) -> None:
        super().__init__()
        self.urls: list[str] = []
        self.overrides = overrides or {}

    def get(self, source: str, url: str) -> bytes:
        self.urls.append(url)
        body = self.overrides[url] if url in self.overrides else self._fixture_for(source, url)
        if isinstance(body, Exception):
            raise body
        return body

    def _fixture_for(self, source: str, url: str) -> bytes:
        if url.startswith(SCORE_URL):
            return self._score_day(url)
        if url.startswith(BOX_URL):
            payload = json.loads(fixture("nhl/boxscore_2025020709.json"))
            payload["id"] = int(url.split("/")[-2])
            return json.dumps(payload).encode()
        if url == TEAM_GAMES_URL:
            return fixture("moneypuck/all_teams_sample.csv")
        if "seasonPlayersSummary" in url:
            return fixture("moneypuck/goalies_2025_sample.zip")
        if "scoreboard" in url:
            return scoreboard(url.endswith("20260110")).encode()
        if url == f"{ESPN}/injuries":
            return fixture("espn/injuries.json")
        if "dailyfaceoff" in url:
            return fixture("daily_faceoff/starting_goalies.html")
        raise SourceError(source, url, "HTTP 404")

    @staticmethod
    def _score_day(url: str) -> bytes:
        if url.endswith("2026-01-10"):
            return fixture("nhl/score_2026-01-10.json")
        return b'{"games": []}'


def scoreboard(with_game: bool) -> str:
    """One ESPN game that matches stored game 2025020697: NYR at BOS, 2026-01-10 18:00Z."""
    payload = json.loads(fixture("espn/scoreboard_20261103.json"))
    event = copy.deepcopy(payload["events"][0])
    event["date"] = "2026-01-10T18:00Z"
    away, home = event["competitions"][0]["competitors"][0:2]
    away["team"]["abbreviation"], home["team"]["abbreviation"] = "NYR", "BOS"
    payload["events"] = [event] if with_game else []
    return json.dumps(payload)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "store.db")
    yield connection
    connection.close()


def count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608


def test_refresh_writes_every_source(conn: sqlite3.Connection) -> None:
    report = refresh(conn, FakeClient(), now=NOW, backfill_from=date(2026, 1, 10))
    assert report.errors == ()
    assert report.written["nhl_scores"] == 14
    assert report.written["nhl_boxscores"] == 14
    assert report.written["moneypuck"] > 0
    assert report.written["espn_starters"] == 2
    assert report.written["espn_injuries"] == 20
    assert count(conn, "games") == 14
    assert count(conn, "goalie_games") == 56
    assert count(conn, "starter_reads") == 2


def test_refresh_reports_unmatched_goalie_reads(conn: sqlite3.Connection) -> None:
    report = refresh(conn, FakeClient(), now=NOW, backfill_from=date(2026, 1, 10))
    assert any(
        "daily_faceoff" in note and "matched no stored game" in note for note in report.notes
    )


def test_refresh_credits_moneypuck_when_rows_written(conn: sqlite3.Connection) -> None:
    report = refresh(conn, FakeClient(), now=NOW, backfill_from=date(2026, 1, 10))
    assert report.credits == (MONEYPUCK_CREDIT,)


def test_refresh_isolates_source_failure(conn: sqlite3.Connection) -> None:
    tomorrow = f"{ESPN}/scoreboard?dates=20260111"
    client = FakeClient({tomorrow: b"<html>maintenance</html>"})
    report = refresh(conn, client, now=NOW, backfill_from=date(2026, 1, 10))
    assert len(report.errors) == 1
    assert "espn" in str(report.errors[0])
    assert report.written.get("espn_starters", 0) == 0
    assert count(conn, "starter_reads") == 0
    assert report.written["nhl_scores"] == 14
    assert report.written["espn_injuries"] == 20
    failed = conn.execute(
        "SELECT source, ok FROM source_reads WHERE ok = 0 AND source = 'espn_starters'"
    ).fetchall()
    assert failed == [("espn_starters", 0)]


def test_refresh_skips_fresh_moneypuck(conn: sqlite3.Connection) -> None:
    three_days_ago = NOW - timedelta(days=3)
    record_read(conn, "moneypuck", TEAM_GAMES_URL, three_days_ago)
    for season in range(2014, 2026):
        record_read(conn, "moneypuck", goalie_games_url(season), three_days_ago)
    conn.commit()
    client = FakeClient()
    refresh(conn, client, now=NOW, backfill_from=date(2026, 1, 10))
    assert not [url for url in client.urls if "moneypuck" in url or "peter-tanner" in url]


def test_refresh_reads_stale_moneypuck_files_again(conn: sqlite3.Connection) -> None:
    eight_days_ago = NOW - timedelta(days=8)
    record_read(conn, "moneypuck", TEAM_GAMES_URL, eight_days_ago)
    for season in range(2014, 2026):
        record_read(conn, "moneypuck", goalie_games_url(season), eight_days_ago)
    conn.commit()
    client = FakeClient()
    refresh(conn, client, now=NOW, backfill_from=date(2026, 1, 10))
    requested = [url for url in client.urls if "moneypuck" in url or "peter-tanner" in url]
    assert sorted(requested) == sorted([TEAM_GAMES_URL, goalie_games_url(2025)])


def test_refresh_is_incremental(conn: sqlite3.Connection) -> None:
    refresh(conn, FakeClient(), now=NOW, backfill_from=date(2026, 1, 10))
    refresh(conn, FakeClient(), now=NOW + timedelta(days=2))
    client = FakeClient()
    report = refresh(conn, client, now=NOW + timedelta(days=2, hours=1))
    score_days = sorted(u[len(SCORE_URL) :] for u in client.urls if u.startswith(SCORE_URL))
    assert score_days
    assert score_days[0] >= "2026-01-11"
    assert not [u for u in client.urls if u.startswith(BOX_URL)]
    assert report.written.get("nhl_boxscores", 0) == 0
    assert not [u for u in client.urls if "peter-tanner" in u or "moneypuck" in u]


def test_refresh_reads_a_day_again_until_it_is_over(conn: sqlite3.Connection) -> None:
    refresh(conn, FakeClient(), now=NOW, backfill_from=date(2026, 1, 10))
    client = FakeClient()
    refresh(conn, client, now=NOW + timedelta(hours=1))
    assert f"{SCORE_URL}2026-01-10" in client.urls


def test_refresh_finishes_a_game_that_was_in_progress(conn: sqlite3.Connection) -> None:
    live = json.loads(fixture("nhl/score_2026-01-10.json"))
    for game in live["games"]:
        game["gameState"] = "LIVE"
    url = f"{SCORE_URL}2026-01-10"
    first = refresh(
        conn, FakeClient({url: json.dumps(live).encode()}), now=NOW, backfill_from=date(2026, 1, 10)
    )
    assert first.written.get("nhl_boxscores", 0) == 0
    later = NOW + timedelta(hours=20)
    refresh(conn, FakeClient(), now=later)
    finals = conn.execute("SELECT COUNT(*) FROM games WHERE state = 'OFF'").fetchone()[0]
    assert finals == 14
    assert count(conn, "goalie_games") == 56


def test_refresh_stops_a_source_after_three_failures_in_a_row(conn: sqlite3.Connection) -> None:
    overrides: dict[str, bytes | Exception] = {
        f"{SCORE_URL}2026-01-{day:02d}": SourceError("nhl", "u", "HTTP 503") for day in range(1, 12)
    }
    client = FakeClient(overrides)
    report = refresh(conn, client, now=NOW, backfill_from=date(2026, 1, 1))
    assert len(report.errors) >= 3
    score_requests = [u for u in client.urls if u.startswith(SCORE_URL)]
    assert len(score_requests) == 3


def test_refresh_retries_a_failed_boxscore_only_after_a_day(conn: sqlite3.Connection) -> None:
    bad = f"{BOX_URL}2025020697/boxscore"
    refresh(
        conn,
        FakeClient({bad: SourceError("nhl", bad, "HTTP 404")}),
        now=NOW,
        backfill_from=date(2026, 1, 10),
    )
    client = FakeClient({bad: SourceError("nhl", bad, "HTTP 404")})
    refresh(conn, client, now=NOW + timedelta(hours=2))
    assert bad not in client.urls
    client = FakeClient()
    refresh(conn, client, now=NOW + timedelta(days=2))
    assert bad in client.urls


def test_refresh_rejects_naive_now(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="no timezone"):
        refresh(conn, FakeClient(), now=datetime(2026, 1, 10, 10, 0))


def test_refresh_uses_clock_for_each_read(conn: sqlite3.Connection) -> None:
    ticks = iter(NOW + timedelta(seconds=n) for n in range(10_000))
    refresh(conn, FakeClient(), now=NOW, backfill_from=date(2026, 1, 10), clock=lambda: next(ticks))
    stamps = {row[0] for row in conn.execute("SELECT fetched_at FROM goalie_games")}
    assert len(stamps) > 1


@pytest.mark.parametrize(
    ("moment", "season"),
    [
        (datetime(2026, 1, 10, tzinfo=UTC), 2025),
        (datetime(2026, 6, 30, tzinfo=UTC), 2025),
        (datetime(2026, 7, 1, tzinfo=UTC), 2026),
        (datetime(2026, 11, 3, tzinfo=UTC), 2026),
    ],
)
def test_current_season_start(moment: datetime, season: int) -> None:
    assert current_season_start(moment) == season


def test_a_finished_season_is_read_again_when_the_last_read_was_mid_season(
    conn: sqlite3.Connection,
) -> None:
    mid_season = datetime(2026, 4, 10, tzinfo=UTC)
    record_read(conn, "moneypuck", TEAM_GAMES_URL, mid_season)
    for season in range(2014, 2026):
        record_read(conn, "moneypuck", goalie_games_url(season), mid_season)
    conn.commit()
    client = FakeClient()
    refresh(conn, client, now=datetime(2026, 7, 2, tzinfo=UTC), backfill_from=date(2026, 7, 1))
    requested = [url for url in client.urls if "peter-tanner" in url]
    assert goalie_games_url(2025) in requested
    assert goalie_games_url(2026) in requested
    assert goalie_games_url(2024) not in requested


def test_a_season_read_after_it_ended_is_not_read_again(conn: sqlite3.Connection) -> None:
    after_season = datetime(2026, 7, 2, tzinfo=UTC)
    record_read(conn, "moneypuck", TEAM_GAMES_URL, after_season)
    for season in range(2014, 2027):
        record_read(conn, "moneypuck", goalie_games_url(season), after_season)
    conn.commit()
    client = FakeClient()
    refresh(conn, client, now=datetime(2026, 12, 1, tzinfo=UTC), backfill_from=date(2026, 12, 1))
    requested = [url for url in client.urls if "peter-tanner" in url]
    assert requested == [goalie_games_url(2026)]


def test_an_evening_refresh_reads_the_eastern_game_day(conn: sqlite3.Connection) -> None:
    evening = datetime(2026, 1, 11, 1, 0, tzinfo=UTC)  # 8 pm Eastern on January 10
    client = FakeClient()
    refresh(conn, client, now=evening, backfill_from=date(2026, 1, 10))
    espn_days = sorted(u[-8:] for u in client.urls if "scoreboard?dates=" in u)
    assert espn_days == ["20260110", "20260111"]
    assert f"{SCORE_URL}2026-01-12" in client.urls
    assert f"{SCORE_URL}2026-01-13" not in client.urls


def test_a_stopped_source_says_how_much_it_left(conn: sqlite3.Connection) -> None:
    overrides: dict[str, bytes | Exception] = {
        f"{SCORE_URL}2026-01-{day:02d}": SourceError("nhl", "u", "HTTP 503") for day in range(1, 12)
    }
    report = refresh(conn, FakeClient(overrides), now=NOW, backfill_from=date(2026, 1, 1))
    assert any("nhl_scores: stopped after 3 failed days; 9 not tried" in n for n in report.notes)


def test_skipped_boxscores_are_counted_in_the_notes(conn: sqlite3.Connection) -> None:
    bad = f"{BOX_URL}2025020697/boxscore"
    refresh(
        conn,
        FakeClient({bad: SourceError("nhl", bad, "HTTP 404")}),
        now=NOW,
        backfill_from=date(2026, 1, 10),
    )
    report = refresh(
        conn, FakeClient({bad: SourceError("nhl", bad, "HTTP 404")}), now=NOW + timedelta(hours=2)
    )
    assert any("nhl_boxscores: 1 skipped" in n for n in report.notes)
