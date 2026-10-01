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
  h_jev          Jev (TypeSafe) schaetzt fuer JEDEN preisbestaetigten Kandidaten die
                 Wahrscheinlichkeit, dass das Take-Profit vor dem Stop-Loss erreicht wird.
                 Grundmenge = ganzer Topf, nicht Top-N (der Rangvergleich braucht ihn).
                 Nur aktiv mit JEV_SHADOW=on (Default aus), keinerlei Einfluss auf den Handel.
  h_tv_screener  Dieselbe Screener-Logik wie screener_source (Stage 2), aber Stage 1
                 ueber den TradingView-Scanner: ganzer US-Markt (~4.200 Aktien) statt
                 des festen 546er-Universums. Frage: bringt die Breite bessere
                 Kandidaten? Fail-open — faellt der Scanner aus, entfaellt nur diese Spur.

Aufruf
------
    python3 shadow_selection.py            # auswählen + reife Einträge bewerten
    python3 shadow_selection.py --select    # nur auswählen
    python3 shadow_selection.py --evaluate  # nur bewerten
    python3 shadow_selection.py --report    # nur Bericht
    python3 shadow_selection.py --jev-dry-run  # h_jev: Zustaende + Kosten zeigen, nichts schreiben
    python3 shadow_selection.py --tv-dry-run   # h_tv_screener: Auswahl zeigen, nichts schreiben
