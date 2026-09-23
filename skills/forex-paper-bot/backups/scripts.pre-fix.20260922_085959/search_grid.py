"""
search_grid.py — Autonomer Grid-Search nach einer profitablen Trendfolge-Variante
mit vernünftiger Trade-Anzahl, inkl. Pyramiding (Nachkauf in Trendrichtung).

Ziel: Finde Parameter, die nach Spread-Kosten (netto) profitabel sind UND eine
sinnvolle Anzahl Trades über das Lookback erzeugen. Limit: max 50 Kombinationen.

Parameterraum:
  ema_fast:  [8, 20]
  ema_slow:  [21, 50]   (nur > fast)
  min_strength: [0.0002, 0.001, 0.003, 0.005]
  sl_atr_mult: [1.0, 1.5]
  trailing_atr_mult: [0.5, 1.0, 2.0]
  use_4h:  [False, True]
  pyramid: [False, True]   (Nachkauf alle N ATR in Gewinnrichtung)

Pyramiding-Logik: solange LONG in Gewinn, wenn Preis um pyramid_every_atr*ATR über
den letzten Einstieg steigt, eine weitere Einheit nachkaufen (bis pyramid_max Adds).
Jede Einheit wird separat mit Trailing/SL exitet (additiv, gleiche Richtung).
"""
import sys, os, json, itertools, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as cfg
from fetch import fetch_pair, fetch_trend_timeframe
import pandas as pd
import numpy as np


def ema_np(arr, span):
    alpha = 2.0 / (span + 1.0)
    arr = np.asarray(arr).ravel()
    out = np.empty_like(arr)
    out[0] = arr[0]
    for i in range(1, len(arr)):
        out[i] = alpha * arr[i] + (1 - alpha) * out[i - 1]
    return out


def atr_series(df, n=14):
    h = df["High"].astype(float); l = df["Low"].astype(float); c = df["Close"].astype(float)
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def bias_series(h_df, span):
    close = h_df["Close"].astype(float).to_numpy().ravel()
    e = ema_np(close, span)
    return np.where(close > e, 1, np.where(close < e, -1, 0)).astype(float)


def bias_to_15m(bias_arr, src_df, df15):
    src_times = pd.to_datetime(src_df.index)
    bias_s = pd.Series(np.asarray(bias_arr).ravel(), index=src_times)
    times15 = pd.to_datetime(df15.index)
    merged = bias_s.reindex(bias_s.index.union(times15)).ffill().bfill().reindex(times15)
    return merged.to_numpy(dtype=float)


