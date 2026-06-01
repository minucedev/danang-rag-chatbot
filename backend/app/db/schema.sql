CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT    PRIMARY KEY,
    title       TEXT    NOT NULL,
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role        TEXT    NOT NULL CHECK(role IN ('user', 'assistant')),
    content     TEXT    NOT NULL DEFAULT '',
    sources_json TEXT,
    intent      TEXT,
    created_at  INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at);

CREATE TABLE IF NOT EXISTS profiles (
    session_id   TEXT    PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    profile_json TEXT    NOT NULL,
    updated_at   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT    NOT NULL,
    source_event_id TEXT    NOT NULL,
    title           TEXT    NOT NULL,
    description     TEXT,
    start_time      INTEGER,
    end_time        INTEGER,
    venue_name      TEXT,
    address         TEXT,
    district        TEXT,
    latitude        REAL,
    longitude       REAL,
    url             TEXT,
    image_url       TEXT,
    raw_json        TEXT,
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL,
    last_seen_at    INTEGER NOT NULL,
    UNIQUE (source, source_event_id)
);

CREATE INDEX IF NOT EXISTS idx_events_start ON events(start_time);
CREATE INDEX IF NOT EXISTS idx_events_district ON events(district);

CREATE TABLE IF NOT EXISTS session_context (
    session_id   TEXT    PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    context_json TEXT    NOT NULL,
    updated_at   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS missed_queries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    query           TEXT    NOT NULL,
    rewritten_query TEXT,
    intent          TEXT,
    session_id      TEXT,
    retry_count     INTEGER DEFAULT 0,
    status          TEXT    DEFAULT 'pending',
    created_at      INTEGER NOT NULL,
    last_tried_at   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_missed_queries_status ON missed_queries(status, created_at);
