"""
Company Validator – Pipeline zur Pruefung neuer Firmen vor Insert in `companies`.

Public API:
    validate(name)                  -> result dict (nur lesen, kein DB-Write)
    validate_and_register(name)     -> result dict (validiert + ggf. DB-Insert)

Result Dict:
    {
        "status":  "accepted" | "rejected" | "already_known",
        "ticker":  "AAPL" | None,
        "reason":  None | "unknown" | "not_equity" | "name_mismatch" | "low_liquidity" | "yf_error",
        "details": dict mit Zusatzinfos (yahoo_name, quote_type, volume, etc.)
    }
"""
import sqlite3
import time
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

import yfinance as yf

# Suffix-Stripper aus technical_validator wiederverwenden
import sys
sys.path.insert(0, '/root/.hermes/profiles/hermes_trading/skills/trading/scripts')
from technical_validator import _strip_suffixes
from config import DB_PATH
from utils import retry, VALIDATION_REJECTS_LOG

# --- Konfiguration ---
# VALIDATION_REJECTS_LOG → VALIDATION_REJECTS_LOG aus config.py

# Liquiditaets-Schwelle: avg_volume * price > 1M (Waehrung egal, FX-Konvertierung optional)
MIN_LIQUIDITY = 1_000_000

# Adaptiver Name-Plausibilitaets-Threshold abhaengig von Input-Laenge
# Bei kurzen Namen ('HP', 'MU') muss Yahoo-Name SEHR aehnlich sein, um Mehrdeutigkeit zu vermeiden.
def _name_threshold(name: str) -> float:
    n = len(name.strip())
    if n <= 3:  return 0.6
    if n <= 8:  return 0.4
    return 0.25


