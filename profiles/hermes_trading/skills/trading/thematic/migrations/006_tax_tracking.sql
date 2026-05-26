-- Migration 006: Tax-Year-Tracking

CREATE TABLE IF NOT EXISTS tax_year_tracking (
    year                            INTEGER PRIMARY KEY,
    realized_gains_eur              REAL DEFAULT 0,
    realized_losses_eur             REAL DEFAULT 0,
    net_realized_eur                REAL DEFAULT 0,
    sparerpauschbetrag_eur          REAL DEFAULT 1000,
    sparerpauschbetrag_used         REAL DEFAULT 0,
    estimated_tax_liability_eur     REAL DEFAULT 0,
    dividends_us_received_eur       REAL DEFAULT 0,
    withholding_tax_credit_eur      REAL DEFAULT 0,
    notes                           TEXT,
    last_recalculated               TEXT
);