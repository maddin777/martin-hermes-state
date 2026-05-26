-- Migration 004: Portfolio-Drawdown-Tracking + System-State

CREATE TABLE IF NOT EXISTS drawdown_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date            DATE NOT NULL,
    portfolio_value REAL,
    all_time_high   REAL,
    drawdown_pct    REAL,
    trigger_level   TEXT,
    action_taken    TEXT,
    user_notes      TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS system_state (
    key             TEXT PRIMARY KEY,
    value           TEXT,
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- Beispiel-Keys (werden bei Bedarf gesetzt):
-- 'system_paused'        = 'true' | 'false'
-- 'pause_reason'         = 'drawdown_20pct' | ...
-- 'pause_timestamp'      = ISO-Datetime
-- 'reactivation_eligible_at' = ISO-Datetime
-- 'reactivation_reflection'  = User-Text