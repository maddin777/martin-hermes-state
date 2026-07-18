"""
Script 2: Signal Extractor mit Chunking

Zwei Modi (Umschalter: Environment-Variable EXTRACTOR_MODE):

  two_pass (Default, Rollen-Sprint R3)
      Pass A "Scout"   – pro Chunk, NUR Firmenerkennung + wörtliches Snippet
                         + grobes Fallback-Sentiment.
      Pass B "Analyst" – EIN Call pro Video, sieht NICHT das Transkript, nur die
                         deduplizierte Firmenliste mit Snippets. Liefert das
                         fundierte Urteil (sentiment/strength/reason/…/catalyst).

  legacy
      Der bisherige Mega-Prompt pro Chunk, vollständig unverändert erhalten.
      Per Env-Var ohne Deploy erreichbar → Rollback ist ein Einzeiler in der
      Crontab, kein Deploy.

Das finale Ergebnis-Objekt pro Video ist in BEIDEN Modi byte-kompatibel zum
bisherigen Format (companies mit name/sentiment/strength/reason/mentioned_price/
price_target/action_hint, plus market_outlook, key_themes, source).
`catalyst` ist ein rein additives Feld und fließt in diesem Sprint NICHT in
Conviction/Scoring – watchlist_manager bleibt unangetastet.
"""
import sqlite3
import requests
import json
import os
import sys
sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")
import env_loader  # noqa: F401  (side-effect: laedt .env)
from datetime import datetime, date
from utils import get_logger, retry
log = get_logger("signal_extractor")
from config import DB_PATH, SIGNALS_PATH, db_connect

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
MODEL = "deepseek/deepseek-v4-flash"
FALLBACK_MODEL = "openai/gpt-4o-mini"
CHUNK_SIZE = 15000
OVERLAP = 1000

# two_pass | legacy — Rollback ohne Deploy
EXTRACTOR_MODE = os.environ.get("EXTRACTOR_MODE", "two_pass").strip().lower()

# Max. Snippets pro Firma, die an den Analyst gehen (Kostendeckel)
MAX_SNIPPETS_PER_COMPANY = 3


# ── Legacy-Prompt (unverändert) ───────────────────────────────────────────────
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


# ── Pass A: Scout — NUR Erkennung ─────────────────────────────────────────────
# Die Erkennungsregeln sind bewusst wortgleich zum Legacy-Prompt: die
# Erkennungsleistung ist heute gut und soll sich durch den Umbau NICHT ändern.
# Weggelassen ist alles, was Urteil war (sentiment/strength/reason/Preisziele).
SCOUT_PROMPT = """Du bist ein Scout, der YouTube-Transkripte auf Unternehmensnennungen scannt.
Analysiere einen Ausschnitt eines YouTube-Transkripts eines deutschen Finanzkanals.
Extrahiere ALLE explizit erwähnten börsennotierten Unternehmen - auch obskure, kleine oder unbekannte.
SEI GROSSZÜGIG: Wenn ein Unternehmen genannt wird, nimm es auf. Lieber ein falsches Positives als ein verpasstes Unternehmen.
Der Name kann im Transkript falsch ausgesprochen oder geschrieben sein - erkenne das Unternehmen trotzdem.

Deine EINZIGE Aufgabe ist die ERKENNUNG. Du bewertest nicht und analysierst nicht.
Ein anderer Analyst urteilt später auf Basis der Zitate, die du lieferst.

Verwende IMMER den vollständigen Unternehmensnamen, KEINE Tickersymbole.
Antworte NUR mit validem JSON, kein Text davor oder danach, keine Markdown-Backticks:
{
  "companies": [
    {
      "name": "Nike",
      "context_snippet": "wörtliches Zitat aus dem Transkript, max 300 Zeichen",
      "rough_sentiment": "bearish"
    }
  ],
  "market_outlook": "bearish",
  "key_themes": ["Iran-Konflikt", "DAX Allzeithoch"]
}
context_snippet: das WÖRTLICHE Zitat aus dem Transkript, in dem die Firma vorkommt.
  So viel Kontext wie möglich, max 300 Zeichen. Keine Paraphrase, keine Interpretation.
rough_sentiment: bullish | bearish | neutral — nur eine grobe Einordnung als
  Fallback. Im Zweifel "neutral".
market_outlook: bullish | bearish | neutral
Regeln:
- JEDES börsennotierte Unternehmen extrahieren (keine Universitäten, Personen, NGOs)
- Auch Unternehmen im Videotitel berücksichtigen
- Bei Unsicherheit: LIEBER AUFNEHMEN als weglassen
- Nur Unternehmen die explizit im Text erwähnt werden
- Keine Duplikate
- VOLLSTAENDIGE NAMEN: Gib immer den vollstaendigen offiziellen Firmennamen an. FALSCH: "Kri", "Konk", "Haid", "Macy" (abgeschnitten). RICHTIG: "Krispy Kreme", "ConocoPhillips", "Haidilao", "Macy's"
- KEINE Ticker im name-Feld: Schreibe "NVIDIA" nicht "NVDA" oder "NVD.DE"
- Mindestlaenge: Namen mit weniger als 4 Zeichen NICHT aufnehmen"""


