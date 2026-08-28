#!/usr/bin/env python3
"""
backtest_variants.py — Exit- & Signal-Varianten auf den REALEN 81 gehandelten Positionen.

Nimmt die tatsächlich gehandelten (geschlossenen) Positionen aus trading.db und
simuliert, was alternative Exit- bzw. Signal-Logik statt des realen Exits erzielt hätte.

Varianten:
  C)  Exit-Asymmetrie: 1R Risiko / 3R Ziel + Zeit-Stopp (7 Handelstage)
     + Chandelier-Trailing vom Peak (ab +1R profit lock). Testet die
     Exit-Mathematik auf DENSELBEN Entries (kein Signal-Lookahead).
  B)  Crowd-Veto: Entries mit hoher Mention-Count (= Retail-Crowd) weglassen.
     Prüft ob "meide die Crowd" die Signalselektion verbessert.

Datenbasis: reale entry_price, stop_loss, shares, direction. 1R = geplantes
Risiko (|entry - stop_loss|). Kein Lookahead: ATR & R werden am Entry-Tag
berechnet, OHLC-Pfade danach simuliert.

Usage:
    cd /root/.hermes/profiles/hermes_trading/skills/trading
    PYTHONPATH=. /root/.pyenv/versions/3.12.13/bin/python3 scripts/backtest_variants.py
"""
from __future__ import annotations
import os, sys, json, sqlite3
from datetime import datetime, timedelta

TRADING_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(TRADING_ROOT, "data")
sys.path.insert(0, TRADING_ROOT)

import pandas as pd
import yfinance as yf

# Monkey-Patch yfinance date parsing (wie im Rest des Systems)
import _strptime as _st
from dateutil import parser as _dp
_orig = _st._strptime
def _safe(data_string, format="%a %b %d %H:%M:%S %Y"):
    try:
        return _orig(data_string, format)
    except ValueError as e:
        if "unconverted data remains" in str(e):
            try:
                p = _dp.parse(data_string); t = tuple(p.timetuple())
                return t + (p.tzname(), int(p.utcoffset().total_seconds()) if p.tzinfo else None), p.microsecond, 0
            except Exception:
                pass
        raise
_st._strptime = _safe

DB = os.path.join(DATA_DIR, "trading.db")
RR = 3.0            # Ziel-Multiple (1R:3R)
TIME_STOP_DAYS = 7  # Handelstage ohne Funken
CHANDELIER_MULT = 2.0  # ATR-Multiplikator fuer Chandelier vom Peak
CROWD_MENTIONS = 5  # >=5 Mentions = Retail-Crowd (Veto in Variante B)


def atr14(bars, lookback=14):
    """ATR(14) ueber die letzten `lookback` Bars (erwartet geordnete OHLC-liste)."""
    if len(bars) < lookback + 1:
        return None
    trs = []
    for i in range(1, lookback + 1):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i-1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / len(trs)


def fetch_ohlc(ticker, entry_date):
    """Hol OHLC von 45 Tage VOR entry bis 75 Tage NACH entry."""
    start = (datetime.strptime(entry_date[:10], "%Y-%m-%d") - timedelta(days=45)).strftime("%Y-%m-%d")
    end = (datetime.strptime(entry_date[:10], "%Y-%m-%d") + timedelta(days=75)).strftime("%Y-%m-%d")
    df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=False)
    if df is None or df.empty:
        return []
    if isinstance(df.columns, pd.MultiIndex):
        df = df.droplevel(1, axis=1)
    bars = []
    for idx, row in df.iterrows():
        bars.append({
            "time": idx.strftime("%Y-%m-%d"),
            "high": float(row["High"]), "low": float(row["Low"]),
            "close": float(row["Close"]),
        })
    return bars


