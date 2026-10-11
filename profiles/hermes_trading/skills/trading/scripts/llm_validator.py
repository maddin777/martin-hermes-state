"""
LLM-Kreuzvalidierung für High-Conviction Signale.
Läuft NACH watchlist_manager.py, VOR signal_manager.py.
Nur für Kandidaten mit conviction >= 0.70.

P5 (30.09.2026): Die ersten Läufe lieferten 19 von 19 Kandidaten als UNCERTAIN, weil der Validator kaum etwas zu
bewerten bekam: (1) er prüfte Monate alte Watchlist-Einträge (last_seen im Kompaktformat YYYYMMDD galt beim
String-Vergleich immer als frisch), (2) er suchte Begründungen nur unter dem exakten Watchlist-Namen, die Mentions
stehen aber unter Varianten ('AMD', 'Deutsche Lufthansa'), (3) Kandidaten nur mit einer Screener-Zeile
('Tech LONG conf=0.80 ...') enthalten keine Meinung, die sich validieren ließe. Jetzt: nur Kandidaten mit Mention in
den letzten 14 Tagen, Begründungen der letzten 30 Tage über Name, Ticker, Aliase und Namens-Key, Kandidaten ohne
Meinungs-Begründung werden ohne LLM-Call übersprungen (llm_verdict 'SKIPPED ...'), der Prompt nennt Technik und
Entscheidungsregeln, am Ende steht eine Zählzeile.
"""
import json, os, requests, sqlite3
import sys
from datetime import datetime, timedelta

# Projektwurzel aus dem Dateiort (live wie in einer Sandbox-Kopie), scripts/ fuer watchlist_dedup
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))
sys.path.insert(0, _ROOT)
import env_loader  # noqa: F401  (side-effect: laedt .env)
from config import DB_PATH, db_connect, DETERMINISTIC_CHANNELS  # noqa: F401

OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY")
VALIDATION_MODEL = "deepseek/deepseek-v4.1-flash"
FRESH_DAYS = 14        # nur Kandidaten mit Mention in den letzten 14 Tagen (wie der Stale-Drop der Watchlist)
REASON_DAYS = 30       # Begründungen der letzten 30 Tage
MAX_REASONS = 8
MIN_KEY_LEN = 3        # Namens-Keys kürzer als 3 Zeichen nur als exakter Treffer


def _name_key(name):
    """Vergleichs-Key wie in watchlist_dedup ('Deutsche Lufthansa AG' == 'Deutsche Lufthansa')."""
    try:
        from watchlist_dedup import _name_compare_key
        return _name_compare_key(name or "")
    except Exception:
        return (name or "").strip().lower()


def collect_reasons(con, name, ticker, days=REASON_DAYS, today=None):
    """[(kanal, begründung)] der letzten `days` Tage, neueste zuerst.

    Treffer über den Watchlist-Namen, das Tickersymbol, die Aliase des Tickers (company_aliases) und den
    Namens-Key dieser Schreibweisen."""
    since = ((today or datetime.now()) - timedelta(days=days)).strftime("%Y-%m-%d")
    exact = {(name or "").strip().lower(), (ticker or "").strip().lower()}
    keys = {_name_key(name), _name_key(ticker)}
    try:
        for (alias,) in con.execute("SELECT alias FROM company_aliases WHERE ticker = ?", (ticker,)).fetchall():
            exact.add((alias or "").strip().lower())
            keys.add(_name_key(alias))
    except sqlite3.Error:
        pass
    exact.discard("")
    keys = {k for k in keys if len(k) >= MIN_KEY_LEN}
    rows = con.execute("""
        SELECT name, channel, reason FROM watchlist_mentions
        WHERE reason IS NOT NULL AND reason != '' AND mention_date >= ?
        ORDER BY mention_date DESC, id DESC
    """, (since,)).fetchall()
    out = []
    for r in rows:
        mname = (r["name"] or "").strip()
        if mname.lower() in exact or _name_key(mname) in keys:
            out.append((r["channel"] or "?", r["reason"]))
    return out