def simulate(df, h1_b, b4h, fast, slow, mom_lb, min_strength, sl_mult, trail_mult,
             hold_cap_bars, use_4h, pyramid, pyr_every_atr=1.5, pyr_max=3):
    """Pyramiding-Trendfolge. Liefert Liste von Teil-Trades (jede Einheit einzeln gewertet).

    Jede 'Einheit' (Lot) wird einzeln mit Trailing laufen gelassen; beim Exit einer
    Einheit wird sie als eigener Trade verbucht. Position kann pyramiden: wenn der
    Preis um pyr_every_atr*ATR weiterläuft, eine zusätzliche Einheit zum aktuellen Preis
    öffnen (mit eigenem SL/Trailing), bis pyr_max zusätzliche Einheiten.
    """
    close = df["Close"].astype(float).to_numpy()
    high = df["High"].astype(float).to_numpy()
    low = df["Low"].astype(float).to_numpy()
    atr = atr_series(df, 14).to_numpy()
    fe = ema_np(close, fast); se = ema_np(close, slow)

    trades = []          # abgeschlossene Einheiten
    units = []           # offene Einheiten: [{dir, entry, sl, extreme, bars}]
    n = len(df)
    start = max(fast, slow) + mom_lb
    i = start
    while i < n:
        a = atr[i]
        # 1) Neue Erstposition (falls keine Einheiten offen)
        if len(units) == 0 and not (np.isnan(a)):
            cross_now = fe[i] > se[i]; cross_prev = fe[i - 1] > se[i - 1]
            prev = close[i - mom_lb] if i - mom_lb >= 0 else 0.0
            mom = (close[i] / prev - 1.0) if prev else 0.0
            h1 = h1_b[i] if i < len(h1_b) else 0.0
            do4 = (b4h[i] if (i < len(b4h)) else 0.0) if b4h is not None else h1
            long_ok = cross_now and not cross_prev and mom > min_strength and h1 == 1
            short_ok = (not cross_now) and cross_prev and mom < -min_strength and h1 == -1
            if use_4h:
                long_ok = long_ok and do4 == 1
                short_ok = short_ok and do4 == -1
            if long_ok:
                units.append({"dir": "LONG", "entry": close[i], "sl": close[i] - sl_mult * a,
                              "extreme": close[i], "bars": 0})
            elif short_ok:
                units.append({"dir": "SHORT", "entry": close[i], "sl": close[i] + sl_mult * a,
                              "extreme": close[i], "bars": 0})
        # 2) Pyramiding: Erstposition da, Preis läuft in Gewinnrichtung
        if len(units) > 0:
            if np.isnan(a): a = atr[i - 1] if i > 0 else 0.0
            dir0 = units[0]["dir"]
            last_entry = units[-1]["entry"]
            adds = sum(1 for u in units if u["bars"] > 0)  # Anzahl Nachkäufe
            if dir0 == "LONG" and adds < pyr_max and close[i] >= last_entry + pyr_every_atr * a:
                units.append({"dir": "LONG", "entry": close[i], "sl": close[i] - sl_mult * a,
                              "extreme": close[i], "bars": 0})
            elif dir0 == "SHORT" and adds < pyr_max and close[i] <= last_entry - pyr_every_atr * a:
                units.append({"dir": "SHORT", "entry": close[i], "sl": close[i] + sl_mult * a,
                              "extreme": close[i], "bars": 0})
            # 3) Trailing + Exit je Einheit
            exits = []
            for u in units:
                u["bars"] += 1
                hi, lo = high[i], low[i]
                if u["dir"] == "LONG":
                    u["extreme"] = max(u["extreme"], hi - trail_mult * a)
                    u["sl"] = max(u["sl"], u["extreme"])
                    if lo <= u["sl"] or u["bars"] >= hold_cap_bars:
                        exits.append({"entry": u["entry"], "exit": u["sl"], "dir": "LONG"})
                else:
                    u["extreme"] = min(u["extreme"], lo + trail_mult * a)
                    u["sl"] = min(u["sl"], u["extreme"])
                    if hi >= u["sl"] or u["bars"] >= hold_cap_bars:
                        exits.append({"entry": u["entry"], "exit": u["sl"], "dir": "SHORT"})
            for e in exits:
                trades.append(e)
                units.remove(next(u for u in units if u["entry"] == e["entry"]))
        i += 1
    # Rest am Daten-Ende glattstellen
    for u in units:
        trades.append({"entry": u["entry"], "exit": close[-1], "dir": u["dir"]})
    return trades


def _f(v):
    if hasattr(v, "item"):
        return float(v.item())
    return float(v)


def metrics(trades, pip_size, spread_pips):
    """Netto-Metriken über pips. returns dict."""
    if not trades:
        return {"trades": 0, "net": 0.0, "pf": 0.0, "wr": 0.0}
    pips = []
    for t in trades:
        p = (_f(t["exit"]) - _f(t["entry"])) / pip_size
        if t["dir"] == "SHORT":
            p = -p
        pips.append(p - 2.0 * spread_pips)  # netto
    wins = [p for p in pips if p > 0]
    losses = [p for p in pips if p <= 0]
    gw = sum(wins); gl = abs(sum(losses))
    pf = gw / gl if gl else (gw if gw else 0.0)
    return {"trades": len(trades), "net": round(sum(pips), 1),
            "pf": round(pf, 2), "wr": round(len(wins) / len(trades), 3)}


