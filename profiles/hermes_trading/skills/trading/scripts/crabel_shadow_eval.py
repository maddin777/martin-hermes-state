#!/usr/bin/env python3
"""
Crabel Shadow Eval — Forward-Pricing der vom Gate verhinderten Entries.

Warum das existiert:
Der Strategy-Optimizer resimuliert SL/TP auf Trades, die STATTGEFUNDEN haben.
Ein Entry-Filter verändert aber, WELCHE Trades existieren – was er blockt,
landet nie in `positions`. Aus `positions` allein lässt sich deshalb nie
lernen, ob der Filter gut ist (Survivorship Bias). Dieses Skript baut den
fehlenden Counterfactual: es bepreist jeden geblockten Kandidaten vorwärts
und beantwortet "was hätte der Trade gemacht?".

Läuft täglich nach der Trading-Pipeline. Stufe 1 = MESSEN, keine Entscheidungen:
das Skript ändert weder Config noch Positionen.

Simulation:
- SL/TP-Level kommen aus blocked_entries (mit signal_manager.compute_sl_tp
  berechnet – identische Formel wie der Live-Entry).
- Exit-Logik spiegelt active_exit_check: AKTION 2 (Profit-Lock ab
  profit_lock_atr) + AKTION 3 (Trailing ab profit_lock_atr). Ohne das würden
  die Shadow-Trades ihre Gewinner zu oft bis zum vollen TP laufen lassen und
  systematisch besser aussehen als die echten Trades → Bias gegen das Gate.
- Bekannte Vereinfachungen (bewusst, dokumentiert): kein Partial-TP, keine
  Thesis-Exits, kein Breaking-News-Exit. Der Vergleich ist richtungsweisend,
  nicht exakt.
"""
import sys
import os
import json
from datetime import datetime, timedelta

