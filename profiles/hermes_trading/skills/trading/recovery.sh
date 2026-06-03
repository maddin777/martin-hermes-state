#!/bin/bash
BASE="/root/.hermes/profiles/hermes_trading/skills/trading"
LOG="$BASE/data/cron.log"
export PYTHONPATH="$BASE"

echo "=== $(date) === MANUAL RECOVERY START ===" >> "$LOG"

# 1. KI Analyse (llm_validator)
echo "--- llm_validator ---" >> "$LOG"
/usr/bin/python3 "$BASE/scripts/llm_validator.py" >> "$LOG" 2>&1
echo "Exit: $?" >> "$LOG"

# 2. Watchlist Update (trading_pipeline / watchlist_manager)
echo "--- trading_pipeline ---" >> "$LOG"
/usr/bin/python3 "$BASE/scripts/trading_pipeline.py" >> "$LOG" 2>&1
echo "Exit: $?" >> "$LOG"

# 3. Nightly Eval
echo "--- nightly_eval ---" >> "$LOG"
/usr/bin/python3 "$BASE/scripts/nightly_eval.py" >> "$LOG" 2>&1
echo "Exit: $?" >> "$LOG"

# 4. Signal Manager
echo "--- signal_manager ---" >> "$LOG"
/usr/bin/python3 "$BASE/scripts/signal_manager.py" full >> "$LOG" 2>&1
echo "Exit: $?" >> "$LOG"

# 5. Thematic: Theme Discovery
echo "--- theme_discovery ---" >> "$LOG"
cd "$BASE" && "$BASE/venv/bin/python3" thematic/theme_discovery.py >> "$BASE/data/thematic.log" 2>&1
echo "Exit: $?" >> "$LOG"

echo "=== $(date) === MANUAL RECOVERY DONE ===" >> "$LOG"
echo "Fertig. Log: $LOG"

