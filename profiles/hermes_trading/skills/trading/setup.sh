#!/bin/bash
# Trading Skill - Cron Setup Script
# Ausfuehren mit: bash setup_cron.sh

SCRIPTS="/root/.hermes/profiles/hermes_trading/skills/trading/scripts"
LOG="/root/.hermes/profiles/hermes_trading/skills/trading/data/cron.log"
BACKUP="/root/obsidian-vault/Projekte"
PYTHON="/usr/bin/python3"

# API Keys aus .env lesen
OR_KEY=$(grep "^OPENROUTER_API_KEY=" /root/.hermes/.env | cut -d'=' -f2 | tr -d ' \n\r')
TG_TOKEN=$(grep "^TELEGRAM_BOT_TOKEN=" /root/.hermes/.env | cut -d'=' -f2 | tr -d ' \n\r')
TG_CHAT="-1003918757178"

echo "Richte Trading Cron-Jobs ein..."

# Bestehende Crontab sichern
crontab -l > /tmp/crontab_before_trading.txt 2>/dev/null
echo "Alte Crontab gesichert: /tmp/crontab_before_trading.txt"

# Nicht-Trading Zeilen behalten
grep -v "trading\|yt_channel\|signal_\|technical_validator\|watchlist\|strategy_optimizer\|trading_db_backup" \
    /tmp/crontab_before_trading.txt > /tmp/new_cron.txt 2>/dev/null || echo "" > /tmp/new_cron.txt

# Umgebungsvariablen
cat >> /tmp/new_cron.txt << ENVEOF
OPENROUTER_API_KEY=${OR_KEY}
TELEGRAM_BOT_TOKEN=${TG_TOKEN}
TELEGRAM_CHAT_ID=${TG_CHAT}

ENVEOF

# Helper Funktion fuer Cron-Zeilen mit Timestamp-Logging
add_cron() {
    local schedule="$1"
    local script="$2"
    local label="$3"
    local args="${4:-}"
    echo "${schedule} echo \"=== \$(date) === ${label} START ===\" >> ${LOG} && ${PYTHON} ${SCRIPTS}/${script} ${args} >> ${LOG} 2>&1 && echo \"=== \$(date) === ${label} DONE ===\" >> ${LOG}" >> /tmp/new_cron.txt
}

# ═══ TRADING SYSTEM ═══
echo "# ═══ TRADING SYSTEM ═══" >> /tmp/new_cron.txt

# Taeglich Mo-Fr
add_cron "0 11 * * 1-5"  "yt_channel_monitor.py"  "yt_channel_monitor"
add_cron "30 11 * * 1-5" "signal_extractor.py"     "signal_extractor"
add_cron "45 11 * * 1-5" "watchlist_manager.py"    "watchlist_manager"
add_cron "0 12 * * 1-5"  "technical_validator.py"  "technical_validator"
add_cron "15 12 * * 1-5" "signal_manager.py"       "signal_manager_full"     "full"

# Stuendlich SL/TP Check Mo-Fr 09-20
echo "0 9-20 * * 1-5 echo \"--- \$(date) --- signal_manager check ---\" >> ${LOG} && ${PYTHON} ${SCRIPTS}/signal_manager.py check_only >> ${LOG} 2>&1" >> /tmp/new_cron.txt

# Woechentlich
add_cron "0 20 * * 5"  "signal_manager.py"       "signal_manager_friday"   "full"
add_cron "0 10 * * 0"  "strategy_optimizer.py"   "strategy_optimizer"

# Taegliches DB Backup
echo "0 22 * * * cp /root/.hermes/profiles/hermes_trading/skills/trading/data/trading.db ${BACKUP}/trading_db_backup_\$(date +\%Y\%m\%d).db" >> /tmp/new_cron.txt

# Crontab aktivieren
crontab /tmp/new_cron.txt

echo ""
echo "Cron-Jobs eingerichtet:"
crontab -l | grep -E "TRADING|yt_channel|signal_|technical|watchlist|strategy|trading_db"
echo ""
echo "Aktive Jobs:"
crontab -l | grep -v "^#\|^$\|^[A-Z]" | wc -l

# Pruefe ob Dashboard Service laeuft
echo ""
echo "Pruefe Dashboard Service..."
if systemctl is-active --quiet trading-dashboard; then
    echo "Dashboard: aktiv (Port 8081)"
else
    echo "Dashboard: nicht aktiv - starte..."
    systemctl start trading-dashboard
    systemctl enable trading-dashboard
fi

# Pruefe Python Dependencies
echo ""
echo "Pruefe Dependencies..."
/usr/bin/python3 -c "import yfinance, pandas_ta, youtube_transcript_api, requests" 2>/dev/null \
    && echo "Dependencies: OK" \
    || echo "Dependencies fehlen - installiere..." && \
       pip3 install yfinance pandas-ta youtube-transcript-api requests yt-dlp --break-system-packages

echo ""
echo "Setup abgeschlossen."