def validate_signal(name, ticker, sentiment, mentions, reasons, tech=None):
    """
    Fragt zweites LLM ob das Signal plausibel ist.
    reasons: Liste '[Kanal] Begründung'; tech: (tech_direction, tech_score) oder None.
    Returns: ('CONFIRMED'|'CONTRADICTED'|'UNCERTAIN', Begründung)
    """
    if not OPENROUTER_KEY:
        return "UNCERTAIN", "OPENROUTER_API_KEY nicht gesetzt"

    tech_line = ""
    if tech and tech[1] is not None:
        tech_line = f"Technik: {tech[0] or '?'}, Score {float(tech[1]):.2f} (0 = stark bearish, 1 = stark bullish)\n"
    reason_lines = "\n".join(f"- {r}" for r in reasons[:MAX_REASONS]) or "- (keine)"
    prompt = f"""Du bist ein erfahrener Aktienanalyst. Prüfe ein Trading-Signal, das aus YouTube-, RSS- und X-Quellen stammt.

Aktie: {name} ({ticker})
Richtung laut Quellen: {sentiment} ({mentions} Erwähnungen in 30 Tagen)
{tech_line}
Aussagen der Quellen (neueste zuerst, [Kanal] Begründung):
{reason_lines}

Frage: Ist die Richtung "{sentiment}" durch diese Aussagen und durch das, was du über das Unternehmen weißt, gedeckt?
- CONFIRMED: Die Aussagen stützen die Richtung inhaltlich (konkrete Gründe, Katalysatoren, Zahlen) und du kennst keinen offensichtlichen Gegengrund.
- CONTRADICTED: Die Aussagen stützen die Richtung nicht (sie widersprechen ihr oder sind nur beiläufige Erwähnungen ohne Bewertung), oder es gibt einen offensichtlichen Gegengrund.
- UNCERTAIN: Nur wenn sich Für und Wider die Waage halten oder du das Unternehmen nicht einordnen kannst.

Antworte NUR mit einem JSON-Objekt:
{{"verdict": "CONFIRMED|CONTRADICTED|UNCERTAIN", "reason": "kurze Begründung"}}"""

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": VALIDATION_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                # FIX 28.09.2026: deepseek-v4-flash ist ein Reasoning-Modell; bei
                # max_tokens=200 verbrauchte das Reasoning das Limit -> leeres oder
                # abgeschnittenes content, Testlauf: 10/10 UNCERTAIN. Reasoning aus
                # wie beim Analysten im signal_extractor (gemessen 22.09.).
                "max_tokens": 400,
                "reasoning": {"enabled": False},
                "temperature": 0.1,
            },
            timeout=30,
        )
        if response.status_code == 401:
            print(f"  ⚠ Auth-Fehler 401: OPENROUTER_API_KEY ungültig oder abgelaufen", flush=True)
            return "UNCERTAIN", "Auth 401"
        if response.status_code != 200:
            print(f"  ⚠ HTTP {response.status_code}: {response.text[:200]}", flush=True)
            return "UNCERTAIN", f"HTTP {response.status_code}"
        data = response.json()
        text = data["choices"][0]["message"].get("content")
        if not text:
            print(f"  ⚠ LLM gab leeres Content-Feld zurück", flush=True)
            return "UNCERTAIN", "empty LLM response"
        text = text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        result = json.loads(text)
        verdict = str(result.get("verdict", "UNCERTAIN")).upper().strip()
        if verdict not in ("CONFIRMED", "CONTRADICTED", "UNCERTAIN"):
            verdict = "UNCERTAIN"
        return verdict, result.get("reason", "")
    except Exception as e:
        print(f"  ⚠ LLM-Validierung fehlgeschlagen: {e}", flush=True)
        return "UNCERTAIN", str(e)


