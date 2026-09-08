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
            "volume": float(row["Volume"]) if "Volume" in row else 0.0,
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


def volume_ratio_at_entry(pos, bars, avg_back=20):
    """Volume-Verhältnis am Entry-Tag: entry_vol / Ø(20 Tage VOR entry).

    Ratio >= 1.0 = erhöhtes Volumen am Entry (Breakout-Bestätigung).
    Returns float oder None wenn keine Daten.
    """
    entry_date = pos["entry_date"][:10]
    idx = None
    for i, b in enumerate(bars):
        if b["time"] >= entry_date:
            idx = i
            break
    if idx is None or idx < avg_back:
        return None
    vols = [b["volume"] for b in bars[idx - avg_back:idx]]
    ref = sum(vols) / len(vols) if vols else 0
    if ref <= 0:
        return None
    return bars[idx]["volume"] / ref


def simulate_variant_volume(pos, bars, boom_mult=1.5, avg_back=20):
    """VOLUME-Bestätigungs-Filter (Momentum-Swing-Post-Regel).

    Blockt den Trade wenn das Volumen am Entry-Tag unter boom_mult×Ø lag.
    Returns (blocked: bool, reason: str).
    """
    ratio = volume_ratio_at_entry(pos, bars, avg_back)
    if ratio is None:
        return False, "nodata"
    if ratio < boom_mult:
        return True, f"low-vol-entry (x{ratio:.2f} < {boom_mult:.1f})"
    return False, f"volume-ok (x{ratio:.2f})"


