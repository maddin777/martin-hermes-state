"""
trade.py — Paper-Positions-Management für den Forex-Paper-Bot.

Nutzung:
  python3 trade.py --check       # Standardlauf: Signale prüfen, Positionen verwalten (Session-Cron)
  python3 trade.py --test        # Testmodus: fetch + Signal + Drawdown-Gate, keine DB-Writer

Ablauf (jeder 15-min-Lauf):
  1. Session-Status prüfen (London/NY). Außerhalb → nur offene Positionen verwalten (Trailing), keine neuen Entries.
  2. Drawdown-Gate: wenn Drawdown >= max_drawdown_pct (50%), keine neuen Entries (offene Trades laufen aus).
  3. Für jedes Paar: Signal via forex_signal. Bei LONG/SHORT und Session+Gate ok → Paper-Trade eröffnen.
  4. Offene Positionen: Trailing-Stop aktualisieren, SL/TP prüfen, bei Exit PnL netto (spread-bereinigt) verbuchen.
"""
import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as cfg
from fetch import fetch_pair, _scalar
import forex_signal as sig

import yfinance as yf


# ── Spread/PnL-Helfer ────────────────────────────────────────────────

def _pip_size(pair_cfg):
    return pair_cfg.get("pip_size", 0.0001)


def _pip_value(pair_cfg):
    """$ pro pip pro Standard-Lot (100k units). Default 10$."""
    return pair_cfg.get("pip_value_usd", 10.0)


def spread_cost_eur(pair, pair_cfg, size_units):
    """Spread-Kosten in EUR für eine Position."""
    spread_pips = pair_cfg.get("spread_pips", 1.0)
    pip_value = _pip_value(pair_cfg)
    lots = size_units / 100000.0
    cost_usd = spread_pips * pip_value * lots
    # grobe USD→EUR (Fix 1.0/1.0; wäre präziser via aktuellem Kurs, für Paper ok)
    return cost_usd


def latest_price(pair):
    """Latest Close für ein Paar (via yfinance)."""
    df = fetch_pair(pair, 2, "15m")
    if df is None or len(df) == 0:
        return None
    return _scalar(df["Close"].iloc[-1])


# ── Positions-Management ─────────────────────────────────────────────

def open_trade(con, pair, pair_cfg, params, price, direction):
    """Eröffnet einen Paper-Trade. Liefert dict oder None (wenn geblockt)."""
    if direction not in ("LONG", "SHORT"):
        return None
    # Position Sizing: max 2% Risk, basierend auf SL-Distanz
    risk_eur = cfg.CONFIG["capital"] * cfg.CONFIG["risk_per_trade_pct"]
    sl_mult = params.get("sl_atr_mult", 1.5)
    # ATR für Sizing — vereinfacht: 0.5% vom Preis als SL-Distanz-Annahme
    dist = price * 0.005  # 0.5% Puffer
    size_units = risk_eur / dist
    sl = price - sl_mult * dist if direction == "LONG" else price + sl_mult * dist
    tp_mult = params.get("tp_atr_mult", 2.5)
    tp = price + tp_mult * dist if direction == "LONG" else price - tp_mult * dist

    con.execute(
        "INSERT INTO trades (pair, direction, entry_time, entry_price, sl, tp, trail_stop, "
        "size_units, risk_eur, spread_cost_eur, pnl_gross, pnl_net, status, params_snapshot) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 'open', ?)",
        (pair, direction, datetime.now().isoformat(), price, sl, tp, sl,
         size_units, risk_eur, spread_cost_eur(pair, pair_cfg, size_units),
         json.dumps(params))
    )
    con.commit()
    return {"pair": pair, "direction": direction, "price": price, "sl": sl, "tp": tp,
            "size": size_units}


def manage_open_positions(con, params_by_pair):
    """Prüft offene Positionen: Trailing + SL/TP + Exit. Verbucht PnL netto."""
    rows = con.execute("SELECT * FROM trades WHERE status='open'").fetchall()
    results = []
    for row in rows:
        price = latest_price(row["pair"])
        if price is None:
            continue
        pair_cfg = cfg.CONFIG["pairs"].get(row["pair"], {})
        exit_evt = None
        if row["direction"] == "LONG":
            if price <= row["sl"]:
                exit_evt = ("SL", price)
            elif price >= row["tp"]:
                exit_evt = ("TP", price)
        else:
            if price >= row["sl"]:
                exit_evt = ("SL", price)
            elif price <= row["tp"]:
                exit_evt = ("TP", price)
        if exit_evt:
            reason, exit_price = exit_evt
            _close_trade(con, row, exit_price, reason, pair_cfg)
            results.append({"pair": row["pair"], "action": "EXIT", "reason": reason})
        else:
            # Trailing-Stop aktualisieren (nur in Trendrichtung nachziehen)
            _update_trailing(con, row, price, pair_cfg)
    return results


