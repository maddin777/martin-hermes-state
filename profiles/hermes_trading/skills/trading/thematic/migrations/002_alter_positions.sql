-- Migration 002: Bestehende positions-Tabelle erweitern
-- Thesis-Tracking, Conviction-Scoring, Signal-Source, FX-Tracking, PM-Tracking

ALTER TABLE positions ADD COLUMN thesis_text TEXT;
ALTER TABLE positions ADD COLUMN thesis_theme_id INTEGER;
ALTER TABLE positions ADD COLUMN thesis_current_status TEXT DEFAULT 'intact';
ALTER TABLE positions ADD COLUMN entry_conviction_tier TEXT;
ALTER TABLE positions ADD COLUMN entry_conviction_score REAL;
ALTER TABLE positions ADD COLUMN signal_source TEXT;
ALTER TABLE positions ADD COLUMN highest_price REAL;
ALTER TABLE positions ADD COLUMN currency TEXT DEFAULT 'EUR';
ALTER TABLE positions ADD COLUMN entry_fx_rate REAL DEFAULT 1.0;
ALTER TABLE positions ADD COLUMN exit_fx_rate REAL;
ALTER TABLE positions ADD COLUMN pnl_local_currency REAL;
ALTER TABLE positions ADD COLUMN pnl_fx_effect_eur REAL;
ALTER TABLE positions ADD COLUMN pm_supporting_markets TEXT;