# ── Pass B: Analyst — Urteil auf Basis der Snippets ───────────────────────────
ANALYST_PROMPT = """Du bist ein erfahrener Finanzanalyst.

Ein Scout hat aus einem YouTube-Video eines deutschen Finanzkanals Firmennennungen
mit den zugehörigen wörtlichen Transkript-Zitaten extrahiert. Du bekommst NICHT das
Transkript, sondern nur diese Zitate.

Deine Aufgabe: Fälle pro Firma ein fundiertes Urteil darüber, was der Kanal über sie
sagt. Bewerte, was IM ZITAT steht – nicht deine eigene Marktmeinung über die Aktie.

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
      "action_hint": "watch_for_reversal",
      "catalyst": "none"
    }
  ]
}
sentiment: bullish | bearish | neutral
strength: strong | moderate | weak
action_hint: buy | sell | watch_for_reversal | avoid | hold
catalyst: earnings | product | macro | legal | technical | none
Regeln:
- Gib JEDE Firma aus der Eingabeliste zurück, exakt mit dem gelieferten Namen.
  Keine Firma weglassen, keine erfinden, Namen NICHT umschreiben oder korrigieren.
- reason: kurze Begründung, max 120 Zeichen, aus dem Zitat abgeleitet.
- Ist ein Zitat zu dünn für ein Urteil: sentiment "neutral", strength "weak".
- mentioned_price / price_target: nur wenn im Zitat eine konkrete Zahl genannt wird,
  sonst null. Nichts schätzen, nichts aus eigenem Wissen ergänzen.
- catalyst: der konkrete Auslöser laut Zitat. Kein erkennbarer Auslöser → "none"."""


# ══ Generischer API-Layer (Legacy und 2-Pass teilen sich das) ═════════════════

