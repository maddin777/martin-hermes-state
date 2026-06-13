"""
Script 2: Signal Extractor mit Chunking
Liest pending Videos aus SQLite, analysiert mit Gemini Flash Lite
Chunks langes Transkript in 15.000-Zeichen-Abschnitte
"""
import sqlite3
import requests
import json
import os
import sys
sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")
import env_loader  # noqa: F401  (side-effect: laedt .env)
from datetime import datetime
from utils import get_logger, retry
log = get_logger("signal_extractor")
from config import DB_PATH, SIGNALS_PATH, db_connect

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
MODEL = "deepseek/deepseek-v4-flash"
CHUNK_SIZE = 15000
OVERLAP = 1000

SYSTEM_PROMPT = """Du bist ein erfahrener Finanzanalyst, der YouTube-Transkripte auf Unternehmensnennungen scannt.
Analysiere einen Ausschnitt eines YouTube-Transkripts eines deutschen Finanzkanals.
Extrahiere ALLE explizit erwähnten börsennotierten Unternehmen - auch obskure, kleine oder unbekannte.
SEI GROSSZÜGIG: Wenn ein Unternehmen genannt wird, nimm es auf. Lieber ein falsches Positives als ein verpasstes Unternehmen.
Der Name kann im Transkript falsch ausgesprochen oder geschrieben sein - erkenne das Unternehmen trotzdem.

Verwende IMMER den vollständigen Unternehmensnamen, KEINE Tickersymbole.
Antworte NUR mit validem JSON, kein Text davor oder danach, keine Markdown-Backticks:
{
  "companies": [
    {
      "name": "Nike",
      "sentiment": "bearish",
      "strength": "strong",
      "reason": "12-Jahrestief, strukturelle Probleme laut Analyse",
      "mentioned_price": null,
      "price_target": null,
      "action_hint": "watch_for_reversal"
    }
  ],
  "market_outlook": "bearish",
  "key_themes": ["Iran-Konflikt", "DAX Allzeithoch"]
}
sentiment: bullish | bearish | neutral
strength: strong | moderate | weak
action_hint: buy | sell | watch_for_reversal | avoid | hold
Regeln:
- JEDES börsennotierte Unternehmen extrahieren (keine Universitäten, Personen, NGOs)
- Auch Unternehmen im Videotitel berücksichtigen
- Bei Unsicherheit: LIEBER AUFNEHMEN als weglassen
- Nur Unternehmen die explizit im Text erwähnt werden
- Keine Duplikate
- VOLLSTAENDIGE NAMEN: Gib immer den vollstaendigen offiziellen Firmennamen an. FALSCH: "Kri", "Konk", "Haid", "Macy" (abgeschnitten). RICHTIG: "Krispy Kreme", "ConocoPhillips", "Haidilao", "Macy's"
- KEINE Ticker im name-Feld: Schreibe "NVIDIA" nicht "NVDA" oder "NVD.DE"
- Mindestlaenge: Namen mit weniger als 4 Zeichen NICHT aufnehmen"""


FALLBACK_MODEL = "openai/gpt-4o-mini"


def call_api(chunk, channel, title, date, chunk_num, total_chunks):
    user_content = (
        f"Kanal: {channel}\nTitel: {title}\nDatum: {date}\n"
        f"Transkript-Abschnitt {chunk_num}/{total_chunks}:\n\n{chunk}"
    )

    @retry(max_attempts=3, backoff=2.0, exceptions=(requests.RequestException, KeyError))
    def _request(model, system_extra=""):
        try:
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "max_tokens": 4000,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT + system_extra},
                        {"role": "user",   "content": user_content}
                    ]
                },
                timeout=60
            )
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"     ⚠ API-Verbindungsfehler ({model}): {e}", flush=True)
            raise
        data = r.json()
        if "choices" not in data:
            raise KeyError(f"Keine 'choices' in API-Antwort: {data}")
        text = data["choices"][0]["message"]["content"].strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return text.strip()

    def _try_parse(text):
        """JSON parsen, bei Fehler regex-repair versuchen."""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Regex-repair: ersetze einfache Anführungszeichen, trailing commas, etc.
            import re
            fixed = re.sub(r",\s*}", "}", text)  # trailing comma vor }
            fixed = re.sub(r",\s*]", "]", fixed)  # trailing comma vor ]
            fixed = re.sub(r"(?<!\\)'(?=[^']*':)", '"', fixed)  # 'key': -> "key":
            fixed = re.sub(r":\s*'([^']*)'", r': "\1"', fixed)  # : 'value' -> : "value"
            # Entferne Steuerzeichen
            fixed = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', fixed)
            try:
                return json.loads(fixed)
            except json.JSONDecodeError:
                raise

    # Versuch 1: DeepSeek mit max_tokens=4000
    try:
        content = _request(MODEL)
        return _try_parse(content)
    except json.JSONDecodeError:
        print("     ⚠ JSON Fehler DeepSeek, versuche gpt-4o-mini...", flush=True)

    # Versuch 2: Fallback auf gpt-4o-mini (liefert sehr verlässliches JSON)
    try:
        content = _request(FALLBACK_MODEL)
        return _try_parse(content)
    except json.JSONDecodeError as e:
        print(f"     ⚠ Auch gpt-4o-mini JSON fehlerhaft: {e}, überspringe", flush=True)
        return {"companies": [], "market_outlook": "neutral", "key_themes": []}