def run(con, validate=None, today=None):
    """Validiert die Top-Kandidaten und schreibt conviction_score/llm_verdict. Gibt die Zählung je Urteil zurück."""
    validate = validate or validate_signal
    now = today or datetime.now()
    fresh = (now - timedelta(days=FRESH_DAYS)).strftime("%Y%m%d")
    candidates = con.execute("""
        SELECT w.name, w.ticker, w.conviction_score, w.mention_count,
               w.bullish_count, w.bearish_count, w.channels,
               w.tech_score, w.tech_direction
        FROM watchlist w
        WHERE w.status = 'watching'
        AND w.conviction_score >= 0.70
        AND w.ticker IS NOT NULL
        AND w.tech_score >= 0.50
        AND replace(substr(COALESCE(w.last_seen, ''), 1, 10), '-', '') >= ?
        ORDER BY w.conviction_score DESC
        LIMIT 10
    """, (fresh,)).fetchall()

    print(f"🔍 LLM-Validierung für {len(candidates)} Kandidaten...", flush=True)
    stats = {"CONFIRMED": 0, "CONTRADICTED": 0, "UNCERTAIN": 0, "SKIPPED": 0}
    stamp = now.strftime("%Y-%m-%d %H:%M")

    for c in candidates:
        found = collect_reasons(con, c["name"], c["ticker"], today=now)
        opinion = [f"[{ch}] {r}" for ch, r in found if ch not in DETERMINISTIC_CHANNELS]
        if not opinion:
            stats["SKIPPED"] += 1
            print(f"  ⏭ {c['name']:25} übersprungen (keine Meinungs-Begründung, nur Screener)")
            con.execute("UPDATE watchlist SET llm_verdict=?, llm_verdict_at=? WHERE ticker=? AND name=?",
                        ("SKIPPED (keine Meinungs-Begründung)", stamp, c["ticker"], c["name"]))
            continue

        sentiment = "bullish" if (c["bullish_count"] or 0) > (c["bearish_count"] or 0) else "bearish"
        verdict, reason = validate(c["name"], c["ticker"], sentiment, c["mention_count"], opinion,
                                   tech=(c["tech_direction"], c["tech_score"]))
        verdict = verdict if verdict in stats else "UNCERTAIN"
        stats[verdict] += 1

        if verdict == "CONFIRMED":
            boost = min(0.10, 0.05 * (c["mention_count"] / 5))
            new_conv = min(1.0, c["conviction_score"] + boost)
            delta_str = f"+{boost:.2f}"
            print(f"  ✅ {c['name']:25} CONFIRMED ({delta_str}) → {new_conv:.2f}")
        elif verdict == "CONTRADICTED":
            penalty = 0.15
            new_conv = max(0.0, c["conviction_score"] - penalty)
            delta_str = f"-{penalty:.2f}"
            print(f"  ❌ {c['name']:25} CONTRADICTED ({delta_str}) → {new_conv:.2f}")
        else:
            new_conv = c["conviction_score"]
            delta_str = "0.00"
            print(f"  ❓ {c['name']:25} UNCERTAIN (unverändert)")
        if reason:
            print(f"     {str(reason)[:140]}", flush=True)

        # conviction_score_raw bleibt unangetastet (channel-basierter Rohwert).
        # conviction_score enthält den LLM-validierten Wert.
        con.execute("""
            UPDATE watchlist
            SET conviction_score=?,
                llm_verdict=?,
                llm_verdict_at=?
            WHERE ticker=? AND name=?
        """, (round(new_conv, 3), f"{verdict} ({delta_str})", stamp, c["ticker"], c["name"]))

    con.commit()
    print(f"  → CONFIRMED {stats['CONFIRMED']} | CONTRADICTED {stats['CONTRADICTED']} | "
          f"UNCERTAIN {stats['UNCERTAIN']} | übersprungen {stats['SKIPPED']}", flush=True)
    return stats


def main():
    if not OPENROUTER_KEY:
        print("⚠ OPENROUTER_API_KEY nicht gesetzt – überspringe LLM-Validierung")
        return

    con = db_connect()
    try:
        run(con)
        print("✅ LLM-Validierung abgeschlossen", flush=True)
    finally:
        con.close()


if __name__ == "__main__":
    main()
