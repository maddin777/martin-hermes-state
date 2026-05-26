-- Migration 001: Kern-Tabellen fuer Thematic Investing
-- Themes, Beneficiaries, Fundamentals, Factor Scores, Setup Zones, Thesis Status, Briefings

CREATE TABLE IF NOT EXISTS theme_definitions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    category        TEXT,
    description     TEXT NOT NULL,
    first_detected  DATE NOT NULL,
    last_seen       DATE NOT NULL,
    status          TEXT DEFAULT 'active',
    momentum        TEXT,
    underreported_score REAL,
    coverage_count  INTEGER DEFAULT 0,
    sources_json    TEXT,
    parent_theme_id INTEGER,
    embedding_vector TEXT,
    pm_confirmation_status TEXT,
    pm_confirmation_score REAL,
    archived_reason TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY(parent_theme_id) REFERENCES theme_definitions(id)
);
CREATE INDEX IF NOT EXISTS idx_theme_status ON theme_definitions(status);
CREATE INDEX IF NOT EXISTS idx_theme_last_seen ON theme_definitions(last_seen);

CREATE TABLE IF NOT EXISTS theme_beneficiaries (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    theme_id            INTEGER NOT NULL,
    ticker              TEXT NOT NULL,
    company_name        TEXT,
    play_type           TEXT,
    llm_confidence_count INTEGER,
    llm_models_picked   TEXT,
    rationale           TEXT,
    added_date          DATE NOT NULL,
    last_updated        DATE,
    status              TEXT DEFAULT 'candidate',
    archived_reason     TEXT,
    FOREIGN KEY(theme_id) REFERENCES theme_definitions(id),
    UNIQUE(theme_id, ticker)
);
CREATE INDEX IF NOT EXISTS idx_benef_status ON theme_beneficiaries(status);
CREATE INDEX IF NOT EXISTS idx_benef_ticker ON theme_beneficiaries(ticker);

CREATE TABLE IF NOT EXISTS fundamentals_snapshot (
    date            DATE NOT NULL,
    ticker          TEXT NOT NULL,
    market_cap_eur  REAL,
    pe_ttm          REAL,
    pe_forward      REAL,
    pe_sector_median REAL,
    fcf_yield       REAL,
    revenue_growth_yoy REAL,
    short_interest_pct REAL,
    analyst_count   INTEGER,
    debt_to_equity  REAL,
    roic            REAL,
    next_earnings_date DATE,
    flags_json      TEXT,
    PRIMARY KEY (date, ticker)
);

CREATE TABLE IF NOT EXISTS factor_scores (
    date            DATE NOT NULL,
    ticker          TEXT NOT NULL,
    momentum_score  REAL,
    quality_score   REAL,
    value_score     REAL,
    revision_score  REAL,
    lowvol_score    REAL,
    composite_score REAL,
    rank_in_universe INTEGER,
    PRIMARY KEY (date, ticker)
);
CREATE INDEX IF NOT EXISTS idx_factor_composite ON factor_scores(date, composite_score DESC);

CREATE TABLE IF NOT EXISTS setup_zones (
    date            DATE NOT NULL,
    ticker          TEXT NOT NULL,
    setup_type      TEXT NOT NULL,
    strength        REAL,
    distance_pct    REAL,
    notes           TEXT,
    PRIMARY KEY (date, ticker, setup_type)
);

CREATE TABLE IF NOT EXISTS thesis_status_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id     INTEGER,
    beneficiary_id  INTEGER,
    ticker          TEXT NOT NULL,
    theme_id        INTEGER,
    check_date      DATE NOT NULL,
    status          TEXT,
    confidence      REAL,
    rationale       TEXT,
    news_summary    TEXT,
    triggering_urls TEXT,
    pm_signal_used  TEXT,
    llm_model_used  TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY(position_id) REFERENCES positions(id),
    FOREIGN KEY(beneficiary_id) REFERENCES theme_beneficiaries(id)
);
CREATE INDEX IF NOT EXISTS idx_thesis_ticker_date ON thesis_status_log(ticker, check_date DESC);

CREATE TABLE IF NOT EXISTS briefings (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    date                DATE UNIQUE NOT NULL,
    content_md          TEXT NOT NULL,
    new_themes_count    INTEGER,
    red_alerts_count    INTEGER,
    yellow_alerts_count INTEGER,
    new_candidates_count INTEGER,
    thesis_breaks_count INTEGER,
    pm_signal_alerts    INTEGER,
    sent_to_telegram    INTEGER DEFAULT 0,
    user_marked_read    INTEGER DEFAULT 0,
    created_at          TEXT DEFAULT (datetime('now'))
);