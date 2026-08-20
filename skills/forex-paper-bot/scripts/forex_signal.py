"""
signal.py — Trendfolge-Signal auf 15m-Candles mit H1-Trendfilter.

Nutzung:
  python3 signal.py EURUSD=X          # Signal für ein Paar
  python3 signal.py --all             # Signal für alle Paare
  python3 signal.py --params '<json>' # mit angepassten Signale-Parametern (WF)

Signal-Logik (Trendfolge):
  1. H1-Trend (EMA-H1 über H1-EMA) als Gate: erlaubt nur LONG wenn H1 bullish,
     nur SHORT wenn H1 bearish. Bei neutral/ungerichtet → NEUTRAL.
  2. 15m-Trend: EMA_fast vs EMA_slow Kreuz + Momentum-Lookback-Schwelle.
  3. Nur wenn 15m-Trend zur H1-Richtung passt UND Momentum stark genug → Signal.
"""
import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as cfg
from fetch import fetch_pair, fetch_trend_timeframe, _scalar

import pandas as pd


def ema(series, span):
    return series.ewm(span=span, adjust=False).mean()


def h1_direction(pair, trend_cfg, cache_days=30):
    """Liefert 'bullish'|'bearish'|'neutral' für H1-Trendfilter."""
    df = fetch_trend_timeframe(pair, cache_days, "1h")
    if df is None or len(df) < trend_cfg["h1_ema"] + 5:
        return "neutral"
    close = df["Close"].astype(float)
    e = ema(close, trend_cfg["h1_ema"])
    if _scalar(close.iloc[-1]) > _scalar(e.iloc[-1]):
        return "bullish"
    if _scalar(close.iloc[-1]) < _scalar(e.iloc[-1]):
        return "bearish"
    return "neutral"


def signal_for_pair(pair, sig_cfg, trend_cfg, pair_cfg):
    """Berechnet das Signal für ein Paar. Liefert dict."""
    df15 = fetch_pair(pair, 5, "15m")
    if df15 is None or len(df15) < sig_cfg["ema_slow"] + sig_cfg["momentum_lookback"] + 5:
        return {"pair": pair, "signal": "NEUTRAL", "reason": "zu wenig Daten", "h1": "unknown"}

    close = df15["Close"].astype(float)
    fast = ema(close, sig_cfg["ema_fast"])
    slow = ema(close, sig_cfg["ema_slow"])

    # Momentum: % Veränderung über momentum_lookback Candles
    lb = sig_cfg["momentum_lookback"]
    prev = _scalar(close.iloc[-1 - lb]) if len(close) > lb else 0.0
    cur = _scalar(close.iloc[-1])
    mom = (cur / prev - 1.0) if prev else 0.0
    min_strength = sig_cfg.get("min_trend_strength", 0.0002)

    # 15m-Trend aus EMA-Kreuz (aktueller + vorheriger Wert)
    cross_now = _scalar(fast.iloc[-1]) > _scalar(slow.iloc[-1])
    cross_prev = _scalar(fast.iloc[-2]) > _scalar(slow.iloc[-2])

    h1 = h1_direction(pair, trend_cfg)

    # Signal = 15m-Trend muss zur H1-Gate-Richtung passen UND Momentum stark genug
    if h1 == "bullish" and cross_now and mom > min_strength:
        return {"pair": pair, "signal": "LONG", "reason": f"H1 bullish + 15m EMA-Kreuz up, mom {mom:.5f}", "h1": h1}
    if h1 == "bearish" and not cross_now and mom < -min_strength:
        return {"pair": pair, "signal": "SHORT", "reason": f"H1 bearish + 15m EMA-Kreuz down, mom {mom:.5f}", "h1": h1}
    # Kreuz-Übergang als Signal (auch ohne super-starkes Momentum, aber mit H1-Gate)
    if h1 == "bullish" and cross_now and not cross_prev:
        return {"pair": pair, "signal": "LONG", "reason": "frischer 15m EMA-Kreuz up, H1 bullish", "h1": h1}
    if h1 == "bearish" and not cross_now and cross_prev:
        return {"pair": pair, "signal": "SHORT", "reason": "frischer 15m EMA-Kreuz down, H1 bearish", "h1": h1}

    return {"pair": pair, "signal": "NEUTRAL", "reason": "kein Treffer", "h1": h1}


def in_session(now=None, cfg_session=None):
    """Prüft ob jetzt innerhalb der London/NY-Session (Mo-Fr)."""
    now = now or datetime.now()
    if now.weekday() >= 5:  # Sa/So
        return False
    hour = now.hour
    start = cfg_session["session_start_hour"]
    end = cfg_session["session_end_hour"]
    return start <= hour < end


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pair", nargs="?", help="Paar (z.B. EURUSD=X). Ohne: --all")
    ap.add_argument("--all", action="store_true", help="Alle Paare")
    ap.add_argument("--params", help="Signal-Parameter als JSON (WF-Override)")
    ap.add_argument("--session-check", action="store_true", help="Nur Session-Status")
    args = ap.parse_args()

    c = cfg.CONFIG
    sig_cfg = dict(c["signal"])
    if args.params:
        sig_cfg.update(json.loads(args.params))

    if args.session_check:
        print("IN_SESSION" if in_session(cfg_session=c.get("session", c)) else "OUT_SESSION")
        return 0

    session = c.get("session", c)
    print(f"=== Signal ({datetime.now().strftime('%Y-%m-%d %H:%M')}) ===")
    print(f"Session: {'✅ in London/NY' if in_session(cfg_session=session) else '⏸ außerhalb Session'}")

    pairs = [args.pair] if args.pair else (list(c["pairs"].keys()) if args.all else [])
    if not pairs:
        pairs = list(c["pairs"].keys())

    out = []
    for p in pairs:
        res = signal_for_pair(p, sig_cfg, c.get("signal", {}), c["pairs"].get(p, {}))
        out.append(res)
        print(f"  {res['pair']:10} → {res['signal']:6} (H1 {res['h1']:7}) {res['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
