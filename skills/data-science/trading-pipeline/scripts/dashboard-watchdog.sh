#!/bin/bash
# Dashboard-Watchdog — prüft alle 15min ob Port 8081 antwortet
# Restartet dashboard.py bei Fehlschlag
# Silent bei OK, Telegram-Benachrichtigung bei Restart

DASHBOARD_DIR="/root/.hermes/profiles/hermes_trading/skills/trading"
DASHBOARD_SCRIPT="$DASHBOARD_DIR/dashboard.py"
VENV_PYTHON="$DASHBOARD_DIR/venv/bin/python"

if ! curl -sf -o /dev/null http://localhost:8081/ 2>/dev/null; then
    pkill -f "dashboard.py" 2>/dev/null || true
    sleep 1
    cd "$DASHBOARD_DIR" && nohup "$VENV_PYTHON" dashboard.py > /dev/null 2>&1 &
    echo "⚠️ Dashboard war down → neu gestartet (PID: $!)"
fi