def merge_results(results):
    seen = {}
    themes = []
    outlooks = []
    strength_order = {"strong": 3, "moderate": 2, "weak": 1}

    for result in results:
        for company in result.get("companies", []):
            key = company["name"].lower().strip()
            if key not in seen:
                seen[key] = company
            else:
                if strength_order.get(company.get("strength","weak"), 0) > \
                   strength_order.get(seen[key].get("strength","weak"), 0):
                    seen[key] = company
        for theme in result.get("key_themes", []):
            if theme not in themes:
                themes.append(theme)
        if result.get("market_outlook"):
            outlooks.append(result["market_outlook"])

    return {
        "companies": list(seen.values()),
        "market_outlook": max(set(outlooks), key=outlooks.count) if outlooks else "neutral",
        "key_themes": themes[:10]
    }


def analyze(transcript, channel, title, date):
    chunks = []
    start = 0
    t_len = len(transcript)
    while start < t_len:
        end = min(start + CHUNK_SIZE + OVERLAP, t_len)
        chunks.append(transcript[start:end])
        start += CHUNK_SIZE
        if start >= t_len:
            break

    total = len(chunks)
    print(f"     → {len(transcript)} Zeichen, {total} Chunk(s)", flush=True)
    results = []
    for i, chunk in enumerate(chunks, 1):
        print(f"     → Chunk {i}/{total}...", flush=True)
        results.append(call_api(chunk, channel, title, date, i, total))
    return merge_results(results)


def main():
    con = db_connect()
    pending = con.execute(
        "SELECT * FROM videos WHERE status='pending' ORDER BY upload_date DESC"
    ).fetchall()

    print(f"Pending Videos: {len(pending)}", flush=True)

    # Signals-JSON laden (Append-only – bestehende Ergebnisse bleiben)
    if os.path.exists(SIGNALS_PATH):
        with open(SIGNALS_PATH, encoding="utf-8") as f:
            all_signals = json.load(f)
    else:
        all_signals = []

    # Cache: video_ids die bereits analysiert wurden (aus DB – robust gegen JSON-Verlust)
    done_ids = {
        row["video_id"]
        for row in con.execute(
            "SELECT video_id FROM videos WHERE status='done'"
        ).fetchall()
    }

    for row in pending:
        print(f"\n[{row['channel']}] {row['title'][:60]}...", flush=True)

        # DB-Status ist der primäre Cache (robust gegen JSON-Verlust)
        if row['video_id'] in done_ids:
            print("  ⏭ Bereits analysiert (DB-Cache)", flush=True)
            continue

        try:
            result = analyze(row['transcript'], row['channel'], row['title'], row['upload_date'])
            result["source"] = {
                "channel":  row['channel'],
                "title":    row['title'],
                "date":     row['upload_date'],
                "video_id": row['video_id']
            }
            companies = result.get('companies', [])
            print(f"  ✓ {len(companies)} Unternehmen: {[c['name'] for c in companies]}", flush=True)
            con.execute(
                "UPDATE videos SET status='done', analyzed_at=? WHERE video_id=?",
                (datetime.now().isoformat(), row['video_id'])
            )
            con.commit()
            all_signals.append(result)

        except Exception as e:
            print(f"  ✗ Fehler: {e}", flush=True)
            con.execute("UPDATE videos SET status='error' WHERE video_id=?", (row['video_id'],))
            con.commit()

    os.makedirs(os.path.dirname(SIGNALS_PATH), exist_ok=True)
    with open(SIGNALS_PATH, "w", encoding="utf-8") as f:
        json.dump(all_signals, f, ensure_ascii=False, indent=2)

    total_co = sum(len(s.get('companies', [])) for s in all_signals)
    print(f"\n✅ Fertig. {len(all_signals)} Videos, {total_co} Unternehmen.", flush=True)
    con.close()


if __name__ == "__main__":
    main()