def _update_trailing(con, row, price, pair_cfg):
    trailing_atr = cfg.CONFIG["sl_tp"].get("trailing_atr_mult", 1.0)
    dist = price * 0.005 * trailing_atr
    new_trail = price - dist if row["direction"] == "LONG" else price + dist
    old = row["trail_stop"]
    # Nur nachziehen (profit-locking), nie zurück
    if row["direction"] == "LONG" and new_trail > old:
        con.execute("UPDATE trades SET trail_stop=? WHERE id=?", (new_trail, row["id"]))
        con.execute("UPDATE trades SET sl=? WHERE id=?", (new_trail, row["id"]))
        con.commit()
    elif row["direction"] == "SHORT" and new_trail < old:
        con.execute("UPDATE trades SET trail_stop=? WHERE id=?", (new_trail, row["id"]))
        con.execute("UPDATE trades SET sl=? WHERE id=?", (new_trail, row["id"]))
        con.commit()


def _close_trade(con, row, exit_price, reason, pair_cfg):
    direction = row["direction"]
    entry = _scalar(row["entry_price"])
    exit_price = float(exit_price)
    if direction == "LONG":
        pnl_gross = (exit_price - entry) / entry * row["size_units"]
    else:
        pnl_gross = (entry - exit_price) / entry * row["size_units"]
    # Spread-Kosten subtrahieren (netto)
    spread_cost = row["spread_cost_eur"] if row["spread_cost_eur"] else 0.0
    pnl_net = pnl_gross - spread_cost
    con.execute(
        "UPDATE trades SET exit_time=?, exit_price=?, pnl_gross=?, pnl_net=?, exit_reason=?, status='closed' "
        "WHERE id=?",
        (datetime.now().isoformat(), exit_price, pnl_gross, pnl_net, reason, row["id"])
    )
    # Portfolio-Update
    cash = con.execute("SELECT cash FROM portfolio WHERE id=1").fetchone()[0]
    new_cash = cash + pnl_net
    peak = con.execute("SELECT equity_peak FROM portfolio WHERE id=1").fetchone()[0]
    if new_cash > peak:
        peak = new_cash
    con.execute("UPDATE portfolio SET cash=?, equity_peak=?, realized_pnl=realized_pnl+? WHERE id=1",
                (new_cash, peak, pnl_net))
    con.commit()


# ── Main ─────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="Standardlauf (Session-Cron)")
    ap.add_argument("--test", action="store_true", help="Testmodus ohne DB-Writer")
    args = ap.parse_args()

    c = cfg.CONFIG
    con = cfg.db_connect()
    cfg.init_db(con)

    # Aktive Param-Snapshots (letzter je Paar)
    params_by_pair = {}
    for row in con.execute(
        "SELECT pair, params_json FROM params_snapshots s WHERE s.created_at = "
        "(SELECT MAX(created_at) FROM params_snapshots WHERE pair=s.pair) GROUP BY pair"
    ).fetchall():
        try:
            params_by_pair[row["pair"]] = json.loads(row["params_json"])
        except Exception:
            params_by_pair[row["pair"]] = dict(c["signal"])

    in_sess = sig.in_session(cfg_session=c.get("session", c))
    dd = cfg.drawdown_pct(con)
    dd_blocked = dd >= c["max_drawdown_pct"]

    print(f"=== Forex Trade-Check ({datetime.now().strftime('%Y-%m-%d %H:%M')}) ===")
    print(f"Session: {'✅' if in_sess else '⏸ außerhalb'} | Drawdown: {dd:.1%} "
          f"({'🚫 BLOCKED' if dd_blocked else '✅ ok'})")

    # 1. Neue Entries nur wenn in Session + nicht drawdown-blocked
    if in_sess and not dd_blocked and not args.test:
        for pair, pair_cfg in c["pairs"].items():
            params = params_by_pair.get(pair, dict(c["signal"]))
            res = sig.signal_for_pair(pair, params, c.get("signal", {}), pair_cfg)
            if res["signal"] in ("LONG", "SHORT"):
                # kein offener Trade auf demselben Paar
                already = con.execute(
                    "SELECT COUNT(*) FROM trades WHERE pair=? AND status='open'", (pair,)).fetchone()[0]
                if already == 0:
                    price = latest_price(pair)
                    if price:
                        t = open_trade(con, pair, pair_cfg, params, price, res["signal"])
                        print(f"  📈 {pair}: {res['signal']} @ {price:.5f} | Size {t['size']:.0f} units")
    elif args.test:
        # Test: Signale anzeigen, aber nichts eröffnen
        for pair, pair_cfg in c["pairs"].items():
            params = params_by_pair.get(pair, dict(c["signal"]))
            res = sig.signal_for_pair(pair, params, c.get("signal", {}), pair_cfg)
            print(f"  [{pair}] Signal: {res['signal']:6} (H1 {res['h1']}) — {res['reason']}")

    # 2. Offene Positionen verwalten (auch außerhalb Session)
    exits = manage_open_positions(con, params_by_pair)
    for e in exits:
        print(f"  🔻 {e['pair']}: EXIT ({e['reason']})")

    con.close()
    print("✅ Trade-Check abgeschlossen")
    return 0


if __name__ == "__main__":
    sys.exit(main())
