#!/usr/bin/env python3
"""
Diagnose-Sonde fuer die Committee-Rollen.

Beantwortet EINE Frage: warum liefert der Bear-Call unparsbares JSON?
Ruft OpenRouter direkt auf (nicht ueber llm_client), weil wir Felder
brauchen, die llm_client nicht durchreicht: finish_reason und
usage.completion_tokens_details.reasoning_tokens.

    python3 scripts/probe_bear.py                  # Bear-Modell, max_tokens=800
    python3 scripts/probe_bear.py --max-tokens 3000
    python3 scripts/probe_bear.py --role committee_bull
    python3 scripts/probe_bear.py --no-reasoning   # Reasoning abschalten
"""
import argparse
import json
import os
import sys

sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")
import env_loader  # noqa: F401

import requests

from thematic.lib import llm_client

PROMPT = (
    "Du bist Bear Analyst. Antworte AUSSCHLIESSLICH mit JSON, keine Erklaerung.\n\n"
    "Bull-These zu SMCI (SHORT): 'SMCI steht unter Abwaertsdruck, 56% unter "
    "52-Wochen-Hoch, AI-Hardware-Sektor schwach, Tech-Richtung SHORT.'\n\n"
    "Greife diese These an. Schema:\n"
    '{"counter_thesis": "...", "severity": 0.0, "dealbreaker": false, '
    '"dealbreaker_reason": "..."}'
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--role", default="committee_bear")
    ap.add_argument("--max-tokens", type=int, default=800)
    ap.add_argument("--no-reasoning", action="store_true")
    args = ap.parse_args()

    model = llm_client.get_model(args.role)
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        print("OPENROUTER_API_KEY fehlt")
        return 1

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": PROMPT}],
        "temperature": 0.3,
        "max_tokens": args.max_tokens,
        "response_format": {"type": "json_object"},
    }
    if args.no_reasoning:
        payload["reasoning"] = {"exclude": True}

    print(f"Modell     : {model}")
    print(f"max_tokens : {args.max_tokens}")
    print(f"reasoning  : {'exclude' if args.no_reasoning else 'default'}")
    print("-" * 70)

    r = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"},
        json=payload,
        timeout=120,
    )
    if r.status_code != 200:
        print(f"HTTP {r.status_code}: {r.text[:500]}")
        return 1

    data = r.json()
    choice = data["choices"][0]
    content = choice["message"].get("content") or ""
    reasoning = choice["message"].get("reasoning") or ""
    usage = data.get("usage", {})
    details = usage.get("completion_tokens_details", {}) or {}

    print(f"finish_reason      : {choice.get('finish_reason')}   "
          f"<-- 'length' = abgeschnitten")
    print(f"prompt_tokens      : {usage.get('prompt_tokens')}")
    print(f"completion_tokens  : {usage.get('completion_tokens')}   "
          f"<-- > max_tokens? dann greift der Deckel nicht")
    print(f"reasoning_tokens   : {details.get('reasoning_tokens')}")
    print(f"content len        : {len(content)} Zeichen")
    print(f"reasoning len      : {len(reasoning)} Zeichen "
          f"(separates Feld, nicht in content)")
    print("-" * 70)
    print("CONTENT (roh):")
    print(repr(content[:1500]))
    print("-" * 70)
    try:
        json.loads(content.strip())
        print("Parse: OK")
    except json.JSONDecodeError as e:
        print(f"Parse: FEHLER -> {e}")
        print(f"Balance: {content.count('{')} x '{{'  vs  {content.count('}')} x '}}'")
        print("  (ungleich = truncation bestaetigt)")
    print("-" * 70)
    print(f"Via llm_client.parse_json_response: "
          f"{llm_client.parse_json_response({'ok': True, 'content': content}, {})}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