"""
import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

_TRADING_ROOT = "/root/.hermes/profiles/hermes_trading/skills/trading"
for _p in (_TRADING_ROOT, os.path.join(_TRADING_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import env_loader  # noqa: F401  (side-effect: laedt .env)

from config import db_connect, get_asset_type, get_exit_config, get_sector_regime, sector_regime_key
from utils import get_logger, get_price_data_cached, prefetch_prices
from exit_rules import YT_FADE_MODE, simulate_fade_close

log = get_logger("shadow_selection")

# Wie viele Kandidaten jede Hypothese pro Tag benennen darf. Bewusst gleich für
# alle: sonst vergleicht man Trefferquoten über unterschiedlich selektive Regeln
# und misst die Selektivität statt der Signalgüte.
TOP_N = 5

# Horizont der Vorwärtsbepreisung, konsistent zu crabel_shadow_eval.
HORIZON_DAYS = 21

HYPOTHESES = ("live_baseline", "live_baseline_v1", "h1_momentum", "h2_pead",
              "h3_crowding", "h_jev", "h_tv_screener")

# Ab diesem Auswahldatum shortet der Live-Entry YouTube-LONG-Kandidaten
# (YT-Fade, exit_mode yt_fade_40d). live_baseline bildet das ab; die Zeilen
# davor wurden unter der alten Live-Logik (alles LONG) ausgewaehlt und heissen
# jetzt live_baseline_v1. Als Referenz fuer die Vorab-Kriterien zaehlen BEIDE —
# jeweils die Live-Logik, die am Auswahltag galt.
FADE_SINCE = "2026-09-29"
BASELINES = ("live_baseline", "live_baseline_v1")

# ── Vorab festgelegte Erfolgskriterien ──────────────────────────────────────
# Festgelegt am 28.09.2026, BEVOR der erste Eintrag bewertet war (erste Reife
# 29.09.). Wer die Latte erst nach den Zahlen legt, sucht sich den Gewinner
# aus. Aenderungen nur mit neuem Datum hier UND Neustart der Zaehlung.
# Eine Hypothese gilt erst als Live-Kandidat, wenn ALLE Punkte erfuellt sind —
# gemessen mit dem Live-Exit, netto:
#   1. mindestens MIN_INDEPENDENT unabhaengige Trades
#   2. Ø besser als live_baseline im selben Zeitraum
#   3. auch mit COST_STRESS_MULT-fachen Kosten Ø > 0
#   4. ohne die DROP_TOP_K besten Trades Summe > 0
CRITERIA_FIXED_ON = "2026-09-28"
MIN_INDEPENDENT = 30
COST_STRESS_MULT = 2.0
DROP_TOP_K = 3
# Ein Titel zaehlt pro Hypothese hoechstens einmal je INDEPENDENCE_DAYS. h1
# waehlt taeglich dieselben Top-Titel (28.09.: 25 Zeilen, 6 Titel) — ohne
# Dedup waere N=30 nach einer Woche erreicht, ohne dass etwas bewiesen ist.
INDEPENDENCE_DAYS = 28
# Signal-Horizont-Exit: nur Anfangs-Stop, dann HOLD_BARS Handelstage halten.
# Momentum und PEAD wirken ueber Wochen; der Live-Exit (Donchian-Trail +
# Time-Stop 5d) kann ein tragfaehiges Signal abwuergen. Der Abstand zwischen
# beiden Exits zeigt, ob die Selektion oder die Haltedauer das Problem ist.
HOLD_BARS = 20


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
    # 28.09.2026: Exit-Bewertung netto (siehe evaluate_exits)
    cols = {r[1] for r in con.execute("PRAGMA table_info(shadow_selection)")}
    for col, typ in (("pnl_live_net", "REAL"), ("pnl_hold_net", "REAL"),
                     ("cost_pct", "REAL"), ("exit_eval_date", "TEXT"),
                     ("exit_mode", "TEXT")):
        if col not in cols:
            con.execute(f"ALTER TABLE shadow_selection ADD COLUMN {col} {typ}")
    # Idempotent: Baseline-Zeilen vor der Fade-Umstellung umbenennen (s. FADE_SINCE)
    con.execute("UPDATE shadow_selection SET hypothesis='live_baseline_v1' "
                "WHERE hypothesis='live_baseline' AND select_date < ?", (FADE_SINCE,))
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
        # h_tv_screener: Titel ausserhalb von companies bringen den yfinance-Sektor mit
        sector = p.get("sector") or _sector_of(con, p["ticker"])
        lv = _levels(con, p["ticker"], p["direction"], sector)
        if not lv:
            skipped += 1
            continue
        if p.get("exit_mode") == YT_FADE_MODE:
            # wie signal_manager: Notfallstop statt ATR-Stop, TP nur Anzeige
            lv["sl"] = lv["entry"] * (1 + p.get("stop_pct", 0.40))
            lv["tp"] = lv["entry"] * 0.5
        con.execute("""
            INSERT OR IGNORE INTO shadow_selection
            (hypothesis, ticker, name, direction, select_date, selected_at,
             rank_in_set, score, rationale, price_at_select, would_entry,
             would_sl, would_tp, atr_at_select, asset_type, exit_mode)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (hypothesis, p["ticker"], p.get("name"), p["direction"], today,
              datetime.now().strftime("%Y-%m-%d %H:%M"), rank,
              p.get("score"), p.get("rationale"),
              round(lv["price"], 4), round(lv["entry"], 4), round(lv["sl"], 4),
              round(lv["tp"], 4), round(lv["atr"], 4), lv["asset_type"],
              p.get("exit_mode")))
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
    from signal_manager import MENTIONS_CLAUSE, _mentions_params, _derive_signal_source
    rows = con.execute(f"""
        SELECT w.ticker, w.name, w.conviction_score conv, w.tech_score ts, w.channels
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
    fade_on = bool(cfg.get("yt_fade_enabled"))
    picks = []
    for r in rows:
        try:
            channels = json.loads(r["channels"] or "[]")
        except Exception:
            channels = []
        fade = fade_on and _derive_signal_source(channels) == "youtube"
        picks.append({
            "ticker": r["ticker"], "name": r["name"],
            "direction": "SHORT" if fade else "LONG",
            "exit_mode": YT_FADE_MODE if fade else None,
            "stop_pct": cfg.get("yt_fade_stop_pct", 0.40),
            "score": r["conv"],
            "rationale": (f"live: conv={r['conv']:.2f} tech={r['ts']}"
                          + (" | YT-Fade" if fade else ""))})
    return picks


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


# ── h_jev: Jev-Wahrscheinlichkeit als Kandidaten-Score (23.09.2026) ───────────
# Frage: ordnet P(Take-Profit vor Stop-Loss) von Jev die spaeteren simulierten
# Ergebnisse besser als conviction_score und tech_score? Grundmenge ist der GANZE
# Topf preisbestaetigter LONG-Kandidaten, weil Kennzahl A (Rangkorrelation) die
# Scores der nicht ausgewaehlten Kandidaten braucht. rank_in_set = Rang nach Jev,
# die Jev-Top-5 sind also rank_in_set <= 5.
JEV_POOL_MIN_TECH = 0.70
JEV_MAX_CANDIDATES = 150     # Kostenbremse, falls der Topf unerwartet waechst
JEV_WORKERS = 8
JEV_LOOKBACK_DAYS = 30
JEV_MAX_REASONS = 3
JEV_BUDGET_ROLE = "jev_shadow"
JEV_TASK = (
    "A stock is a candidate for a long swing trade of about 3 weeks. It is described as of today: "
    "how often and how positively the company was mentioned by German finance YouTube channels "
    "or automated stock screeners (the channel names are listed), a technical score, the weekly "
    "trend, the sector regime and the distance of stop-loss and take-profit measured in ATR "
    "(average daily range). Repeated hits from one screener are not independent opinions. "
    "Judge only from this description.")
JEV_QUESTIONS = {
    "tp_first": {"type": "noul",
                 "instructions": "The take-profit level is reached before the stop-loss level within about 3 weeks"},
}


def _jev_enabled():
    return os.environ.get("JEV_SHADOW", "").strip().lower() == "on"


def _tier(x, lo, hi):
    x = x or 0.0
    return "low" if x < lo else ("medium" if x < hi else "high")


def _mention_names(con, ticker, name):
    names = {str(ticker).lower(), (name or "").lower()}
    try:
        for r in con.execute("SELECT alias FROM company_aliases WHERE ticker=?", (ticker,)):
            names.add((r["alias"] or "").lower())
    except Exception:
        pass
    names.discard("")
    return sorted(names)


def _regime_label(con, sector):
    try:
        return get_sector_regime(sector_regime_key(sector, None), con) or "unknown"
    except Exception:
        return "unknown"


def build_jev_state(con, cand, lv, sector, as_of):
    """Zustand in Worten und Stufen, ohne rohe Kurse. Nur Nennungen bis einschliesslich as_of."""
    names = _mention_names(con, cand["ticker"], cand["name"])
    q = ",".join("?" * len(names))
    rows = con.execute(f"""
        SELECT channel, sentiment, reason, mention_date FROM watchlist_mentions
        WHERE lower(name) IN ({q}) AND mention_date <= ?
          AND mention_date >= date(?, '-{JEV_LOOKBACK_DAYS} days')
        ORDER BY mention_date DESC, id DESC
    """, (*names, as_of, as_of)).fetchall()
    ref = datetime.strptime(as_of, "%Y-%m-%d").date()
    reasons, seen = [], set()
    for r in rows:
        note = (r["reason"] or "")[:200]
        if note and note not in seen and len(reasons) < JEV_MAX_REASONS:
            seen.add(note)      # Screener wiederholen denselben Text taeglich
            days = (ref - datetime.strptime(r["mention_date"][:10], "%Y-%m-%d").date()).days
            reasons.append({"days_ago": days, "channel_sentiment": r["sentiment"],
                            "analyst_note": note})
    sent = [r["sentiment"] for r in rows]
    atr = lv["atr"]
    return {
        "task": JEV_TASK, "company": cand["name"], "direction": "LONG",
        "mentions_last_30d": len(rows),
        "distinct_channels": len({r["channel"] for r in rows}),
        "channels": sorted({r["channel"] for r in rows if r["channel"]})[:5],
        "bullish_mentions": sent.count("bullish"), "bearish_mentions": sent.count("bearish"),
        "neutral_mentions": sent.count("neutral"),
        "conviction": _tier(cand["conv"], 0.4, 0.6), "technical_score": _tier(cand["ts"], 0.8, 0.9),
        "weekly_trend": cand["wt"] or "unknown", "sector_regime": _regime_label(con, sector),
        "daily_volatility": _tier(atr / lv["price"], 0.015, 0.03).replace("medium", "normal"),
        "stop_distance_atr": round((lv["entry"] - lv["sl"]) / atr, 1),
        "target_distance_atr": round((lv["tp"] - lv["entry"]) / atr, 1),
        "latest_analyst_notes": reasons,
    }


def jev_states(con, as_of=None):
    """Baut fuer den ganzen Topf den Jev-Zustand (Haupt-Thread, DB-Zugriff). Kandidaten ohne Kursdaten entfallen."""
    as_of = as_of or datetime.now().strftime("%Y-%m-%d")
    pool = con.execute("""
        SELECT ticker, name, conviction_score conv, tech_score ts, weekly_trend wt
        FROM watchlist
        WHERE status='watching' AND ticker IS NOT NULL AND tech_direction='LONG'
          AND tech_score >= ?
        ORDER BY tech_score DESC, conviction_score DESC LIMIT ?
    """, (JEV_POOL_MIN_TECH, JEV_MAX_CANDIDATES)).fetchall()
    cands = [dict(r) for r in pool]
    if cands:
        try:
            prefetch_prices([c["ticker"] for c in cands])
        except Exception as e:
            log.warning("prefetch fehlgeschlagen: %s", e)
    items = []
    for c in cands:
        sector = _sector_of(con, c["ticker"])
        lv = _levels(con, c["ticker"], "LONG", sector)
        if not lv:
            continue
        items.append({**c, "state": build_jev_state(con, c, lv, sector, as_of)})
    return items


def _ask_jev(items):
    """Parallele HTTP-Aufrufe (kein DB-Zugriff in den Threads). -> Liste (p, usage, model) oder None je Kandidat."""
    from thematic.lib import jev_client as jc

    def one(item):
        resp = jc.decide(item["state"], JEV_QUESTIONS, timeout=60)
        if not resp:
            return None
        p = jc.noul_of(resp, "tp_first")
        return None if p is None else (p, jc.usage_of(resp), jc.model_of(resp) or "?")

    with ThreadPoolExecutor(max_workers=JEV_WORKERS, thread_name_prefix="jev-shadow") as pool:
        return list(pool.map(one, items))


def select_h_jev(con, as_of=None):
    """Jev-Score fuer den ganzen Topf, absteigend sortiert. Ohne JEV_SHADOW=on: [] und kein Aufruf."""
    if not _jev_enabled():
        return []
    items = jev_states(con, as_of)
    if not items:
        return []
    from thematic.lib import jev_client as jc
    answers = _ask_jev(items)
    ok = [(it, a) for it, a in zip(items, answers) if a]
    # jev-pin-20260925: Version je Antwort mitloggen; Abweichung vom festgeschriebenen Modell laut melden
    models = sorted({a[2] for _it, a in ok})
    if ok and models != [jc.JEV_MODEL]:
        print(f"  ⚠ h_jev: Antwortmodell(e) {models} statt festgeschrieben {jc.JEV_MODEL}", flush=True)
    failed = len(items) - len(ok)
    t_in = sum(a[1][0] for _it, a in ok)
    t_out = sum(a[1][1] for _it, a in ok)
    cost = sum(a[1][2] for _it, a in ok)
    print(f"  h_jev          {len(ok)}/{len(items)} Jev-Antworten"
          + (f", {failed} fehlgeschlagen" if failed else "")
          + f", {t_in} Tokens, ${cost:.4f}", flush=True)
    if t_in or t_out:
        try:
            from roles import budget as _role_budget
            _role_budget.record_spend(con, JEV_BUDGET_ROLE, datetime.now().strftime("%Y-%m-%d"),
                                      t_in, t_out, models[0] if len(models) == 1 else jc.JEV_MODEL)
        except Exception as e:
            print(f"  ⚠ Budget-Buchung ({JEV_BUDGET_ROLE}) fehlgeschlagen: {e}", flush=True)
    picks = [{"ticker": it["ticker"], "name": it["name"], "direction": "LONG",
              "score": round(a[0], 4),
              "rationale": (f"jev={a[0]:.2f} conv={it['conv']:.2f} tech={it['ts']:.2f} "
                            f"mentions30={it['state']['mentions_last_30d']} model={a[2]}")}
             for it, a in ok]
    picks.sort(key=lambda p: -p["score"])
    return picks


def jev_dry_run(con, sample=3):
    """Zeigt Zustaende und Kosten, ruft Jev nur fuer wenige Beispiele auf, schreibt und bucht NICHTS."""
    items = jev_states(con)
    if not items:
        print("  h_jev: kein Kandidat im Topf")
        return
    q_tok = len(json.dumps(JEV_QUESTIONS, ensure_ascii=False)) // 3
    tok = sum(len(json.dumps(it["state"], ensure_ascii=False)) // 3 + q_tok for it in items)
    print(f"h_jev Trockenlauf: {len(items)} Kandidaten im Topf (tech >= {JEV_POOL_MIN_TECH}, LONG, watching)")
    print(f"  geschaetzte Eingabetokens/Tag ~{tok} -> ~${tok * 0.042 / 1e6:.4f}/Tag "
          f"(~${tok * 0.042 / 1e6 * 22:.3f}/Monat bei 22 Laeufen)")
    for it in items[:2]:
        print(f"\n  Beispielzustand {it['ticker']}:\n" + json.dumps(it["state"], ensure_ascii=False, indent=2))
    print(f"\n  Jev-Antworten fuer {min(sample, len(items))} Beispiele (nichts wird geschrieben):")
    for it, a in zip(items[:sample], _ask_jev(items[:sample])):
        print(f"    {it['ticker']:10} conv={it['conv']:.2f} tech={it['ts']:.2f} -> P(TP zuerst) = "
              + (f"{a[0]:.2f}" if a else "keine Antwort"))


# ── Bewertung ───────────────────────────────────────────────────────────────

# ── h_tv_screener: TradingView-Scanner als Stage 1 (29.09.2026) ────────────
# Stage 1 = EIN Aufruf an den TradingView-Scanner (Paket tradingview-screener,
# inoffizieller Endpoint, kein Login), serverseitig grob vorgefiltert. Die
# Schwellen sind bewusst lockerer als die von Stage 2 (TradingView rechnet das
# 52W-Hoch intraday, Perf.3M ist nur ~63 Handelstage): Stage 1 soll nichts
# verlieren, was Stage 2 nehmen wuerde. Stage 2 = screener_source.screen_stage2,
# unveraendert. Pools zusammen = MAX_STAGE2_CANDIDATES (400er Kurs-Cache).
TV_EXCHANGES = ["NASDAQ", "NYSE", "AMEX"]
TV_MIN_PRICE = 2.0
TV_MIN_TURNOVER_USD = 600_000      # ~ screener_source.MIN_STAGE1_TURNOVER_EUR
TV_LONG_MAX_BELOW_HIGH = 0.20      # Stage 2: 15 % unter 52W-Hoch (Schlusskurs)
TV_SHORT_ABOVE_LOW = (0.03, 0.20)  # Stage 2: 5-15 % ueber 52W-Tief
TV_REL_SLACK = 5.0                 # Prozentpunkte Spielraum auf die relative Staerke
TV_MAX_LONG_POOL = 300
TV_MAX_SHORT_POOL = 100
TV_CHUNK = 50
TV_FIELDS = ["name", "close", "average_volume_30d_calc", "price_52_week_high",
             "price_52_week_low", "Perf.3M"]


def tv_to_yf(symbol):
    """TradingView-Kuerzel -> yfinance ('BRK.B' -> 'BRK-B')."""
    return str(symbol).strip().upper().replace(".", "-").replace("/", "-")


def tv_fetch_universe():
    """Alle primaer gelisteten US-Stammaktien ab TV_MIN_PRICE (Netzwerk)."""
    from tradingview_screener import Query, col
    _n, df = (Query().set_markets("america")
              .select(*TV_FIELDS)
              .where(col("type") == "stock", col("subtype") == "common",
                     col("exchange").isin(TV_EXCHANGES), col("is_primary") == True,  # noqa: E712
                     col("close") >= TV_MIN_PRICE)
              .order_by("market_cap_basic", ascending=False)
              .limit(6000)
              .get_scanner_data())
    return df.to_dict("records")


def tv_stage1(rows, bench_ret):
    """Reine Funktion: Long- und Short-Pool (yfinance-Ticker) nach Umsatz sortiert."""
    longs, shorts = [], []
    for r in rows:
        try:
            close = float(r["close"])
            turnover = close * float(r["average_volume_30d_calc"])
            hi, lo = float(r["price_52_week_high"]), float(r["price_52_week_low"])
            perf = float(r["Perf.3M"])
        except (TypeError, ValueError, KeyError):
            continue
        if perf != perf or turnover != turnover:      # NaN
            continue
        if not (close >= TV_MIN_PRICE and turnover >= TV_MIN_TURNOVER_USD and hi > 0 and lo > 0):
            continue
        rel = perf - bench_ret
        t = tv_to_yf(r["name"])
        if close >= hi * (1 - TV_LONG_MAX_BELOW_HIGH) and rel >= -TV_REL_SLACK:
            longs.append((turnover, t))
        elif (lo * (1 + TV_SHORT_ABOVE_LOW[0]) <= close <= lo * (1 + TV_SHORT_ABOVE_LOW[1])
              and rel <= TV_REL_SLACK):
            shorts.append((turnover, t))
    longs.sort(key=lambda x: (-x[0], x[1]))
    shorts.sort(key=lambda x: (-x[0], x[1]))
    return ([t for _, t in longs[:TV_MAX_LONG_POOL]],
            [t for _, t in shorts[:TV_MAX_SHORT_POOL]])


def tv_screener_picks(verbose=True):
    """Stage 1 (TradingView) + Stage 2 (screener_source) -> Top-N-Picks.

    Fail-open: jeder Fehler -> [] mit Warnung, der Rest der Pipeline laeuft.
    """
    try:
        import screener_source as sc
        rows = tv_fetch_universe()
    except Exception as e:
        print(f"  ⚠ h_tv_screener: TradingView-Scanner nicht erreichbar ({e}) – übersprungen", flush=True)
        log.warning("h_tv_screener Stage 1 fehlgeschlagen: %s", e)
        return []
    if not rows:
        print("  ⚠ h_tv_screener: Scanner lieferte 0 Titel – übersprungen", flush=True)
        return []
    try:
        regime, vix, overlay = sc._current_regime()
        p = sc.regime_params(regime, vix, overlay)
        bench_ret = sc._benchmark_return(sc.REL_STRENGTH_LOOKBACK)
        long_pool, short_pool = tv_stage1(rows, bench_ret)
        stage2 = list(dict.fromkeys(long_pool + short_pool))
        for i in range(0, len(stage2), TV_CHUNK):
            prefetch_prices(stage2[i:i + TV_CHUNK])
        longs, shorts = sc.screen_stage2(stage2, {t: "tradingview" for t in stage2}, p, bench_ret)
        selected = sorted(sc.select_candidates(longs + shorts, p),
                          key=lambda c: c["composite"], reverse=True)[:TOP_N]
    except Exception as e:
        print(f"  ⚠ h_tv_screener: Stage 2 fehlgeschlagen ({e}) – übersprungen", flush=True)
        log.warning("h_tv_screener Stage 2 fehlgeschlagen: %s", e)
        return []
    if verbose:
        print(f"  h_tv_screener  TradingView {len(rows)} Titel → Stage 1 "
              f"{len(long_pool)} long / {len(short_pool)} short → Stage 2 "
              f"{len(longs)} long / {len(shorts)} short → {len(selected)} gewählt", flush=True)
    picks = []
    for c in selected:
        info = c.get("info") or {}
        picks.append({"ticker": c["ticker"],
                      "name": info.get("shortName") or info.get("longName") or c["ticker"],
                      "direction": c["direction"].upper(),
                      "score": round(c["composite"], 3),
                      "sector": info.get("sector"),
                      "rationale": "tv: " + c["reason"]})
    return picks


# ── Jev-Veto als Annotation auf die h_tv_screener-Picks (29.09.2026) ──────── jev-tv-veto-20260929
# Probe 29.09. (scripts/jev_veto_probe.py, Erklaerung.md): Jev erkennt aus Schlagzeilen Ereignisse, die ein
# Kurs-Setup entwerten, fast so gut wie DeepSeek (Recall 85 %, Precision 79 %) und ist gut kalibriert. Am
# Stichtag lag aber kein Veto-Titel in den Top-5. Deshalb NUR Annotation: Auswahl und Reihenfolge bleiben
# unveraendert, die Begruendung bekommt "veto=<kategorie>;p=<P(Veto)>;m=<modell>" (P(Veto) = 1 - P(none)),
# "veto=no_news" oder "veto=n/a" (Fehler). Kategorien und Fragetext identisch zur Probe — nicht aendern,
# sonst gelten deren Messwerte nicht mehr.
JEV_VETO_BUDGET_ROLE = "jev_tv_veto"
JEV_VETO_NEWS_DAYS = 14
JEV_VETO_MAX_NEWS = 12
JEV_VETO_FLAG_P = 0.5        # nur fuer die Konsolenmeldung; gespeichert wird p selbst
JEV_VETO_CATS = {
    "acquisition_pending": "the company itself has agreed to be acquired or taken private, or is the target of a "
                           "pending tender offer or merger (it is the TARGET, not the buyer)",
    "offering_dilution": "the company announced or priced a share offering, secondary sale by the company, "
                         "convertible notes, an at-the-market program or another issuance that dilutes shareholders",
    "legal_accounting": "a credible, company-specific problem: regulator or government investigation, fraud "
                        "allegation, short-seller report, restatement, delayed filing or auditor resignation "
                        "(generic law-firm press releases soliciting investors do NOT count)",
    "guidance_cut": "the company lowered its guidance or outlook, issued a profit warning or clearly missed "
                    "earnings expectations",
    "none": "none of the above: routine, positive or unrelated news, or not enough information",
}
JEV_VETO_TASK = ("News items about one US-listed company from the last two weeks, newest first. Judge ONLY what "
                 "the news says about this company. Pick the single most important development.")
JEV_VETO_QUESTIONS = {"event": {"type": "choice",
                                "instructions": "Which category best describes the most important "
                                                "company-specific development in these news items?",
                                "criteria": JEV_VETO_CATS}}


def _jev_veto_enabled():
    return os.environ.get("JEV_TV_VETO", "").strip().lower() == "on"


def _veto_news(ticker, today):
    """Finnhub company-news der letzten JEV_VETO_NEWS_DAYS Tage, neueste zuerst, ohne Dubletten.
    [] = keine Nachrichten, None = Abruffehler."""
    import requests
    key = os.environ.get("FINNHUB_API_KEY")
    if not key:
        return None
    try:
        r = requests.get("https://finnhub.io/api/v1/company-news", timeout=20,
                         params={"symbol": str(ticker).replace("-", "."),
                                 "from": (today - timedelta(days=JEV_VETO_NEWS_DAYS)).isoformat(),
                                 "to": today.isoformat(), "token": key})
        data = r.json() if r.status_code == 200 else None
    except Exception:
        return None
    if not isinstance(data, list):
        return None
    items, seen = [], set()
    for n in sorted(data, key=lambda x: -(x.get("datetime") or 0)):
        h = (n.get("headline") or "").strip()
        if not h or h.lower() in seen:
            continue
        seen.add(h.lower())
        days = (today - datetime.fromtimestamp(n.get("datetime") or 0).date()).days
        items.append({"when": "this week" if days <= 6 else "last week",
                      "headline": h[:220], "summary": (n.get("summary") or "").strip()[:300]})
        if len(items) >= JEV_VETO_MAX_NEWS:
            break
    return items


def _veto_state(pick, news):
    """Nur Text: Firma und Schlagzeilen, keine Kurse oder Scores (Jev ist bei Zahlen schwach)."""
    return {"task": JEV_VETO_TASK, "company": pick.get("name") or pick["ticker"],
            "ticker": pick["ticker"], "news": news}


def jev_veto_annotate(picks, today=None):
    """Haengt an die Begruendung jedes Picks das Jev-Veto an (in place). Kein DB-Zugriff.
    Returns (tokens_in, tokens_out, model) fuer die Buchung durch den Aufrufer."""
    from thematic.lib import jev_client as jc
    today = today or datetime.now().date()
    t_in = t_out = answered = flagged = 0
    cost = 0.0
    for p in picks:
        news = _veto_news(p["ticker"], today)
        tag = "veto=n/a"
        if news is not None and not news:
            tag = "veto=no_news"
        elif news:
            resp = jc.decide(_veto_state(p, news), JEV_VETO_QUESTIONS, timeout=60)
            ch = jc.choice_of(resp, "event", options=JEV_VETO_CATS) if resp else None
            if ch:
                label, _conf, probs = ch
                pv = min(1.0, max(0.0, 1.0 - float(probs.get("none", 0.0))))
                ti, to, c = jc.usage_of(resp)
                t_in, t_out, cost = t_in + ti, t_out + to, cost + c
                answered += 1
                flagged += pv >= JEV_VETO_FLAG_P
                tag = f"veto={label};p={pv:.2f};m={jc.model_of(resp) or '?'}"
        p["rationale"] = f"{p['rationale']} | {tag}" if p.get("rationale") else tag
    print(f"  h_tv_screener  Jev-Veto: {answered}/{len(picks)} Antworten, {flagged} markiert "
          f"(P >= {JEV_VETO_FLAG_P}), ${cost:.4f}", flush=True)
    return t_in, t_out, jc.JEV_MODEL


def tv_screener_picks_annotated(con=None):
    """tv_screener_picks() plus Jev-Veto-Annotation (nur mit JEV_TV_VETO=on).
    Fail-open: jeder Fehler -> unannotierte Picks. Gebucht wird nur mit con (Haupt-Thread)."""
    picks = tv_screener_picks()
    if not picks or not _jev_veto_enabled():
        return picks
    annotated = [dict(p) for p in picks]
    try:
        t_in, t_out, model = jev_veto_annotate(annotated)
    except Exception as e:
        print(f"  ⚠ h_tv_screener: Jev-Veto fehlgeschlagen ({e}) – Picks ohne Annotation", flush=True)
        log.warning("Jev-Veto fehlgeschlagen: %s", e)
        return picks
    if con is not None and (t_in or t_out):
        try:
            from roles import budget as _role_budget
            _role_budget.record_spend(con, JEV_VETO_BUDGET_ROLE, datetime.now().strftime("%Y-%m-%d"),
                                      t_in, t_out, model)
        except Exception as e:
            print(f"  ⚠ Budget-Buchung ({JEV_VETO_BUDGET_ROLE}) fehlgeschlagen: {e}", flush=True)
    return annotated


def tv_dry_run():
    picks = tv_screener_picks_annotated()      # ohne con: keine Buchung
    for p in picks:
        print(f"  {p['direction']:5} {p['ticker']:8} score={p['score']:.2f} "
              f"sektor={p['sector'] or '?'}  {p['rationale']}", flush=True)
    print("  (Trockenlauf: nichts geschrieben)", flush=True)


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


def _typical_position_size(con):
    """Median der Positionsgroessen der letzten 90 Tage — fuer den
    Kommissionsanteil der Kosten (Schatten-Trades haben keine eigene Groesse)."""
    rows = con.execute("""
        SELECT position_size FROM positions
        WHERE position_size > 0 AND entry_date >= date('now', '-90 day')
        ORDER BY position_size
    """).fetchall()
    return rows[len(rows) // 2][0] if rows else 800.0


def evaluate_exits(con):
    """Jeden reifen Kandidaten mit ZWEI Exits bewerten, beide netto (28.09.2026).

    live — exakt die Exit-Logik des Optimizers (strategy_optimizer.
           backtest_params: Exit-Matrix x Exit-Profil, Donchian-primary,
           Partial, Time-Stop aus strategy_config, Roundtrip-Kosten).
           Frage: was haette dieses Signal im heutigen Live-System verdient?
    hold — Anfangs-Stop, sonst HOLD_BARS Handelstage halten, Kosten abgezogen.
           Frage: was gibt das Signal selbst her?

    Die alte pnl_pct_sim (simulate_forward: Chandelier, Tag-7-Stop, brutto)
    bleibt zur Kontinuitaet stehen, ist aber keine Entscheidungsgroesse mehr:
    sie bildet weder den Live-Exit noch den Signal-Horizont ab.
    """
    from trade_paths import _download, entry_index
    from exit_rules import replay_exit_path, replay_fill_settings
    from utils import roundtrip_cost_pct
    from config import EXIT_PROFILES
    import strategy_optimizer as so

    cfg = so.load_config()
    profile = cfg.get("exit_profile", "current")
    time_stop = cfg.get("time_stop_trading_days", 7)
    scale = EXIT_PROFILES.get(profile, EXIT_PROFILES["current"])["sl_scale"]
    size = _typical_position_size(con)
    cost = roundtrip_cost_pct(size)
    fade_hold = cfg.get("yt_fade_hold_days", 40)
    fade_stop = cfg.get("yt_fade_stop_pct", 0.40)
    fade_cutoff = (datetime.now() - timedelta(days=fade_hold * 7 // 5 + 2)).strftime("%Y-%m-%d")
    # grob HOLD_BARS Handelstage in Kalendertagen; die exakte Reife prueft
    # unten die Bar-Anzahl
    cutoff = (datetime.now() - timedelta(days=HOLD_BARS * 7 // 5 + 2)).strftime("%Y-%m-%d")
    rows = con.execute("""
        SELECT * FROM shadow_selection
        WHERE pnl_live_net IS NULL AND eval_status != 'no_data' AND select_date <= ?
        ORDER BY select_date
    """, (cutoff,)).fetchall()
    if not rows:
        print("  Exit-Bewertung: keine reifen Eintraege "
              f"(Reife nach {HOLD_BARS} Handelstagen).", flush=True)
        return 0

    bars_by_key = {}
    done = unripe = 0
    for row in rows:
        is_fade = row["exit_mode"] == YT_FADE_MODE
        if is_fade and row["select_date"] > fade_cutoff:
            unripe += 1          # Fade braucht fade_hold Bars — nicht vorher laden
            continue
        key = (row["ticker"], row["select_date"])
        if key not in bars_by_key:
            bars_by_key[key] = _download(row["ticker"], row["select_date"])
        bars = bars_by_key[key]
        idx = entry_index(bars, row["select_date"]) if bars else None
        atr = row["atr_at_select"]
        need = max(HOLD_BARS, fade_hold) if is_fade else HOLD_BARS
        if idx is None or not atr or len(bars) - idx - 1 < need:
            unripe += 1
            continue
        entry = bars[idx]["close"]
        asset_type = row["asset_type"] or "STANDARD"
        trade = {"_bars": bars, "_entry_idx": idx, "_atr": atr,
                 "entry_price": entry, "direction": row["direction"],
                 "asset_type": asset_type, "position_size": size}
        if is_fade:
            # Live-Exit des YT-Fade: Notfallstop auf Schlusskurs oder fade_hold
            # Bars — dieselbe Regel wie exit_rules.fade_exit_decision (live)
            _why, fpx, _n = simulate_fade_close(bars, idx, entry, fade_stop, fade_hold)
            live = ([{"pnl_pct": (entry - fpx) / entry * 100 - cost}]
                    if fpx is not None else [])
        else:
            live = so.backtest_params([trade], profile, time_stop)
        if not live:
            unripe += 1
            continue

        ex = get_exit_config(asset_type=asset_type, regime="sideways")
        sl_mult = round(ex["sl"] * scale, 2)
        res = replay_exit_path(
            bars, idx, entry, row["direction"], atr,
            sl_mult=sl_mult, partial_atr=ex["partial_atr"], partial_pct=0.0,
            profit_lock_atr=1e9, chandelier_mult=ex["chandelier_mult"],
            donchian_primary=False, time_stop_bars=HOLD_BARS, tp_mult=None,
            **replay_fill_settings(cfg))   # M5/N9: gleiche Fills wie der Live-Exit-Zweig
        hold = (res["r_multiple"] * (sl_mult * atr / entry * 100) - cost
                if res["r_multiple"] is not None else None)

        con.execute("""
            UPDATE shadow_selection SET pnl_live_net=?, pnl_hold_net=?,
                cost_pct=?, exit_eval_date=? WHERE id=?
        """, (round(live[0]["pnl_pct"], 3),
              round(hold, 3) if hold is not None else None,
              round(cost, 4), datetime.now().strftime("%Y-%m-%d"), row["id"]))
        done += 1
    con.commit()
    print(f"  Exit-Bewertung: {done} bewertet (Live-Exit {profile}/{time_stop}d "
          f"vs. Halten {HOLD_BARS}d, Kosten {cost:.2f}%), {unripe} noch nicht reif",
          flush=True)
    return done


def _independent(rows):
    """Pro (Ticker, Richtung) hoechstens ein Trade je INDEPENDENCE_DAYS."""
    kept, last = [], {}
    for r in rows:
        k = (r["ticker"], r["direction"])
        d = datetime.strptime(r["select_date"], "%Y-%m-%d")
        if k in last and (d - last[k]).days < INDEPENDENCE_DAYS:
            continue
        last[k] = d
        kept.append(r)
    return kept


def _exit_rows(con, hypothesis):
    return _independent(con.execute("""
        SELECT select_date, ticker, direction, pnl_live_net, pnl_hold_net, cost_pct
        FROM shadow_selection
        WHERE hypothesis=? AND pnl_live_net IS NOT NULL
        ORDER BY select_date
    """, (hypothesis,)).fetchall())


def criteria_report(con):
    """Prueft jede Hypothese gegen die VORAB festgelegten Kriterien."""
    cols = {r[1] for r in con.execute("PRAGMA table_info(shadow_selection)")}
    if "pnl_live_net" not in cols:
        return   # Schema ohne Exit-Bewertung (z.B. Test-Fixture) — nichts zu pruefen
    print(f"\n🎯 Vorab-Kriterien (festgelegt {CRITERIA_FIXED_ON}) — Live-Exit, netto, "
          f"unabhaengige Trades", flush=True)
    print(f"  {'Hypothese':14} {'N':>4} {'Ø live':>8} {'Ø halten':>9} "
          f"{'Ø Kost.x2':>10} {'o.Top3 Σ':>9}  Urteil", flush=True)
    base = sorted(_exit_rows(con, "live_baseline") + _exit_rows(con, "live_baseline_v1"),
                  key=lambda r: r["select_date"])
    for h in HYPOTHESES:
        rows = _exit_rows(con, h)
        n = len(rows)
        if not n:
            continue
        live = [r["pnl_live_net"] for r in rows]
        hold = [r["pnl_hold_net"] for r in rows if r["pnl_hold_net"] is not None]
        mean = sum(live) / n
        mean_hold = sum(hold) / len(hold) if hold else float("nan")
        stress = sum(p - (COST_STRESS_MULT - 1) * (r["cost_pct"] or 0)
                     for p, r in zip(live, rows)) / n
        rest = sorted(live, reverse=True)[DROP_TOP_K:]
        rest_sum = sum(rest) if rest else float("nan")

        checks = [(f"N {n}/{MIN_INDEPENDENT}", n >= MIN_INDEPENDENT),
                  (f"Kosten x{COST_STRESS_MULT:g}", stress > 0),
                  (f"ohne Top-{DROP_TOP_K}", bool(rest) and rest_sum > 0)]
        if h not in BASELINES:
            lo, hi = rows[0]["select_date"], rows[-1]["select_date"]
            b = [r["pnl_live_net"] for r in base if lo <= r["select_date"] <= hi]
            bmean = sum(b) / len(b) if b else None
            checks.append(("> Referenz", bmean is not None and mean > bmean))
        failed = [name for name, ok in checks if not ok]
        verdict = "✅ ALLE ERFUELLT — Live-Kandidat" if not failed \
            else "offen: " + ", ".join(failed)
        print(f"  {h:14} {n:>4} {mean:>+7.2f}% {mean_hold:>+8.2f}% "
              f"{stress:>+9.2f}% {rest_sum:>+8.1f}%  {verdict}", flush=True)
    print(f"  Ø halten = nur Anfangs-Stop, {HOLD_BARS} Handelstage. Liegt es klar "
          f"ueber Ø live,\n  wuergt der Live-Exit das Signal ab — dann ist die "
          f"Haltedauer das Problem, nicht die Selektion.", flush=True)


# ── Bericht ─────────────────────────────────────────────────────────────────

def _source_health(con, hypothesis):
    """Sagt, ob die DATENQUELLE einer Hypothese ueberhaupt noch laeuft.

    Ohne das liest sich eine tote Spur im Bericht wie eine junge: beide zeigen
    "noch keine Daten". h1_momentum liefert seit dem 13.07.2026 dauerhaft 0
    Kandidaten, weil factor_scores nicht mehr befuellt wird. KORREKTUR 19.09.:
    thematic/factor_ranker.py existiert sehr wohl (und wurde am 08.09. sogar
    ueberarbeitet) — die gesamte thematic/-Pipeline hat nur seit dem 13.07.
    keinen Cron-Eintrag mehr und laeuft deshalb nicht. Das ist ein Betriebs-
    defekt, kein Reifeproblem — und muss auch so dastehen.
    """
    if hypothesis == "h1_momentum":
        row = con.execute("SELECT MAX(date) d FROM factor_scores").fetchone()
        last = row["d"] if row else None
        if not last:
            return False, "factor_scores leer"
        age = (datetime.now().date()
               - datetime.strptime(last, "%Y-%m-%d").date()).days
        if age > 7:
            return False, f"factor_scores {age}d alt (Stand {last})"
    cols = {r[1] for r in con.execute("PRAGMA table_info(shadow_selection)")}
    if hypothesis == "h_tv_screener" and "select_date" in cols:
        row = con.execute("SELECT MAX(select_date) d FROM shadow_selection "
                          "WHERE hypothesis='h_tv_screener'").fetchone()
        last = row["d"] if row else None
        if last:   # vor dem ersten Lauf: junge Spur, nicht tot
            age = (datetime.now().date()
                   - datetime.strptime(last, "%Y-%m-%d").date()).days
            if age > 7:
                return False, f"TradingView-Scanner liefert seit {last} nichts"
    return True, ""


def report(con):
    print("\n📊 Schattenbücher — Stand", datetime.now().strftime("%Y-%m-%d"), flush=True)
    print(f"  {'Hypothese':14} {'ausgew.':>8} {'bewertet':>9} {'WR':>6} "
          f"{'Ø %':>8} {'Σ %':>8}  Bewertung", flush=True)
    base_avg = None
    for h in HYPOTHESES:
        tot = con.execute("SELECT COUNT(*) FROM shadow_selection WHERE hypothesis=?",
                          (h,)).fetchone()[0]
        if h == "h_jev" and not tot and not _jev_enabled():
            continue     # bewusst aus, keine tote Spur
        r = con.execute("""
            SELECT COUNT(*) n, SUM(pnl_pct_sim > 0) w,
                   AVG(pnl_pct_sim) avg, SUM(pnl_pct_sim) tot
            FROM shadow_selection WHERE hypothesis=? AND eval_status='evaluated'
        """, (h,)).fetchone()
        n = r["n"] or 0
        alive, why = _source_health(con, h)
        if not n:
            status = "noch keine Daten" if alive else f"⛔ QUELLE TOT — {why}"
            print(f"  {h:14} {tot:>8} {0:>9} {'–':>6} {'–':>8} {'–':>8}  "
                  f"{status}", flush=True)
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
    print("\n  Hinweis: Tabelle oben = Alt-Simulation (Chandelier, Tag-7-Stop, brutto,\n"
          "  Tageszeilen statt unabhaengiger Trades). Entscheidungsgroesse sind die\n"
          "  Vorab-Kriterien unten.", flush=True)
    criteria_report(con)
    dead = [h for h in HYPOTHESES if not _source_health(con, h)[0]]
    if dead:
        print(f"⛔ {len(dead)} Hypothese(n) ohne laufende Datenquelle: "
              f"{', '.join(dead)}\n"
              "   Diese Spur sammelt NICHT im Hintergrund weiter — sie ist "
              "defekt und braucht eine\n"
              "   Entscheidung (Quelle reparieren oder Hypothese streichen).",
              flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--select", action="store_true", help="nur auswählen")
    ap.add_argument("--evaluate", action="store_true", help="nur bewerten")
    ap.add_argument("--report", action="store_true", help="nur Bericht")
    ap.add_argument("--jev-dry-run", action="store_true",
                    help="h_jev: Zustaende und Kosten zeigen, nichts schreiben")
    ap.add_argument("--tv-dry-run", action="store_true",
                    help="h_tv_screener: Auswahl zeigen, nichts schreiben")
    args = ap.parse_args()
    do_all = not (args.select or args.evaluate or args.report)

    con = db_connect()
    try:
        ensure_schema(con)
        today = datetime.now().strftime("%Y-%m-%d")
        if args.jev_dry_run:
            jev_dry_run(con)
            return
        if args.tv_dry_run:
            tv_dry_run()
            return

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
            if _jev_enabled():
                record(con, "h_jev",     today, select_h_jev(con))
            record(con, "h_tv_screener", today, tv_screener_picks_annotated(con))

        if do_all or args.evaluate:
            print(f"\n🔍 Vorwärtsbepreisung (Horizont {HORIZON_DAYS} Tage)", flush=True)
            evaluate(con)
            evaluate_exits(con)

        if do_all or args.report:
            report(con)
    finally:
        con.close()


if __name__ == "__main__":
    main()
