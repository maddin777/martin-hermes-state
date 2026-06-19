"""
config.py — Zentrales Konfigurations-Modul für Hermes Trading

Alle Pfade, Konstanten und Trading-Parameter an einem Ort.
Alle anderen Module importieren von hier:

    from config import DB_PATH, SIGNALS_PATH, ...

Pfad-Anpassung bei Server-Migration: nur hier ändern.
"""
import os
import sqlite3

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

TELEGRAM_TOKEN        = os.environ.get("TELEGRAM_BOT_TOKEN", "")
# TELEGRAM_HOME_CHANNEL: primär aus TELEGRAM_HOME_CHANNEL, Fallback auf TELEGRAM_CHAT_ID
# (Abwärtskompatibilität — alle Module nutzen diese config-Konstante statt direkt os.environ)
TELEGRAM_HOME_CHANNEL = os.environ.get("TELEGRAM_HOME_CHANNEL") \
                        or os.environ.get("TELEGRAM_CHAT_ID", "")
TELEGRAM_CHAT_ID      = TELEGRAM_HOME_CHANNEL  # Alias für Rückwärtskompatibilität

# ── Sentiment-Aging ───────────────────────────────────────────────────────────
CONVICTION_HALF_LIFE_DAYS = 14    # Halbwertszeit für Time-Decay in conviction_aged
CONVICTION_PRIOR_NEUTRAL  = 3.0   # Bayesian Prior (höher = konservativer bei wenig Daten)

# ── Trading-Parameter ─────────────────────────────────────────────────────────

WATCHLIST_DAYS  = 14      # Tage bis ein Signal aus der Watchlist fällt
MIN_MENTIONS    = 2       # Mindest-Mentions für Watchlist-Aufnahme
MIN_CONVICTION  = 0.55    # Mindest-Conviction Score (leicht gesenkt für SHORT)

# ── Portfolio-Limits ──────────────────────────────────────────────────────────

CASH_RESERVE_EUR  = 1500.0   # Immer liquide halten
MAX_ALLOC_PCT     = 0.70     # Max 70% des Kapitals investiert
MAX_POSITION_PCT  = 0.20     # Max 20% in einer einzelnen Position

# ── Asset-Typ-Klassifizierung (dynamische Exit-Regeln) ─────────────────────────
# Abgeleitet aus dem Sektor einer Position.
# Siehe wiki/concepts/Exit Management.md für die vollständige Dokumentation.

SECTOR_TO_ASSET_TYPE = {
    # TECH — höhere Volatilität, brauchen mehr Raum
    "Technology":            "TECH",
    "Communication Services": "TECH",
    # DEFENSIVE — niedrige Vola, enge Stops möglich
    "Consumer Defensive":    "DEFENSIVE",
    "Healthcare":            "DEFENSIVE",
    "Utilities":             "DEFENSIVE",
    # Alles andere → STANDARD
}

ASSET_TYPE_MULTIPLIERS = {
    "STANDARD": {
        "atr_sl": 1.5,
        "atr_tp": 2.5,
        "partial_atr": 1.5,
        "partial_pct": 0.50,
        "profit_lock_atr": 2.0,
        "trailing_step": 0.5,
    },
    "TECH": {
        "atr_sl": 2.0,
        "atr_tp": 3.5,
        "partial_atr": 2.0,
        "partial_pct": 0.50,
        "profit_lock_atr": 2.5,
        "trailing_step": 0.75,
    },
    "DEFENSIVE": {
        "atr_sl": 1.0,
        "atr_tp": 2.0,
        "partial_atr": 1.0,
        "partial_pct": 0.50,
        "profit_lock_atr": 1.5,
        "trailing_step": 0.3,
    },
}

DEFAULT_ASSET_TYPE = "STANDARD"


def get_asset_type(sector: str) -> str:
    """Leite den Asset-Typ aus dem Sektor ab."""
    return SECTOR_TO_ASSET_TYPE.get(sector, DEFAULT_ASSET_TYPE)


def get_asset_multipliers(asset_type: str = None, sector: str = None) -> dict:
    """Hole die ATR-Multiplikatoren für einen Asset-Typ.
    
    Args:
        asset_type: Direkter Typ (TECH/STANDARD/DEFENSIVE)
        sector: Sektor-Name (alternativ, wird dann in asset_type umgerechnet)
    """
    if asset_type is None and sector is not None:
        asset_type = get_asset_type(sector)
    at = asset_type or DEFAULT_ASSET_TYPE
    return ASSET_TYPE_MULTIPLIERS.get(at, ASSET_TYPE_MULTIPLIERS[DEFAULT_ASSET_TYPE])


# ── Slippage & Kosten ─────────────────────────────────────────────────────────

SLIPPAGE_PCT     = 0.001   # 0,1% pro Seite
COMMISSION_EUR   = 1.0     # Trade Republic: 1€ pro Trade


# ── Zentrale DB-Connection ─────────────────────────────────────────────────────
def db_connect(path=None):
    """Einheitliche DB-Connection mit WAL mode + busy_timeout + Row-Factory.
    Alle Scripts nutzen diese Funktion statt raw sqlite3.connect()."""
    if path is None:
        path = DB_PATH
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA busy_timeout=30000;")
    con.row_factory = sqlite3.Row
    return con
