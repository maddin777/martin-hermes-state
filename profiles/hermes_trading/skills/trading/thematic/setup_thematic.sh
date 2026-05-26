#!/bin/bash
# Hermes Thematic Bot — Setup
# Fuehrt DB-Migrationen aus + Cron-Jobs setzen

set -e

SKILL_DIR="/root/.hermes/profiles/hermes_trading/skills/trading"
THEMATIC_DIR="$SKILL_DIR/thematic"
DB_PATH="$SKILL_DIR/data/trading.db"
LOG_PATH="$SKILL_DIR/data/thematic.log"
PYTHON="/usr/bin/python3"

echo "=== Hermes Thematic Setup ==="
echo ""

# 1. DB-Backup
if [ -f "$DB_PATH" ]; then
    cp "$DB_PATH" "${DB_PATH}.backup_$(date +%Y%m%d_%H%M%S)"
    echo "✅ DB-Backup erstellt"
fi

# 2. Migrationen ausfuehren
echo "📦 Fuehre Migrationen aus..."
for migration in "$THEMATIC_DIR/migrations"/*.sql; do
    echo "  → $(basename $migration)"
    sqlite3 "$DB_PATH" < "$migration" 2>/dev/null || echo "    ⚠ Einige Spalten existieren bereits (OK)"
done
echo "✅ Migrationen abgeschlossen"

# 3. Table-Integrity check
echo ""
echo "📊 DB-Tabellen:"
sqlite3 "$DB_PATH" ".tables"

# 4. Cron-Setup
echo ""
echo "⏰ Setze Cron-Jobs..."
TMP_CRON=$(mktemp)
crontab -l 2>/dev/null | grep -v "thematic/" > "$TMP_CRON" || true

cat >> "$TMP_CRON" << 'CRONEOF'

# Hermes Thematic Bot — Main Pipeline (Mo-Fr)
30 2 * * 1-5  /usr/bin/python3 /root/.hermes/profiles/hermes_trading/skills/trading/thematic/prediction_market_scanner.py >> /root/.hermes/profiles/hermes_trading/skills/trading/data/thematic.log 2>&1
0  3 * * 1-5  /usr/bin/python3 /root/.hermes/profiles/hermes_trading/skills/trading/thematic/thematic_pipeline.py >> /root/.hermes/profiles/hermes_trading/skills/trading/data/thematic.log 2>&1
0  7 * * 1-5  /usr/bin/python3 /root/.hermes/profiles/hermes_trading/skills/trading/thematic/briefing.py >> /root/.hermes/profiles/hermes_trading/skills/trading/data/thematic.log 2>&1

# Intraday Risk Monitoring (Mo-Fr)
0  10 * * 1-5 /usr/bin/python3 /root/.hermes/profiles/hermes_trading/skills/trading/thematic/drawdown_monitor.py >> /root/.hermes/profiles/hermes_trading/skills/trading/data/thematic.log 2>&1
30 15 * * 1-5 /usr/bin/python3 /root/.hermes/profiles/hermes_trading/skills/trading/thematic/thesis_monitor.py --intraday >> /root/.hermes/profiles/hermes_trading/skills/trading/data/thematic.log 2>&1
0  17 * * 1-5 /usr/bin/python3 /root/.hermes/profiles/hermes_trading/skills/trading/thematic/drawdown_monitor.py >> /root/.hermes/profiles/hermes_trading/skills/trading/data/thematic.log 2>&1

# Daily
0  22 * * *  /usr/bin/python3 /root/.hermes/profiles/hermes_trading/skills/trading/thematic/tax_tracker.py >> /root/.hermes/profiles/hermes_trading/skills/trading/data/thematic.log 2>&1

# Weekly (Sonntag)
0  4 * * 0   /usr/bin/python3 /root/.hermes/profiles/hermes_trading/skills/trading/thematic/news_cleanup.py >> /root/.hermes/profiles/hermes_trading/skills/trading/data/thematic.log 2>&1
0  8 * * 0   /usr/bin/python3 /root/.hermes/profiles/hermes_trading/skills/trading/thematic/weekly_review.py >> /root/.hermes/profiles/hermes_trading/skills/trading/data/thematic.log 2>&1
CRONEOF

crontab "$TMP_CRON"
rm "$TMP_CRON"
echo "✅ Cron-Jobs gesetzt"

# 5. Dependencies check
echo ""
echo "🔍 Pruefe Dependencies..."
$PYTHON -c "import yfinance, requests, sqlite3, json, numpy; print('✅ Basis-Dependencies OK')" 2>/dev/null || echo "⚠ Basis-Dependencies fehlen"
$PYTHON -c "import sentence_transformers; print('✅ sentence-transformers OK')" 2>/dev/null || echo "ℹ sentence-transformers nicht installiert (optional)"

# 6. Config
echo ""
echo "⚙️ Konfiguration:"
echo "  thematic_config.json: $THEMATIC_DIR/config/thematic_config.json"
echo "  news_sources.json:    $THEMATIC_DIR/config/news_sources.json"
echo "  universe.json:        $THEMATIC_DIR/config/universe.json"

echo ""
echo "=== Setup abgeschlossen ==="
echo ""
echo "Benötigte Env-Variablen:"
echo "  OPENROUTER_API_KEY  (fuer LLM-Calls via OpenRouter)"
echo "  GROK_LITE_API_KEY   (optional, fuer Grok Lite)"
echo "  TAVILY_API_KEY      (fuer News-Aggregation)"
echo "  FINNHUB_API_KEY     (fuer Fundamentaldaten)"
echo "  (Embeddings laufen ebenfalls via OPENROUTER_API_KEY)"
echo "  TELEGRAM_BOT_TOKEN  (für Telegram-Alerts)"
echo "  TELEGRAM_CHAT_ID"
echo ""
echo "Dashboard: http://192.168.178.16:8081 → Tab '🎓 Thematic'"