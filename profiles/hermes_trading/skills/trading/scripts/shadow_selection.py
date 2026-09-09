#!/usr/bin/env python3
"""
Shadow Selection — konkurrierende Selektions-Hypothesen als getrennte Bücher.

Warum das existiert
-------------------
Die Auswertung der 84 realen Trades (08.09.2026) ergab: der Erwartungswert ist
negativ (−15 €/Trade, Payoff 0.94), und das Top-Band des eigenen Conviction-
Scores trägt 93 % des Verlusts. Der eigene Varianten-Backtest vom 27.08. hatte
bereits festgestellt, dass weder ein besserer Exit noch ein Crowd-Filter das
rettet — das Problem ist die Selektion.

Der strukturelle Grund: vier heterogene Quellen werden zu EINEM Skalar
(conviction_score) verrechnet und dann ABSOLUT geschwellt. Dieses Design kann
nicht lernen, welche Quelle trägt, weil alle Beiträge verblendet sind. Und die
absolute Schwelle kennt nur zwei Zustände: Flut (Juni: 32 Trades, −1.480 €)
oder Hunger (08.09.: null Kandidaten).

Dieses Skript ändert daran NICHTS am Live-System. Es lässt konkurrierende
Selektions-Regeln täglich parallel laufen, schreibt ihre Kandidaten mit den
Levels mit, die gegolten hätten, und bepreist sie vorwärts — jede Hypothese mit
eigenem P&L. Nach genug Trades ist beantwortbar, welche Regel trägt.

Es trifft KEINE Entscheidung, ändert weder Config noch `positions`.

Hypothesen
----------
  live_baseline  Was der Live-Entry heute auswählen würde. Referenz — ohne sie
                 sind die anderen Zahlen bedeutungslos.
  h1_momentum    Cross-sectional: täglich die Top-N des Universums nach
                 factor_scores.composite_score. Kein absoluter Schwellenwert →
                 hungert nie, flutet nie. (Der Momentum-Faktor darin war bis
                 08.09. defekt, siehe factor_ranker._compute_momentum_score.)
  h2_pead        Post-Earnings-Announcement-Drift als Primärquelle statt als
                 +2 %-Aufschlag auf die Conviction.
  h3_crowding    Sentiment INVERTIERT: unter den preisbestätigten Kandidaten
                 die mit der NIEDRIGSTEN Conviction. Die einzige Lesart, die die
                 84 Trades direkt stützen (Band 1.00 = −1.168 €).

Aufruf
------
    python3 shadow_selection.py            # auswählen + reife Einträge bewerten
    python3 shadow_selection.py --select    # nur auswählen
    python3 shadow_selection.py --evaluate  # nur bewerten
    python3 shadow_selection.py --report    # nur Bericht
"""
import argparse
import os
import sys
from datetime import datetime, timedelta

