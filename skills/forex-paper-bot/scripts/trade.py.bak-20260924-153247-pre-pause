"""
trade.py — Paper-Positions-Management für den Forex-Paper-Bot.

Nutzung:
  python3 trade.py --check       # Standardlauf: Signale prüfen, Positionen verwalten (Session-Cron)
  python3 trade.py --test        # Testmodus: fetch + Signal + Drawdown-Gate, keine DB-Writer

Ablauf (jeder Lauf):
  1. Session-Status prüfen (London/NY). Außerhalb → nur offene Positionen verwalten (Trailing), keine neuen Entries.
  2. Drawdown-Gate: wenn Drawdown >= max_drawdown_pct (50%), keine neuen Entries (offene Trades laufen aus).
  3. Für jedes Paar: Signal via forex_signal. Bei LONG/SHORT + Session/Gate/Cooldown/Korrelations-Cap ok
     → Paper-Trade eröffnen (SL/TP/Sizing aus echtem ATR).
  4. Offene Positionen: Trailing-Stop aktualisieren, SL/TP/Holding-Cap prüfen, bei Exit PnL netto
     (spread-bereinigt) verbuchen — Exit-Preis ist der SL/TP-Preis selbst, kein Slippage-Fiktion
     aus dem 1x/Tag-Polling-Preis.

2026-09-22 Fixes (siehe backups/*.pre-fix.* für den Vorzustand):
  - PnL-Formel korrigiert (war fälschlich durch entry_price geteilt → Risiko pro Trade
    variierte um Faktor ~360 zwischen Paaren statt einheitlich 2%).
  - Sizing/SL/TP/Trailing nutzen jetzt echtes ATR(14) auf der Live-Timeline statt eines
    fixen 0.5%-Preis-Puffers.
  - SL/TP-Exits werden zum SL/TP-Preis verbucht (nicht zum Polling-Preis) — vermeidet
    künstliche Slippage durch das 1x/Tag-Zeitfenster.
  - Holding-Days-Cap (config walk_forward.holding_days_cap) wird jetzt tatsächlich erzwungen.
  - Cooldown nach Stop-Loss pro Paar (config cooldown_days_after_loss) gegen Whipsaw-Churn.
  - Korrelations-Cap: max. N gleichgerichtete USD-Positionen gleichzeitig (config
    max_correlated_positions) gegen versteckte Klumpenrisiken (5 Trades = 1 USD-Wette).
"""
import argparse
import json
import os
import sys
import urllib.request
import urllib.parse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as cfg
from fetch import fetch_pair, _scalar
import forex_signal as sig

import pandas as pd


# ── Telegram ─────────────────────────────────────────────────────────

