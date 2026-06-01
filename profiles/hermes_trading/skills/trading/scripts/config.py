"""
config.py — Zentrales Konfigurations-Modul für Hermes Trading

Alle Pfade, Konstanten und Trading-Parameter an einem Ort.
Alle anderen Module importieren von hier:

    from config import DB_PATH, SIGNALS_PATH, ...

Pfad-Anpassung bei Server-Migration: nur hier ändern.
"""
import os

# ── Basis-Verzeichnisse ───────────────────────────────────────────────────────

TRADING_ROOT = "/root/.hermes/profiles/hermes_trading/skills/trading"
SCRIPTS_DIR  = os.path.join(TRADING_ROOT, "scripts")
DATA_DIR     = os.path.join(TRADING_ROOT, "data")
CONFIG_DIR   = os.path.join(TRADING_ROOT, "config")

# ── Datenbank ─────────────────────────────────────────────────────────────────

DB_PATH = os.path.join(DATA_DIR, "trading.db")

# ── Signal-Dateien ────────────────────────────────────────────────────────────

SIGNALS_PATH           = os.path.join(DATA_DIR, "trading_signals.json")
SIGNALS_VALIDATED_PATH = os.path.join(DATA_DIR, "trading_signals_validated.json")
MACRO_SIGNAL_PATH      = os.path.join(DATA_DIR, "macro_signal.json")

# ── Konfigurations-Dateien ────────────────────────────────────────────────────

SOURCES_CONFIG_PATH   = os.path.join(CONFIG_DIR, "sources.json")
STRATEGY_CONFIG_PATH  = os.path.join(DATA_DIR, "strategy_config.json")

# ── Log-Dateien ───────────────────────────────────────────────────────────────

CRON_LOG_PATH          = os.path.join(DATA_DIR, "cron.log")
THEMATIC_LOG_PATH      = os.path.join(DATA_DIR, "thematic.log")
VALIDATION_REJECTS_LOG = os.path.join(DATA_DIR, "company_validation_rejects.log")

# ── Report-Dateien ────────────────────────────────────────────────────────────

BACKTEST_REPORT_PATH     = os.path.join(DATA_DIR, "backtest_results.json")
OPTIMIZATION_REPORT_PATH = os.path.join(DATA_DIR, "optimization_report.json")

# ── Externe Pfade ─────────────────────────────────────────────────────────────

OBSIDIAN_WATCHLIST_PATH = "/root/obsidian-vault/Trading/Watchlist.md"

# ── Telegram ──────────────────────────────────────────────────────────────────

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ── Trading-Parameter ─────────────────────────────────────────────────────────

WATCHLIST_DAYS  = 14      # Tage bis ein Signal aus der Watchlist fällt
MIN_MENTIONS    = 2       # Mindest-Mentions für Watchlist-Aufnahme
MIN_CONVICTION  = 0.55    # Mindest-Conviction Score (leicht gesenkt für SHORT)

# ── Portfolio-Limits ──────────────────────────────────────────────────────────

CASH_RESERVE_EUR  = 1500.0   # Immer liquide halten
MAX_ALLOC_PCT     = 0.70     # Max 70% des Kapitals investiert
MAX_POSITION_PCT  = 0.20     # Max 20% in einer einzelnen Position

# ── Slippage & Kosten ─────────────────────────────────────────────────────────

SLIPPAGE_PCT     = 0.001   # 0,1% pro Seite
COMMISSION_EUR   = 1.0     # Trade Republic: 1€ pro Trade
