"""
fetch.py — holt 15m-Candles für alle konfigurierten Forex-Paare via yfinance.

Nutzung:
  python3 fetch.py --test          # Test: prüft alle Paare, keine DB-Writer
  python3 fetch.py --pair EURUSD=X # einzelnes Paar, latest Close zurückgeben
  python3 fetch.py --cache-days N  # wie viele Tage 15m-Daten (Default 5)
"""
import argparse
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as cfg

import yfinance as yf
import pandas as pd


def _scalar(v):
    """Nimmt einen Wert aus pandas und liefert einen float-Skalar (Series→float)."""
    if hasattr(v, "item"):
        return float(v.item())
    return float(v)


def fetch_pair(pair, period_days=5, interval="15m"):
    """Liefert DataFrame mit 15m-Candles oder None."""
    period = f"{period_days}d"
    try:
        df = yf.download(pair, period=period, interval=interval,
                         progress=False, auto_adjust=False, threads=False)
    except Exception as e:
        print(f"  ❌ {pair}: Download-Fehler: {e}", flush=True)
        return None
    if df is None or df.empty:
        print(f"  ⚠️  {pair}: keine Daten", flush=True)
        return None
    # MultiIndex-Spalten flach machen (Close-Spalte als 1D)
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col in df.columns and hasattr(df[col], "columns"):
            if len(df[col].columns) == 1:
                df[col] = df[col].iloc[:, 0]
    df.index = pd.to_datetime(df.index)
    keep = [c for c in ["Open", "High", "Low", "Close"] if c in df.columns]
    df = df[keep].dropna()
    return df


def fetch_trend_timeframe(pair, period_days=30, interval="1h"):
    """Holt 1h-Candles für den H1-Trendfilter."""
    period = f"{period_days}d"
    try:
        df = yf.download(pair, period=period, interval=interval,
                         progress=False, auto_adjust=False, threads=False)
    except Exception as e:
        print(f"  ⚠️  {pair}: H1-Download-Fehler: {e}", flush=True)
        return None
    if df is None or df.empty:
        return None
    if hasattr(df["Close"], "columns") and len(df["Close"].columns) == 1:
        df["Close"] = df["Close"].iloc[:, 0]
    df.index = pd.to_datetime(df.index)
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="Prüft alle Paare")
    ap.add_argument("--pair", help="Nur dieses Paar (z.B. EURUSD=X)")
    ap.add_argument("--cache-days", type=int, default=5)
    args = ap.parse_args()

    c = cfg.CONFIG
    pairs = [args.pair] if args.pair else list(c["pairs"].keys())

    if args.test:
        print(f"=== Forex-Daten-Test ({datetime.now().strftime('%Y-%m-%d %H:%M')}) ===")
        ok = 0
        for p in pairs:
            df = fetch_pair(p, args.cache_days, c["timeframe"])
            if df is not None and len(df) >= 50:
                last = _scalar(df["Close"].iloc[-1])
                print(f"  ✅ {p:10} {len(df)} Zeilen | last Close {last:.5f}")
                ok += 1
            else:
                print(f"  ❌ {p:10} zu wenig Daten")
        print(f"\nErgebnis: {ok}/{len(pairs)} Paare OK")
        return 0 if ok == len(pairs) else 1

    # Einzelnes Paar: Latest Close ausgeben
    df = fetch_pair(pairs[0], args.cache_days, c["timeframe"])
    if df is None or len(df) == 0:
        print("NO_DATA", flush=True)
        return 1
    print(f"{df['Close'].iloc[-1]:.5f}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