def build_grid():
    """Baut bis zu 50 Parameter-Kombinationen (dedupliziert, slow>fast)."""
    combos = []
    for fast, slow, ms, slm, trm, use4h, pyr in itertools.product(
            [8, 20], [21, 50], [0.0002, 0.001, 0.003, 0.005],
            [1.0, 1.5], [0.5, 1.0, 2.0], [False, True], [False, True]):
        if slow <= fast:
            continue
        combos.append(dict(fast=fast, slow=slow, min_strength=ms, sl_mult=slm,
                           trailing=trm, use_4h=use4h, pyramid=pyr))
    # deterministisch mischen und auf 50 deckeln
    random.seed(42)
    random.shuffle(combos)
    seen = set()
    dedup = []
    for c in combos:
        k = (c["fast"], c["slow"], c["min_strength"], c["sl_mult"], c["trailing"], c["use_4h"], c["pyramid"])
        if k in seen:
            continue
        seen.add(k)
        dedup.append(c)
    return dedup[:50]


def main():
    c = cfg.CONFIG
    wf = c["walk_forward"]
    lookback_days = wf["lookback_weeks"] * 7
    h1_ema = c["signal"]["h1_ema"]
    hold_cap_days = wf["holding_days_cap"]
    hold_cap_bars = hold_cap_days * 4 * 16
    mom_lb = 8

    grid = build_grid()
    pairs = list(c["pairs"].keys())
    print(f"=== GRID-SEARCH: {len(grid)} Kombis × {len(pairs)} Paare (netto nach Spread) ===")

    # Pro Paar: Daten + Bias vorladen
    pair_data = {}
    for pair in pairs:
        df15 = fetch_pair(pair, lookback_days, "15m")
        dfh1 = fetch_trend_timeframe(pair, lookback_days, "1h")
        if df15 is None or dfh1 is None or len(df15) < 200:
            print(f"  ❌ {pair}: keine Daten")
            continue
        b1h = bias_to_15m(bias_series(dfh1, h1_ema), dfh1, df15)
        dfh4 = fetch_trend_timeframe(pair, lookback_days, "4h")
        b4h = bias_to_15m(bias_series(dfh4, h1_ema), dfh4, df15) if dfh4 is not None and len(dfh4) > 5 else None
        pair_data[pair] = {"df": df15, "b1h": b1h, "b4h": b4h,
                           "pip": c["pairs"][pair]["pip_size"], "spread": c["pairs"][pair]["spread_pips"]}

    # Ergebnis je Kombi
    rows = []
    for idx, gp in enumerate(grid):
        total_net = 0.0
        total_trades = 0
        per_pair = {}
        for pair, pd_ in pair_data.items():
            trades = simulate(pd_["df"], pd_["b1h"], pd_["b4h"], gp["fast"], gp["slow"], mom_lb,
                              gp["min_strength"], gp["sl_mult"], gp["trailing"], hold_cap_bars,
                              gp["use_4h"], gp["pyramid"])
            m = metrics(trades, pd_["pip"], pd_["spread"])
            per_pair[pair] = m
            total_net += m["net"]
            total_trades += m["trades"]
        rows.append({"combo": gp, "net": round(total_net, 1), "trades": total_trades, "per_pair": per_pair})
        # Fortschritt
        if (idx + 1) % 10 == 0:
            print(f"  ... {idx+1}/{len(grid)} Kombis")

    # Sortieren: profitabel + mindestens 8 Trades bevorzugt, sonst netto absteigend.
    good = [r for r in rows if r["net"] > 0 and r["trades"] >= 8]
    rest = [r for r in rows if not (r["net"] > 0 and r["trades"] >= 8)]
    good.sort(key=lambda r: (-r["net"], -r["trades"]))
    rest.sort(key=lambda r: (-r["net"], -r["trades"]))
    ranking = good + rest

    print(f"\n=== TOP 12 (nach Profit & Trade-Anzahl gewichtet) ===")
    print(f"{'#':>3} {'net[pips]':>10}{'trades':>8}  Beschreibung")
    for i, r in enumerate(ranking[:12]):
        g = r["combo"]
        desc = (f"EMA{g['fast']}/{g['slow']} schwel={g['min_strength']} sl={g['sl_mult']} "
                f"trail={g['trailing']} 4h={g['use_4h']} pyr={g['pyramid']}")
        print(f"{i+1:>3} {r['net']:>10}{r['trades']:>8}  {desc}")

    # Komplettes Ranking als JSON ablegen
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "reports", "grid_search_result.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"ranking": ranking[:25]}, f, indent=2, ensure_ascii=False)
    print(f"\nDetail-Ranking gespeichert: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
