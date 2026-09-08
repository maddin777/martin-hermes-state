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
MIN_CONVICTION  = 0.60    # Mindest-Conviction Score (leicht gesenkt für SHORT)

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

# ── Sektor→ETF-Regime-Map (06.09.2026) ──────────────────────────────────────
# Jeder Sektor bekommt sein eigenes Markt-Regime aus seinem Sektor-ETF,
# statt dem globalen SPY/DAX-Regime. Ermöglicht: Tech kann bull sein, während
# der Gesamtmarkt sideways ist — Gold-Minen können bull sein, wenn SPY seitwärts.
# Fallback für unbekannte Sektoren = SPY.
SECTOR_TO_ETF = {
    "Technology":              "XLK",   # Tech-Sektor
    "Communication Services":  "XLC",   # Kommunikation
    "Consumer Cyclical":       "XLY",   # zyklischer Konsum
    "Consumer Defensive":      "XLP",   # defensiver Konsum
    "Healthcare":              "XLV",   # Gesundheit
    "Financial Services":      "XLF",   # Finanzen
    "Energy":                  "XLE",   # Energie
    "Industrials":             "XLI",   # Industrie
    "Basic Materials":         "XLB",   # Grundstoffe (inkl. Gold-Minen-Proxy... GDX besser)
    "Utilities":               "XLU",   # Versorger
    "Real Estate":             "XLRE",  # Immobilien
}
# Edelmetall-Sonderfall: Basic Materials enthält Gold-Minen, die sich stark von
# XLB unterscheiden. GDX (Gold-Miner) ist der bessere Regime-Proxy für Gold-Titel.
# Wird in fundamental_data.py je nach Unternehmen (Gold) aufgelöst; hier als
# Zusatz-Hinweis dokumentiert.
PRECIOUS_METALS_SECTOR_HINT = "Basic Materials"

# Alle Sektor-ETFs die ein eigenes Regime bekommen (für den täglichen Scan).
REGIME_ETF_UNIVERSE = sorted(set(SECTOR_TO_ETF.values()) | {"XLK", "GDX", "SPY"})


