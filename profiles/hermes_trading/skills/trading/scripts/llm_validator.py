"""
LLM-Kreuzvalidierung für High-Conviction Signale.
Läuft NACH watchlist_manager.py, VOR signal_manager.py.
Nur für Kandidaten mit conviction >= 0.70.
"""
import json, os, requests, sqlite3
import sys
sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")
import env_loader  # noqa: F401  (side-effect: laedt .env)
from datetime import datetime

DB_PATH = "/root/.hermes/profiles/hermes_trading/skills/trading/data/trading.db"
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY")
VALIDATION_MODEL = "openrouter/owl-alpha"


def validate_signal(name, ticker, sentiment, mentions, reasons):
    """
    Fragt zweites LLM ob das Signal plausibel ist.
    Returns: 'confirmed', 'contradicted', 'uncertain'
    """
    prompt = """Du bist ein erfahrener Aktienanalyst. Bewerte folgendes Trading-Signal:

Aktie: {name} ({ticker})
Sentiment aus Quellen: {sentiment} (basierend auf {mentions} Erwähnungen)
Begründungen der Quellen: {'; '.join(reasons[:5])}

Aufgabe:
1. Ist das Sentiment logisch nachvollziehbar?
2. Gibt es offensichtliche Gegenargumente?
3. Bewertung: CONFIRMED, CONTRADICTED, oder UNCERTAIN

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
                "max_tokens": 200,
                "temperature": 0.1,
            },
            timeout=30,
        )
        data = response.json()
        text = data["choices"][0]["message"]["content"]
        result = json.loads(text.strip().strip("```json").strip("```"))
        return result.get("verdict", "UNCERTAIN"), result.get("reason", "")
    except Exception as e:
        print(f"  ⚠ LLM-Validierung fehlgeschlagen: {e}")
        return "UNCERTAIN", str(e)


def main():
    if not OPENROUTER_KEY:
        print("⚠ OPENROUTER_API_KEY nicht gesetzt – überspringe LLM-Validierung")
        return

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    candidates = con.execute("""
        SELECT w.name, w.ticker, w.conviction_score, w.mention_count,
               w.bullish_count, w.bearish_count, w.channels,
               w.tech_score, w.tech_direction
        FROM watchlist w
        WHERE w.status = 'watching'
        AND w.conviction_score >= 0.70
        AND w.ticker IS NOT NULL
        AND w.tech_score >= 0.50
        ORDER BY w.conviction_score DESC
        LIMIT 10
    """).fetchall()

    print(f"🔍 LLM-Validierung für {len(candidates)} Kandidaten...", flush=True)

    for c in candidates:
        reasons = [r[0] for r in con.execute("""
            SELECT reason FROM watchlist_mentions
            WHERE name = ? AND reason IS NOT NULL AND reason != ''
            ORDER BY mention_date DESC LIMIT 5
        """, (c["name"],)).fetchall()]

        sentiment = "bullish" if c["bullish_count"] > c["bearish_count"] else "bearish"

        verdict, reason = validate_signal(
            c["name"], c["ticker"], sentiment,
            c["mention_count"], reasons
        )

        if verdict == "CONFIRMED":
            boost = min(0.10, 0.05 * (c["mention_count"] / 5))
            new_conv = min(1.0, c["conviction_score"] + boost)
            print(f"  ✅ {c['name']:25} CONFIRMED (+{boost:.2f}) → {new_conv:.2f}")
        elif verdict == "CONTRADICTED":
            penalty = 0.15
            new_conv = max(0.0, c["conviction_score"] - penalty)
            print(f"  ❌ {c['name']:25} CONTRADICTED (-{penalty:.2f}) → {new_conv:.2f}")
        else:
            new_conv = c["conviction_score"]
            print(f"  ❓ {c['name']:25} UNCERTAIN (unverändert)")

        con.execute(
            "UPDATE watchlist SET conviction_score=? WHERE name=?",
            (round(new_conv, 3), c["name"])
        )

    con.commit()
    con.close()
    print("✅ LLM-Validierung abgeschlossen", flush=True)


if __name__ == "__main__":
    main()
