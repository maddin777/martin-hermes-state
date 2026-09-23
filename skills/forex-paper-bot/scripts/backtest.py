"""
backtest.py — Walk-Forward-Optimierung für den Forex-Paper-Bot.

Nutzung:
  python3 backtest.py --dry-run          # sucht robusten Satz, schreibt KEINE Param-Snapshots
  python3 backtest.py --pair EURUSD=X    # Robustheits-Suche nur auf diesem einen Paar (Debug)

Walk-Forward-Logik (22.09.2026 auf EINEN robusten Parametersatz umgestellt, siehe unten):
  - Lookback: letzte N Wochen (config: walk_forward.lookback_weeks)
  - Grid-Search über ema_fast/ema_slow/momentum_lookback/sl_atr_mult/tp_atr_mult
  - Simulation folgt der LIVE-Signal-Logik aus forex_signal.py: Trendfilter-Gate
    (config trend_timeframe, z.B. Weekly-EMA) + Timeline-EMA-Kreuz + Momentum,
    SL/TP aus echtem ATR(14), Holding-Days-Cap.
  - **EIN Parametersatz für ALLE Paare** statt pro Paar einzeln optimiert:
    Kriterium 1 (hart): netto Pips (nach Spread auf Entry+Exit) positiv in JEDEM Paar.
    Kriterium 2 (Tiebreak unter den robusten): höchste Summe Netto-Pips über alle Paare.
    Findet sich kein Kandidat, der in ALLEN Paaren positiv ist, fällt der Rang auf
    "meiste positive Paare, dann höchste Summe" zurück — klar als NICHT robust markiert.
  - Der gewinnende Satz wird für jedes Paar als eigener Snapshot gespeichert (gleicher
    params_json-Wert je Paar), damit trade.py's Pro-Paar-Ladelogik unverändert bleibt.

2026-09-22 (zwei Fixes am selben Tag):

1) Timeframe-Fix: lief zuvor hardcodiert auf interval="15m" — yfinance liefert 15m-Daten
   nur 60 Tage zurück, das konfigurierte Lookback (140 Wochen = 980 Tage, fürs 1D-Setup
   gedacht) lieferte seit dem Umstieg auf 1D (29.08.) für JEDES Paar "keine Daten",
   meldete aber trotzdem "✅ Walk-Forward abgeschlossen" (Exit 0). Jetzt: nutzt
   cfg.timeframe, simuliert das tatsächliche Gate, bricht mit Exit-Code 1 ab statt ✅ zu
   melden, wenn für kein einziges Paar ein Ergebnis zustande kommt.

2) Robust-statt-pro-Paar-Fix: der erste Lauf nach Fix 1 optimierte noch PRO PAAR
   einzeln (breites Grid je Paar) — fand für GBP/USD einen Satz mit PF=0.967
   (netto-negativ im eigenen Backtest), der trotzdem live gehandelt worden wäre.
   Das widerspricht der eigentlich validierten Methodik (SKILL.md "ZENTRALE
   ERKENNTNIS" 28.08. / search_grid_robust.py): EIN robuster Satz für alle Paare
   vermeidet genau dieses Overfitting UND das Konzentrationsrisiko (ein dominantes
   Paar verzerrt die Optimierung). trade.py hat zusätzlich seit diesem Tag einen
   Qualitäts-Floor (walk_forward.min_snapshot_score) als zweites Sicherheitsnetz.
"""
import argparse
import itertools
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as cfg
from fetch import fetch_pair, fetch_trend_timeframe

import pandas as pd
import numpy as np


# Grid der zu optimierenden Parameter (5 Dimensionen wie dokumentiert, 108 Kombis).
# Wertebereiche um die validierte 1D-Konfiguration (EMA 13/150) herum statt um die
# alte 15m-Konfiguration (EMA 10-30/30-80).
FAST_GRID = [8, 13, 20]
SLOW_GRID = [50, 100, 150]
MOM_GRID = [3, 5, 8]
SL_GRID = [1.0, 1.5]
TP_GRID = [2.5, 3.5]

MIN_TOTAL_TRADES = 10  # Mindestanzahl Trades (Summe über alle Paare), sonst zu wenig Konfidenz


