#!/bin/bash
# Notfall-Fix: DB-Migration einzeln durchführen (robust gegen bestehende Spalten)
DB="/root/.hermes/profiles/hermes_trading/skills/trading/data/trading.db"

echo "🗄  DB-Migration (robust)..."

# Jede Spalte einzeln — Fehler werden ignoriert
run_sql() {
    sqlite3 "$DB" "$1" 2>/dev/null && echo "   ✓ $2" || echo "   ℹ $2 (bereits vorhanden)"
}

run_sql "ALTER TABLE watchlist  ADD COLUMN conviction_score_bear REAL DEFAULT 0"    "conviction_score_bear"
run_sql "ALTER TABLE positions  ADD COLUMN partial_exit_done INTEGER DEFAULT 0"     "partial_exit_done"
run_sql "ALTER TABLE positions  ADD COLUMN highest_price REAL"                      "highest_price"
run_sql "ALTER TABLE positions  ADD COLUMN lowest_price  REAL"                      "lowest_price"
run_sql "ALTER TABLE positions  ADD COLUMN breakeven_set INTEGER DEFAULT 0"         "breakeven_set"
run_sql "ALTER TABLE eval_metrics ADD COLUMN sortino_30d REAL DEFAULT 0"            "sortino_30d"
run_sql "ALTER TABLE eval_metrics ADD COLUMN calmar_30d REAL DEFAULT 0"             "calmar_30d"
run_sql "ALTER TABLE eval_metrics ADD COLUMN max_drawdown_30d REAL DEFAULT 0"       "max_drawdown_30d"
run_sql "ALTER TABLE eval_metrics ADD COLUMN avg_r_multiple REAL DEFAULT 0"         "avg_r_multiple"
run_sql "ALTER TABLE eval_metrics ADD COLUMN exposure_long_pct REAL DEFAULT 0"      "exposure_long_pct"
run_sql "ALTER TABLE eval_metrics ADD COLUMN exposure_short_pct REAL DEFAULT 0"     "exposure_short_pct"
run_sql "ALTER TABLE eval_metrics ADD COLUMN exposure_net_pct REAL DEFAULT 0"       "exposure_net_pct"

# CREATE TABLE IF NOT EXISTS — immer sicher
sqlite3 "$DB" << 'SQL'
CREATE TABLE IF NOT EXISTS source_registry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL,
    source_key TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    language TEXT DEFAULT 'en',
    region TEXT DEFAULT 'global',
    category TEXT DEFAULT 'general',
    status TEXT DEFAULT 'candidate',
    status_changed_at TEXT,
    added_at TEXT DEFAULT (datetime('now')),
    added_by TEXT DEFAULT 'manual',
    weight REAL DEFAULT 1.0,
    enabled INTEGER DEFAULT 1,
    scan_interval_hours INTEGER DEFAULT 6,
    total_mentions INTEGER DEFAULT 0,
    total_bought INTEGER DEFAULT 0,
    total_wins INTEGER DEFAULT 0,
    total_losses INTEGER DEFAULT 0,
    win_rate_alltime REAL DEFAULT 0,
    win_rate_90d REAL DEFAULT 0,
    avg_pnl_per_trade REAL DEFAULT 0,
    avg_conviction_at_buy REAL DEFAULT 0,
    last_mention_date TEXT,
    last_win_date TEXT,
    consecutive_losses INTEGER DEFAULT 0,
    probation_start TEXT,
    probation_trades INTEGER DEFAULT 0,
    probation_wins INTEGER DEFAULT 0,
    probation_target_trades INTEGER DEFAULT 5,
    discovery_reason TEXT,
    rejection_reason TEXT,
    subscriber_count INTEGER,
    content_frequency TEXT
);
CREATE INDEX IF NOT EXISTS idx_source_status ON source_registry(status, source_type);
CREATE INDEX IF NOT EXISTS idx_source_perf   ON source_registry(win_rate_90d, total_bought);

CREATE TABLE IF NOT EXISTS benchmark (
    date TEXT PRIMARY KEY,
    spy_close REAL, dax_close REAL, portfolio_value REAL,
    spy_return_ytd REAL, dax_return_ytd REAL, portfolio_return_ytd REAL,
    alpha_spy REAL, alpha_dax REAL
);

CREATE TABLE IF NOT EXISTS backtest_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date TEXT, params_json TEXT, total_trades INTEGER,
    win_rate REAL, profit_factor REAL, sharpe REAL, sortino REAL,
    max_drawdown REAL, total_pnl_pct REAL, oos_profitable INTEGER, fold_details TEXT
);
SQL

echo "   ✓ Tabellen angelegt"

# Source Registry befüllen
SKILL="/root/.hermes/profiles/hermes_trading/skills/trading"
echo ""
echo "🔄 Source Registry befüllen..."
cd "$SKILL" && venv/bin/python scripts/source_lifecycle.py 2>&1 | grep -E "Migrier|✅|🔄|⚠|aktiv|DACH|US|UK" | head -30

# Cron-Job
echo ""
echo "⏰ Cron prüfen..."
CRON_LINE="0 7 * * 0  cd $SKILL && venv/bin/python scripts/source_lifecycle.py >> data/cron.log 2>&1"
if ! crontab -l 2>/dev/null | grep -q "source_lifecycle"; then
    (crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -
    echo "   ✓ Cron eingetragen (So. 07:00)"
else
    echo "   ℹ bereits in crontab"
fi

# Syntax-Check
echo ""
echo "🔍 Syntax-Check..."
ERRORS=0
for f in "$SKILL/scripts/"*.py; do
    result=$(cd "$SKILL" && venv/bin/python -c "import ast; ast.parse(open('$f').read())" 2>&1)
    if [ -n "$result" ]; then echo "   ❌ $(basename $f): $result"; ERRORS=$((ERRORS+1)); fi
done
[ $ERRORS -eq 0 ] && echo "   ✅ Alle Skripte OK" || echo "   ⚠ $ERRORS Fehler"

echo ""
echo "✅ Migration abgeschlossen"
echo ""
echo "Nächste Schritte:"
echo "  1.  cd /root/.hermes/profiles/hermes_trading/skills/trading"
echo "  2.  venv/bin/python scripts/signal_manager.py check_only"
echo "  3.  venv/bin/python scripts/fundamental_data.py   # Benchmark initialisieren"
echo "  4.  venv/bin/python scripts/dashboard.py           # Dashboard starten"