def simulate_variant_c(pos, bars, rr=RR, time_stop=TIME_STOP_DAYS, chandelier=CHANDELIER_MULT):
    """Simuliere C-Exit auf einer Long/Short-Position. Returns (exit_price, reason, r_multi)."""
    entry, sl, direction = pos["entry_price"], pos["stop_loss"], pos["direction"]
    if entry is None or sl is None or entry <= 0 or sl <= 0:
        return None
    # Entry-Bar finden (erster Bar >= entry_date)
    entry_d = pos["entry_date"][:10]
    start_i = None
    for i, b in enumerate(bars):
        if b["time"] >= entry_d:
            start_i = i
            break
    if start_i is None:
        return None
    # ATR am Entry (Bars VOR entry)
    atr = atr14(bars[:start_i + 1], 14)
    if atr is None or atr <= 0:
        atr = abs(entry - sl)  # Fallback
    # 1R
    if direction == "LONG":
        r1 = entry - sl
        if r1 <= 0:
            return None
        target = entry + rr * r1
        peak = entry
        stop = sl
        # Trailing erst ab +1R Gewinn
        trailing_armed = False
    else:  # SHORT
        r1 = sl - entry
        if r1 <= 0:
            return None
        target = entry - rr * r1
        trough = entry
        stop = sl
        trailing_armed = False

    held = 0
    for b in bars[start_i:]:
        held += 1
        h, l, c = b["high"], b["low"], b["close"]
        if direction == "LONG":
            if h > peak:
                peak = h
            # profit lock: trailing aktiv wenn >=1R im Plus
            if not trailing_armed and (peak - entry) >= r1:
                trailing_armed = True
            if trailing_armed:
                trail_stop = peak - chandelier * atr
                stop = max(stop, trail_stop)  # ratchet
            # Exit-Check (konservativ: SL vor Target bei gleicher Bar)
            if l <= stop:
                exit_p = stop
                reason = "SL"
                r = (exit_p - entry) / r1
                return exit_p, reason, r
            if h >= target:
                exit_p = target
                reason = "TARGET"
                r = (target - entry) / r1
                return exit_p, reason, r
            if held >= time_stop:
                return c, "TIME", (c - entry) / r1
        else:  # SHORT
            if l < trough:
                trough = l
            if not trailing_armed and (entry - trough) >= r1:
                trailing_armed = True
            if trailing_armed:
                trail_stop = trough + chandelier * atr
                stop = min(stop, trail_stop)
            if h >= stop:
                exit_p = stop
                reason = "SL"
                r = (entry - exit_p) / r1
                return exit_p, reason, r
            if l <= target:
                exit_p = target
                reason = "TARGET"
                r = (entry - target) / r1
                return exit_p, reason, r
            if held >= time_stop:
                return c, "TIME", (entry - c) / r1
    # Ende der Daten ohne Exit -> zum letzten Close
    last = bars[-1]["close"]
    r = (last - entry) / r1 if direction == "LONG" else (entry - last) / r1
    return last, "EOF", r


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute("""
        SELECT p.ticker, p.direction, p.entry_date, p.entry_price, p.stop_loss,
               p.position_size, p.pnl_eur, p.pnl_pct, p.exit_reason,
               w.mention_count, ROUND(w.conviction_score_aged,2) AS aged
        FROM positions p LEFT JOIN watchlist w ON w.ticker = p.ticker
        WHERE p.exit_date IS NOT NULL AND p.pnl_eur IS NOT NULL
        ORDER BY p.entry_date
    """).fetchall()
    con.close()

    trades = []
    for r in rows:
        trades.append({
            "ticker": r["ticker"], "direction": r["direction"],
            "entry_date": r["entry_date"], "entry_price": r["entry_price"],
            "stop_loss": r["stop_loss"], "position_size": r["position_size"],
            "pnl_eur": r["pnl_eur"], "exit_reason": r["exit_reason"],
            "mention_count": r["mention_count"] or 0,
            "aged": r["aged"] or 0.0,
        })

    print(f"{len(trades)} Positionen geladen. Simuliere Variante C (1R/{RR:.0f}R, "
          f"TimeStop {TIME_STOP_DAYS}d, Chandelier {CHANDELIER_MULT:.1f}xATR)...", flush=True)

    results = []
    cache = {}
    for t in trades:
        bars = cache.get(t["ticker"])
        if bars is None:
            bars = fetch_ohlc(t["ticker"], t["entry_date"])
            cache[t["ticker"]] = bars
        res = simulate_variant_c(t, bars)
        shares = t["position_size"] / t["entry_price"] if t["entry_price"] else 0
        row = dict(t)
        if res:
            exit_p, reason, r = res
            row["c_exit_p"] = exit_p
            row["c_reason"] = reason
            row["c_r"] = r
            direction_sign = 1 if t["direction"] == "LONG" else -1
            row["c_pnl_eur"] = shares * direction_sign * (exit_p - t["entry_price"])
        else:
            row["c_exit_p"], row["c_reason"], row["c_r"], row["c_pnl_eur"] = None, "NO_DATA", None, None
        results.append(row)

    # ── Aggregation ──
    def agg(rows_sub, label):
        n = len(rows_sub)
        if n == 0:
            print(f"  {label}: 0 Trades"); return
        real = sum(x["pnl_eur"] for x in rows_sub if x["pnl_eur"] is not None)
        c_vals = [x["c_pnl_eur"] for x in rows_sub if x["c_pnl_eur"] is not None]
        c_pnl = sum(c_vals)
        c_rs = [x["c_r"] for x in rows_sub if x.get("c_r") is not None]
        c_wr = sum(1 for r in c_rs if r > 0) / len(c_rs) if c_rs else 0
        wins = sum(1 for r in c_rs if r > 0) if c_rs else 0
        losses = [r for r in c_rs if r <= 0]
        avg_win = sum(r for r in c_rs if r > 0) / wins if wins else 0
        avg_loss = sum(losses) / len(losses) if losses else 0
        payoff = (avg_win / abs(avg_loss)) if avg_loss else float('inf')
        ev_r = sum(c_rs) / len(c_rs) if c_rs else 0
        reasons = {}
        for x in rows_sub:
            rs = x.get("c_reason")
            reasons[rs] = reasons.get(rs, 0) + 1
        print(f"  {label}: n={n} | REAL PnL {real:>8.0f}€ | Variante-C PnL {c_pnl:>8.0f}€")
        print(f"      C: WR {c_wr:.0%} | avg_win {avg_win:.2f}R | avg_loss {avg_loss:.2f}R | "
              f"Payoff {payoff:.2f} | EV {ev_r:+.2f}R/trade | Exits {reasons}")

    print("\n===== VARIANTE C: Exit-Asymmetrie auf realen Entries =====")
    agg(results, "ALLE")

    # ── Variante B: Crowd-Veto (mention_count >= CROWD_MENTIONS) ──
    print("\n===== VARIANTE B: Crowd-Veto (mention_count >= %d) =====" % CROWD_MENTIONS)
    crowded = [x for x in results if x["mention_count"] >= CROWD_MENTIONS]
    quiet = [x for x in results if x["mention_count"] < CROWD_MENTIONS]
    print(f"  Crowded (>= {CROWD_MENTIONS} Mentions): n={len(crowded)}, "
          f"real PnL {sum(x['pnl_eur'] for x in crowded if x['pnl_eur'] is not None):.0f}€")
    print(f"  Quiet (< {CROWD_MENTIONS} Mentions):      n={len(quiet)}, "
          f"real PnL {sum(x['pnl_eur'] for x in quiet if x['pnl_eur'] is not None):.0f}€")
    print("  => Wenn du diese Entries im Live-Betrieb NICHT getradet haettest:")
    agg(quiet, "NUR quieter Entries (real)")

    # Note zu Punkt-in-Zeit
    print("\n  (Caveat: mention_count ist AKTUELL, nicht Point-in-Time am Entry — Naeherung)")

    with open(os.path.join(DATA_DIR, "backtest_variants_result.json"), "w") as f:
        json.dump({"results": results}, f, indent=1, default=str)
    print("\nDetail gespeichert: data/backtest_variants_result.json")


if __name__ == "__main__":
    main()