def _call(model, system_prompt, user_content, system_extra="", max_tokens=4000):
    """
    Ein einzelner OpenRouter-Call.

    Returns: (text, tokens_in, tokens_out)
    Retry-Logik unverändert aus dem bisherigen call_api() übernommen.
    """
    @retry(max_attempts=3, backoff=2.0, exceptions=(requests.RequestException, KeyError))
    def _request():
        try:
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "max_tokens": max_tokens,
                    "messages": [
                        {"role": "system", "content": system_prompt + system_extra},
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
        msg_content = data["choices"][0]["message"].get("content")
        if not msg_content:
            raise KeyError(
                f"Leeres content-Feld in API-Antwort: "
                f"{data.get('choices', [{}])[0].get('message', {})}"
            )
        text = msg_content.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        usage = data.get("usage", {}) or {}
        return (text.strip(),
                int(usage.get("prompt_tokens", 0) or 0),
                int(usage.get("completion_tokens", 0) or 0))

    return _request()


def _try_parse(text):
    """JSON parsen, bei Fehler konservative Reparatur versuchen."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        import re
        fixed = text
        # Nur strukturelle Fehler reparieren, keine Strings manipulieren
        fixed = re.sub(r",\s*}", "}", fixed)    # trailing comma vor }
        fixed = re.sub(r",\s*]", "]", fixed)    # trailing comma vor ]
        # Steuerzeichen entfernen (außer \t \n \r die in JSON legal sind)
        fixed = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', fixed)
        # KEIN Apostrophen-Ersatz: würde Macy's, L'Oréal, etc. zerstören.
        # Stattdessen: beim Retry das Modell explizit zu reinem JSON drängen.
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            raise


_STRICT_EXTRA = ("\n\nWICHTIG: Antworte AUSSCHLIESSLICH mit validem JSON. "
                 "Keine Markdown-Blöcke, kein Text davor oder danach. "
                 "Alle Strings in doppelten Anführungszeichen.")


def _call_cascade(system_prompt, user_content, primary_model=MODEL,
                  default=None, max_tokens=4000):
    """
    Die dreistufige Fallback-Kaskade des bisherigen call_api(), jetzt generisch
    für Legacy-, Scout- und Analyst-Calls:

      1. primary_model
      2. primary_model + strengerer JSON-Hinweis
      3. gpt-4o-mini (liefert sehr verlässliches JSON)

    Fehlerverhalten IDENTISCH zum bisherigen call_api():
      - Nur ein json.JSONDecodeError eskaliert auf die nächste Stufe.
      - Alle anderen Exceptions (Netzwerk, KeyError, …) propagieren nach oben,
        nachdem @retry sie 3x versucht hat. main() setzt das Video dann auf
        status='error' + error_count+1 → es wird beim nächsten Lauf erneut
        versucht. Würde die Kaskade sie schlucken, wäre das Video 'done' mit 0
        Firmen und käme nie wieder – stiller Datenverlust.

    Returns: (parsed_dict, tokens_in, tokens_out).
    Bei erschöpfter JSON-Kaskade: (default, tokens_in, tokens_out).
    """
    t_in = t_out = 0

    attempts = (
        (primary_model, "", "retry mit strengerem Prompt"),
        (primary_model, _STRICT_EXTRA, "versuche gpt-4o-mini"),
        (FALLBACK_MODEL, "", None),
    )

    for idx, (model, extra, next_step) in enumerate(attempts):
        try:
            content, ti, to = _call(model, system_prompt, user_content,
                                    system_extra=extra, max_tokens=max_tokens)
            t_in += ti
            t_out += to
            return _try_parse(content), t_in, t_out
        except json.JSONDecodeError as e:
            if next_step:
                print(f"     ⚠ JSON Fehler {model}, {next_step}...", flush=True)
            else:
                print(f"     ⚠ Auch {model} JSON fehlerhaft: {e}, überspringe",
                      flush=True)

    return (default if default is not None else {}), t_in, t_out


# ══ Legacy-Pfad (Verhalten unverändert) ══════════════════════════════════════

def call_api(chunk, channel, title, date_str, chunk_num, total_chunks):
    user_content = (
        f"Kanal: {channel}\nTitel: {title}\nDatum: {date_str}\n"
        f"Transkript-Abschnitt {chunk_num}/{total_chunks}:\n\n{chunk}"
    )
    parsed, _ti, _to = _call_cascade(
        SYSTEM_PROMPT, user_content,
        default={"companies": [], "market_outlook": "neutral", "key_themes": []},
    )
    return parsed


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
                if strength_order.get(company.get("strength", "weak"), 0) > \
                   strength_order.get(seen[key].get("strength", "weak"), 0):
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


# ══ 2-Pass-Pfad (Rollen-Sprint R3) ═══════════════════════════════════════════

def call_scout(chunk, channel, title, date_str, chunk_num, total_chunks):
    """Pass A: reine Erkennung pro Chunk."""
    user_content = (
        f"Kanal: {channel}\nTitel: {title}\nDatum: {date_str}\n"
        f"Transkript-Abschnitt {chunk_num}/{total_chunks}:\n\n{chunk}"
    )
    parsed, _ti, _to = _call_cascade(
        SCOUT_PROMPT, user_content,
        default={"companies": [], "market_outlook": "neutral", "key_themes": []},
    )
    return parsed


def merge_scout_results(results):
    """
    Dedupliziert Firmen über alle Chunks und sammelt bis zu
    MAX_SNIPPETS_PER_COMPANY Snippets pro Firma.

    Folgt dem bestehenden merge_results-Muster (Key = name.lower().strip()).
    """
    seen = {}
    themes = []
    outlooks = []

    for result in results:
        for company in result.get("companies", []):
            name = (company.get("name") or "").strip()
            if not name:
                continue
            key = name.lower()
            snippet = (company.get("context_snippet") or "")[:300]
            if key not in seen:
                seen[key] = {
                    "name": name,
                    "snippets": [snippet] if snippet else [],
                    "rough_sentiment": company.get("rough_sentiment") or "neutral",
                }
            else:
                s = seen[key]
                if snippet and len(s["snippets"]) < MAX_SNIPPETS_PER_COMPANY \
                        and snippet not in s["snippets"]:
                    s["snippets"].append(snippet)
                # Ein nicht-neutrales Sentiment schlägt ein neutrales
                if s["rough_sentiment"] == "neutral" and \
                        company.get("rough_sentiment") in ("bullish", "bearish"):
                    s["rough_sentiment"] = company["rough_sentiment"]
        for theme in result.get("key_themes", []):
            if theme not in themes:
                themes.append(theme)
        if result.get("market_outlook"):
            outlooks.append(result["market_outlook"])

    return {
        "companies": list(seen.values()),
        "market_outlook": max(set(outlooks), key=outlooks.count) if outlooks else "neutral",
        "key_themes": themes[:10],
    }


def _scout_fallback(scout_companies):
    """
    Fallback-Kaskade Stufe 1: Pass B nicht verfügbar (Fehler/Parse/Budget)
    → Firmen aus Pass A mit grobem Sentiment durchreichen.
    Die Pipeline liefert damit NIE weniger als der Legacy-Pfad.
    """
    out = []
    for s in scout_companies:
        snippet = s["snippets"][0] if s["snippets"] else ""
        out.append({
            "name": s["name"],
            "sentiment": s.get("rough_sentiment") or "neutral",
            "strength": "moderate",
            "reason": snippet[:150],
            "mentioned_price": None,
            "price_target": None,
            "action_hint": "watch_for_reversal",
            "catalyst": "none",
        })
    return out


_VALID_SENTIMENT = {"bullish", "bearish", "neutral"}
_VALID_STRENGTH  = {"strong", "moderate", "weak"}
_VALID_ACTION    = {"buy", "sell", "watch_for_reversal", "avoid", "hold"}
_VALID_CATALYST  = {"earnings", "product", "macro", "legal", "technical", "none"}


def call_analyst(con, scout_companies, channel, title, date_str):
    """
    Pass B: EIN Call pro Video. Sieht nur Firmennamen + Snippets, nie das
    Transkript.

    Rückgabe ist feldkompatibel zum bisherigen companies-Schema (plus additives
    `catalyst`). Jeder Fehlerpfad → Fallback auf die Scout-Daten.
    """
    if not scout_companies:
        return []

    today = date.today().isoformat()

    # Budget-Gate: erschöpft → Fallback, keine Kosten
    try:
        from roles import budget as _role_budget
        if not _role_budget.check_and_reserve(con, "extractor_analyst", today):
            return _scout_fallback(scout_companies)
    except Exception as e:
        print(f"     ⚠ Budget-Check (extractor_analyst) fehlgeschlagen: {e}", flush=True)

    try:
        from thematic.lib import llm_client
        analyst_model = llm_client.get_model("extractor_analyst")
    except Exception:
        analyst_model = MODEL

    lines = []
    for s in scout_companies:
        quotes = "\n".join(f'    - "{q}"' for q in s["snippets"]) or "    - (kein Zitat)"
        lines.append(
            f'- {s["name"]} (Scout-Einschätzung: {s.get("rough_sentiment")})\n{quotes}'
        )

    user_content = (
        f"Kanal: {channel}\nTitel: {title}\nDatum: {date_str}\n\n"
        f"Firmennennungen mit wörtlichen Zitaten aus dem Video:\n\n"
        + "\n".join(lines)
    )

    # Anders als Scout/Legacy darf ein Analyst-Fehler das Video NICHT auf
    # status='error' setzen: die Erkennung (Pass A) ist bereits gelaufen und
    # bezahlt. Deshalb hier abfangen und auf die Scout-Daten zurückfallen.
    t_in = t_out = 0
    try:
        parsed, t_in, t_out = _call_cascade(
            ANALYST_PROMPT, user_content,
            primary_model=analyst_model,
            default={"companies": []},
            max_tokens=4000,
        )
    except Exception as e:
        print(f"     ⚠ Analyst-Call fehlgeschlagen ({e}) → Fallback auf Scout-Daten",
              flush=True)
        parsed = {"companies": []}

    try:
        from roles import budget as _role_budget
        if t_in or t_out:
            _role_budget.record_spend(con, "extractor_analyst", today,
                                      t_in, t_out, analyst_model)
    except Exception:
        pass

    analyzed = {
        (c.get("name") or "").lower().strip(): c
        for c in parsed.get("companies", [])
        if c.get("name")
    }
    if not analyzed:
        print("     ⚠ Analyst lieferte keine Firmen → Fallback auf Scout-Daten",
              flush=True)
        return _scout_fallback(scout_companies)

    # Fallback-Kaskade Stufe 2 (pro Firma): der Analyst darf keine Firma
    # verschlucken – wer fehlt, kommt über den Scout-Fallback rein. Damit ist
    # die Firmenmenge des 2-Pass-Pfads garantiert die des Scouts.
    out = []
    missing = 0
    for s in scout_companies:
        a = analyzed.get(s["name"].lower().strip())
        if not a:
            missing += 1
            out.append(_scout_fallback([s])[0])
            continue
        snippet = s["snippets"][0] if s["snippets"] else ""
        sentiment = str(a.get("sentiment") or "").lower()
        strength  = str(a.get("strength") or "").lower()
        action    = str(a.get("action_hint") or "").lower()
        catalyst  = str(a.get("catalyst") or "").lower()
        out.append({
            # Name IMMER aus dem Scout: der Analyst darf ihn nicht umschreiben,
            # sonst bricht das Matching im company_normalizer.
            "name": s["name"],
            "sentiment": sentiment if sentiment in _VALID_SENTIMENT
                         else (s.get("rough_sentiment") or "neutral"),
            "strength": strength if strength in _VALID_STRENGTH else "moderate",
            "reason": (a.get("reason") or snippet)[:300],
            "mentioned_price": a.get("mentioned_price"),
            "price_target": a.get("price_target"),
            "action_hint": action if action in _VALID_ACTION else "watch_for_reversal",
            "catalyst": catalyst if catalyst in _VALID_CATALYST else "none",
        })

    if missing:
        print(f"     ⚠ Analyst hat {missing} Firma(en) ausgelassen → Scout-Fallback",
              flush=True)
    return out


# ══ Dispatcher ═══════════════════════════════════════════════════════════════

def _chunk_transcript(transcript):
    chunks = []
    start = 0
    t_len = len(transcript)
    while start < t_len:
        end = min(start + CHUNK_SIZE + OVERLAP, t_len)
        chunks.append(transcript[start:end])
        start += CHUNK_SIZE
        if start >= t_len:
            break
    return chunks


def analyze(transcript, channel, title, date_str, con=None):
    chunks = _chunk_transcript(transcript)
    total = len(chunks)
    mode = EXTRACTOR_MODE if EXTRACTOR_MODE in ("two_pass", "legacy") else "two_pass"
    print(f"     → {len(transcript)} Zeichen, {total} Chunk(s) [{mode}]", flush=True)

    # con=None → Legacy (Budget-Buchung braucht eine Connection)
    if mode == "legacy" or con is None:
        results = []
        for i, chunk in enumerate(chunks, 1):
            print(f"     → Chunk {i}/{total}...", flush=True)
            results.append(call_api(chunk, channel, title, date_str, i, total))
        return merge_results(results)

    # ── Pass A: Scout ────────────────────────────────────────────────────
    scout_results = []
    for i, chunk in enumerate(chunks, 1):
        print(f"     → Scout-Chunk {i}/{total}...", flush=True)
        scout_results.append(call_scout(chunk, channel, title, date_str, i, total))
    merged = merge_scout_results(scout_results)

    # ── Pass B: Analyst (ein Call für das ganze Video) ───────────────────
    print(f"     → Analyst ({len(merged['companies'])} Firmen)...", flush=True)
    companies = call_analyst(con, merged["companies"], channel, title, date_str)

    return {
        "companies": companies,
        "market_outlook": merged["market_outlook"],
        "key_themes": merged["key_themes"],
    }


def main():
    con = db_connect()
    pending = con.execute(
        "SELECT * FROM videos WHERE status='pending' ORDER BY upload_date DESC"
    ).fetchall()

    print(f"Pending Videos: {len(pending)} [Modus: {EXTRACTOR_MODE}]", flush=True)

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

        # Transiente Fehler: nach 3 Fehler-Versuchen dauerhaft skippen
        try:
            error_count = row["error_count"] or 0
        except (IndexError, KeyError):
            error_count = 0
        try:
            row_status = row["status"]
        except (IndexError, KeyError):
            row_status = "pending"
        if row_status == "error" and error_count >= 3:
            print(f"  ⏭ Zu viele Fehler ({error_count}x) – dauerhaft übersprungen", flush=True)
            continue

        try:
            result = analyze(row['transcript'], row['channel'], row['title'],
                             row['upload_date'], con=con)
            result["source"] = {
                "channel":  row['channel'],
                "title":    row['title'],
                "date":     row['upload_date'],
                "video_id": row['video_id']
            }
            companies = result.get('companies', [])
            print(f"  ✓ {len(companies)} Unternehmen: {[c['name'] for c in companies]}", flush=True)
            con.execute(
                "UPDATE videos SET status='done', analyzed_at=?, error_count=0 WHERE video_id=?",
                (datetime.now().isoformat(), row['video_id'])
            )
            con.commit()
            all_signals.append(result)

        except Exception as e:
            print(f"  ✗ Fehler: {e}", flush=True)
            new_error_count = error_count + 1
            con.execute(
                "UPDATE videos SET status='error', error_count=? WHERE video_id=?",
                (new_error_count, row['video_id'])
            )
            con.commit()

    os.makedirs(os.path.dirname(SIGNALS_PATH), exist_ok=True)
    # Rolling: nur Einträge der letzten 30 Tage behalten (verhindert unbegrenztes Wachstum)
    from datetime import timedelta
    cutoff_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    all_signals = [
        s for s in all_signals
        if (s.get("source") or {}).get("date", "9999") >= cutoff_date
    ]
    with open(SIGNALS_PATH, "w", encoding="utf-8") as f:
        json.dump(all_signals, f, ensure_ascii=False, indent=2)

    total_co = sum(len(s.get('companies', [])) for s in all_signals)
    print(f"\n✅ Fertig. {len(all_signals)} Videos, {total_co} Unternehmen.", flush=True)
    con.close()


if __name__ == "__main__":
    main()