_TRADING_ROOT = "/root/.hermes/profiles/hermes_trading/skills/trading"
for _p in (_TRADING_ROOT, os.path.join(_TRADING_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import env_loader  # noqa: F401  (side-effect: laedt .env)
import yfinance as yf
from config import db_connect, STRATEGY_CONFIG_PATH, get_asset_multipliers
from utils import get_logger, realized_pnl_from_effective_entry

log = get_logger("crabel_shadow_eval")

# Kalendertage, die einem geblockten Entry Zeit gegeben werden, bevor er
# ausgewertet wird. ~21 Kalendertage ≈ 15 Handelstage – deckt die im
# Post-Mortem identifizierte produktive Haltedauer (8–14 Tage) ab.
DEFAULT_HORIZON_DAYS = 21


def load_cfg():
    try:
        with open(STRATEGY_CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _col(df, name):
    """Multi-Index-sichere Spaltenextraktion (yfinance)."""
    s = df[name]
    return s.iloc[:, 0] if s.ndim > 1 else s


def simulate_forward(df, entry, sl, tp, atr, direction, asset_type, cfg):
    """
    Simuliert den geblockten Trade auf Tagesbars ab dem Tag NACH dem Block.

    Returns (outcome, exit_price, days) mit outcome ∈ SL_HIT | TP_HIT | TIMEOUT.

    Intrabar-Ambiguität (SL und TP im selben Bar getroffen): SL gewinnt.
    Tagesbars sagen nicht, was zuerst kam – die konservative Annahme verhindert,
    dass die Shadow-Trades zu gut aussehen.
    """
    mult        = get_asset_multipliers(asset_type)
    trail_step  = mult["trailing_step"]
    sl_mult     = mult["atr_sl"]
    profit_lock = cfg.get("profit_lock_atr", 2.0)

    highs  = _col(df, "High")
    lows   = _col(df, "Low")
    closes = _col(df, "Close")

    cur_sl = sl
    for i in range(len(df)):
        hi, lo, cl = float(highs.iloc[i]), float(lows.iloc[i]), float(closes.iloc[i])
        day = i + 1

        # 1. Exit-Prüfung auf Intrabar-Extremen — SL zuerst (konservativ)
        if direction == "LONG":
            if lo <= cur_sl:
                return "SL_HIT", cur_sl, day
            if hi >= tp:
                return "TP_HIT", tp, day
        else:
            if hi >= cur_sl:
                return "SL_HIT", cur_sl, day
            if lo <= tp:
                return "TP_HIT", tp, day

        # 2. SL-Nachführung auf Close-Basis (wie active_exit_check, das EOD läuft)
        pnl_atr = (cl - entry) / atr if direction == "LONG" else (entry - cl) / atr
        if pnl_atr >= profit_lock:
            if direction == "LONG":
                # AKTION 2: Profit-Lock
                cur_sl = max(cur_sl, entry + (pnl_atr * 0.5 * atr))
                # AKTION 3: Trailing
                ideal = cl - (sl_mult * atr)
                if ideal > cur_sl + (trail_step * atr):
                    cur_sl = ideal
            else:
                cur_sl = min(cur_sl, entry - (pnl_atr * 0.5 * atr))
                ideal = cl + (sl_mult * atr)
                if ideal < cur_sl - (trail_step * atr):
                    cur_sl = ideal

    return "TIMEOUT", float(closes.iloc[-1]), len(df)


def check_later_entry(con, row):
    """
    Wurde derselbe Kandidat später doch noch real eingekauft?

    Das ist der springende Punkt: Das Gate wirft den Kandidaten nicht weg – er
    bleibt auf der Watchlist. Die echte Alternative zum geblockten Entry ist
    also nicht "kein Trade", sondern "Entry ein paar Tage später zum bestätigten
    Kurs". Genau das misst dieses Feld.
    """
    r = con.execute("""
        SELECT entry_date, entry_price FROM positions
        WHERE ticker=? AND direction=? AND entry_date > ?
        ORDER BY entry_date ASC LIMIT 1
    """, (row["ticker"], row["direction"], row["blocked_at"])).fetchone()
    if not r:
        return 0, None, None
    try:
        d0 = datetime.strptime(row["block_date"], "%Y-%m-%d")
        d1 = datetime.strptime(r["entry_date"][:10], "%Y-%m-%d")
        days = (d1 - d0).days
    except Exception:
        days = None
    # Nur Entries innerhalb des Auswertungsfensters zählen – ein Entry drei
    # Monate später hat mit dem geblockten Setup nichts mehr zu tun.
    if days is not None and days > DEFAULT_HORIZON_DAYS:
        return 0, None, None
    return 1, days, r["entry_price"]


def main():
    cfg     = load_cfg()
    horizon = int(cfg.get("crabel_shadow_horizon_days", DEFAULT_HORIZON_DAYS))
    con     = db_connect()
    print(f"🔍 Crabel Shadow Eval (Horizont: {horizon} Kalendertage)", flush=True)

    cutoff = (datetime.now() - timedelta(days=horizon)).strftime("%Y-%m-%d")
    rows = con.execute("""
        SELECT * FROM blocked_entries
        WHERE eval_status='pending' AND block_date <= ?
        ORDER BY block_date ASC
    """, (cutoff,)).fetchall()

    if not rows:
        pend = con.execute(
            "SELECT COUNT(*) FROM blocked_entries WHERE eval_status='pending'"
        ).fetchone()[0]
        print(f"  Keine reifen Einträge. {pend} warten noch auf den Horizont.", flush=True)
        con.close()
        return

    print(f"  {len(rows)} geblockte Entries auswertbar", flush=True)
    evaluated = no_data = 0

    for row in rows:
        ticker = row["ticker"]
        try:
            start = (datetime.strptime(row["block_date"], "%Y-%m-%d")
                     + timedelta(days=1)).strftime("%Y-%m-%d")
            end   = (datetime.strptime(row["block_date"], "%Y-%m-%d")
                     + timedelta(days=horizon + 1)).strftime("%Y-%m-%d")
            df = yf.download(ticker, start=start, end=end, interval="1d",
                             progress=False, auto_adjust=True)
            df = df.dropna()
            if df.empty or len(df) < 3:
                con.execute(
                    "UPDATE blocked_entries SET eval_status='no_data', eval_date=? WHERE id=?",
                    (datetime.now().strftime("%Y-%m-%d"), row["id"])
                )
                no_data += 1
                continue

            outcome, exit_price, days = simulate_forward(
                df, row["would_entry"], row["would_sl"], row["would_tp"],
                row["atr_at_block"], row["direction"],
                row["asset_type"] or "STANDARD", cfg
            )
            # pnl_pct ohne Commission – konsistent zu positions.pnl_pct.
            # Nominalgröße egal, pnl_pct ist size-invariant.
            _, pnl_pct = realized_pnl_from_effective_entry(
                row["would_entry"], exit_price, 1000.0, row["direction"]
            )
            later, later_days, later_price = check_later_entry(con, row)

            con.execute("""
                UPDATE blocked_entries SET
                    eval_status='evaluated', eval_date=?, outcome=?,
                    days_to_outcome=?, exit_price_sim=?, pnl_pct_sim=?,
                    later_entered=?, later_entry_days=?, later_entry_price=?
                WHERE id=?
            """, (
                datetime.now().strftime("%Y-%m-%d"), outcome, days,
                round(exit_price, 4), round(pnl_pct * 100, 2),
                later, later_days, later_price, row["id"]
            ))
            evaluated += 1
            tag = "→ später doch gekauft" if later else ""
            print(f"  {ticker:10} {row['direction']:5} {outcome:8} "
                  f"nach {days:2}d: {pnl_pct*100:+6.2f}% {tag}", flush=True)

        except Exception as e:
            log.warning("Shadow-Eval Fehler (%s): %s", ticker, e)
            con.execute(
                "UPDATE blocked_entries SET eval_status='no_data', eval_date=? WHERE id=?",
                (datetime.now().strftime("%Y-%m-%d"), row["id"])
            )
            no_data += 1

    con.commit()

    # Laufende Zwischenbilanz (rein informativ – keine Entscheidung)
    agg = con.execute("""
        SELECT COUNT(*) n, AVG(pnl_pct_sim) avg_pnl,
               SUM(CASE WHEN pnl_pct_sim > 0 THEN 1 ELSE 0 END) wins
        FROM blocked_entries WHERE eval_status='evaluated'
    """).fetchone()
    print(f"\n  ✅ {evaluated} ausgewertet, {no_data} ohne Daten", flush=True)
    if agg and agg["n"]:
        wr = agg["wins"] / agg["n"] * 100
        print(f"  📊 Shadow-Sample gesamt: N={agg['n']} | "
              f"Ø {agg['avg_pnl']:+.2f}% | WR {wr:.0f}%", flush=True)
        if agg["n"] < 30:
            print(f"     (N<30 – noch keine belastbare Aussage, "
                  f"Auswertung im weekly_review)", flush=True)
    con.close()
    print("[Crabel Shadow Eval] DONE.", flush=True)


if __name__ == "__main__":
    main()
