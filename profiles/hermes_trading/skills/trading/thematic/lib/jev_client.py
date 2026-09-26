"""
jev_client.py — Client fuer OpenRouters Decisions API (TypeSafe "Jev", System-One-Modell).

Jev liefert keine Texte, sondern Wahrscheinlichkeiten fuer vorgegebene Fragen:
    noul    {"type": "noul",   "instructions": "..."}
    choice  {"type": "choice", "instructions": "...", "criteria": {"label": "Beschreibung", ...}}
    score   {"type": "score",  "instructions": "...", "criteria": ["niedrigste Stufe", ..., "hoechste"]}

Antwortformen (live gemessen 23.09.2026):
    noul   → {"type": "noul", "noul": 0.97}
    choice → {"type": "choice", "choice": "bearish", "probabilities": {...}, "confidence": 1}
    score  → {"type": "score", "score": 1.91, "legend": {...}, "probabilities": {...}, "confidence": 0.87}

FAIL-OPEN: decide() wirft nie eine Exception, sondern liefert bei JEDEM Fehler None
(fehlender Key, Provider nicht freigeschaltet = 404, Timeout, kaputtes JSON, ...).
Der Endpoint liegt unter /api/alpha/ und kann sich ohne Ankuendigung aendern.

Buchung ins llm_budget_log ist Sache des Aufrufers (usage_of() liefert die Zahlen),
weil die sqlite-Connection nicht thread-sicher ist und nur im Haupt-Thread benutzt
werden darf.
"""
import os
import sys
import time

import requests

sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")
import env_loader  # noqa: F401  (side-effect: laedt .env)

DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
# Festgeschrieben (25.09.2026, jev-pin-20260925): Schwellen und Shadow-Auswertungen gelten fuer EINE Version.
# Der Alias "~typesafe/jev-latest" wuerde bei einem neuen Release lautlos wechseln und Stichproben mischen.
# Neue Version nur bewusst eintragen und die laufende Auswertung dann neu beginnen.
JEV_MODEL = "typesafe/jev-1.13-20260917"
MAX_RETRIES = 2                      # zusaetzlich zum ersten Versuch
_RETRY_STATUS = (429, 500, 502, 503, 504)


def decide(state, questions, timeout=60, model=JEV_MODEL):
    """Stellt `questions` zum `state`. Returns das Antwort-Dict oder None (fail-open)."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        print("     ⚠ Jev: OPENROUTER_API_KEY nicht gesetzt", flush=True)
        return None
    payload = {"model": model, "state": state, "questions": questions}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    for attempt in range(MAX_RETRIES + 1):
        try:
            r = requests.post(DECISIONS_URL, headers=headers, json=payload, timeout=timeout)
        except requests.RequestException as e:
            if attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)
                continue
            print(f"     ⚠ Jev: Netzwerkfehler ({type(e).__name__})", flush=True)
            return None
        if r.status_code in _RETRY_STATUS and attempt < MAX_RETRIES:
            time.sleep(2 ** attempt)
            continue
        if r.status_code != 200:
            # 4xx (z.B. 404 = Provider "typesafe" nicht freigeschaltet) wird nicht wiederholt
            print(f"     ⚠ Jev: HTTP {r.status_code}: {r.text[:160]}", flush=True)
            return None
        try:
            data = r.json()
        except ValueError:
            print("     ⚠ Jev: Antwort ist kein JSON", flush=True)
            return None
        if not isinstance(data, dict) or not isinstance(data.get("answers"), dict):
            print("     ⚠ Jev: Antwort ohne 'answers'", flush=True)
            return None
        return data
    return None


def model_of(resp):
    """Modellversion, die tatsaechlich geantwortet hat (Feld "model"), sonst ""."""
    m = (resp or {}).get("model") if isinstance(resp, dict) else None
    return str(m) if m else ""


def usage_of(resp):
    """(tokens_in, tokens_out, cost_usd) aus einer Antwort; (0, 0, 0.0) wenn nicht vorhanden."""
    u = (resp or {}).get("usage") or {}
    return (int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0),
            float(u.get("cost") or 0.0))


def choice_of(resp, key, options=None):
    """(label, confidence, probabilities) einer choice-Frage oder None bei ungueltiger Antwort.

    Mit `options` wird zusaetzlich geprueft, dass das Label eine der erlaubten Optionen ist.
    """
    try:
        a = resp["answers"][key]
        label = a["choice"]
        conf = float(a["confidence"])
        probs = {k: float(v) for k, v in a["probabilities"].items()}
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    if options is not None and label not in options:
        return None
    return label, conf, probs


def noul_of(resp, key):
    """Wahrscheinlichkeit einer noul-Frage (0..1) oder None."""
    try:
        p = float(resp["answers"][key]["noul"])
    except (KeyError, TypeError, ValueError):
        return None
    return p if 0.0 <= p <= 1.0 else None
