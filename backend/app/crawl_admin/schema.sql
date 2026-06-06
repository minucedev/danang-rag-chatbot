-- Schema cho crawl-admin (SQLite: backend/data/crawl.db, xem crawl_admin/config.DB_PATH)

-- Danh sách URL nguồn được quản lý qua UI (v1: URL trang chi tiết entity Foody)
CREATE TABLE IF NOT EXISTS sources (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    url         TEXT    NOT NULL UNIQUE,
    category    TEXT    NOT NULL DEFAULT '',
    label       TEXT    NOT NULL DEFAULT '',
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  INTEGER NOT NULL
);

-- Entity đã crawl: data_json bị GHI ĐÈ hoàn toàn mỗi lần re-crawl;
-- last_crawl_at dùng để xét độ "cũ" (freshness) theo crawl-update.txt.
CREATE TABLE IF NOT EXISTS entities (
    id            TEXT    PRIMARY KEY,        -- id ổn định suy từ url
    url           TEXT    NOT NULL UNIQUE,
    source_id     INTEGER,
    name          TEXT    NOT NULL DEFAULT '',
    district      TEXT    NOT NULL DEFAULT '',
    data_json     TEXT    NOT NULL DEFAULT '',
    review_count  INTEGER,
    last_crawl_at INTEGER,                    -- epoch giây; NULL = chưa crawl lần nào
    status        TEXT    NOT NULL DEFAULT 'pending',  -- pending|crawling|done|error
    error         TEXT    NOT NULL DEFAULT '',
    created_at    INTEGER NOT NULL,
    updated_at    INTEGER NOT NULL,
    FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_entities_last_crawl ON entities(last_crawl_at);

-- Trạng thái mỗi engine (foody/traveloka/booking) — để gate freshness theo engine
CREATE TABLE IF NOT EXISTS engine_state (
    engine       TEXT    PRIMARY KEY,        -- 'foody'|'traveloka'|'booking'
    last_run_at  INTEGER,
    last_status  TEXT    NOT NULL DEFAULT '',
    enabled      INTEGER NOT NULL DEFAULT 1
);

-- Lịch sử mỗi lần chạy crawl
CREATE TABLE IF NOT EXISTS crawl_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    engine      TEXT    NOT NULL DEFAULT '',
    trigger     TEXT    NOT NULL DEFAULT 'manual',
    started_at  INTEGER NOT NULL,
    finished_at INTEGER,
    status      TEXT    NOT NULL DEFAULT 'running',  -- running|done|error
    total       INTEGER NOT NULL DEFAULT 0,
    ok          INTEGER NOT NULL DEFAULT 0,
    failed      INTEGER NOT NULL DEFAULT 0
);

-- Log từng bước (vừa lưu lịch sử vừa stream realtime ra UI)
CREATE TABLE IF NOT EXISTS crawl_logs (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id  INTEGER,
    ts      INTEGER NOT NULL,
    level   TEXT    NOT NULL DEFAULT 'info',
    message TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_logs_run ON crawl_logs(run_id, id);
