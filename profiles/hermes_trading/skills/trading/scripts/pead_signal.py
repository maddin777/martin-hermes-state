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
from datetime import datetime, timedelta

import yfinance as yf

log = logging.getLogger("pead_signal")

# Konfiguration
PEAD_BOOST_AMOUNT = 0.05       # Conviction-Boost bei Earnings-Surprise
PEAD_SIGNAL_WINDOW_DAYS = 4     # Nur innerhalb von 4 Tagen nach Filing
PEAD_EARNINGS_LIMIT = 4         # Letzte 4 Earnings-Events prüfen
PEAD_CACHE_TTL_HOURS = 6        # Cache nach 6 Stunden verfallen lassen


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

            diff = act - est
            if diff > 0:
                info = {
                    "surprise": "BEAT",
                    "filing_date": filing_date_str,
                    "eps_actual": act,
                    "eps_estimate": est,
                    "age_days": age_days,
                }
                return PEAD_BOOST_AMOUNT, 0.0, info
            elif diff < 0:
                info = {
                    "surprise": "MISS",
                    "filing_date": filing_date_str,
                    "eps_actual": act,
                    "eps_estimate": est,
                    "age_days": age_days,
                }
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