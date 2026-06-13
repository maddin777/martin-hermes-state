"""
LLM-Kreuzvalidierung für High-Conviction Signale.
Läuft NACH watchlist_manager.py, VOR signal_manager.py.
Nur für Kandidaten mit conviction >= 0.70.
"""
import json, os, requests, sqlite3
import sys
from datetime import datetime
sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")
import env_loader  # noqa: F401  (side-effect: laedt .env)
from datetime import datetime
from config import DB_PATH, db_connect

OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY")
VALIDATION_MODEL = "deepseek/deepseek-v4-flash"


def validate_signal(name, ticker, sentiment, mentions, reasons):
    """
    Fragt zweites LLM ob das Signal plausibel ist.
    Returns: 'confirmed', 'contradicted', 'uncertain'
    """
    if not OPENROUTER_KEY:
        return "UNCERTAIN", "OPENROUTER_API_KEY nicht gesetzt"

    prompt = f"""Du bist ein erfahrener Aktienanalyst. Bewerte folgendes Trading-Signal:

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
        if response.status_code == 401:
            print(f"  ⚠ Auth-Fehler 401: OPENROUTER_API_KEY ungültig oder abgelaufen", flush=True)
            return "UNCERTAIN", "Auth 401"
        if response.status_code != 200:
            print(f"  ⚠ HTTP {response.status_code}: {response.text[:200]}", flush=True)
            return "UNCERTAIN", f"HTTP {response.status_code}"
        data = response.json()
        text = data["choices"][0]["message"]["content"]
        text = text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        result = json.loads(text)
        return result.get("verdict", "UNCERTAIN"), result.get("reason", "")
    except Exception as e:
        print(f"  ⚠ LLM-Validierung fehlgeschlagen: {e}", flush=True)
        return "UNCERTAIN", str(e)


def main():
    if not OPENROUTER_KEY:
        print("⚠ OPENROUTER_API_KEY nicht gesetzt – überspringe LLM-Validierung")
        return

    con = db_connect()
    try:
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

            # conviction_score_raw bleibt unangetastet (channel-basierter Rohwert).
            # conviction_score enthält den LLM-validierten Wert.
            # llm_verdict + llm_delta für Dashboard-Diagnose (Migration via init_db in signal_manager).
            con.execute("""
                UPDATE watchlist
                SET conviction_score=?,
                    llm_verdict=?,
                    llm_verdict_at=?
                WHERE ticker=? AND name=?
            """, (round(new_conv, 3), f"{verdict} ({delta_str})",
                  datetime.now().strftime("%Y-%m-%d %H:%M"),
                  c["ticker"], c["name"]))

        con.commit()
        print("✅ LLM-Validierung abgeschlossen", flush=True)
    finally:
        con.close()


if __name__ == "__main__":
    main()
