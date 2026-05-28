"""
LLM Client — Zentraler Wrapper fuer OpenRouter und Grok Lite.
Alle Modelle sind in thematic_config.json konfigurierbar.
"""
import json
import os
import sys
sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")
import env_loader  # noqa: F401  (side-effect: laedt .env)
import time
import requests
from typing import Optional

OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY")
GROK_LITE_KEY = os.environ.get("GROK_LITE_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

_config_cache = None
_config_ts = 0


def _load_config():
    global _config_cache, _config_ts
    now = time.time()
    if _config_cache and now - _config_ts < 60:
        return _config_cache
    try:
        path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "config", "thematic_config.json"
        )
        with open(path) as f:
            _config_cache = json.load(f)
        _config_ts = now
    except Exception:
        _config_cache = {}
    return _config_cache


def get_model(task: str) -> str:
    """Ermittelt das konfigurierte Modell fuer eine Aufgabe."""
    cfg = _load_config()
    return cfg.get("llm_models", {}).get(task, "google/gemini-2.0-flash-001")


def call_llm(
    prompt: str,
    model: str,
    system_prompt: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 2000,
    json_mode: bool = False,
    timeout: int = 60,
) -> dict:
    """
    Einheitlicher LLM-Call via OpenRouter oder Grok Lite.

    Returns: {"ok": True, "content": "...", "model": "...", "tokens": {...}}
    Bei Fehler: {"ok": False, "error": "..."}
    """
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    # Grok Lite direct (x.ai)
    if model.startswith("grok-"):
        return _call_grok(messages, model, temperature, max_tokens, timeout)

    # OpenRouter (default)
    return _call_openrouter(messages, model, temperature, max_tokens, json_mode, timeout)


def _call_openrouter(messages, model, temperature, max_tokens, json_mode, timeout):
    if not OPENROUTER_KEY:
        return {"ok": False, "error": "OPENROUTER_API_KEY nicht gesetzt"}

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json",
    }

    for attempt in range(3):
        try:
            resp = requests.post(OPENROUTER_URL, headers=headers,
                                 json=payload, timeout=timeout)
            if resp.status_code == 429:
                wait = 2 ** attempt
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            choice = data["choices"][0]
            return {
                "ok": True,
                "content": choice["message"]["content"],
                "model": data.get("model", model),
                "tokens": {
                    "input": data.get("usage", {}).get("prompt_tokens", 0),
                    "output": data.get("usage", {}).get("completion_tokens", 0),
                },
            }
        except requests.Timeout:
            if attempt == 2:
                return {"ok": False, "error": f"Timeout nach {timeout}s"}
            time.sleep(2)
        except Exception as e:
            if attempt == 2:
                return {"ok": False, "error": str(e)}
            time.sleep(2)

    return {"ok": False, "error": "Unbekannter Fehler"}


def _call_grok(messages, model, temperature, max_tokens, timeout):
    if not GROK_LITE_KEY:
        return {"ok": False, "error": "GROK_LITE_API_KEY nicht gesetzt"}

    grok_model = "grok-2-latest" if model == "grok-lite" else model
    url = "https://api.x.ai/v1/chat/completions"

    payload = {
        "model": grok_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    headers = {
        "Authorization": f"Bearer {GROK_LITE_KEY}",
        "Content-Type": "application/json",
    }

    for attempt in range(3):
        try:
            resp = requests.post(url, headers=headers,
                                 json=payload, timeout=timeout)
            if resp.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            data = resp.json()
            choice = data["choices"][0]
            return {
                "ok": True,
                "content": choice["message"]["content"],
                "model": grok_model,
                "tokens": {
                    "input": data.get("usage", {}).get("prompt_tokens", 0),
                    "output": data.get("usage", {}).get("completion_tokens", 0),
                },
            }
        except requests.Timeout:
            if attempt == 2:
                return {"ok": False, "error": f"Grok Timeout nach {timeout}s"}
            time.sleep(2)
        except Exception as e:
            if attempt == 2:
                return {"ok": False, "error": f"Grok Error: {e}"}
            time.sleep(2)

    return {"ok": False, "error": "Unbekannter Fehler"}


def parse_json_response(result: dict, default=None) -> dict:
    """Extrahiert JSON aus LLM-Antwort, bereinigt Markdown-Wrapper."""
    if not result.get("ok"):
        return default or {}
    text = result["content"].strip()
    for marker in ["```json", "```"]:
        if marker in text:
            text = text.split(marker)[1].split("```")[0].strip()
            break
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            # Versuche, erstes JSON-Objekt im Text zu finden
            import re
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
        return default or {}