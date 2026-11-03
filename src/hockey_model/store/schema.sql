-- Source tables are append-only: each read carries fetched_at as ISO UTC, and a later
-- read adds a row. The exceptions are skater_games and goalie_games, which are written
-- once per game from a final boxscore and keyed on the game.

CREATE TABLE schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE source_reads (
    source TEXT,
    url TEXT,
    fetched_at TEXT NOT NULL,
    ok INTEGER,
    error TEXT
);

CREATE TABLE games (
    game_id INTEGER,
    season INTEGER,
    game_type INTEGER,
    start_utc TEXT,
    home TEXT,
    away TEXT,
    state TEXT,
    home_score INTEGER,
    away_score INTEGER,
    last_period TEXT,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (game_id, fetched_at)
);

CREATE TABLE players (
    nhl_id INTEGER,
    full_name TEXT,
    position TEXT,
    team TEXT,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (nhl_id, fetched_at)
);

-- Written once from a final boxscore, so keyed on the game only.
CREATE TABLE skater_games (
    game_id INTEGER,
    team TEXT,
    nhl_id INTEGER,
    toi_seconds INTEGER,
    goals INTEGER,
    assists INTEGER,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (game_id, nhl_id)
);

CREATE TABLE goalie_games (
    game_id INTEGER,
    team TEXT,
    nhl_id INTEGER,
    toi_seconds INTEGER,
    started INTEGER,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (game_id, nhl_id)
);

CREATE TABLE mp_team_games (
    game_id INTEGER,
    team TEXT,
    game_date TEXT,
    xg_for REAL,
    xg_against REAL,
    goals_for INTEGER,
    goals_against INTEGER,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (game_id, team, fetched_at)
);

CREATE TABLE mp_goalie_games (
    game_id INTEGER,
    nhl_id INTEGER,
    team TEXT,
    xg_against REAL,
    goals_against INTEGER,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (game_id, nhl_id, fetched_at)
);

CREATE TABLE starter_reads (
    game_id INTEGER,
    team TEXT,
    source TEXT,
    goalie_name TEXT,
    nhl_id INTEGER,
    status TEXT,
    fetched_at TEXT NOT NULL
);

CREATE TABLE injury_reads (
    team TEXT,
    player_name TEXT,
    nhl_id INTEGER,
    status TEXT,
    return_date TEXT,
    fetched_at TEXT NOT NULL
);

CREATE TABLE model_fits (
    fit_id INTEGER PRIMARY KEY,
    fit_through_season INTEGER,
    features TEXT,
    weights TEXT,
    created_at TEXT NOT NULL
);

-- Indexes for the as-of reads, which filter by time, team, and player.
CREATE INDEX IF NOT EXISTS games_start ON games (start_utc);
CREATE INDEX IF NOT EXISTS goalie_games_team ON goalie_games (team, started);
CREATE INDEX IF NOT EXISTS mp_team_games_team ON mp_team_games (team);
CREATE INDEX IF NOT EXISTS mp_goalie_games_player ON mp_goalie_games (nhl_id);
CREATE INDEX IF NOT EXISTS starter_reads_game ON starter_reads (game_id, team);
CREATE INDEX IF NOT EXISTS injury_reads_time ON injury_reads (fetched_at);
