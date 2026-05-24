#!/bin/bash
# Trading Skill Runner
# Wird von Hermes aufgerufen

SCRIPTS="/root/.hermes/profiles/hermes_trading/skills/trading/scripts"
LOG="/root/.hermes/profiles/hermes_trading/skills/trading/data/cron.log"
PYTHON="/usr/bin/python3"

source /root/.bashrc

case "$1" in
  scan)
    echo "🔍 Starte YouTube Scan..."
    $PYTHON $SCRIPTS/yt_channel_monitor.py 2>&1 | tee -a $LOG
    $PYTHON $SCRIPTS/signal_extractor.py 2>&1 | tee -a $LOG
    $PYTHON $SCRIPTS/technical_validator.py 2>&1 | tee -a $LOG
    $PYTHON $SCRIPTS/signal_manager.py full 2>&1 | tee -a $LOG
    ;;
  check)
    $PYTHON $SCRIPTS/signal_manager.py check_only 2>&1 | tee -a $LOG
    ;;
  optimize)
    $PYTHON $SCRIPTS/strategy_optimizer.py 2>&1 | tee -a $LOG
    ;;
  status)
    $PYTHON $SCRIPTS/signal_manager.py check_only 2>&1
    ;;
  *)
    echo "Usage: run.sh {scan|check|optimize|status}"
    ;;
esac

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a $LOG
}

  watchlist)
    $PYTHON $SCRIPTS/watchlist_manager.py 2>&1 | tee -a $LOG
    ;;
