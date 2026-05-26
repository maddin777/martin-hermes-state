-- Migration 007: Prediction Markets (Polymarket)

CREATE TABLE IF NOT EXISTS prediction_markets (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    platform            TEXT NOT NULL DEFAULT 'polymarket',
    market_id           TEXT UNIQUE NOT NULL,
    question            TEXT NOT NULL,
    category            TEXT,
    resolution_date     DATE,
    current_yes_price   REAL,
    price_7d_ago        REAL,
    price_30d_ago       REAL,
    delta_7d            REAL,
    delta_24h           REAL,
    volume_24h_usd      REAL,
    total_volume_usd    REAL,
    liquidity_score     REAL,
    related_themes      TEXT,
    related_tickers     TEXT,
    classification_done INTEGER DEFAULT 0,
    status              TEXT DEFAULT 'active',
    last_updated        TEXT,
    created_at          TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_pm_active ON prediction_markets(status, total_volume_usd DESC);

CREATE TABLE IF NOT EXISTS prediction_market_history (
    market_id           TEXT NOT NULL,
    timestamp           TEXT NOT NULL,
    yes_price           REAL,
    volume_24h_usd      REAL,
    PRIMARY KEY (market_id, timestamp)
);

CREATE TABLE IF NOT EXISTS pm_index_definitions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT UNIQUE,
    description         TEXT,
    constituent_markets TEXT,
    current_value       REAL,
    delta_7d            REAL,
    last_calculated     TEXT
);