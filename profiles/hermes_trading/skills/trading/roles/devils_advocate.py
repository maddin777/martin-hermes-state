"""
roles/devils_advocate.py — Stufe 2 des Thesis Monitors.

Problem: Stufe 1 (ein einziger Gemini-Prompt "ist die These intakt?") erzeugt
Bestaetigungsbias — das Modell findet fast immer Gruende, warum die These noch
halbwegs stimmt. Verlustpositionen bleiben zu lange INTACT.

Loesung: Ein zweiter Call bei einem ANDEREN Provider (DeepSeek), der explizit
den Gegenbeweis fuehren MUSS, aber nur ausgeloest wird, wenn die Position
tatsaechlich im Minus steht (Trigger im Aufrufer).

Ergebnis darf NUR auf WEAKENING downgraden — nie direkt auf BROKEN. Die
Eskalation uebernimmt der bestehende, getestete 3-Tage-WEAKENING-Streak.
Es wird KEIN neuer Exit-Pfad gebaut.
"""
import json
import sys
from datetime import date as _date

sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")
import env_loader  # noqa: F401  (side-effect: laedt .env)

from roles import ensure_roles_schema
from roles import budget

from thematic.lib import llm_client, prompt_loader

ROLE = "devils_advocate"


def run_devils_advocate(con, ticker: str, company_name: str, thesis_text: str,
                        theme_name: str, news_text: str, entry_date: str,
                        pnl_pct: float, direction: str) -> dict:
    """
    Args:
        con:       bestehende DB-Connection (durchgereicht)
        pnl_pct:   unrealisierter PnL als Dezimalwert (z.B. -0.075 fuer -7.5%),
                   RICHTUNGSKORREKT vom Aufrufer berechnet
        news_text: bereits geholte News (kein zweiter Tavily-Call!)

    Returns:
        {"ok": True, "kill_reasons": [...], "kill_probability": float}
        {"ok": False} bei jedem Fehler → Aufrufer behaelt Stufe-1-Verdict.

    Wirft NIEMALS.
    """
    today = _date.today().isoformat()
    try:
        ensure_roles_schema(con)

        prompt = prompt_loader.load_prompt(
            "devils_advocate_v1.md",
            ticker=ticker,
            company_name=company_name or ticker,
            direction=direction,
            thesis_text=thesis_text or "Keine explizite These dokumentiert.",
            theme_name=theme_name or "–",
            entry_date=(entry_date or "")[:10],
            pnl_pct=f"{pnl_pct * 100:.1f}",
            news_snippets=news_text or "Keine aktuellen News.",
        )
        if not prompt:
            print("  ⚠ Devil's Advocate: Prompt devils_advocate_v1.md fehlt", flush=True)
            return {"ok": False}

        model = llm_client.get_model("devils_advocate")
        res = llm_client.call_llm(
            prompt, model, temperature=0.3, json_mode=True, max_tokens=800
        )
        toks = res.get("tokens") or {}
        budget.record_spend(
            con, ROLE, today,
            int(toks.get("input", 0) or 0), int(toks.get("output", 0) or 0),
            res.get("model") or model,
        )

        if not res.get("ok"):
            print(f"  ⚠ Devil's Advocate ({ticker}): {res.get('error')}", flush=True)
            return {"ok": False}

        data = llm_client.parse_json_response(res, default={})
        if not isinstance(data, dict) or "kill_probability" not in data:
            print(f"  ⚠ Devil's Advocate ({ticker}): Parse-Fehler", flush=True)
            return {"ok": False}

        reasons = data.get("kill_reasons") or []
        if not isinstance(reasons, list):
            reasons = [str(reasons)]
        reasons = [str(r)[:300] for r in reasons][:3]

        try:
            kill_p = float(data.get("kill_probability", 0.0))
        except (TypeError, ValueError):
            return {"ok": False}
        kill_p = max(0.0, min(1.0, kill_p))

        return {"ok": True, "kill_reasons": reasons, "kill_probability": kill_p,
                "model": res.get("model") or model}

    except Exception as e:
        print(f"  ⚠ Devil's Advocate ({ticker}) Fehler: {e}", flush=True)
        return {"ok": False}


def merge_verdict(verdict: str, rationale: str, devil: dict) -> tuple:
    """
    Deterministische, konservative Merge-Regel (Abschnitt 3.3).

    Nur Downgrade auf WEAKENING, nie direkt BROKEN.

    Returns: (verdict, rationale)
    """
    if not devil.get("ok"):
        return verdict, rationale
    p = devil.get("kill_probability", 0.0)
    if p >= 0.70 and verdict in ("INTACT", "UNCERTAIN"):
        reasons = "; ".join(devil.get("kill_reasons") or [])
        rationale = f"[Devil's Advocate p={p:.2f}] {reasons} | {rationale}"
        verdict = "WEAKENING"
    return verdict, rationale


def to_db_fields(devil: dict) -> tuple:
    """Returns (devil_kill_prob, devil_reasons_json) — (None, None) wenn nicht gelaufen."""
    if not devil.get("ok"):
        return None, None
    return (
        devil.get("kill_probability"),
        json.dumps(devil.get("kill_reasons") or [], ensure_ascii=False),
    )