def get_atr_at(bars, idx, lookback=14):
    """ATR(14) bis einschliesslich bar[idx]."""
    sub = bars[max(0, idx - lookback):idx + 1]
    if len(sub) < lookback:
        return None
    trs = []
    for i in range(1, len(sub)):
        h, l, pc = sub[i]["high"], sub[i]["low"], sub[i-1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / len(trs) if trs else None


def simulate_variant_current(pos, bars, exit_cfg, regime="sideways"):
    """Simuliert den Exit nach der AKTUELLEN Exit-Matrix (get_exit_config).

    Modelliert get_exit_config()-Regeln auf dem realen OHLC-Pfad:
      - SL = entry ∓ sl×ATR(14)
      - TP = entry ± tp×ATR (full close erst wenn kein Partial-Verkauf vorher)
      - Partial-TP: bei +partial_atr×ATR wird partial_pct (0.50) verkauft,
        danach SL auf profit_lock_atr×ATR hochgezogen (profit-lock)
      - Chandelier-Trailing ab profit_lock: step×ATR vom Peak ratchet
      - holding_days_cap nicht simuliert (kein Datums-Cap hier, nur Preis)
    Returns (exit_price, reason, est_pnl_eur_frac) — Achtung: partial=komplex.
    Hier für den Volume-A/B-Vergleich: nutzen wir den REALEN entry/stop + ATR-Matrix,
    aber Output = ob der Trade mit dieser Exit-Regel + Volume-Filter profitabel war.
    """
    entry, direction = pos["entry_price"], pos["direction"]
    entry_date = pos["entry_date"][:10]
    if entry is None or entry <= 0:
        return None
    start_i = None
    for i, b in enumerate(bars):
        if b["time"] >= entry_date:
            start_i = i
            break
    if start_i is None:
        return None
    atr = get_atr_at(bars, start_i - 1) or get_atr_at(bars, start_i)
    if atr is None or atr <= 0:
        return None
    sl_mult = exit_cfg.get("sl", 1.5)
    tp_mult = exit_cfg.get("tp", 2.5)
    prof_lock = exit_cfg.get("profit_lock_atr", 1.0)
    step = exit_cfg.get("step", 0.75)
    if direction == "LONG":
        stop = entry - sl_mult * atr
        target = entry + tp_mult * atr
    else:
        stop = entry + sl_mult * atr
        target = entry - tp_mult * atr
    # 1R (fürs Reporting)
    r1 = abs(entry - (entry - sl_mult * atr if direction == "LONG" else entry + sl_mult * atr))
    if r1 <= 0:
        return None
    peak = entry
    trailing_armed = False
    held = 0
    for b in bars[start_i:]:
        held += 1
        h, l, c = b["high"], b["low"], b["close"]
        if direction == "LONG":
            peak = max(peak, h)
            if not trailing_armed and (peak - entry) >= prof_lock * atr:
                trailing_armed = True
            if trailing_armed:
                stop = max(stop, peak - step * atr)
            if l <= stop:
                return stop, "SL", (stop - entry) / r1
            if h >= target:
                return target, "TARGET", (target - entry) / r1
        else:  # SHORT
            peak = min(peak, l)
            if not trailing_armed and (entry - peak) >= prof_lock * atr:
                trailing_armed = True
            if trailing_armed:
                stop = min(stop, peak + step * atr)
            if h >= stop:
                return stop, "SL", (entry - stop) / r1
            if l <= target:
                return target, "TARGET", (entry - target) / r1
    last = bars[-1]["close"]
    r = (last - entry) / r1 if direction == "LONG" else (entry - last) / r1
    return last, "EOF", r


def simulate_variant_partial(pos, bars, exit_cfg, partial_pct=0.50, regime="sideways"):
    """Simuliert Exit MIT Partial-TP-Staffelung, wie die aktuelle Exit-Matrix.

    Modell (signal_manager get_exit_config + partial_tp_pct):
      1. LONG: bei High >= entry + partial_atr×ATR → 50% (partial_pct) zum
         Partial-Preis verkaufen. SL danach auf Breakeven/profit-lock anheben.
      2. Rest (1-partial_pct) läuft: SL = Chandelier (step×ATR vom Peak, ratchet),
         TP = entry + tp×ATR. Exit beim ersten Treffer.
      Gewichteter PnL: partial_pct*R_teil + (1-partial_pct)*R_rest.
    Returns (weighted_pnl_pct, reasons) oder None. weighted = % vom Entry.
    """
    entry, direction = pos["entry_price"], pos["direction"]
    entry_date = pos["entry_date"][:10]
    if entry is None or entry <= 0:
        return None
    start_i = None
    for i, b in enumerate(bars):
        if b["time"] >= entry_date:
            start_i = i
            break
    if start_i is None:
        return None
    atr = get_atr_at(bars, start_i - 1) or get_atr_at(bars, start_i)
    if atr is None or atr <= 0:
        return None
    sl_mult = exit_cfg.get("sl", 1.5)
    tp_mult = exit_cfg.get("tp", 2.5)
    partial_atr = exit_cfg.get("partial_atr", 1.5)
    profit_lock = exit_cfg.get("profit_lock_atr", 1.0)
    step = exit_cfg.get("step", 0.75)

    if direction == "LONG":
        init_sl = entry - sl_mult * atr
        target = entry + tp_mult * atr
        partial_price = entry + partial_atr * atr
        def sign(x): return x
    else:
        init_sl = entry + sl_mult * atr
        target = entry - tp_mult * atr
        partial_price = entry - partial_atr * atr
        def sign(x): return -x  # Gewinn wenn Preis fällt

    partial_done = False
    stop = init_sl
    peak = entry
    rest_ret = None   # Return der Rest-Position (als fraction des Entry, vorzeichenrichtig)
    held = 0
    for b in bars[start_i:]:
        held += 1
        h, l = b["high"], b["low"]
        if direction == "LONG":
            peak = max(peak, h)
            # Partial-Trigger
            if not partial_done and h >= partial_price:
                partial_done = True
                stop = max(stop, entry + profit_lock * atr)  # profit-lock
            if partial_done:
                stop = max(stop, peak - step * atr)  # chandelier ratchet
            # Exit
            if l <= stop:
                rest_ret = (stop - entry) / entry
                rest_reason = "SL_trail"
                break
            if not partial_done and h >= target:
                # kein Partial erreicht, direkt Target
                return sign(target - entry) / entry * 1.0, "FULL_TARGET"
        else:
            peak = min(peak, l)
            if not partial_done and l <= partial_price:
                partial_done = True
                stop = min(stop, entry - profit_lock * atr)
            if partial_done:
                stop = min(stop, peak + step * atr)
            if h >= stop:
                rest_ret = (entry - stop) / entry
                rest_reason = "SL_trail"
                break
            if not partial_done and l <= target:
                return (entry - target) / entry * 1.0, "FULL_TARGET"

    # Am Datenende ohne Exit -> Markt
    if rest_ret is None:
        last = bars[-1]["close"]
        rest_ret = (last - entry) / entry if direction == "LONG" else (entry - last) / entry
        rest_reason = "EOF"

    if partial_done:
        # 50% beim Partial-Preis (partial_price), 50% Rest
        partial_ret = (partial_price - entry) / entry if direction == "LONG" else (entry - partial_price) / entry
        weighted = partial_pct * partial_ret + (1 - partial_pct) * rest_ret
        return weighted, f"PARTIAL+{rest_reason}"
    # Kein Partial erreicht -> volle Position mit initial SL
    return rest_ret, f"NO_PARTIAL_{rest_reason}"


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute("""
        SELECT p.ticker, p.direction, p.entry_date, p.entry_price, p.stop_loss,
               p.position_size, p.pnl_eur, p.pnl_pct, p.exit_reason, p.asset_type,
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
            "asset_type": r["asset_type"] or "STANDARD",
            "mention_count": r["mention_count"] or 0,
            "aged": r["aged"] or 0.0,
        })

    print(f"{len(trades)} Positionen geladen. Simuliere Variante C (1R/{RR:.0f}R, "
          f"TimeStop {TIME_STOP_DAYS}d, Chandelier {CHANDELIER_MULT:.1f}xATR)...", flush=True)

    results = []
    cache = {}
    vol_blocked = {"count": 0, "real_pnl_avoided": 0.0, "good_blocks": 0, "bad_blocks": 0}
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

        # ── VOLUME-GATE: hätte der Filter diesen Trade geblockt? (Ratio speichern) ──
        ratio = volume_ratio_at_entry(t, bars) if bars else None
        row["vol_ratio"] = ratio
        row["volume_blocked"] = (ratio is not None and ratio < 1.5)
        row["volume_reason"] = f"x{ratio:.2f}" if ratio is not None else "nodata"
        row["bars"] = bars  # für aktuelle-Config-Simulation (Variante E)
        if row["volume_blocked"] and t["pnl_eur"] is not None:
            vol_blocked["count"] += 1
            vol_blocked["real_pnl_avoided"] += t["pnl_eur"]
            if t["pnl_eur"] < 0:
                vol_blocked["good_blocks"] += 1
            else:
                vol_blocked["bad_blocks"] += 1
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

    # ── Variante D: Volume-Bestätigung — Schwellen-Sweep + Score-Boost ──
    total_real_all = sum(x["pnl_eur"] for x in results if x["pnl_eur"] is not None)
    print("\n===== VARIANTE D: Volume-Bestätigung — Schwellen-Sweep =====")
    print(f"  (realer Gesamt-PnL aller {len(results)} Entries: {total_real_all:+.0f}€)")
    print(f"  {'Schwelle':>8} {'Behalten':>8} {'PnL':>9} {'geblockt':>8} {'verluste':>9} {'gewinne':>8}  {'Diff':>8}")
    for mult in [0.8, 1.0, 1.2, 1.5, 2.0]:
        keep = [x for x in results if x["vol_ratio"] is not None and x["vol_ratio"] >= mult]
        blocked = [x for x in results if x["vol_ratio"] is not None and x["vol_ratio"] < mult]
        pnl = sum(x["pnl_eur"] for x in keep if x["pnl_eur"] is not None)
        n_keep = len(keep)
        # verluste/gewinne unter den geblockten
        lost_avoid = sum(1 for x in blocked if (x["pnl_eur"] or 0) < 0)
        win_miss = sum(1 for x in blocked if (x["pnl_eur"] or 0) > 0)
        diff = pnl - total_real_all
        print(f"  {mult:>7.1f}x {n_keep:>8} {pnl:>+9.0f}€ {len(blocked):>8} {lost_avoid:>9} {win_miss:>8}  {diff:>+8.0f}€")

    # ── Variante D2: Score-Boost statt hartem Gate ──
    print("\n===== VARIANTE D2: Volume als Score-Boost (statt hartem Gate) =====")
    print("  (Score-Boost-Modell: volume-bestätigte Entries bekommen Bonus, werden NICHT geblockt)")
    print("  Idee: +Punkte für hohes Entry-Volumen → Rang oben, aber kein Ausschluss.")
    # Prüfe: sind die volume-bestätigten Entries die profitableren? (Korrelation ratio↔PnL)
    ratio_pnl = [(x["vol_ratio"] or 0, x["pnl_eur"] or 0) for x in results if x["vol_ratio"] is not None]
    if len(ratio_pnl) >= 10:
        high = [p for r, p in ratio_pnl if r >= 1.5]
        low = [p for r, p in ratio_pnl if r < 1.5]
        def stats(lst):
            if not lst: return (0, 0.0)
            wins = sum(1 for p in lst if p > 0)
            return (len(lst), (sum(lst) / len(lst)))
        hn, hav = stats(high); ln, lav = stats(low)
        print(f"  volume>=1.5x (n={hn}): Ø PnL {hav:+.0f}€/Trade")
        print(f"  volume<1.5x  (n={ln}): Ø PnL {lav:+.0f}€/Trade")
        print(f"  → Wenn hohes Volume Ø besser: Score-Boost (+Volumen im Score) würde "
              f"qualitativ bessere Entries nach oben rücken lassen.")
        # mittlerer PnL + Korrelation
        corr = sum((r - sum(r_ for r_, _ in ratio_pnl)/len(ratio_pnl)) * (p - sum(p_ for _, p_ in ratio_pnl)/len(ratio_pnl))
                   for r, p in ratio_pnl)
        var_r = sum((r - sum(r_ for r_, _ in ratio_pnl)/len(ratio_pnl))**2 for r, _ in ratio_pnl)
        var_p = sum((p - sum(p_ for _, p_ in ratio_pnl)/len(ratio_pnl))**2 for _, p in ratio_pnl)
        import math
        corr_c = corr / math.sqrt(var_r * var_p) if var_r and var_p else 0
        print(f"  Korrelation Volume-Ratio ↔ PnL: {corr_c:+.2f}")

    # ── Variante E: AKTUELLE Exit-Config (get_exit_config) mit vs. ohne Volume-Gate 1.2x ──
    print("\n===== VARIANTE E: Aktuelle get_exit_config-Exit-Matrix, mit vs. ohne Volume-Gate 1.2x =====")
    try:
        from config import get_exit_config, db_connect as _dbc
        _con = _dbc()
        try:
            regime = _con.execute("SELECT regime FROM regime_history ORDER BY date DESC LIMIT 1").fetchone()[0]
        except Exception:
            regime = "sideways"
        _con.close()
        print(f"  (Regime: {regime}; Exit-Matrix je Asset-Typ in diesem Regime)")
        for at in ["STANDARD", "TECH", "DEFENSIVE"]:
            ec = get_exit_config(asset_type=at, regime=regime)
            print(f"    {at:10}: sl={ec.get('sl')}×ATR tp={ec.get('tp')}×ATR profit_lock={ec.get('profit_lock_atr')} step={ec.get('step')}")

        def sim_pnl_pct(row):
            """Simuliert Trade mit aktueller Exit-Matrix, gibt pnl_pct (Gewinn/Entry) zurück."""
            bars = row.get("bars")
            if not bars:
                return None
            at = row.get("asset_type") or "STANDARD"
            ec = get_exit_config(asset_type=at, regime=regime)
            res = simulate_variant_current(row, bars, ec, regime)
            if not res:
                return None
            exit_p, reason, r = res
            direction_sign = 1 if row["direction"] == "LONG" else -1
            return direction_sign * (exit_p - row["entry_price"]) / row["entry_price"]

        # Alle Trades simulieren (aktuelle Matrix)
        sims = []
        for row in results:
            pp = sim_pnl_pct(row)
            sims.append({"row": row, "pp": pp})

        def report(subset, label):
            pps = [s["pp"] for s in subset if s["pp"] is not None]
            n_sim = len(pps)
            if n_sim == 0:
                print(f"  {label}: 0 simulierbar"); return
            avg = sum(pps) / n_sim
            wins = sum(1 for p in pps if p > 0)
            print(f"  {label}: n={n_sim} sim | Ø {avg*100:+.2f}% | WR {wins/n_sim:.0%} | "
                  f"Summe-äquiv {sum(pps)/n_sim*100:+.2f}%")

        report(sims, "ALLE (aktuelle Matrix)")
        # Mit Volume-Gate 1.2x: nur Trades mit vol_ratio >= 1.2
        gated = [s for s in sims if s["row"].get("vol_ratio") is not None and s["row"]["vol_ratio"] >= 1.2]
        report(gated, "Volume-Gate 1.2x (nur bestätigt)")
        # Kontrafaktisch: was wäre ohne gate
        nogate_loss = [s for s in sims if s["row"].get("vol_ratio") is not None and s["row"]["vol_ratio"] < 1.2]
        report(nogate_loss, "Ohne Gate weggefallen (<1.2x)")
        print("  → Vergleich: Ist Ø der 1.2x-bestätigten > Ø aller? Dann hilft das Gate auch unter aktueller Config.")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"  (Variante E Fehler: {e})")

    # ── Variante F: AKTUELLE Config MIT Partial-TP-Staffelung (realistischer) ──
    print("\n===== VARIANTE F: Aktuelle Config MIT Partial-TP (50%@partial_atr + Trail) =====")
    try:
        from config import get_exit_config
        _con = _dbc()
        try:
            regime = _con.execute("SELECT regime FROM regime_history ORDER BY date DESC LIMIT 1").fetchone()[0]
        except Exception:
            regime = "sideways"
        _con.close()
        PARTIAL_PCT = 0.50
        print(f"  (Regime: {regime}; Partial 50% @ partial_atr×ATR, Rest chandelier-trail)")

        def sim_partial(row):
            bars = row.get("bars")
            if not bars:
                return None
            at = row.get("asset_type") or "STANDARD"
            ec = get_exit_config(asset_type=at, regime=regime)
            return simulate_variant_partial(row, bars, ec, PARTIAL_PCT, regime)

        psims = []
        for row in results:
            pp = sim_partial(row)
            psims.append({"row": row, "pp": pp, "reason": pp[1] if pp else "nodata"})

        def report_p(subset, label):
            pps = [s["pp"][0] for s in subset if s["pp"] is not None]
            if not pps:
                print(f"  {label}: 0 simulierbar"); return
            avg = sum(pps) / len(pps)
            wins = sum(1 for p in pps if p > 0)
            print(f"  {label}: n={len(pps)} | Ø {avg*100:+.3f}% | WR {wins/len(pps):.0%}")
            return avg

        a_all = report_p(psims, "ALLE (Partial-TP-Modell)")
        gated_p = [s for s in psims if s["row"].get("vol_ratio") is not None and s["row"]["vol_ratio"] >= 1.2]
        a_gate = report_p(gated_p, "Volume-Gate 1.2x (nur bestätigt)")
        nogate_p = [s for s in psims if s["row"].get("vol_ratio") is not None and s["row"]["vol_ratio"] < 1.2]
        report_p(nogate_p, "Ohne Gate weggefallen (<1.2x)")
        if a_all is not None and a_gate is not None:
            print(f"  → Partial-Modell: Gate verbessert Ø um {(a_gate-a_all)*100:+.3f} pp "
                  f"({a_all*100:+.2f}% → {a_gate*100:+.2f}%)")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"  (Variante F Fehler: {e})")

    with open(os.path.join(DATA_DIR, "backtest_variants_result.json"), "w") as f:
        json.dump({"results": results}, f, indent=1, default=str)
    print("\nDetail gespeichert: data/backtest_variants_result.json")


if __name__ == "__main__":
    main()