def _sharpe(rets):
    rets = np.array(rets, dtype=float)
    if len(rets) == 0 or rets.std() == 0:
        return 0.0
    return float(rets.mean() / rets.std() * np.sqrt(252 * 4))


def atr_series(df, n=14):
    """Vektorisierte ATR-Berechnung. Liefert pd.Series."""
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    close = df["Close"].astype(float)
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def ema_np(arr, span):
    """EWMA als numpy-Array."""
    alpha = 2.0 / (span + 1.0)
    arr = np.asarray(arr, dtype=float).ravel()
    out = np.empty_like(arr)
    out[0] = arr[0]
    for i in range(1, len(arr)):
        out[i] = alpha * arr[i] + (1 - alpha) * out[i - 1]
    return out


def trend_bias_series(pair, target_index, trend_cfg):
    """Bias +1 (bullish) / -1 (bearish) / 0 (neutral) je Ziel-Timeframe-Kerze, aus dem
    konfigurierten Trendfilter (config trend_timeframe, z.B. 1wk) — Zeitreihen-Analogon zu
    forex_signal.h1_direction() für den Backtest. Jedem Ziel-Zeitpunkt wird der letzte
    ABGESCHLOSSENE Trendfilter-Wert bis zu diesem Zeitpunkt zugeordnet (kein Lookahead)."""
    tf = cfg.CONFIG.get("trend_timeframe", "1h")
    lookback = 500 if tf in ("1wk", "1w") else 30
    df = fetch_trend_timeframe(pair, lookback, tf)
    n = len(target_index)
    if df is None or len(df) < trend_cfg.get("h1_ema", 20) + 5:
        return np.zeros(n)
    close = df["Close"].astype(float).to_numpy().ravel()
    e = ema_np(close, trend_cfg.get("h1_ema", 20))
    bias = np.where(close > e, 1, np.where(close < e, -1, 0))
    src_index = pd.to_datetime(df.index)
    times = pd.to_datetime(target_index)
    out = np.zeros(n)
    j = 0
    for i, t in enumerate(times):
        while j + 1 < len(src_index) and src_index[j + 1] <= t:
            j += 1
        out[i] = bias[j] if src_index[j] <= t else 0
    return out


def simulate(df, bias, fast, slow, mom_lb, min_strength, sl_mult, tp_mult, hold_cap_days,
             trailing_mult=0.0):
    """Simuliert die LIVE-Signal-Logik (forex_signal.signal_for_pair + trade.py) auf df:
    Trend-Gate (bias) + EMA-Kreuz + Momentum-Schwelle ODER frischer Kreuz-Übergang,
    SL/TP aus echtem ATR, optionaler Holding-Days-Cap, UND täglich nachgezogenes
    Trailing-Stop (wie trade.py._update_trailing: nur in Gewinnrichtung, nie zurück) —
    fixer TP-Zielwert bleibt bei Entry stehen, nur der SL wandert. trailing_mult kommt
    NICHT aus dem Grid (in trade.py global aus config.sl_tp, nicht Teil des Snapshots).
    Ein Trade zur Zeit (wie trade.py: kein offener Trade auf demselben Paar, solange
    einer läuft)."""
    close = df["Close"].astype(float).to_numpy()
    high = df["High"].astype(float).to_numpy()
    low = df["Low"].astype(float).to_numpy()
    atr = atr_series(df, 14).to_numpy()
    fe = ema_np(close, fast)
    se = ema_np(close, slow)
    idx = df.index

    trades = []
    pos = None
    n = len(df)
    start = max(fast, slow) + mom_lb
    for i in range(start, n):
        if pos is None:
            cross_now = fe[i] > se[i]
            cross_prev = fe[i - 1] > se[i - 1]
            prev = close[i - mom_lb] if i - mom_lb >= 0 else 0.0
            mom = (close[i] / prev - 1.0) if prev else 0.0
            a = atr[i] if not np.isnan(atr[i]) else 0.0
            if a <= 0:
                continue
            b = bias[i]
            long_ok = b > 0 and cross_now and (mom > min_strength or not cross_prev)
            short_ok = b < 0 and not cross_now and (mom < -min_strength or cross_prev)
            if long_ok:
                pos = {"dir": "LONG", "entry": close[i], "entry_i": i,
                       "sl": close[i] - sl_mult * a, "tp": close[i] + tp_mult * a}
            elif short_ok:
                pos = {"dir": "SHORT", "entry": close[i], "entry_i": i,
                       "sl": close[i] + sl_mult * a, "tp": close[i] - tp_mult * a}
        else:
            hi, lo = high[i], low[i]
            held_days = (idx[i] - idx[pos["entry_i"]]).days if hold_cap_days else 0
            exited = False
            if pos["dir"] == "LONG":
                if lo <= pos["sl"]:
                    trades.append({"entry": pos["entry"], "exit": pos["sl"], "dir": "LONG", "reason": "SL"})
                    exited = True
                elif hi >= pos["tp"]:
                    trades.append({"entry": pos["entry"], "exit": pos["tp"], "dir": "LONG", "reason": "TP"})
                    exited = True
                elif hold_cap_days and held_days >= hold_cap_days:
                    trades.append({"entry": pos["entry"], "exit": close[i], "dir": "LONG", "reason": "CAP"})
                    exited = True
            else:
                if hi >= pos["sl"]:
                    trades.append({"entry": pos["entry"], "exit": pos["sl"], "dir": "SHORT", "reason": "SL"})
                    exited = True
                elif lo <= pos["tp"]:
                    trades.append({"entry": pos["entry"], "exit": pos["tp"], "dir": "SHORT", "reason": "TP"})
                    exited = True
                elif hold_cap_days and held_days >= hold_cap_days:
                    trades.append({"entry": pos["entry"], "exit": close[i], "dir": "SHORT", "reason": "CAP"})
                    exited = True
            if exited:
                pos = None
            elif trailing_mult:
                a = atr[i] if not np.isnan(atr[i]) else 0.0
                if a > 0:
                    dist = trailing_mult * a
                    if pos["dir"] == "LONG":
                        new_trail = close[i] - dist
                        if new_trail > pos["sl"]:
                            pos["sl"] = new_trail
                    else:
                        new_trail = close[i] + dist
                        if new_trail < pos["sl"]:
                            pos["sl"] = new_trail
    return trades


