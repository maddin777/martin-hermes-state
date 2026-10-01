"""PEAD-Signal für die Trading-Pipeline.

Holt yfinance Earnings-Daten und berechnet einen Boost für den
Conviction-Score basierend auf dem Post-Earnings-Announcement Drift.

BEAT (EPS actual > Estimate) → +Boost für Long
MISS (EPS actual < Estimate) → +Boost für Short

Nutzt yfinance OHNE Paid-API. BEAT/MISS wird selbst berechnet.

Usage:
    from pead_signal import get_pead_boost
    boost_long, boost_short, info = get_pead_boost("AAPL")
    # boost_long = 0.05 bei BEAT, 0.0 sonst
    # boost_short = 0.05 bei MISS, 0.0 sonst
    # info = {"surprise": "BEAT", "filing_date": "2025-10-30", ...} oder None
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

import yfinance as yf

log = logging.getLogger("pead_signal")

# ── Konfiguration ────────────────────────────────────────────────────────────
#
# Kalibrierung 08.09.2026. Befund: nur 9 von 1.038 Cache-Eintraegen hatten
# ueberhaupt einen Boost != 0 (0.9 %). Das ist kein Fehler, sondern strukturell —
# aber zwei Parameter passten nicht zum Effekt, den sie abbilden sollen:
#
# 1. FENSTER. 4 Tage nach dem Filing erfassen die Ankuendigungs-Reaktion, nicht
#    den Drift. Post-Earnings-Announcement-Drift laeuft ueber Wochen NACH der
#    Meldung — ein 4-Tage-Fenster misst also gerade das, was der Effekt nicht ist.
#    Auf 10 Tage erweitert (Einstiegsfenster; die Haltedauer bestimmt der Exit).
#
# 2. SCHWELLE. `diff > 0` zaehlte jede noch so kleine Abweichung als BEAT — auch
#    +0.0001 EPS. Ein reiner Vorzeichentest auf verrauschten Schaetzungen ist
#    nahe an einem Muenzwurf. Jetzt ist eine relative Mindest-Ueberraschung
#    noetig; `surprise_pct` wird zusaetzlich mitgeschrieben, damit die Schwelle
#    spaeter aus Daten kalibriert werden kann statt geraten zu werden
#    (shadow_selection.py, Hypothese h2_pead).
#
# Beides per Environment uebersteuerbar, Rollback ohne Deploy.
def _env_float(name, default, lo, hi):
    try:
        v = float(os.environ.get(name, default))
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))


def _env_int(name, default, lo, hi):
    try:
        v = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))


PEAD_BOOST_AMOUNT = 0.05        # Conviction-Boost bei Earnings-Surprise
PEAD_SIGNAL_WINDOW_DAYS = _env_int("PEAD_WINDOW_DAYS", 10, 1, 60)
PEAD_MIN_SURPRISE_PCT   = _env_float("PEAD_MIN_SURPRISE_PCT", 0.02, 0.0, 1.0)
PEAD_EARNINGS_LIMIT = 4         # Letzte 4 Earnings-Events prüfen
PEAD_CACHE_TTL_HOURS = 6        # Cache nach 6 Stunden verfallen lassen


def _surprise_pct(actual: float, estimate: float):
    """Relative Ueberraschung. None, wenn die Schaetzung ~0 ist (nicht skalierbar)."""
    if estimate is None or abs(estimate) < 1e-9:
        return None
    return (actual - estimate) / abs(estimate)


def get_pead_boost(ticker: str) -> tuple[float, float, dict | None]:
    """Berechne PEAD-Boost für einen Ticker.

    Args:
        ticker: Ticker-Symbol (z.B. "AAPL")

    Returns:
        (boost_long, boost_short, info)
        - boost_long: +0.05 bei BEAT im Signal-Fenster, sonst 0.0
        - boost_short: +0.05 bei MISS im Signal-Fenster, sonst 0.0
        - info: Dict mit Details oder None wenn kein Signal
    """
    try:
        ticker_obj = yf.Ticker(ticker)
        earnings = ticker_obj.earnings_dates
        if earnings is None or earnings.empty:
            return 0.0, 0.0, None

        # Spalten automatisch finden
        col_estimate = None
        col_actual = None
        for col in earnings.columns:
            cl = col.lower()
            if 'estimate' in cl:
                col_estimate = col
            elif 'reported' in cl or 'actual' in cl:
                col_actual = col

        if not col_estimate or not col_actual:
            return 0.0, 0.0, None

        now = datetime.now()
        today = now.date()

        for idx, row in earnings.head(PEAD_EARNINGS_LIMIT).iterrows():
            # Filing-Datum aus dem Index
            filing_date = idx
            if hasattr(filing_date, 'strftime'):
                filing_dt = filing_date.to_pydatetime() if hasattr(filing_date, 'to_pydatetime') else filing_date
                filing_date_str = filing_dt.strftime("%Y-%m-%d")
                filing_date_dt = filing_dt.date() if hasattr(filing_dt, 'date') else filing_dt
            else:
                continue

            # Prüfen ob im Signal-Fenster (max 4 Tage alt)
            age_days = (today - filing_date_dt).days if hasattr(filing_date_dt, '__sub__') else 999
            if age_days < 0 or age_days > PEAD_SIGNAL_WINDOW_DAYS:
                continue

            # EPS-Werte holen
            eps_estimate = row.get(col_estimate)
            eps_actual = row.get(col_actual)

            if eps_estimate is None or eps_actual is None:
                continue

            try:
                est = float(eps_estimate)
                act = float(eps_actual)
            except (ValueError, TypeError):
                continue

            if not (isinstance(est, (int, float)) and isinstance(act, (int, float))):
                continue

            # Relative statt absoluter Ueberraschung: +0.01 EPS auf eine
            # Schaetzung von 0.05 ist etwas anderes als +0.01 auf 4.00.
            surp = _surprise_pct(act, est)
            if surp is None or abs(surp) < PEAD_MIN_SURPRISE_PCT:
                continue

            info = {
                "surprise": "BEAT" if surp > 0 else "MISS",
                "filing_date": filing_date_str,
                "eps_actual": act,
                "eps_estimate": est,
                "surprise_pct": round(surp, 4),
                "age_days": age_days,
                "window_days": PEAD_SIGNAL_WINDOW_DAYS,
                "min_surprise_pct": PEAD_MIN_SURPRISE_PCT,
            }
            if surp > 0:
                return PEAD_BOOST_AMOUNT, 0.0, info
            return 0.0, PEAD_BOOST_AMOUNT, info

        return 0.0, 0.0, None

    except Exception as e:
        log.warning("PEAD-Fehler für %s: %s", ticker, e)
        return 0.0, 0.0, None


def get_pead_boost_cached(ticker: str, con=None) -> tuple[float, float, dict | None]:
    """Gecachte Version von get_pead_boost().

    Vermeidet yfinance-Calls bei jedem Pipeline-Lauf durch Cache in der
    pead_cache-Tabelle. Cache verfällt nach PEAD_CACHE_TTL_HOURS.
    """
    # Falls kein DB-Connection: direkt holen
    if con is None:
        return get_pead_boost(ticker)

    try:
        # Prüfen ob gecachter Eintrag existiert und noch frisch ist
        cutoff = (datetime.now() - timedelta(hours=PEAD_CACHE_TTL_HOURS)).isoformat()
        row = con.execute(
            "SELECT boost_long, boost_short, info_json, fetched_at "
            "FROM pead_cache WHERE ticker=? AND fetched_at > ?",
            (ticker, cutoff)
        ).fetchone()

        if row:
            import json
            info = json.loads(row["info_json"]) if row["info_json"] else None
            return float(row["boost_long"]), float(row["boost_short"]), info

        # Neu berechnen
        boost_long, boost_short, info = get_pead_boost(ticker)

        # Wegschreiben
        import json
        con.execute(
            "INSERT OR REPLACE INTO pead_cache (ticker, boost_long, boost_short, info_json, fetched_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (ticker, boost_long, boost_short,
             json.dumps(info) if info else None,
             datetime.now().isoformat())
        )
        con.commit()

        return boost_long, boost_short, info

    except Exception as e:
        log.warning("PEAD-Cache-Fehler für %s: %s", ticker, e)
        return get_pead_boost(ticker)  # Fallback ohne Cache


def ensure_pead_cache_table(con):
    """Erstelle pead_cache-Tabelle + Migration."""
    con.execute("""
        CREATE TABLE IF NOT EXISTS pead_cache (
            ticker TEXT PRIMARY KEY,
            boost_long REAL DEFAULT 0,
            boost_short REAL DEFAULT 0,
            info_json TEXT,
            fetched_at TEXT NOT NULL
        )
    """)
    con.commit()


if __name__ == "__main__":
    # Test
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    boost_long, boost_short, info = get_pead_boost(ticker)
    print(f"PEAD {ticker}:")
    print(f"  Long-Boost:  +{boost_long:.2f}")
    print(f"  Short-Boost: +{boost_short:.2f}")
    if info:
        print(f"  Signal: {info['surprise']} am {info['filing_date']}")
        print(f"  EPS: {info['eps_actual']:.2f} vs {info['eps_estimate']:.2f} (Estimate)")
    else:
        print(f"  Kein aktuelles PEAD-Signal")