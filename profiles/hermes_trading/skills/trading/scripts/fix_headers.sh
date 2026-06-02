#!/bin/bash
# Fix für watchlist_manager.py - fehlenden Header wiederherstellen
# und signal_manager.py - fehlenden Header wiederherstellen

SCRIPTS="/root/.hermes/profiles/hermes_trading/skills/trading/scripts"

# === BACKUP ===
cp "$SCRIPTS/watchlist_manager.py" "$SCRIPTS/watchlist_manager.py.bak"
cp "$SCRIPTS/signal_manager.py" "$SCRIPTS/signal_manager.py.bak"

echo "=== Fixing watchlist_manager.py ==="

# Finde wo der aktuelle Inhalt anfängt (erste Zeile nach dem kaputten sed)
# Aktuell fängt die Datei mit "from company_normalizer import" an
# Wir brauchen alles davor wieder

cat > /tmp/wm_header.py << 'HEADER'
"""
Watchlist Manager
- Liest analysierte Signale aus trading_signals.json
- Pflegt Watchlist über 14 Tage (reduziert von 30)
- Berechnet Conviction Score (bullish + bearish)
- Watchlist-Hygiene: Ticker-Drop, Tech-Score-Drop
"""
import sqlite3
import json
import os
import re
import math
import yfinance as yf
import pandas_ta as ta
from datetime import datetime, timedelta

# Validierungs-Pipeline aus Paket B
import sys as _sys
_sys.path.insert(0, '/root/.hermes/profiles/hermes_trading/skills/trading/scripts')
from company_validator import validate_and_register
# DRY: zentrale Funktionen aus Shared-Modulen
from utils import get_technical_score              # war lokale Kopie
HEADER

# Jetzt den Header + die bestehende Datei zusammenfügen
# Die Datei fängt aktuell mit "from company_normalizer" an - das behalten wir
# Aber wir müssen die doppelte "log = get_logger" und "from utils import get_logger" bereinigen

# Schritt 1: Header voranstellen
cat /tmp/wm_header.py "$SCRIPTS/watchlist_manager.py" > /tmp/wm_combined.py

# Schritt 2: Doppelte log-Zeile entfernen (die zweite "log = get_logger" Occurrence)
# Die erste ist jetzt korrekt nach "from utils import get_logger"
python3 -c "
content = open('/tmp/wm_combined.py').read()
# Entferne die doppelte 'log = get_logger(\"watchlist_manager\")' - behalte nur die erste
lines = content.split('\n')
found = False
clean = []
for line in lines:
    if line.strip() == 'log = get_logger(\"watchlist_manager\")':
        if not found:
            found = True
            clean.append(line)
        else:
            pass  # Skip duplicate
    else:
        clean.append(line)
open('/tmp/wm_final.py', 'w').write('\n'.join(clean))
"

cp /tmp/wm_final.py "$SCRIPTS/watchlist_manager.py"
echo "  ✅ watchlist_manager.py repariert"

# === Fixing signal_manager.py ===
echo "=== Fixing signal_manager.py ==="

# signal_manager.py fängt aktuell mit "from utils import get_logger" an
# Alles davor fehlt

cat > /tmp/sm_header.py << 'HEADER'
"""
Script 4: Signal Manager + Portfolio Manager
- Verwaltet offene Positionen (max 8)
- ATR-basierter SL/TP mit Slippage + Commission
- Position Sizing mit Cash-Reserve und Budget-Limit
- SHORT-Positionen (simuliert als Knockout-Zertifikat 1x Hebel)
- Partial Take-Profit bei +1.5x ATR
- Liquiditätsfilter
- Post-Trade-Analyse und Strategie-Anpassung
- Telegram-Benachrichtigungen
"""
import sqlite3
import json
import os
import sys
sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")
import env_loader  # noqa: F401  (side-effect: laedt .env)
import requests
import yfinance as yf
import pandas_ta as ta
from datetime import datetime, timedelta
from utils import passes_liquidity_filter, apply_slippage, COMMISSION_EUR
HEADER

cat /tmp/sm_header.py "$SCRIPTS/signal_manager.py" > /tmp/sm_combined.py

# Doppelte Zeilen bereinigen
python3 -c "
content = open('/tmp/sm_combined.py').read()
lines = content.split('\n')
found_log = False
found_config = False
clean = []
for line in lines:
    stripped = line.strip()
    # Doppelte log-Zeile
    if stripped == 'log = get_logger(\"signal_manager\")':
        if not found_log:
            found_log = True
            clean.append(line)
        else:
            pass
    # Doppelte config-Import-Zeile
    elif stripped.startswith('from config import DB_PATH, SIGNALS_VALIDATED_PATH, STRATEGY_CONFIG_PATH'):
        if not found_config:
            found_config = True
            clean.append(line)
        else:
            pass
    else:
        clean.append(line)
open('/tmp/sm_final.py', 'w').write('\n'.join(clean))
"

cp /tmp/sm_final.py "$SCRIPTS/signal_manager.py"
echo "  ✅ signal_manager.py repariert"

# === Verify ===
echo ""
echo "=== Verification ==="
echo "--- watchlist_manager.py header ---"
head -30 "$SCRIPTS/watchlist_manager.py"
echo ""
echo "--- signal_manager.py header ---"
head -30 "$SCRIPTS/signal_manager.py"
echo ""
echo "--- Import tests ---"
cd "$SCRIPTS"
python3 -c "
import sys
sys.path.insert(0, '.')
sys.path.insert(0, '/root/.hermes/profiles/hermes_trading/skills/trading')
" 2>&1

python3 -c "import watchlist_manager" 2>&1 | head -5
python3 -c "import signal_manager" 2>&1 | head -5
python3 -c "import signal_extractor" 2>&1 | head -5
python3 -c "import technical_validator" 2>&1 | head -5

echo ""
echo "=== Done. Backups: .bak files ==="
