"""
Pre-Delivery-Verification-Gate (seit 14.09.2026)
================================================
Anthropic "Methode 4" / vault-insights Vorschlag 2: Signal-Outputs vor der
Delivery gegen FESTE Kriterien laufen lassen (proof-of-work statt
Selbstbestätigung). Der erste Blick des Operators soll nicht der erste sein.

Was es tut:
- Nimmt die Top-N Watchlist-Kandidaten (gleiche Shortlist wie der
  Telegram-Report / build_top_signals_line).
- Validiert JEDEN gegen die festen Entry-Kriterien des Systems:
    1. conviction_score_aged >= min_confidence    (Default 0.60 aus config)
    2. tech_score vorhanden (NOT NULL)
    3. tech_direction == 'LONG'                     (Entry braucht LONG-Richtung;
       NEUTRAL/SHORT sind trotz hoher Conviction NICHT long-entry-fähig)
    4. kein DQ-Fall: kein '.L'-Microcap ohne tech_score
- Hängt eine kompakte Verifikationszeile an den Report:
     ✅ = entry-fähig   ⚠️ = Warnung (z.B. NEUTRAL-direction)   ❌ = blockiert

WICHTIG: Das Gate liefert einen BEFUND als Text-String (proof-of-work). Es
blockiert NICHT die Zustellung — der Report geht immer raus, aber der
Operator sieht sofort, welche Top-Signale das Entry-Gate tatsächlich
passieren. Das senkt den manuellen Review-Aufwand.

Nutzung:
    from config import db_connect
    from scripts.pre_delivery_gate import build_gate_line
    print(build_gate_line(db_connect(), limit=5))

DB-first: Schwellen werden aus config.py geholt (min_confidence), keine
Hardcodes außer dem fallback.
"""
import re


def _entry_threshold(con):
    """min_confidence für Entries — DB/Config statt Hardcode."""
    try:
        from config import DEFAULT_CONFIG
        return float(DEFAULT_CONFIG.get("min_confidence", 0.60))
    except Exception:
        return 0.60


def _fetch_candidates(con, limit):
    """Gleiche Query wie nightly_eval.calc_top_signals — konsistente Shortlist."""
    return con.execute(
        """
        SELECT name, ticker, conviction_score, conviction_score_aged,
               conviction_score_bear, tech_score, tech_direction,
               mention_count, status
        FROM watchlist
        WHERE status = 'watching'
          AND ticker IS NOT NULL
        ORDER BY conviction_score_aged DESC, tech_score DESC, conviction_score DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def verify_candidate(row, threshold):
    """
    Prüft einen Kandidaten gegen die festen Entry-Kriterien.
    Rückgabe: (status, grund) mit status in pass|warn|block.
      pass  - entry-fähig (Conv + Tech + LONG)
      warn  - technisch nicht LONG (NEUTRAL/SHORT) ODER nur 1 Mention
      block - conviction zu niedrig ODER kein tech_score (.L-DQ o.ä.)
    """
    conv = row["conviction_score_aged"] if "conviction_score_aged" in row.keys() else row["conviction_score"]
    conv = conv or 0.0
    tech = row["tech_score"] if "tech_score" in row.keys() else None
    direction = (row["tech_direction"] or "").upper() if "tech_direction" in row.keys() else ""
    ticker = row["ticker"] or ""
    mentions = row["mention_count"] or 0

    # Kriterium 1: conviction-Schwelle (ältere Einträge/Alterung schon eingerechnet)
    if conv < threshold:
        return "block", f"Conv {conv:.0%} < {threshold:.0%}"

    # Kriterium 4: DQ-Fall '.L'-Microcap ohne tech_score -> nicht entry-fähig
    if ticker.upper().endswith(".L") and tech is None:
        return "block", "DQ .L ohne Tech-Score"

    # Kriterium 2: tech_score vorhanden
    if tech is None:
        return "block", "kein tech_score"

    # Kriterium 3: LONG-Richtung (Entry braucht LONG). NEUTRAL/SHORT warnen.
    if direction != "LONG":
        return "warn", f"tech_direction {direction}"

    # Nur-1-Mention-Warnung: Einzel-Mention-Hit kann Rauschen sein (aged-Score
    # mildert das teilweise, aber 1 Mention bleibt fragil).
    if mentions <= 1:
        return "warn", "nur 1 Mention"

    return "pass", "entry-fähig"


def build_gate_line(con, limit=5):
    """
    Verifikationszeile für den Telegram-Report. Startet mit der Live-Query
    damit sie IMMER den aktuellen Stand prüft (kein Cache, keine Altlasten).
    """
    threshold = _entry_threshold(con)
    try:
        rows = _fetch_candidates(con, limit)
    except Exception as e:
        return f"🛡 Pre-Delivery-Gate: ❌ Query-Fehler ({e})"

    if not rows:
        return "🛡 Pre-Delivery-Gate: (keine Kandidaten)"

    counts = {"pass": 0, "warn": 0, "block": 0}
    parts = []
    for r in rows:
        status, grund = verify_candidate(r, threshold)
        counts[status] += 1
        if status == "pass":
            icon = "✅"
        elif status == "warn":
            icon = "⚠️"
        else:
            icon = "🚫"
        parts.append(f"{icon} <b>{r['name']}</b> ({r['ticker']}) {grund}")

    verdict = "✅ alle entry-fähig" if counts["block"] == 0 and counts["warn"] == 0 else (
        f"⚠️ {counts['warn']} gewarnt" if counts["block"] == 0 else f"🚫 {counts['block']} blockiert"
    )
    header = f"🛡 <b>Pre-Delivery-Gate:</b> {verdict} (Schwelle {threshold:.0%})\n"
    lines = "\n".join(parts)
    return header + lines


if __name__ == "__main__":
    from config import db_connect
    print(build_gate_line(db_connect(), limit=5))
