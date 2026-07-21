#!/usr/bin/env python3
"""
probe_confidence_shift.py  (v2 – isolierter Code-Effekt)

READ-ONLY. Misst NUR den Effekt der Donchian-Konfluenz-Komponente auf die
tech_score/tech_direction – auf IDENTISCHEN (heutigen) Kursdaten.

Warum v2: Ein Vergleich gegen die in der DB gespeicherten tech_scores mischt
zwei Dinge – den Code-Change UND die Markt-Drift seit dem letzten
watchlist_manager-Lauf (EMA/RSI/MACD/Weekly wandern taeglich). Fuer die Frage
"verschiebt der Donchian-Change Entscheidungsgrenzen?" muss man mit und ohne
Donchian auf DENSELBEN Daten vergleichen.

Trick: get_technical_score() liefert den rohen `score`. Der Donchian-Beitrag
ist bekannt und deterministisch (+1.0 / +0.5 / -0.5 / -1.0), also laesst sich
der Score OHNE Donchian exakt rekonstruieren:
    score_ohne   = score_mit - donchian_beitrag
    confidence   = clamp((score + 10) / 20)          # max_score = 10
    direction    = LONG  wenn score >= 2
                   SHORT wenn score <= -2
                   sonst NEUTRAL

AUSFUEHREN (nach Deploy der neuen utils.py):
    cd /root/.hermes/profiles/hermes_trading/skills/trading/scripts
    python3 probe_confidence_shift.py [--min-conviction 0.3] [--all]
"""
import sys
import argparse
import json
sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading/scripts")
import env_loader  # noqa: F401
from config import STRATEGY_CONFIG_PATH, db_connect
from utils import get_technical_score, prefetch_prices

MAX_SCORE = 10  # muss zu utils.get_technical_score passen


def load_thresholds():
    long_thr, short_thr = 0.60, 0.65
    try:
        with open(STRATEGY_CONFIG_PATH) as f:
            cfg = json.load(f)
        long_thr  = cfg.get("min_confidence", long_thr)
        short_thr = cfg.get("min_confidence_short", short_thr)
    except Exception:
        pass
    return long_thr, short_thr


def donchian_contrib(donch):
    """Rekonstruiert den exakten Score-Beitrag der Donchian-Komponente
    (identische Reihenfolge wie in utils.get_technical_score, Komponente 9)."""
    if not donch:
        return 0.0, ""
    if donch.get("breakout_long_slow"):  return  1.0, "55up"
    if donch.get("breakout_long"):       return  0.5, "20up"
    if donch.get("breakout_short_slow"): return -1.0, "55dn"
    if donch.get("breakout_short"):      return -0.5, "20dn"
    return 0.0, ""


def clamp_conf(score):
    return max(0.0, min(1.0, (score + MAX_SCORE) / (2 * MAX_SCORE)))


def direction(score):
    return "LONG" if score >= 2 else "SHORT" if score <= -2 else "NEUTRAL"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-conviction", type=float, default=0.3)
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    long_thr, short_thr = load_thresholds()
    con = db_connect()
    status_filter = "status IN ('watching','bought')" if not args.all else "1=1"
    rows = con.execute(f"""
        SELECT name, ticker, conviction_score, status
        FROM watchlist
        WHERE {status_filter} AND ticker IS NOT NULL AND conviction_score >= ?
        ORDER BY conviction_score DESC
    """, (args.min_conviction,)).fetchall()
    con.close()

    print("Donchian-Code-Effekt Probe v2 (READ-ONLY, identische Daten)")
    print(f"   Long-Gate={long_thr:.2f}  Eintraege={len(rows)} "
          f"(conviction >= {args.min_conviction})\n")

    prefetch_prices([r["ticker"] for r in rows if r["ticker"]])

    affected = flips = crossings = nodata = 0
    max_delta = 0.0
    print(f"  {'Name':26} {'Ticker':9} {'ohne':>5} {'mit':>5} {'D':>6}  "
          f"{'Dir ohne->mit':16} {'Donch':5} Flag")
    print("  " + "-" * 90)

    for r in rows:
        tech = get_technical_score(r["ticker"])
        if not tech:
            nodata += 1
            continue

        score_with = tech["score"]
        contrib, tag = donchian_contrib(tech.get("donchian"))
        if contrib == 0.0:
            continue  # Donchian inaktiv -> exakt null Effekt, nicht ausgeben

        affected += 1
        score_without = score_with - contrib
        conf_with    = tech["confidence"]           # == clamp_conf(score_with)
        conf_without = clamp_conf(score_without)
        dir_with     = tech["direction"]
        dir_without  = direction(score_without)
        delta = conf_with - conf_without
        max_delta = max(max_delta, abs(delta))

        flag = []
        if dir_without != dir_with:
            flips += 1
            flag.append("FLIP")
        if (conf_without < long_thr <= conf_with) or (conf_with < long_thr <= conf_without):
            crossings += 1
            flag.append(f"x{long_thr:.2f}")

        print(f"  {r['name'][:26]:26} {r['ticker']:9} {conf_without:>5.2f} "
              f"{conf_with:>5.2f} {delta:>+6.3f}  "
              f"{(dir_without + '->' + dir_with):16} {tag:5} {' '.join(flag)}")

    print("\n" + "=" * 52)
    print(f"Eintraege mit Donchian-Signal : {affected}/{len(rows) - nodata}")
    print(f"max |D confidence|            : {max_delta:.4f}  (Deckel: 0.0500)")
    print(f"Richtungs-Flips durch Code    : {flips}")
    print(f"Gate-Crossings durch Code     : {crossings}  (Long-Gate {long_thr:.2f})")
    print(f"Ohne Kursdaten                : {nodata}")
    if flips == 0 and crossings == 0:
        print("\nOK: Der Donchian-Change ueberschreitet KEINE Entscheidungsgrenze. "
              "refresh_tech_scores.py ist unbedenklich.")
    else:
        print("\nHinweis: Obige Grenzfaelle pruefen - aber D ist per Design <= 0.05, "
              "also Titel, die exakt auf der Gate-Kante lagen.")


if __name__ == "__main__":
    main()