ASSET_TYPE_MULTIPLIERS = {
    "STANDARD": {
        "atr_sl": 1.5,
        "atr_tp": 2.5,
        "partial_atr": 1.5,
        "partial_pct": 0.50,
        "profit_lock_atr": 1.0,
        "trailing_step": 0.5,
    },
    "TECH": {
        "atr_sl": 2.0,
        "atr_tp": 3.5,
        "partial_atr": 2.0,
        "partial_pct": 0.50,
        "profit_lock_atr": 1.0,
        "trailing_step": 0.75,
    },
    "DEFENSIVE": {
        "atr_sl": 1.0,
        "atr_tp": 2.0,
        "partial_atr": 1.0,
        "partial_pct": 0.50,
        "profit_lock_atr": 1.0,
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


# ── Exit-Config-Matrix (Single Source of Truth, 09.08.2026) ────────────────
# Konsolidiert die drei vorherigen überlagerten Trail-/SL-/TP-Quellen
# (ASSET_TYPE_MULTIPLIERS + regime_configs in signal_manager + strategy_config)
# in EINE deterministische Matrix. get_exit_config() ist die einzige Quelle für
# Exit-Parameter — kein weiteres Regime-Trippen in signal_manager mehr nötig.
#
# profit_lock_atr = 1.0x Kompromiss: niedriger als der alte 2.0 (im Sideways
# unerreichbar → 0% TP), hoch genug um Intraday-Noise-Trails (0.5) zu vermeiden.
# Eine volle Tages-ATR an Raum gilt als Swing-verträglich (glm-5.2-Review 09.08).
_EXIT_CONFIG_MATRIX = {
    ("STANDARD", "bull"):     {"sl": 1.5, "tp": 4.5, "partial_atr": 1.5, "profit_lock_atr": 1.0, "chandelier_mult": 2.0, "step": 0.75},
    ("STANDARD", "sideways"): {"sl": 1.5, "tp": 4.5, "partial_atr": 1.5, "profit_lock_atr": 1.0, "chandelier_mult": 2.0, "step": 0.75},
    ("STANDARD", "bear"):     {"sl": 2.0, "tp": 6.0, "partial_atr": 1.5, "profit_lock_atr": 1.0, "chandelier_mult": 2.0, "step": 0.75},
    ("TECH", "bull"):         {"sl": 2.0, "tp": 6.0, "partial_atr": 2.0, "profit_lock_atr": 1.0, "chandelier_mult": 2.0, "step": 0.75},
    ("TECH", "sideways"):     {"sl": 2.0, "tp": 6.0, "partial_atr": 2.0, "profit_lock_atr": 1.0, "chandelier_mult": 2.0, "step": 0.75},
    ("TECH", "bear"):         {"sl": 2.5, "tp": 7.5, "partial_atr": 2.0, "profit_lock_atr": 1.0, "chandelier_mult": 2.0, "step": 0.75},
    ("DEFENSIVE", "bull"):    {"sl": 1.0, "tp": 3.0, "partial_atr": 1.0, "profit_lock_atr": 1.0, "chandelier_mult": 2.0, "step": 0.3},
    ("DEFENSIVE", "sideways"):{"sl": 1.0, "tp": 3.0, "partial_atr": 1.0, "profit_lock_atr": 1.0, "chandelier_mult": 2.0, "step": 0.3},
    ("DEFENSIVE", "bear"):    {"sl": 1.5, "tp": 4.5, "partial_atr": 1.0, "profit_lock_atr": 1.0, "chandelier_mult": 2.0, "step": 0.3},
}
DEFAULT_EXIT_CONFIG = {"sl": 1.5, "tp": 4.5, "partial_atr": 1.5, "profit_lock_atr": 1.0, "chandelier_mult": 2.0, "step": 0.75}


def get_exit_config(asset_type=None, sector=None, regime="sideways"):
    """Single Source of Truth für Exit-Parameter.

    Liefert {sl, tp, partial_atr, profit_lock_atr, chandelier_mult, step}
    deterministisch aus der
    Exit-Matrix für (asset_type, regime). Konsolidiert die drei vorherigen
    Config-Quellen. Fallback auf DEFAULT_EXIT_CONFIG bei unbekannter Kombi.
    """
    if asset_type is None and sector is not None:
        asset_type = get_asset_type(sector)
    at = asset_type or DEFAULT_ASSET_TYPE
    if at not in ("STANDARD", "TECH", "DEFENSIVE"):
        at = DEFAULT_ASSET_TYPE
    regime = (regime or "sideways").lower()
    if regime not in ("bull", "sideways", "bear"):
        regime = "sideways"
    return dict(_EXIT_CONFIG_MATRIX.get((at, regime), DEFAULT_EXIT_CONFIG))


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


# ── Sektor-Regime (06.09.2026) ────────────────────────────────────────────────
# Jeder Sektor hat sein eigenes Markt-Regime (aus Sektor-ETF), gespeichert in
# der `sector_regimes`-Tabelle. signal_manager/get_exit_config lesen daraus das
# regime für den Sektor eines Kandidaten statt das globale SPY-Regime.

def sector_to_etf(sector: str) -> str:
    """Gibt den Sektor-ETF für einen GICS-Sektor zurück. Fallback SPY."""
    if sector is None:
        return "SPY"
    return SECTOR_TO_ETF.get(sector, "SPY")


# Edelmetall-Industries (Gold/Silber/Edelmetall-Minen) → GDX statt XLB,
# weil sie sich stark vom allgemeinen Grundstoff-Sektor unterscheiden.
# Siehe auch SECTOR_TO_ETF-Kommentar zu Basic Materials.
PRECIOUS_METAL_INDUSTRIES = {
    "Gold", "Silver", "Other Precious Metals & Mining", "Gold & Silver",
    "Precious Metals", "Gold and Silver",
}


def sector_regime_key(sector: str, industry: str = None) -> str:
    """Bestimmt den Regime-Schlüssel (sector in sector_regimes) für einen Ticker.

    Für Edelmetall-Industries innerhalb 'Basic Materials' → 'Basic Materials (Gold)'
    (dort wird das GDX-Regime gespeichert). Sonst der Sektor selbst.
    """
    if sector == "Basic Materials" and industry and industry in PRECIOUS_METAL_INDUSTRIES:
        return "Basic Materials (Gold)"
    return sector


def init_sector_regimes_table(con=None):
    """Legt die sector_regimes-Tabelle an (idempotent)."""
    own = con is None
    if own:
        con = db_connect()
    try:
        con.execute("""
            CREATE TABLE IF NOT EXISTS sector_regimes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sector TEXT NOT NULL,
                etf_ticker TEXT NOT NULL,
                regime TEXT NOT NULL,
                date TEXT NOT NULL,
                ret_20d REAL,
                UNIQUE(sector, date)
            )
        """)
        con.commit()
    finally:
        if own:
            con.close()


def get_sector_regime(sector: str, con=None) -> str:
    """Liefert das aktuelle Regime für einen Sektor (aus sector_regimes).

    Fallback: wenn kein Sektor-Eintrag, 'sideways' (konservativ). Das globale
    Regime bleibt über regime_history verfügbar.
    """
    if sector is None:
        return "sideways"
    own = con is None
    if own:
        con = db_connect()
    try:
        row = con.execute(
            "SELECT regime FROM sector_regimes WHERE sector=? ORDER BY date DESC, id DESC LIMIT 1",
            (sector,)
        ).fetchone()
        return row["regime"] if row and row["regime"] in ("bull", "sideways", "bear") else "sideways"
    finally:
        if own:
            con.close()