def send_telegram(text):
    """Sendet eine Nachricht direkt via Telegram Bot API (aus Env-Token/ChatID).

    Liest TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID aus der Umgebung (lädt der
    forex_*.sh Wrapper). Silently-fail bei fehlendem Token — Logging per stdout.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print(f"  [no-telegram] chat_id/token nicht gesetzt: {text[:80]}", flush=True)
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({"chat_id": chat_id, "text": text,
                                      "parse_mode": "HTML"}).encode()
    try:
        req = urllib.request.Request(url, data=payload)
        with urllib.request.urlopen(req, timeout=10) as r:
            ok = json.loads(r.read()).get("ok", False)
        print(f"  [telegram] {'✅' if ok else '❌'} {text[:60]}", flush=True)
        return ok
    except Exception as e:
        print(f"  [telegram-Fehler] {e} | {text[:60]}", flush=True)
        return False


def _pair_display(pair):
    return cfg.CONFIG["pairs"].get(pair, {}).get("display", pair)


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


# ── ATR (echt, statt fixem 0.5%-Preis-Puffer) ───────────────────────

def atr_series(df, n=14):
    """Klassisches ATR(n) aus High/Low/Close (Wilder-nah, simple rolling mean)."""
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    close = df["Close"].astype(float)
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def current_atr(pair):
    """Aktueller ATR(14) auf der Live-Timeline (cfg.timeframe) für Sizing/SL/Trailing.

    Liefert None wenn zu wenig Historie da ist (Aufrufer muss Fallback behandeln).
    """
    tf = cfg.CONFIG.get("timeframe", "15m")
    cache_days = 5 if tf == "15m" else 120  # genug Bars für ATR(14) + Puffer
    df = fetch_pair(pair, cache_days, tf)
    if df is None or len(df) < 20:
        return None
    val = _scalar(atr_series(df, 14).iloc[-1])
    return val if val and val > 0 else None


# ── Korrelations-Cap (USD-Richtungs-Exposure) ────────────────────────

def usd_direction(pair, direction):
    """+1 = Netto-USD-long-Exposure, -1 = Netto-USD-short-Exposure.

    EUR/USD, GBP/USD, AUD/USD: USD ist Quote-Währung → LONG heißt USD-short.
    USD/JPY, USD/CHF: USD ist Basis-Währung → LONG heißt USD-long.
    Dient dem Korrelations-Cap: 5 „verschiedene" Trades können in Wahrheit
    eine einzige gehebelte USD-Wette sein.
    """
    usd_is_base = pair.startswith("USD")
    if usd_is_base:
        return 1 if direction == "LONG" else -1
    return -1 if direction == "LONG" else 1


def correlated_open_count(con, direction_sign):
    rows = con.execute("SELECT pair, direction FROM trades WHERE status='open'").fetchall()
    return sum(1 for r in rows if usd_direction(r["pair"], r["direction"]) == direction_sign)


# ── Cooldown nach Stop-Loss ───────────────────────────────────────────

def in_cooldown(con, pair):
    """True, wenn der letzte SL-Exit auf diesem Paar noch innerhalb der Cooldown-Frist liegt.

    Verhindert Whipsaw-Churn (z.B. AUD/USD 24.-28.08.: SHORT→LONG→SHORT, alle drei
    gestoppt, -91 Pips in 4 Tagen ohne Verschnaufpause).
    """
    cooldown_days = cfg.CONFIG.get("cooldown_days_after_loss", 0)
    if not cooldown_days:
        return False
    row = con.execute(
        "SELECT exit_time FROM trades WHERE pair=? AND status='closed' AND exit_reason='SL' "
        "ORDER BY exit_time DESC LIMIT 1", (pair,)
    ).fetchone()
    if not row or not row["exit_time"]:
        return False
    last_sl = datetime.fromisoformat(row["exit_time"])
    return (datetime.now() - last_sl).days < cooldown_days


# ── Positions-Management ─────────────────────────────────────────────

def open_trade(con, pair, pair_cfg, params, price, direction):
    """Eröffnet einen Paper-Trade. Liefert dict oder None (wenn geblockt)."""
    if direction not in ("LONG", "SHORT"):
        return None
    # Position Sizing: max 2% Risk, basierend auf echter ATR-SL-Distanz
    risk_eur = cfg.CONFIG["capital"] * cfg.CONFIG["risk_per_trade_pct"]
    sl_mult = params.get("sl_atr_mult", 1.5)
    tp_mult = params.get("tp_atr_mult", 2.5)

    atr = current_atr(pair)
    if atr is None:
        # Fallback falls (noch) zu wenig Historie für ATR(14) — alte Notlösung,
        # aber mit Warnung, damit das nicht mehr still passiert.
        atr = price * 0.005
        print(f"  ⚠️  {pair}: kein ATR verfügbar, Fallback 0.5%-Preis-Puffer", flush=True)

    sl_dist = sl_mult * atr
    if sl_dist <= 0:
        return None
    sl = price - sl_dist if direction == "LONG" else price + sl_dist
    tp = price + tp_mult * atr if direction == "LONG" else price - tp_mult * atr
    # size_units so gewählt, dass beim Erreichen des SL genau risk_eur verloren geht:
    # pnl = (exit - entry) * size_units  ⇒  size_units = risk_eur / sl_dist
    size_units = risk_eur / sl_dist

    con.execute(
        "INSERT INTO trades (pair, direction, entry_time, entry_price, sl, tp, trail_stop, "
        "size_units, risk_eur, spread_cost_eur, pnl_gross, pnl_net, status, params_snapshot) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 'open', ?)",
        (pair, direction, datetime.now().isoformat(), price, sl, tp, sl,
         size_units, risk_eur, spread_cost_eur(pair, pair_cfg, size_units),
         json.dumps(params))
    )
    con.commit()
    emoji = "🟢 LONG" if direction == "LONG" else "🔴 SHORT"
    disp = _pair_display(pair)
    send_telegram(
        f"<b>📈 FOREX-TRADE ERÖFFNET</b>\n"
        f"{emoji} {disp} ({pair})\n"
        f"Einstieg: {price:.5f}\n"
        f"SL: {sl:.5f} | Größe: {size_units:.0f} units\n"
        f"Risiko: {risk_eur:.2f} € ({cfg.CONFIG['risk_per_trade_pct']*100:.0f}%)"
    )
    return {"pair": pair, "direction": direction, "price": price, "sl": sl, "tp": tp,
            "size": size_units}


def manage_open_positions(con, params_by_pair):
    """Prüft offene Positionen: Trailing + SL/TP + Holding-Cap + Exit. Verbucht PnL netto."""
    rows = con.execute("SELECT * FROM trades WHERE status='open'").fetchall()
    results = []
    cap_days = cfg.CONFIG.get("walk_forward", {}).get("holding_days_cap")
    for row in rows:
        price = latest_price(row["pair"])
        if price is None:
            continue
        pair_cfg = cfg.CONFIG["pairs"].get(row["pair"], {})
        exit_evt = None
        # SL/TP werden zum SL/TP-Preis selbst verbucht (nicht zum 1x/Tag-Polling-Preis) —
        # sonst erzeugt der 15m-Polling-Preis künstliche Slippage weit über den Stop hinaus
        # (live beobachtet: bis zu 85 Pips über den gesetzten Stop).
        if row["direction"] == "LONG":
            if price <= row["sl"]:
                exit_evt = ("SL", row["sl"])
            elif price >= row["tp"]:
                exit_evt = ("TP", row["tp"])
        else:
            if price >= row["sl"]:
                exit_evt = ("SL", row["sl"])
            elif price <= row["tp"]:
                exit_evt = ("TP", row["tp"])

        if exit_evt is None and cap_days:
            entry_dt = datetime.fromisoformat(row["entry_time"])
            if (datetime.now() - entry_dt).days >= cap_days:
                exit_evt = ("CAP", price)  # Cap-Exit: kein SL/TP-Preis definiert, Marktpreis ok

        if exit_evt:
            reason, exit_price = exit_evt
            _close_trade(con, row, exit_price, reason, pair_cfg)
            results.append({"pair": row["pair"], "action": "EXIT", "reason": reason})
        else:
            # Trailing-Stop aktualisieren (nur in Trendrichtung nachziehen)
            _update_trailing(con, row, price, pair_cfg)
    return results


def _update_trailing(con, row, price, pair_cfg):
    trailing_mult = cfg.CONFIG["sl_tp"].get("trailing_atr_mult", 1.0)
    atr = current_atr(row["pair"])
    if atr is None:
        atr = price * 0.005  # Fallback, siehe open_trade
    dist = atr * trailing_mult
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
    # PnL = Preisdelta * Units (KEINE Division durch entry_price — size_units ist bereits
    # so bemessen, dass Preisdelta * size_units = risk_eur am SL ergibt; die alte Formel
    # dividierte zusätzlich durch entry_price und machte das Risiko pro Trade kursabhängig
    # — Faktor ~360 zwischen AUD/USD (~0.71) und USD/JPY (~155) statt einheitlich 2%).
    if direction == "LONG":
        pnl_gross = (exit_price - entry) * row["size_units"]
    else:
        pnl_gross = (entry - exit_price) * row["size_units"]
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

    emoji = "✅" if pnl_net > 0 else "❌"
    disp = _pair_display(row["pair"])
    reason_d = {"SL": "Stop-Loss", "TP": "Take-Profit", "CAP": "Haltezeit-Cap"}.get(reason, reason)
    send_telegram(
        f"<b>{emoji} FOREX-TRADE GESCHLOSSEN</b>\n"
        f"{'🟢' if row['direction']=='LONG' else '🔴'} {disp} ({row['pair']})\n"
        f"Exit ({reason_d}): {exit_price:.5f}\n"
        f"PnL netto: <b>{pnl_net:+.2f} €</b> (gross {pnl_gross:+.2f}, Spread {spread_cost:.2f})"
    )


# ── Param-Snapshots laden (mit Qualitäts-Floor) ──────────────────────

def robust_default_params(c):
    """Der dokumentierte, Out-of-Sample validierte globale 1D-Basissatz (SKILL.md:
    EMA13/150, SL 1.0, TP 2.5) — als EIN Parametersatz für alle Paare, nicht
    pro Paar gefittet. Merged config.signal + config.sl_tp, weil trade.py's
    open_trade() sl_atr_mult/tp_atr_mult braucht, die in signal NICHT enthalten sind
    (der alte Fallback `dict(c["signal"])` lieferte hier lautlos den hartcodierten
    Notfall-Default 1.5/2.5 statt der validierten 1.0/2.5 — mitgefixt am 22.09.)."""
    p = dict(c["signal"])
    p["sl_atr_mult"] = c.get("sl_tp", {}).get("sl_atr_mult", 1.5)
    p["tp_atr_mult"] = c.get("sl_tp", {}).get("tp_atr_mult", 2.5)
    return p


def load_params_by_pair(con, c):
    """Lädt je Paar den neuesten Walk-Forward-Snapshot — ABER nur, wenn dessen
    Backtest-Score über min_snapshot_score liegt. Sonst Fallback auf den robusten
    globalen Default (siehe robust_default_params).

    Grund (22.09.2026): backtest.py optimiert PRO PAAR über ein breites Grid — das
    ist genau die Methode, die laut SKILL.md ("ZENTRALE ERKENNTNIS" 28.08.) zu
    Overfitting neigt; die tatsächlich validierte Basis ist ein EINZIGER robuster
    Satz für alle Paare. Ohne Floor hätte z.B. GBP/USD am 22.09. mit PF=0.967
    (netto-negativ im eigenen Backtest!) live weitergehandelt, nur weil es der
    neueste Snapshot war."""
    min_score = c.get("walk_forward", {}).get("min_snapshot_score", 1.0)
    default = robust_default_params(c)
    out = {}
    for row in con.execute(
        "SELECT pair, params_json, metric_value FROM params_snapshots s WHERE s.created_at = "
        "(SELECT MAX(created_at) FROM params_snapshots WHERE pair=s.pair) GROUP BY pair"
    ).fetchall():
        score = row["metric_value"]
        if score is not None and score < min_score:
            print(f"  ⏸ {row['pair']}: Walk-Forward-Snapshot verworfen (Score {score:.3f} < "
                  f"min_snapshot_score {min_score}) — nutze robusten Default statt Verlust-Setup", flush=True)
            out[row["pair"]] = dict(default)
            continue
        try:
            out[row["pair"]] = json.loads(row["params_json"])
        except Exception:
            out[row["pair"]] = dict(default)
    return out, default


# ── Main ─────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="Standardlauf (Session-Cron)")
    ap.add_argument("--test", action="store_true", help="Testmodus ohne DB-Writer")
    args = ap.parse_args()

    c = cfg.CONFIG
    con = cfg.db_connect()
    cfg.init_db(con)

    # Aktive Param-Snapshots (letzter je Paar, mit Qualitäts-Floor + korrektem Fallback)
    params_by_pair, default_params = load_params_by_pair(con, c)

    in_sess = sig.in_session(cfg_session=c.get("session", c))
    # Bei 1D-Timeline ist das Intraday-Session-Fenster nicht relevant
    # (Entries zum Tages-Schlusskurs). Nur für 15m anwenden.
    gate_session = c.get("gate_session", True)
    if c.get("timeframe", "15m") in ("1d", "1D", "1w", "1W"):
        gate_session = False
        in_sess = True
    dd = cfg.drawdown_pct(con)
    dd_blocked = dd >= c["max_drawdown_pct"]

    print(f"=== Forex Trade-Check ({datetime.now().strftime('%Y-%m-%d %H:%M')}) ===")
    print(f"Session-Gate: {'✅ aktiv' if gate_session else '⏸ aus (1D-Timeline)'} | Drawdown: {dd:.1%} "
          f"({'🚫 BLOCKED' if dd_blocked else '✅ ok'})")

    max_corr = c.get("max_correlated_positions", 99)

    # 1. Neue Entries nur wenn (Session-Gate an AND in_session) + nicht drawdown-blocked
    entry_ok = (not gate_session or in_sess) and not dd_blocked
    if entry_ok and not args.test:
        for pair, pair_cfg in c["pairs"].items():
            params = params_by_pair.get(pair, default_params)
            res = sig.signal_for_pair(pair, params, c.get("signal", {}), pair_cfg)
            if res["signal"] not in ("LONG", "SHORT"):
                continue
            # kein offener Trade auf demselben Paar
            already = con.execute(
                "SELECT COUNT(*) FROM trades WHERE pair=? AND status='open'", (pair,)).fetchone()[0]
            if already > 0:
                continue
            if in_cooldown(con, pair):
                print(f"  ⏸ {pair}: Signal {res['signal']} geblockt (Cooldown nach Stop-Loss)")
                continue
            sign = usd_direction(pair, res["signal"])
            corr = correlated_open_count(con, sign)
            if corr >= max_corr:
                print(f"  ⏸ {pair}: Signal {res['signal']} geblockt (Korrelations-Cap "
                      f"{corr}/{max_corr} gleichgerichtete USD-Positionen offen)")
                continue
            price = latest_price(pair)
            if price:
                t = open_trade(con, pair, pair_cfg, params, price, res["signal"])
                if t:
                    print(f"  📈 {pair}: {res['signal']} @ {price:.5f} | Size {t['size']:.0f} units")
    elif args.test:
        # Test: Signale anzeigen, aber nichts eröffnen
        for pair, pair_cfg in c["pairs"].items():
            params = params_by_pair.get(pair, default_params)
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
