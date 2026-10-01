"""
Timing Validator — Bewertet technischen Status fuer Ein- und Ausstiege.
Setup-Zonen: RSI_Oversold, EMA50_Touch, Breakout_Retest, Consolidation.
"""
import os
import sqlite3
from datetime import date
import pandas as pd
import numpy as np

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data", "trading.db"
)


def _db_connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _fetch_data(ticker: str):
    """Holt 2 Jahre Kursdaten."""
    try:
        import yfinance as yf
        import pandas_ta as ta
        df = yf.download(ticker, period="2y", interval="1d",
                         progress=False, auto_adjust=True)
        if df.empty or len(df) < 60:
            return None
        close = df["Close"].iloc[:, 0]
        high = df["High"].iloc[:, 0]
        low = df["Low"].iloc[:, 0]
        volume = df["Volume"].iloc[:, 0]

        rsi = ta.rsi(close, length=14)
        ema50 = ta.ema(close, length=50)
        ema200 = ta.ema(close, length=200)

        return {
            "close": close, "high": high, "low": low,
            "volume": volume, "rsi": rsi,
            "ema50": ema50, "ema200": ema200,
        }
    except Exception:
        return None


def _check_setups(data: dict) -> list:
    """Checkt alle Setup-Zonen und gibt aktive Setups zurueck."""
    setups = []
    close = data["close"].iloc[-1]
    rsi = data["rsi"].iloc[-1] if not pd.isna(data["rsi"].iloc[-1]) else 50
    ema50 = data["ema50"].iloc[-1] if not pd.isna(data["ema50"].iloc[-1]) else close
    ema200 = data["ema200"].iloc[-1] if not pd.isna(data["ema200"].iloc[-1]) else close
    low_today = data["low"].iloc[-1]
    high_today = data["high"].iloc[-1]

    # RSI Oversold
    if rsi < 35 and ema50 > ema200:
        strength = (35 - rsi) / 35
        setups.append({
            "type": "RSI_OVERSOLD",
            "strength": round(min(strength, 1.0), 3),
            "distance_pct": 0.0,
            "notes": f"RSI={rsi:.1f}, EMA50>{'EMA200' if ema50 > ema200 else 'under'}",
        })

    # EMA50 Touch
    if ema50 > 0:
        distance_ema50 = abs(low_today - ema50) / ema50
        if distance_ema50 <= 0.02 and ema50 > ema200:
            strength = 1.0 - distance_ema50 / 0.02
            setups.append({
                "type": "EMA50_TOUCH",
                "strength": round(max(strength, 0.0), 3),
                "distance_pct": round(distance_ema50 * 100, 2),
                "notes": f"EMA50={ema50:.2f}",
            })

    # Consolidation (20-Tage-Range < 8%)
    if len(data["close"]) >= 20:
        range_20d = data["high"].iloc[-20:]
        range_low = data["low"].iloc[-20:]
        range_width = (range_20d.max() - range_low.min()) / data["close"].iloc[-20]
        if range_width < 0.08:
            vol_20d = data["volume"].iloc[-20:]
            vol_declining = vol_20d.mean() > vol_20d.iloc[-5:].mean()
            tightness = 1.0 - (range_width / 0.08)
            setups.append({
                "type": "CONSOLIDATION",
                "strength": round(tightness, 3),
                "distance_pct": round(range_width * 100, 2),
                "notes": f"Range={range_width:.1%}, VolDeclining={vol_declining}",
            })

    # Overbought Warning (Negativ-Setup)
    if rsi > 75:
        distance_ema = (close - ema50) / ema50 if ema50 > 0 else 0
        if rsi > 75 or distance_ema > 0.30:
            strength = -(rsi - 75) / 25
            setups.append({
                "type": "OVERBOUGHT_WARNING",
                "strength": round(strength, 3),
                "distance_pct": round(distance_ema * 100, 2),
                "notes": f"RSI={rsi:.1f}, +{distance_ema:.0%} vs EMA50",
            })

    return setups


def _determine_status(setups: list) -> str:
    """Ermittelt den Timing-Status aus aktiven Setups."""
    if not setups:
        return "NEUTRAL"
    positive = [s for s in setups if s["strength"] > 0]
    negative = [s for s in setups if s["strength"] < 0]
    if negative:
        return "OVERBOUGHT"
    if positive:
        return "READY"
    return "NEUTRAL"


def main():
    con = _db_connect()
    today = date.today().isoformat()

    # Alle Candidate/Watching-Beneficiaries
    candidates = con.execute("""
        SELECT DISTINCT ticker FROM theme_beneficiaries
        WHERE status IN ('candidate', 'watching', 'in_position')
    """).fetchall()

    if not candidates:
        print("[Timing Validator] Keine Beneficiaries.")
        con.close()
        return

    print(f"[Timing Validator] {len(candidates)} Ticker...", flush=True)

    ready_count = 0
    for row in candidates:
        ticker = row["ticker"]
        data = _fetch_data(ticker)
        if data is None:
            continue

        setups = _check_setups(data)
        for s in setups:
            con.execute("""
                INSERT OR REPLACE INTO setup_zones
                (date, ticker, setup_type, strength, distance_pct, notes)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                today, ticker,
                s["type"], s["strength"], s["distance_pct"], s["notes"],
            ))

        status = _determine_status(setups)
        if status == "READY":
            ready_count += 1

    con.commit()
    con.close()
    print(f"[Timing Validator] DONE: {ready_count} READY", flush=True)


if __name__ == "__main__":
    main()