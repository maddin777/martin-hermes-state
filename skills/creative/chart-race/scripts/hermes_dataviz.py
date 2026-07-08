#!/usr/bin/env python3
"""
Hermes-Dataviz Orchestrator (OpenRouter).

Nimmt ein natürlichsprachliches Kommando, lässt DeepSeek V4 flash (via OpenRouter)
daraus eine Render-Config (JSON) bauen, validiert sie und ruft die Render-Engine auf.

Zwei Betriebsmodi (automatisch je nach Kommando / vorhandener Datei):
  A) BYO-Daten : Nutzer liefert CSV  -> DeepSeek klärt nur Spalten-Mapping + Style
  B) Self-Fetch: DeepSeek wählt eine Quelle aus der Whitelist und baut die CSV

Aufruf:
    python hermes_dataviz.py "Zusammensetzung Dieselpreis DE als stacked_area, 30s" \
        --data /pfad/zu/daten.csv
    python hermes_dataviz.py "teuerstes Benzin Europa als bar_race, langsam"
"""
import argparse
import json
import os
import subprocess
import sys
import httpx

# .env aus hermes_trading-Profil laden (OPENROUTER_API_KEY)
sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")
import env_loader  # noqa: F401

HERE = os.path.dirname(os.path.abspath(__file__))
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = os.getenv("CHART_MODEL", "deepseek/deepseek-v4-flash")


def load_prompt():
    """Lädt DeepSeek-System-Prompt."""
    p = os.path.join(HERE, "..", "references", "deepseek_prompt.md")
    with open(p, encoding="utf-8") as f:
        return f.read()


def peek_csv(path, n=5):
    """Kopfzeile + erste Zeilen als Kontext für DeepSeek (nie die ganze Datei)."""
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = [next(f).rstrip() for _ in range(n) if not f.closed]
    return "\n".join(lines[:n])


def _deepseek_call(messages, thinking=False, temperature=0.2):
    """Einzelner API-Call an OpenRouter."""
    body = {
        "model": MODEL,
        "messages": messages,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    if thinking:
        body["reasoning_effort"] = "high"

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("FEHLER: OPENROUTER_API_KEY nicht gesetzt", file=sys.stderr)
        sys.exit(1)

    r = httpx.post(OPENROUTER_URL, timeout=120, headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }, json=body)
    r.raise_for_status()
    data = r.json()
    raw = data["choices"][0]["message"]["content"]
    return json.loads(raw)


def call_deepseek(command, csv_head=None, data_file=None, thinking=False):
    """Baut Prompt + ruft DeepSeek auf."""
    sys_prompt = load_prompt()
    user = f"KOMMANDO:\n{command}\n"
    if data_file:
        user += (f"\nDATENDATEI: {data_file}\n"
                 f"ERSTE ZEILEN (zur Spaltenerkennung):\n{csv_head}\n"
                 f"-> Modus A (BYO-Daten): data_file exakt übernehmen, "
                 f"orientation/Spalten daraus ableiten.\n")
    else:
        user += ("\nKEINE Datei übergeben -> Modus B (Self-Fetch): wähle eine "
                 "passende Quelle aus der Whitelist in data_sources.md, setze "
                 "'fetch' im JSON. Falls keine Quelle passt: 'need_input'.\n")

    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user},
    ]
    return _deepseek_call(messages, thinking=thinking)


def maybe_fetch(cfg):
    """Modus B: ruft das in der Config referenzierte Fetch-Skript auf."""
    fetch = cfg.get("fetch")
    if not fetch:
        return cfg
    script = os.path.join(HERE, "fetchers", fetch["script"])
    if not os.path.exists(script):
        print(f"FEHLER: Fetch-Skript {fetch['script']} nicht vorhanden.", file=sys.stderr)
        sys.exit(1)
    subprocess.run([sys.executable, script, *fetch.get("args", [])], check=True)
    cfg["data_file"] = fetch["produces"]
    return cfg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", help="Natürlichsprachliches Kommando")
    ap.add_argument("--data", default=None, help="CSV-Pfad (Modus A)")
    ap.add_argument("--out", default=None, help="Ausgabe-MP4")
    ap.add_argument("--config-only", action="store_true",
                    help="Nur Config bauen und ausgeben, nicht rendern")
    ap.add_argument("--no-fallback", action="store_true",
                    help="Thinking-Fallback bei need_input deaktivieren")
    a = ap.parse_args()

    head = peek_csv(a.data) if a.data else None

    # Pass 1: schnell, Non-Thinking
    cfg = call_deepseek(a.command, head, a.data, thinking=False)

    # Pass 2: kippt ins Nachfragen, einmal mit Thinking-Budget nachlegen
    if cfg.get("need_input") and not a.no_fallback:
        print("need_input im 1. Pass — versuche Thinking-Modus …", file=sys.stderr)
        cfg = call_deepseek(a.command, head, a.data, thinking=True)

    if cfg.get("need_input"):
        print("DeepSeek braucht Angaben:\n  - " +
              "\n  - ".join(cfg["need_input"]), file=sys.stderr)
        sys.exit(3)

    cfg = maybe_fetch(cfg)

    print(json.dumps(cfg, indent=2, ensure_ascii=False))
    if a.config_only:
        return

    # Import erst hier, damit --config-only ohne matplotlib läuft
    sys.path.insert(0, HERE)
    from render_engine import render, validate_config
    errs = validate_config(cfg)
    if errs:
        print("Config ungültig:\n  - " + "\n  - ".join(errs), file=sys.stderr)
        sys.exit(2)
    render(cfg, a.out)


if __name__ == "__main__":
    main()