#!/bin/bash
# ============================================================
# Hermes Trading System — Dependency Installer
# Installiert alle Python-Pakete für klassischen Bot + Thematic Bot
# Ausführen: bash install_dependencies.sh
# ============================================================

set -e

TRADING_DIR="/root/.hermes/profiles/hermes_trading/skills/trading"
VENV="$TRADING_DIR/venv/bin/pip"

echo "============================================================"
echo "Hermes Trading — Dependency Installer"
echo "============================================================"

# Prüfen ob venv existiert
if [ ! -f "$VENV" ]; then
    echo "❌ venv nicht gefunden unter $TRADING_DIR/venv"
    echo "   Bitte zuerst venv anlegen: python3 -m venv $TRADING_DIR/venv"
    exit 1
fi

echo ""
echo "📦 Upgrade pip..."
$VENV install --upgrade pip --quiet

echo ""
echo "📦 Klassischer Bot — Basispakete..."
$VENV install \
    yfinance \
    pandas \
    pandas_ta \
    requests \
    feedparser \
    sqlite3 2>/dev/null || true  # sqlite3 ist stdlib, ignorieren

echo "  ✓ yfinance, pandas, pandas_ta, requests, feedparser"

echo ""
echo "📦 Klassischer Bot — API-Clients..."
$VENV install \
    openai \
    httpx

echo "  ✓ openai, httpx"

echo ""
echo "📦 Thematic Bot — Neue Pakete..."
$VENV install \
    tavily-python \
    finnhub-python \
    sentence-transformers

echo "  ✓ tavily-python, finnhub-python, sentence-transformers"

echo ""
echo "📦 Dashboard..."
$VENV install \
    flask

echo "  ✓ flask"

echo ""
echo "📦 Optional: OpenAI Embeddings (für Theme-Merge)..."
# openai bereits oben installiert
echo "  ✓ openai (bereits installiert)"

echo ""
echo "📦 Verifiziere kritische Imports..."

PYTHON="$TRADING_DIR/venv/bin/python3"

check_import() {
    local pkg=$1
    local import=$2
    if $PYTHON -c "import $import" 2>/dev/null; then
        echo "  ✓ $pkg"
    else
        echo "  ✗ $pkg — FEHLER"
    fi
}

check_import "yfinance"           "yfinance"
check_import "pandas"             "pandas"
check_import "pandas_ta"          "pandas_ta"
check_import "requests"           "requests"
check_import "feedparser"         "feedparser"
check_import "flask"              "flask"
check_import "tavily-python"      "tavily"
check_import "finnhub-python"     "finnhub"
check_import "sentence-transformers" "sentence_transformers"
check_import "openai"             "openai"

echo ""
echo "📦 PYTHONPATH setzen (falls nicht vorhanden)..."
if ! grep -q "PYTHONPATH.*hermes_trading.*trading" /root/.bashrc; then
    echo "export PYTHONPATH=$TRADING_DIR" >> /root/.bashrc
    echo "  ✓ PYTHONPATH in .bashrc eingetragen"
else
    echo "  ✓ PYTHONPATH bereits gesetzt"
fi

echo ""
echo "📦 Environment Variables prüfen..."
check_env() {
    local var=$1
    if [ -n "${!var}" ]; then
        echo "  ✓ $var gesetzt"
    else
        echo "  ⚠ $var NICHT gesetzt — bitte in /root/.bashrc eintragen"
    fi
}

source /root/.bashrc 2>/dev/null || true
check_env "OPENROUTER_API_KEY"
check_env "TELEGRAM_BOT_TOKEN"
check_env "TELEGRAM_CHAT_ID"
check_env "TAVILY_API_KEY"
check_env "FINNHUB_API_KEY"
check_env "TWITTERAPI_IO_KEY"

echo ""
echo "============================================================"
echo "✅ Installation abgeschlossen"
echo ""
echo "Nächste Schritte:"
echo "  1. source /root/.bashrc"
echo "  2. cd $TRADING_DIR"
echo "  3. python3 thematic/theme_discovery.py  (Test)"
echo "============================================================"