# --- Helper ---
def _log_reject(name, ticker, reason, details):
    """Append-only Log fuer rejected Companies."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts}\t{name!r}\t{ticker or '-'}\t{reason}\t{details}\n"
    try:
        with open(VALIDATION_REJECTS_LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass  # Logging-Fehler darf Pipeline nicht stoppen

def _is_known(name: str):
    """
    Check ob Alias bereits in DB.

    Returns:
        None                       -> unbekannt, weiter mit yf.Search
        (ticker_str, "active")     -> aktive, handelbare Aktie
        (None, "private")          -> bekannt aber privat (nicht handelbar)
        (ticker_str, "manual_block"|"delisted")  -> bekannt aber blockiert
    """
    if not Path(DB_PATH).is_file():
        return None
    try:
        con = sqlite3.connect(DB_PATH)
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA busy_timeout=5000;")
        cur = con.cursor()
        # 1. Voller Name
        key = name.lower().strip()
        cur.execute("""
            SELECT a.ticker, c.status
            FROM company_aliases a
            JOIN companies c ON c.ticker = a.ticker
            WHERE a.alias = ?
        """, (key,))
        row = cur.fetchone()
        if row:
            con.close()
            ticker, status = row
            return (None, status) if status == 'private' else (ticker, status)
        # 2. Suffix-gestripped
        stripped = _strip_suffixes(key)
        if stripped and stripped != key:
            cur.execute("""
                SELECT a.ticker, c.status
                FROM company_aliases a
                JOIN companies c ON c.ticker = a.ticker
                WHERE a.alias = ?
            """, (stripped,))
            row = cur.fetchone()
            if row:
                con.close()
                ticker, status = row
                return (None, status) if status == 'private' else (ticker, status)
        con.close()
        return None
    except Exception:
        return None

def _name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


# --- Public API ---
# ── ISIN-Cross-Exchange-Mapping ────────────────────────────────────────────────
# Bekannte ISIN-formatige Ticker wie "US4330001060.SG" → primärer US-Ticker
# Entsteht wenn der LLM oder yfinance ISIN statt Ticker liefert
ISIN_TICKER_MAP = {
    "US4330001060.SG": "HIMS",    # Hims & Hers Health
    "IE00BKVD2N49.SG": "STX",     # Seagate Technology
    "US78446M1099.SG": "SMASM",   # SMA Solar ADR (kein US-Ticker verfügbar)
    "US87155N1090.SG": "SY1.DE",  # Symrise
    "US8334451098.SG": "SNOW",    # Snowflake
    "US7865841024.SG": "SAF.PA",  # Safran
    "US4330001060":    "HIMS",    # ohne .SG-Suffix
    "IE00BKVD2N49":    "STX",
    "US8334451098":    "SNOW",
    "US7865841024":    "SAF.PA",
}

def _resolve_isin_ticker(name_or_ticker: str) -> str | None:
    """
    Erkennt ISIN-formatige Ticker (12 Zeichen, Länderkürzel + Ziffern + Suffix)
    und gibt den primären Ticker zurück falls bekannt.
    Returns None wenn kein Mapping vorhanden.
    """
    import re as _re
    # Direkt im Mapping
    key = name_or_ticker.upper()
    if key in ISIN_TICKER_MAP:
        return ISIN_TICKER_MAP[key]
    # Pattern: US/IE/DE + 10 Ziffern/Buchstaben + optionales .XX
    if _re.match('^[A-Z]{2}[A-Z0-9]{10}(\\.[A-Z]{1,3})?$', key):
        # ISIN-Pattern erkannt, aber kein Mapping → gibt None zurück
        return None
    return None


def validate(name: str) -> dict:
    """
    Validiert einen Firmennamen, OHNE DB-Write.
    Reihenfolge der Checks: cache -> yf.Search -> quoteType -> name-sim -> liquidity.

    Returns dict:
        {"status": "already_known"|"accepted"|"rejected",
         "ticker": str or None,
         "reason": None or str,
         "details": dict mit yahoo_name, quote_type, sector, ...}
    """
    name = (name or "").strip()
    if not name:
        return {"status": "rejected", "ticker": None, "reason": "empty_input", "details": {}}

    # === Step 1: Cache-Lookup ===
    known = _is_known(name)
    if known is not None:
        ticker, status = known
        return {
            "status":  "already_known",
            "ticker":  ticker,
            "reason":  None if status == 'active' else status,  # 'private', 'manual_block', 'delisted'
            "details": {"db_status": status},
        }
    # === Step 2: yf.Search ===
    try:
        results = yf.Search(name, max_results=5)  # mehr Kandidaten als bisher
        quotes = results.quotes or []
    except Exception as e:
        _log_reject(name, None, "yf_error", str(e)[:100])
        return {"status": "rejected", "ticker": None, "reason": "yf_error",
                "details": {"error": str(e)[:100]}}

    if not quotes:
        _log_reject(name, None, "unknown", "yf.Search returned no quotes")
        return {"status": "rejected", "ticker": None, "reason": "unknown",
                "details": {"quotes_count": 0}}

    # Sortier-Heuristik: Bei US-Hauptlisting (kein Suffix) ist Liquiditaet meist viel hoeher
    # als bei DE-Nebenlistings (.F, .MU, .SG). Daher: erst die ohne Suffix probieren,
    # dann DE-Hauptboerse (.DE), dann Rest.
    def _exchange_priority(q):
        sym = q.get("symbol", "")
        if "." not in sym and "-" not in sym:
            return 0   # US/no-suffix: hoechste Prio
        if sym.endswith(".DE"):
            return 1   # XETRA: zweite Prio
        if sym.endswith((".F", ".MU", ".SG", ".DU", ".HM", ".BE")):
            return 3   # DE-Nebenboersen: niedrige Prio
        return 2   # Sonstiges (.PA, .HK, .L etc.): mittel

    sorted_quotes = sorted(quotes, key=_exchange_priority)

    # Probier alle Kandidaten der Reihe nach: Step 3 (quoteType+name+liquidity) inline
    # Nimm den ersten der ALLE Checks besteht. Wenn keiner besteht: ersten yf-Treffer rejecten.
    rejection_details = None
    rejection_reason = None
    rejection_ticker = None

    for cand in sorted_quotes:
        ticker = cand.get("symbol")
        if not ticker:
            continue

        try:
            @retry(max_attempts=2, backoff=1.5, exceptions=(Exception,))
            def _get_info(): return yf.Ticker(ticker).info
            info = _get_info()
        except Exception as e:
            continue  # naechsten probieren

        yahoo_name  = info.get("longName") or info.get("shortName") or ""
        quote_type  = info.get("quoteType")
        volume      = info.get("averageVolume") or 0
        price       = info.get("regularMarketPrice") or info.get("previousClose") or 0

        base_details = {
            "yahoo_name": yahoo_name,
            "quote_type": quote_type,
            "sector":     info.get("sector"),
            "industry":   info.get("industry"),
            "country":    info.get("country"),
            "currency":   info.get("currency"),
            "volume":     volume,
            "price":      price,
        }

        # Check 1: quoteType
        if quote_type != "EQUITY":
            # Merken fuer den Fall dass kein Kandidat ueberlebt
            if rejection_reason is None:
                rejection_reason = "not_equity"
                rejection_ticker = ticker
                rejection_details = base_details
            continue

        # Check 2: name plausibility
        if not yahoo_name:
            continue
        sim = _name_similarity(name, yahoo_name)
        threshold = _name_threshold(name)
        if sim < threshold:
            if rejection_reason is None or rejection_reason == "not_equity":
                rejection_reason = "name_mismatch"
                rejection_ticker = ticker
                rejection_details = {**base_details, "similarity": sim, "threshold": threshold}
            continue

        # Check 3: Liquiditaet
        liquidity = (volume or 0) * (price or 0)
        if liquidity < MIN_LIQUIDITY:
            if rejection_reason is None or rejection_reason in ("not_equity", "name_mismatch"):
                rejection_reason = "low_liquidity"
                rejection_ticker = ticker
                rejection_details = {**base_details, "liquidity": liquidity}
            continue

        # Alle Checks bestanden!
        return {"status": "accepted", "ticker": ticker, "reason": None,
                "details": base_details}

    # Kein Kandidat hat alle Checks bestanden -> Reject mit dem besten Fehlergrund
    _log_reject(name, rejection_ticker, rejection_reason or "unknown",
                str(rejection_details or {})[:200])
    return {"status": "rejected",
            "ticker": rejection_ticker,
            "reason": rejection_reason or "unknown",
            "details": rejection_details or {}}

def validate_and_register(name: str) -> dict:
    """
    Validiert UND schreibt bei status='accepted' in companies + company_aliases.
    
    Reihenfolge:
    1. validate(name) aufrufen
    2. Wenn 'accepted': INSERT in DB (idempotent via INSERT OR IGNORE)
    3. Cache _TICKER_CACHE wird NICHT direkt aktualisiert - 
       neue Einträge sind erst beim nächsten Modul-Import sichtbar.
       (Akzeptabel weil der Cron-Lauf einmalig läuft.)
    """
    result = validate(name)
    
    if result["status"] != "accepted":
        return result  # rejected oder already_known: nichts zu tun

    ticker  = result["ticker"]
    details = result["details"]
    alias   = name.lower().strip()

    try:
        con = sqlite3.connect(DB_PATH)
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA busy_timeout=5000;")
        con.execute("PRAGMA foreign_keys = ON")
        cur = con.cursor()

        # 1. Insert in companies (idempotent: falls Ticker durch parallelen Lauf
        #    schon angelegt wurde, ignorieren)
        cur.execute("""
            INSERT OR IGNORE INTO companies
                (ticker, canonical_name, quote_type, sector, industry,
                 country, currency, isin, status, source, last_validated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'active', 'auto', datetime('now'))
        """, (
            ticker,
            details.get("yahoo_name") or ticker,
            details.get("quote_type"),
            details.get("sector"),
            details.get("industry"),
            details.get("country"),
            details.get("currency"),
        ))

        # 2. Insert Alias - auch den canonical_name als Alias hinzufuegen
        #    damit kuenftige Lookups direkt treffen
        for a in {alias, (details.get("yahoo_name") or "").lower().strip()}:
            if a:
                cur.execute("""
                    INSERT OR IGNORE INTO company_aliases (alias, ticker)
                    VALUES (?, ?)
                """, (a, ticker))

        con.commit()
        con.close()
    except Exception as e:
        # DB-Insert fehlgeschlagen - validate-Ergebnis ist trotzdem korrekt
        result["details"]["db_insert_error"] = str(e)[:100]

    return result

# --- Smoke test ---
if __name__ == "__main__":
    print("company_validator.py loaded.")
    print(f"DB exists: {Path(DB_PATH).is_file()}")
    print(f"Known 'apple': {_is_known('Apple')}")
    print(f"Known 'apple inc.': {_is_known('Apple Inc.')}")
    print(f"Known 'doesnotexist': {_is_known('doesnotexist')}")
    print(f"Name similarity('hp', 'HP Inc.'): {_name_similarity('hp', 'HP Inc.'):.3f}")
    print(f"Name similarity('intuit', 'Intuitive Surgical'): {_name_similarity('intuit', 'Intuitive Surgical'):.3f}")
    print(f"Threshold for 'HP' (len 2): {_name_threshold('HP')}")
    print(f"Threshold for 'Apple' (len 5): {_name_threshold('Apple')}")
    print(f"Threshold for 'Marathon Digital Holdings' (len 25): {_name_threshold('Marathon Digital Holdings')}")