def _npf(v):
    """Robust zu Python-float: numpy-Skalare → float."""
    if hasattr(v, "item"):
        return float(v.item())
    return float(v)


def score_trades(trades):
    """Bewertung EINES Paares: kombinierter Score aus Profit-Faktor + Win-Rate + Sharpe
    (skalen-unabhängig — PF/WR/Sharpe sind Verhältnisse, daher für den je-Paar-Score
    im params_snapshot geeignet, unabhängig von der Preis-Größenordnung des Paares)."""
    if not trades:
        return 0.0, {"trades": 0, "pf": 0.0, "wr": 0.0, "sharpe": 0.0, "net": 0.0}
    wins = [abs(_npf(t["exit"]) - _npf(t["entry"])) for t in trades if
            (t["dir"] == "LONG" and t["exit"] > t["entry"]) or (t["dir"] == "SHORT" and t["exit"] < t["entry"])]
    losses = [abs(_npf(t["exit"]) - _npf(t["entry"])) for t in trades if
              (t["dir"] == "LONG" and t["exit"] <= t["entry"]) or (t["dir"] == "SHORT" and t["exit"] >= t["entry"])]
    gross_win = sum(wins)
    gross_loss = sum(losses)
    pf = gross_win / gross_loss if gross_loss > 0 else (gross_win if gross_win > 0 else 0.0)
    wr = len(wins) / len(trades)
    rets = [(_npf(t["exit"]) - _npf(t["entry"])) * (1 if t["dir"] == "LONG" else -1) for t in trades]
    sharpe = _sharpe(rets)
    net = sum(rets)
    # Score: PF dominiert, bestraft zu wenig Trades
    score = _npf(pf) * 0.5 + wr * 0.2 + max(0.0, sharpe) * 0.3
    if len(trades) < 5:
        score *= 0.5  # zu wenige Trades = geringe Konfidenz
    return score, {"trades": len(trades), "pf": round(_npf(pf), 3), "wr": round(wr, 3),
                   "sharpe": round(sharpe, 2), "net": round(net, 5)}


