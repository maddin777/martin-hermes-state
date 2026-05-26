-- Migration 003: News-Referenzen und Theme-Merge-Queue

CREATE TABLE IF NOT EXISTS news_references (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    url             TEXT UNIQUE NOT NULL,
    title           TEXT,
    source_domain   TEXT,
    published_at    DATE,
    content_hash    TEXT,
    content_snippet TEXT,
    used_in_theme_id INTEGER,
    used_in_thesis_check_id INTEGER,
    fetched_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY(used_in_theme_id) REFERENCES theme_definitions(id),
    FOREIGN KEY(used_in_thesis_check_id) REFERENCES thesis_status_log(id)
);
CREATE INDEX IF NOT EXISTS idx_news_published ON news_references(published_at);
CREATE INDEX IF NOT EXISTS idx_news_fetched ON news_references(fetched_at);

CREATE TABLE IF NOT EXISTS theme_merge_queue (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    new_theme_data          TEXT NOT NULL,
    candidate_existing_id   INTEGER,
    similarity_score        REAL,
    status                  TEXT DEFAULT 'pending',
    decided_at              TEXT,
    decided_by              TEXT DEFAULT 'human',
    created_at              TEXT DEFAULT (datetime('now')),
    FOREIGN KEY(candidate_existing_id) REFERENCES theme_definitions(id)
);