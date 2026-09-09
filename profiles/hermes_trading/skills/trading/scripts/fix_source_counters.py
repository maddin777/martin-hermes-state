#!/usr/bin/env python3
"""
fix_source_counters.py — Einmalige Datenkorrektur (Stand 08.09.2026)

Repariert drei Bestandsschaeden in der Live-DB, die von den Code-Fixes vom
08.09.2026 nur FUER DIE ZUKUNFT verhindert werden – die bereits verfaelschten
Zeilen muessen einmalig nachgezogen werden.

  1. source_registry-Zaehler (total_bought / total_mentions / win_rate / avg_pnl)
     Root-Cause: source_lifecycle.evaluate_active_sources() schrieb
     `total_bought = total_bought + SUM(rollierende 30d-Snapshots ueber 90d)`.
     Jeder Trade steckte in ~30 Snapshots, und die Summe wurde bei JEDEM
     Wochenlauf erneut addiert → exponentielle Inflation
     (Befund: 'der aktionaer' = 6358 bei 84 geschlossenen Trades im System).
     `total_mentions` wurde nie geschrieben und stand ueberall auf 0.

  2. Quellen-Gewichte, die auf Basis dieser Falschdaten auf das Minimum (0.3)
     gesetzt wurden. Nur mit --reset-weights, bewusst als eigener Schalter:
     das Gewicht geht direkt in die Conviction ein und veraendert damit den
     Live-Handel.

  3. watchlist.tech_score ausserhalb [0,1] (Befund: eine Zeile mit 5.0).
     Solche Zeilen passieren JEDEN `tech_score >= X`-Entry-Filter automatisch.

Bewusst ein eigenstaendiges Skript und NICHT Teil des Wochenjobs: eine
Datenkorrektur soll genau einmal, bewusst und protokolliert laufen.

Dry-Run-Muster wie watchlist_cleanup.py nach dem 26.08.-Fix: ohne --apply wird
NUR gelesen und angezeigt, es findet kein einziger Schreibzugriff statt.

    python3 fix_source_counters.py                    # Dry-Run (read-only)
    python3 fix_source_counters.py --apply            # Zaehler + tech_score fixen
    python3 fix_source_counters.py --apply --reset-weights
"""
import argparse
import sys

sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")
sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading/scripts")

from datetime import datetime, timedelta

from config import db_connect
from source_lifecycle import channel_variants, _channel_match_sql

# Gewicht, das demote_bad_sources() als Strafe setzt (THRESHOLDS.penalize_min_weight).
PENALIZED_WEIGHT = 0.3
DEFAULT_WEIGHT = 1.0


def recompute_source_row(con, display_name):
    """Absolute Kennzahlen einer Quelle – identisch zu evaluate_active_sources()."""
    variants = channel_variants(display_name)
    ph = ",".join("?" * len(variants))
    trade_sql, trade_params = _channel_match_sql("source_channel", variants)

    trades = con.execute(f"""
        SELECT pnl_eur, exit_date FROM positions
        WHERE status='closed' AND ({trade_sql})
        ORDER BY exit_date DESC
    """, trade_params).fetchall()

    n = len(trades)
    wins = sum(1 for t in trades if (t["pnl_eur"] or 0) > 0)
    avg_pnl = (sum((t["pnl_eur"] or 0) for t in trades) / n) if n else 0.0

    cutoff_90d = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    recent = [t for t in trades if (t["exit_date"] or "") >= cutoff_90d]
    wr_90d = (sum(1 for t in recent if (t["pnl_eur"] or 0) > 0) / len(recent)) if recent else 0.0

    consec = 0
    for t in trades[:10]:
        if (t["pnl_eur"] or 0) <= 0:
            consec += 1
        else:
            break

    mrow = con.execute(f"""
        SELECT COUNT(*) AS n, MAX(mention_date) AS last_seen
        FROM watchlist_mentions WHERE channel IN ({ph})
    """, variants).fetchone()

    return {
        "total_mentions": mrow["n"] or 0,
        "total_bought": n,
        "total_wins": wins,
        "total_losses": n - wins,
        "win_rate_alltime": round((wins / n) if n else 0.0, 3),
        "win_rate_90d": round(wr_90d, 3),
        "avg_pnl_per_trade": round(avg_pnl, 2),
        "consecutive_losses": consec,
        "last_mention_date": mrow["last_seen"],
    }