def net_pips(trades, pip_size, spread_pips):
    """Netto-Pips nach Spread (Entry+Exit), PIP-normalisiert. Wird NUR für das
    Robustheits-Ranking über mehrere Paare hinweg gebraucht: rohe Preisdeltas sind
    zwischen Paaren nicht vergleichbar (USD/JPY ~157 vs. EUR/USD ~1.15) — ohne
    Pip-Normalisierung würde ein einzelnes Paar die Summe dominieren (das war exakt
    der Fehler im allerersten Grid-Run vom 28.08., siehe SKILL.md PITFALL)."""
    if not trades:
        return 0.0
    pips = []
    for t in trades:
        p = (_npf(t["exit"]) - _npf(t["entry"])) / pip_size
        if t["dir"] == "SHORT":
            p = -p
        pips.append(p - 2.0 * spread_pips)
    return sum(pips)


def find_robust_params(pairs, lookback_days, trend_cfg, hold_cap_days, min_strength, trailing_mult=0.0):
    """Sucht EINEN Parametersatz, der über ALLE (verfügbaren) Paare robust ist.

    Liefert (ranking, pair_data) — ranking ist nach Robustheit + Netto-Pips sortiert
    (robuste Kandidaten zuerst), pair_data die geladenen Kurse/Bias je Paar (für die
    Snapshot-Erzeugung im Anschluss)."""
    c = cfg.CONFIG
    tf = c.get("timeframe", "15m")
    pair_data = {}
    for pair in pairs:
        df = fetch_pair(pair, lookback_days, tf)
        if df is None or len(df) < 200:
            print(f"  ❌ {pair}: keine Daten oder zu wenig Historie ({lookback_days}d, {tf})")
            continue
        bias = trend_bias_series(pair, df.index, trend_cfg)
        pair_data[pair] = {
            "df": df, "bias": bias,
            "pip": c["pairs"][pair]["pip_size"],
            "spread": c["pairs"][pair]["spread_pips"],
        }
    if not pair_data:
        return None, {}

    candidates = []
    for fast, slow, mom_lb, sl_m, tp_m in itertools.product(FAST_GRID, SLOW_GRID, MOM_GRID, SL_GRID, TP_GRID):
        if slow <= fast:
            continue
        per_pair = {}
        for pair, pd_ in pair_data.items():
            trades = simulate(pd_["df"], pd_["bias"], fast, slow, mom_lb, min_strength, sl_m, tp_m,
                               hold_cap_days, trailing_mult)
            pips = net_pips(trades, pd_["pip"], pd_["spread"])
            score, metrics = score_trades(trades)
            per_pair[pair] = {"pips": round(pips, 1), "trades": len(trades), "score": score, "metrics": metrics}
        n_pairs = len(per_pair)
        n_pos = sum(1 for m in per_pair.values() if m["pips"] > 0)
        total_pips = sum(m["pips"] for m in per_pair.values())
        total_trades = sum(m["trades"] for m in per_pair.values())
        robust = (n_pos == n_pairs) and total_trades >= MIN_TOTAL_TRADES
        candidates.append({
            "params": {"ema_fast": fast, "ema_slow": slow, "momentum_lookback": mom_lb,
                       "min_trend_strength": min_strength, "sl_atr_mult": sl_m, "tp_atr_mult": tp_m},
            "robust": robust, "n_pos": n_pos, "n_pairs": n_pairs,
            "total_pips": round(total_pips, 1), "total_trades": total_trades, "per_pair": per_pair,
        })

    robust_c = [x for x in candidates if x["robust"]]
    robust_c.sort(key=lambda r: -r["total_pips"])
    others = [x for x in candidates if not x["robust"]]
    others.sort(key=lambda r: (-r["n_pos"], -r["total_pips"]))
    ranking = robust_c + others
    return ranking, pair_data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--pair", help="Nur dieses Paar in die Robustheits-Suche einbeziehen (Debug)")
    args = ap.parse_args()

    c = cfg.CONFIG
    wf = c["walk_forward"]
    lookback_days = wf["lookback_weeks"] * 7
    hold_cap_days = wf.get("holding_days_cap")
    trend_cfg = c.get("signal", {})
    min_strength = trend_cfg.get("min_trend_strength", 0.002)
    # trailing_atr_mult ist in trade.py GLOBAL (config.sl_tp), nicht Teil des
    # Snapshots/Grids — hier identisch übernehmen, damit die Simulation trade.py's
    # tägliches Nachziehen des Stops (_update_trailing) mit abbildet.
    trailing_mult = c.get("sl_tp", {}).get("trailing_atr_mult", 0.0)

    pairs = [args.pair] if args.pair else list(c["pairs"].keys())
    con = cfg.db_connect()
    cfg.init_db(con)

    tf = c.get("timeframe", "15m")
    grid_n = len(FAST_GRID) * len(SLOW_GRID) * len(MOM_GRID) * len(SL_GRID) * len(TP_GRID)
    print(f"=== Walk-Forward-Optimierung: EIN robuster Satz für {len(pairs)} Paare "
          f"({datetime.now().strftime('%Y-%m-%d %H:%M')}) ===")
    print(f"Timeframe: {tf} | Trendfilter: {c.get('trend_timeframe', '1h')} | "
          f"Lookback: {lookback_days} Tage | Grid: {grid_n} Kombis | Trailing: {trailing_mult}xATR\n")

    ranking, pair_data = find_robust_params(pairs, lookback_days, trend_cfg, hold_cap_days,
                                             min_strength, trailing_mult)

    if not ranking:
        print("\n❌ Walk-Forward FEHLGESCHLAGEN — für kein einziges Paar Daten erhalten. "
              "Keine neuen Snapshots geschrieben, zuletzt gültiger Zustand bleibt aktiv.")
        con.close()
        return 1

    winner = ranking[0]
    ok_pairs = list(pair_data.keys())
    missing = [p for p in pairs if p not in pair_data]

    print(f"Robuste Kandidaten (positiv in ALLEN {len(ok_pairs)} geladenen Paaren, "
          f">= {MIN_TOTAL_TRADES} Trades gesamt): {sum(1 for x in ranking if x['robust'])} / {len(ranking)}")
    print("\n=== TOP 5 ===")
    for i, r in enumerate(ranking[:5]):
        g = r["params"]
        flag = " ← ROBUST" if r["robust"] else ""
        print(f"  #{i+1} total_pips={r['total_pips']:>8} nPos={r['n_pos']}/{r['n_pairs']} "
              f"trd={r['total_trades']:>3}  EMA{g['ema_fast']}/{g['ema_slow']} mom_lb={g['momentum_lookback']} "
              f"sl={g['sl_atr_mult']} tp={g['tp_atr_mult']}{flag}")

    print(f"\n=== Gewinner je Paar ===")
    for pair, m in winner["per_pair"].items():
        print(f"  {pair:10} pips={m['pips']:>8} trades={m['trades']:>3} "
              f"pf={m['metrics']['pf']} wr={m['metrics']['wr']}")

    if not winner["robust"]:
        print(f"\n⚠️  KEIN im Grid gefundener Satz war in ALLEN Paaren positiv — "
              f"Fallback auf den besten Nicht-robusten ({winner['n_pos']}/{winner['n_pairs']} Paare positiv). "
              f"trade.py's Qualitäts-Floor (walk_forward.min_snapshot_score) filtert pro Paar trotzdem "
              f"weiter aus, falls ein einzelnes Paar damit unprofitabel bleibt.")

    if missing:
        print(f"\nℹ️  Ohne Daten (kein neuer Snapshot, alter Stand bleibt aktiv): {', '.join(missing)}")

    if not args.dry_run:
        for pair, m in winner["per_pair"].items():
            con.execute(
                "INSERT INTO params_snapshots (created_at, pair, params_json, lookback_weeks, metric_name, metric_value, note) "
                "VALUES (?, ?, ?, ?, 'combined_score', ?, ?)",
                (datetime.now().isoformat(), pair, json.dumps(winner["params"]), wf["lookback_weeks"],
                 m["score"],
                 f"ROBUST-SET (alle Paare gleich) | robust={winner['robust']} total_pips={winner['total_pips']} | "
                 f"PF={m['metrics']['pf']}, WR={m['metrics']['wr']}, Sharpe={m['metrics']['sharpe']}, Trades={m['metrics']['trades']}")
            )
        con.commit()
    con.close()

    print(f"\n✅ Walk-Forward abgeschlossen. Robuster Satz für {len(ok_pairs)}/{len(pairs)} Paare "
          f"{'gefunden' if winner['robust'] else '(Fallback, siehe Warnung oben)'}"
          f"{' (dry-run, keine Snapshots geschrieben)' if args.dry_run else ', Param-Snapshots gespeichert'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