_TRADING_ROOT = "/root/.hermes/profiles/hermes_trading/skills/trading"
for _p in (_TRADING_ROOT, os.path.join(_TRADING_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import env_loader  # noqa: F401  (side-effect: laedt .env)

from config import db_connect, get_asset_type, get_exit_config, get_sector_regime, sector_regime_key
from utils import get_logger, get_price_data_cached, prefetch_prices

log = get_logger("shadow_selection")

# Wie viele Kandidaten jede Hypothese pro Tag benennen darf. Bewusst gleich für
# alle: sonst vergleicht man Trefferquoten über unterschiedlich selektive Regeln
# und misst die Selektivität statt der Signalgüte.
TOP_N = 5

# Horizont der Vorwärtsbepreisung, konsistent zu crabel_shadow_eval.
HORIZON_DAYS = 21

HYPOTHESES = ("live_baseline", "h1_momentum", "h2_pead", "h3_crowding")


# ── Schema ──────────────────────────────────────────────────────────────────

def ensure_schema(con):
    """Idempotent, gleiches Muster wie blocked_entries."""
    con.executescript("""
        CREATE TABLE IF NOT EXISTS shadow_selection (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            hypothesis      TEXT NOT NULL,
            ticker          TEXT NOT NULL,
            name            TEXT,
            direction       TEXT NOT NULL,
            select_date     TEXT NOT NULL,
            selected_at     TEXT,
            rank_in_set     INTEGER,
            score           REAL,
            rationale       TEXT,
            price_at_select REAL,
            would_entry     REAL,
            would_sl        REAL,
            would_tp        REAL,
            atr_at_select   REAL,
            asset_type      TEXT,
            eval_status     TEXT DEFAULT 'pending',
            eval_date       TEXT,
            outcome         TEXT,
            days_to_outcome INTEGER,
            exit_price_sim  REAL,
            pnl_pct_sim     REAL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_shadow_dedup
            ON shadow_selection(hypothesis, ticker, direction, select_date);
        CREATE INDEX IF NOT EXISTS idx_shadow_status
            ON shadow_selection(eval_status, select_date);
    """)
    con.commit()


# ── Auswahl ─────────────────────────────────────────────────────────────────

def _levels(con, ticker, direction, sector):
    """Kurs, ATR und die Levels, die beim Entry gegolten hätten.

    Bewusst dieselbe Quelle wie der Live-Entry: get_exit_config über den
    Sektor-Regime-Schlüssel. Sonst wäre der Vergleich zwischen Schattenbuch
    und Live-System durch unterschiedliche Exit-Parameter verzerrt.
    """
    close, atr, _df = get_price_data_cached(ticker)
    if not close or not atr:
        return None
    asset_type = get_asset_type(sector)
    regime = get_sector_regime(sector_regime_key(sector, None), con)
    ec = get_exit_config(asset_type=asset_type, regime=regime)
    if direction == "LONG":
        sl = close - ec["sl"] * atr
        tp = close + ec["tp"] * atr
    else:
        sl = close + ec["sl"] * atr
        tp = close - ec["tp"] * atr
    return {"price": close, "atr": atr, "asset_type": asset_type,
            "entry": close, "sl": sl, "tp": tp}


def _sector_of(con, ticker):
    r = con.execute("SELECT sector FROM companies WHERE ticker=?", (ticker,)).fetchone()
    return (r["sector"] if r else None) or "Other"


def record(con, hypothesis, today, picks):
    """Schreibt eine Kandidatenliste. INSERT OR IGNORE über den UNIQUE-Index,
    damit ein zweiter Lauf am selben Tag nichts verdoppelt."""
    written = skipped = 0
    tickers = [p["ticker"] for p in picks]
    if tickers:
        try:
            prefetch_prices(tickers)
        except Exception as e:
            log.warning("prefetch fehlgeschlagen: %s", e)

    for rank, p in enumerate(picks, 1):
        sector = _sector_of(con, p["ticker"])
        lv = _levels(con, p["ticker"], p["direction"], sector)
        if not lv:
            skipped += 1
            continue
        con.execute("""
            INSERT OR IGNORE INTO shadow_selection
            (hypothesis, ticker, name, direction, select_date, selected_at,
             rank_in_set, score, rationale, price_at_select, would_entry,
             would_sl, would_tp, atr_at_select, asset_type)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (hypothesis, p["ticker"], p.get("name"), p["direction"], today,
              datetime.now().strftime("%Y-%m-%d %H:%M"), rank,
              p.get("score"), p.get("rationale"),
              round(lv["price"], 4), round(lv["entry"], 4), round(lv["sl"], 4),
              round(lv["tp"], 4), round(lv["atr"], 4), lv["asset_type"]))
        written += 1
    con.commit()
    print(f"  {hypothesis:14} {written} Kandidaten"
          + (f", {skipped} ohne Kursdaten" if skipped else ""), flush=True)
    return written


def select_live_baseline(con, cfg):
    """Referenz: was der Live-Entry heute selektieren würde.

    Bewusst dieselbe Klausel wie signal_manager, inklusive der quellenabhängigen
    Mindest-Mentions. Ohne diese Referenz sagt die Trefferquote der anderen
    Hypothesen nichts aus.
    """
    from signal_manager import MENTIONS_CLAUSE, _mentions_params
    rows = con.execute(f"""
        SELECT w.ticker, w.name, w.conviction_score conv, w.tech_score ts
        FROM watchlist w
        WHERE w.status='watching' AND w.ticker IS NOT NULL
          AND w.conviction_score >= ?
          {MENTIONS_CLAUSE}
          AND w.tech_score >= ? AND w.tech_direction='LONG'
        ORDER BY w.conviction_score DESC, w.tech_score DESC
        LIMIT ?
    """, (cfg.get("min_conviction", 0.60),
          *_mentions_params(cfg.get("min_mentions", 2)),
          0.70, TOP_N)).fetchall()
    return [{"ticker": r["ticker"], "name": r["name"], "direction": "LONG",
             "score": r["conv"],
             "rationale": f"live: conv={r['conv']:.2f} tech={r['ts']}"} for r in rows]


def select_h1_momentum(con):
    """Cross-sectional: Top-N des jüngsten factor_scores-Laufs.

    Kein absoluter Schwellenwert — es wird immer die relativ stärkste Gruppe
    genommen. Genau das verhindert sowohl Starvation als auch Flut.
    Zusätzlich wird ein Mindest-Momentum-Perzentil verlangt, damit das Composite
    nicht allein über Quality/Value trägt (der Momentum-Faktor war bis 08.09.
    defekt und lieferte für alle Ticker 1.0).
    """
    last = con.execute("SELECT MAX(date) d FROM factor_scores").fetchone()["d"]
    if not last:
        print("  h1_momentum    factor_scores leer – übersprungen", flush=True)
        return []
    age = (datetime.now().date() - datetime.strptime(last, "%Y-%m-%d").date()).days
    if age > 7:
        print(f"  h1_momentum    factor_scores {age} Tage alt ({last}) – "
              f"übersprungen (factor_ranker läuft nicht)", flush=True)
        return []
    rows = con.execute("""
        SELECT ticker, composite_score comp, momentum_score mom, rank_in_universe rk
        FROM factor_scores WHERE date=? AND momentum_score >= 0.60
        ORDER BY composite_score DESC LIMIT ?
    """, (last, TOP_N)).fetchall()
    return [{"ticker": r["ticker"], "name": r["ticker"], "direction": "LONG",
             "score": r["comp"],
             "rationale": f"comp={r['comp']:.1f} mom-pct={r['mom']:.2f} rank={r['rk']}"}
            for r in rows]


def select_h2_pead(con):
    """PEAD als Primärquelle statt als Conviction-Aufschlag.

    Achtung bei der Interpretation: im Live-Cache haben nur 9 von 1.038
    Einträgen überhaupt einen Boost ≠ 0 (0.9 %). Diese Hypothese wird deshalb
    voraussichtlich sehr wenige Kandidaten liefern — das IST das Messergebnis:
    entweder die Surprise-Schwelle ist zu eng oder die Datenquelle liefert zu
    selten. Beides ist wichtiger zu wissen, als es zu erraten.
    """
    rows = con.execute("""
        SELECT ticker, boost_long, boost_short FROM pead_cache
        WHERE (boost_long > 0 OR boost_short > 0)
          AND fetched_at >= date('now', '-5 day')
        ORDER BY MAX(boost_long, boost_short) DESC LIMIT ?
    """, (TOP_N,)).fetchall()
    picks = []
    for r in rows:
        long_side = (r["boost_long"] or 0) >= (r["boost_short"] or 0)
        picks.append({
            "ticker": r["ticker"], "name": r["ticker"],
            "direction": "LONG" if long_side else "SHORT",
            "score": max(r["boost_long"] or 0, r["boost_short"] or 0),
            "rationale": f"pead long={r['boost_long']} short={r['boost_short']}",
        })
    return picks


# H3-Band: "leise, aber vorhanden".
#
# Wichtig ist die Untergrenze. Rankt man einfach aufsteigend nach Conviction,
# gewinnen Einträge mit conv≈0.12 — das ist kein leises Signal, sondern gar
# keines (eine einzelne neutrale Mention). Getestet wird aber die These
# "Aufmerksamkeit ist gegenläufig", und die setzt voraus, dass überhaupt
# Aufmerksamkeit da ist. Deshalb ein BAND statt eines Minimums.
H3_CONV_MIN = 0.30   # darunter: kein Signal, nicht "leise"
H3_CONV_MAX = 0.65   # darüber: beginnt das Band, das live gekauft wird


def select_h3_crowding(con):
    """Sentiment invertiert: unter den preisbestätigten Kandidaten die LEISESTEN.

    Gate bleibt das Preis-Momentum (weekly_trend + tech_direction, wie live).
    Gerankt wird danach AUFSTEIGEND nach Conviction — die Gegenthese zum
    Live-System, das absteigend rankt.

    Falsifizierbar: schneidet dieses Buch nach 30 Trades nicht besser ab als
    live_baseline, war die Inversion ein Artefakt der 84 historischen Trades.
    """
    rows = con.execute("""
        SELECT ticker, name, conviction_score conv, tech_score ts
        FROM watchlist
        WHERE status='watching' AND ticker IS NOT NULL
          AND weekly_trend='bullish' AND tech_direction='LONG'
          AND tech_score BETWEEN 0.70 AND 1.0
          AND conviction_score BETWEEN ? AND ?
        ORDER BY conviction_score ASC, tech_score DESC
        LIMIT ?
    """, (H3_CONV_MIN, H3_CONV_MAX, TOP_N)).fetchall()
    return [{"ticker": r["ticker"], "name": r["name"], "direction": "LONG",
             "score": r["conv"],
             "rationale": f"invers: conv={r['conv']:.2f} im Band "
                          f"{H3_CONV_MIN}-{H3_CONV_MAX} tech={r['ts']}"}
            for r in rows]


# ── Bewertung ───────────────────────────────────────────────────────────────

def evaluate(con, horizon=HORIZON_DAYS):
    """Bepreist reife Kandidaten vorwärts — dieselbe Simulation wie
    crabel_shadow_eval (Import statt Nachbau, damit beide Bücher identisch
    bewertet werden und der Vergleich gültig bleibt)."""
    import yfinance as yf
    from crabel_shadow_eval import simulate_forward, load_cfg, _get_regime

    cfg = load_cfg()
    # _get_regime liefert (regime, vix) — das globale Regime dient nur als
    # Fallback. Bewertet wird mit dem SEKTOR-Regime des jeweiligen Tickers,
    # weil `_levels()` die Entry-Levels ebenfalls damit gebildet hat. Zwei
    # verschiedene Regime fuer Level und Simulation wuerden das Ergebnis
    # verzerren, ohne dass es auffiele.
    global_regime, _vix = _get_regime(con)
    cutoff = (datetime.now() - timedelta(days=horizon)).strftime("%Y-%m-%d")
    rows = con.execute("""
        SELECT * FROM shadow_selection
        WHERE eval_status='pending' AND select_date <= ?
        ORDER BY select_date ASC
    """, (cutoff,)).fetchall()

    if not rows:
        pend = con.execute(
            "SELECT COUNT(*) FROM shadow_selection WHERE eval_status='pending'"
        ).fetchone()[0]
        print(f"  Keine reifen Einträge. {pend} warten auf den Horizont.", flush=True)
        return 0

    done = no_data = 0
    for row in rows:
        try:
            start = (datetime.strptime(row["select_date"], "%Y-%m-%d")
                     + timedelta(days=1)).strftime("%Y-%m-%d")
            end = (datetime.strptime(row["select_date"], "%Y-%m-%d")
                   + timedelta(days=horizon + 1)).strftime("%Y-%m-%d")
            df = yf.download(row["ticker"], start=start, end=end, interval="1d",
                             progress=False, auto_adjust=True).dropna()
            if df.empty or len(df) < 3:
                con.execute("UPDATE shadow_selection SET eval_status='no_data', "
                            "eval_date=? WHERE id=?",
                            (datetime.now().strftime("%Y-%m-%d"), row["id"]))
                no_data += 1
                continue

            sector = _sector_of(con, row["ticker"])
            regime = get_sector_regime(sector_regime_key(sector, None), con)                      or global_regime
            outcome, exit_price, days = simulate_forward(
                df, row["would_entry"], row["would_sl"], row["would_tp"],
                row["atr_at_select"], row["direction"], row["asset_type"],
                cfg, regime=regime)

            entry = row["would_entry"]
            pnl_pct = ((exit_price - entry) / entry * 100 if row["direction"] == "LONG"
                       else (entry - exit_price) / entry * 100)
            con.execute("""
                UPDATE shadow_selection SET eval_status='evaluated', eval_date=?,
                    outcome=?, days_to_outcome=?, exit_price_sim=?, pnl_pct_sim=?
                WHERE id=?
            """, (datetime.now().strftime("%Y-%m-%d"), outcome, days,
                  round(exit_price, 4), round(pnl_pct, 2), row["id"]))
            done += 1
        except Exception as e:
            log.warning("Shadow-Bewertung fehlgeschlagen (%s): %s", row["ticker"], e)
    con.commit()
    print(f"  {done} bewertet, {no_data} ohne Kursdaten", flush=True)
    return done


# ── Bericht ─────────────────────────────────────────────────────────────────

def report(con):
    print("\n📊 Schattenbücher — Stand", datetime.now().strftime("%Y-%m-%d"), flush=True)
    print(f"  {'Hypothese':14} {'ausgew.':>8} {'bewertet':>9} {'WR':>6} "
          f"{'Ø %':>8} {'Σ %':>8}  Bewertung", flush=True)
    base_avg = None
    for h in HYPOTHESES:
        tot = con.execute("SELECT COUNT(*) FROM shadow_selection WHERE hypothesis=?",
                          (h,)).fetchone()[0]
        r = con.execute("""
            SELECT COUNT(*) n, SUM(pnl_pct_sim > 0) w,
                   AVG(pnl_pct_sim) avg, SUM(pnl_pct_sim) tot
            FROM shadow_selection WHERE hypothesis=? AND eval_status='evaluated'
        """, (h,)).fetchone()
        n = r["n"] or 0
        if not n:
            print(f"  {h:14} {tot:>8} {0:>9} {'–':>6} {'–':>8} {'–':>8}  "
                  f"noch keine Daten", flush=True)
            continue
        wr = (r["w"] or 0) / n * 100
        avg = r["avg"] or 0
        if h == "live_baseline":
            base_avg = avg
        verdict = "N<30 – nicht belastbar" if n < 30 else (
            "besser als Referenz" if base_avg is not None and avg > base_avg
            else "nicht besser als Referenz")
        print(f"  {h:14} {tot:>8} {n:>9} {wr:>5.0f}% {avg:>+7.2f}% "
              f"{r['tot']:>+7.1f}%  {verdict}", flush=True)
    print("\n  Hinweis: die Bücher entscheiden nichts. Erst ab N≈30 pro Hypothese\n"
          "  ist der Vergleich mit live_baseline aussagekräftig.", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--select", action="store_true", help="nur auswählen")
    ap.add_argument("--evaluate", action="store_true", help="nur bewerten")
    ap.add_argument("--report", action="store_true", help="nur Bericht")
    args = ap.parse_args()
    do_all = not (args.select or args.evaluate or args.report)

    con = db_connect()
    try:
        ensure_schema(con)
        today = datetime.now().strftime("%Y-%m-%d")

        if do_all or args.select:
            import json
            from config import STRATEGY_CONFIG_PATH
            try:
                cfg = json.load(open(STRATEGY_CONFIG_PATH))
            except Exception:
                cfg = {}
            print(f"🔀 Auswahl für {today} (Top {TOP_N} je Hypothese)", flush=True)
            record(con, "live_baseline", today, select_live_baseline(con, cfg))
            record(con, "h1_momentum",   today, select_h1_momentum(con))
            record(con, "h2_pead",       today, select_h2_pead(con))
            record(con, "h3_crowding",   today, select_h3_crowding(con))

        if do_all or args.evaluate:
            print(f"\n🔍 Vorwärtsbepreisung (Horizont {HORIZON_DAYS} Tage)", flush=True)
            evaluate(con)

        if do_all or args.report:
            report(con)
    finally:
        con.close()


if __name__ == "__main__":
    main()