def fix_counters(con, apply_changes):
    print("\n1. source_registry-Zaehler")
    print("-" * 92)
    total_closed = con.execute(
        "SELECT COUNT(*) FROM positions WHERE status='closed'"
    ).fetchone()[0]
    print(f"   Geschlossene Trades im System (Obergrenze je Quelle): {total_closed}\n")
    print(f"   {'Quelle':32} {'bought alt':>11} {'neu':>6} {'mentions':>9} "
          f"{'avg_pnl alt':>12} {'neu':>8}")

    rows = con.execute(
        "SELECT id, display_name, total_bought, total_mentions, avg_pnl_per_trade "
        "FROM source_registry ORDER BY total_bought DESC"
    ).fetchall()

    changed = inflated = 0
    for src in rows:
        new = recompute_source_row(con, src["display_name"])
        old_bought = src["total_bought"] or 0
        if old_bought > total_closed:
            inflated += 1
        if (old_bought != new["total_bought"]
                or (src["total_mentions"] or 0) != new["total_mentions"]):
            changed += 1
            print(f"   {src['display_name'][:32]:32} {old_bought:>11} "
                  f"{new['total_bought']:>6} {new['total_mentions']:>9} "
                  f"{(src['avg_pnl_per_trade'] or 0):>+12.1f} "
                  f"{new['avg_pnl_per_trade']:>+8.1f}")
        if apply_changes:
            con.execute("""
                UPDATE source_registry SET
                    total_mentions=?, total_bought=?, total_wins=?, total_losses=?,
                    win_rate_alltime=?, win_rate_90d=?, avg_pnl_per_trade=?,
                    consecutive_losses=?,
                    last_mention_date=COALESCE(?, last_mention_date)
                WHERE id=?
            """, (new["total_mentions"], new["total_bought"], new["total_wins"],
                  new["total_losses"], new["win_rate_alltime"], new["win_rate_90d"],
                  new["avg_pnl_per_trade"], new["consecutive_losses"],
                  new["last_mention_date"], src["id"]))

    print(f"\n   → {changed} Quellen mit abweichenden Zaehlern, "
          f"davon {inflated} ueber der physikalischen Obergrenze ({total_closed}).")
    return changed


def reset_weights(con, apply_changes):
    """Setzt Minimal-Gewichte zurueck, die auf Basis der Falschzaehler entstanden."""
    print("\n2. Quellen-Gewichte (nur mit --reset-weights)")
    print("-" * 92)
    rows = con.execute("""
        SELECT id, display_name, weight, avg_pnl_per_trade, total_bought
        FROM source_registry
        WHERE enabled=1 AND status IN ('active','probation') AND weight <= ?
        ORDER BY display_name
    """, (PENALIZED_WEIGHT,)).fetchall()

    if not rows:
        print("   Keine penalisierten Quellen gefunden.")
        return 0

    for src in rows:
        print(f"   {src['display_name'][:36]:36} weight {src['weight']:.2f} "
              f"→ {DEFAULT_WEIGHT:.2f}  (neue Basis: {src['total_bought']} Trades, "
              f"avg_pnl {(src['avg_pnl_per_trade'] or 0):+.1f}€)")
        if apply_changes:
            con.execute("UPDATE source_registry SET weight=? WHERE id=?",
                        (DEFAULT_WEIGHT, src["id"]))

    verb = "zurueckgesetzt" if apply_changes else "wuerden zurueckgesetzt"
    print(f"\n   → {len(rows)} Gewichte auf {DEFAULT_WEIGHT} {verb}. "
          f"Der naechste source_lifecycle-Lauf (So) regelt sie auf Basis der "
          f"korrigierten Zahlen neu nach.")
    return len(rows)


def fix_tech_scores(con, apply_changes):
    print("\n3. watchlist.tech_score ausserhalb [0,1]")
    print("-" * 92)
    rows = con.execute("""
        SELECT rowid AS rid, ticker, name, tech_score, status FROM watchlist
        WHERE tech_score IS NOT NULL AND (tech_score < 0.0 OR tech_score > 1.0)
    """).fetchall()

    if not rows:
        print("   Keine Zeilen ausserhalb des Wertebereichs.")
        return 0

    for r in rows:
        print(f"   {(r['name'] or '?')[:36]:36} {(r['ticker'] or '?'):10} "
              f"{r['status']:9} tech_score={r['tech_score']} → NULL")
        if apply_changes:
            # Bewusst NULL statt Clamping: der Wert ist nachweislich falsch, ein
            # geklemmter 1.0 waere eine erfundene Bestnote. NULL = "kein Score",
            # der naechste technical_validator-/refresh-Lauf rechnet ihn sauber neu.
            con.execute(
                "UPDATE watchlist SET tech_score=NULL, tech_direction=NULL, "
                "weekly_trend=NULL WHERE rowid=?", (r["rid"],)
            )

    verb = "bereinigt" if apply_changes else "wuerden bereinigt"
    print(f"\n   → {len(rows)} Zeilen {verb} (auf NULL, Neuberechnung beim "
          f"naechsten Tech-Lauf).")
    return len(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="Aenderungen wirklich schreiben (ohne: read-only Dry-Run)")
    ap.add_argument("--reset-weights", action="store_true",
                    help="Zusaetzlich penalisierte Quellen-Gewichte auf 1.0 setzen")
    args = ap.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN (read-only)"
    print(f"🔧 fix_source_counters — Modus: {mode}")

    con = db_connect()
    try:
        fix_counters(con, args.apply)
        if args.reset_weights:
            reset_weights(con, args.apply)
        else:
            print("\n2. Quellen-Gewichte: uebersprungen (--reset-weights nicht gesetzt)")
        fix_tech_scores(con, args.apply)

        if args.apply:
            con.commit()
            print("\n✅ Aenderungen geschrieben.")
        else:
            # Kein commit, kein Schreibzugriff — Dry-Run ist echt read-only.
            print("\nℹ Dry-Run: nichts geschrieben. Mit --apply ausfuehren.")
    finally:
        con.close()


if __name__ == "__main__":
    main()
