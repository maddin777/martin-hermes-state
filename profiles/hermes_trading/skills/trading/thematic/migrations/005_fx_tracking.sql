-- Migration 005: FX-Tracking (ALTER positions wurde in 002 erledigt)
-- Diese Migration erstellt die FX-Rates-History-Tabelle

CREATE TABLE IF NOT EXISTS fx_rates_history (
    date        DATE PRIMARY KEY,
    eur_usd     REAL,
    eur_jpy     REAL,
    eur_gbp     REAL,
    eur_nok     REAL,
    eur_chf     REAL,
    eur_sek     REAL,
    fetched_at  TEXT DEFAULT (datetime('now'))
);