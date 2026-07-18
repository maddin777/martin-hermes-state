"""
roles/committee.py — Investment Committee (Pre-Entry Gate).

Drei sequenzielle LLM-Rollen mit bewusst unterschiedlichen Providern:

    Bull Analyst  → baut die staerkste These fuer den Trade
    Bear Analyst  → bekommt die Bull-These und MUSS sie zerstoeren
    Risk Officer  → bekommt beide Thesen + Portfolio-Kontext und urteilt
                    ueber die POSITION (Klumpenrisiko, Regime-Fit), nicht
                    ueber die Aktie

Die Entscheidungsregel liegt DETERMINISTISCH im Code (Abschnitt 2.4), nicht im
LLM. Ein VETO braucht zwei unabhaengige Stimmen (Risk-VETO + Bear-Dealbreaker) —
ein einzelnes Modell darf nie allein einen Trade killen.

Fail-Open: JEDER Fehlerpfad liefert {"final_verdict": "ERROR_FAIL_OPEN",
"size_factor": 1.0}. Es wird niemals eine Exception an den Entry-Loop
weitergereicht.
"""
import json
import sys
import traceback
from datetime import date as _date

sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")
import env_loader  # noqa: F401  (side-effect: laedt .env)

from roles import ensure_roles_schema
from roles import budget

from thematic.lib import llm_client, prompt_loader

ROLE = "committee"


def _clamp(v, lo, hi):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return hi


def _row_get(row, key, default=None):
    """sqlite3.Row-sicherer Zugriff (Bracket-Notation, .get() existiert nicht)."""
    try:
        if hasattr(row, "keys"):
            return row[key] if key in row.keys() else default
        return row.get(key, default)
    except Exception:
        return default


def _fetch_news(ticker: str) -> str:
    """Max. 5 Snippets a 200 Zeichen. Tavily-Fehler → kein Abbruch."""
    try:
        from thematic.lib import tavily_client
        news = tavily_client.fetch_ticker_news(ticker, days=1)
        lines = [
            f"- {a.get('title', '')}: {(a.get('content') or '')[:200]}"
            for a in (news or [])[:5]
        ]
        return "\n".join(lines) if lines else "Keine News verfuegbar."
    except Exception:
        return "Keine News verfuegbar."


def _candidate_text(c, direction: str) -> str:
    channels = []
    try:
        channels = list(set(json.loads(_row_get(c, "channels") or "[]")))[:5]
    except Exception:
        pass

    if direction == "SHORT":
        conv = _row_get(c, "conviction_score_bear") or 0
        conv_label = "Conviction (bearish)"
    else:
        conv = _row_get(c, "conviction_score") or 0
        conv_label = "Conviction (bullish)"

    tech = _row_get(c, "tech_score")
    return (
        f"Name: {_row_get(c, 'name')}\n"
        f"Ticker: {_row_get(c, 'ticker')}\n"
        f"Richtung: {direction}\n"
        f"{conv_label}: {float(conv):.2f}\n"
        f"Tech-Score: {('%.2f' % tech) if tech is not None else 'n/a'} "
        f"(Tech-Richtung: {_row_get(c, 'tech_direction') or 'n/a'})\n"
        f"Mentions (30d): {_row_get(c, 'mention_count') or 0}\n"
        f"Kanaele: {', '.join(channels) if channels else 'n/a'}\n"
        f"Watchlist-Notiz: {(_row_get(c, 'notes') or 'keine')[:400]}"
    )


def _portfolio_text(context: dict) -> str:
    sec = context.get("sector_exposure") or {}
    sec_lines = "\n".join(
        f"  - {k}: {float(v):.0f} EUR" for k, v in sorted(
            sec.items(), key=lambda x: -(x[1] or 0)
        )[:8]
    ) or "  - keine"
    return (
        f"Offene Positionen:\n{context.get('open_positions_text') or '  - keine'}\n"
        f"Sektor-Exposure:\n{sec_lines}\n"
        f"Portfolio-Wert: {float(context.get('portfolio_value') or 0):.0f} EUR\n"
        f"Drawdown vom ATH: {float(context.get('drawdown_pct') or 0):.1%}\n"
        f"Sektor des Kandidaten: {context.get('ticker_sector') or 'Other'}"
    )


def _market_text(context: dict) -> str:
    crabel = context.get("crabel") or {}
    pats = "+".join(crabel.get("patterns") or []) if crabel else ""
    cp = context.get("current_price")
    atr = context.get("atr")
    return (
        f"Makro: {context.get('macro') or 'n/a'} | Regime: {context.get('regime') or 'n/a'}\n"
        f"Aktueller Kurs: {('%.2f' % cp) if cp else 'n/a'} | "
        f"ATR(14): {('%.2f' % atr) if atr else 'n/a'}\n"
        f"Crabel-Pattern: {pats or 'kein Kontraktions-Pattern'}"
    )


def _call_role(con, today, prompt, model_task, results_acc):
    """
    Ein Rollen-Call inkl. Budget-Buchung.

    Returns: (data_dict, ok_bool). ok=False → Fail-Open beim Aufrufer.
    """
    model = llm_client.get_model(model_task)
    res = llm_client.call_llm(
        prompt, model, temperature=0.3, json_mode=True, max_tokens=800
    )
    toks = res.get("tokens") or {}
    t_in, t_out = int(toks.get("input", 0) or 0), int(toks.get("output", 0) or 0)
    results_acc["tokens_in"] += t_in
    results_acc["tokens_out"] += t_out
    results_acc["models"].append(res.get("model") or model)
    budget.record_spend(con, ROLE, today, t_in, t_out, res.get("model") or model)

    if not res.get("ok"):
        print(f"     ⚠ Committee/{model_task}: {res.get('error')}", flush=True)
        return {}, False

    data = llm_client.parse_json_response(res, default={})
    if not isinstance(data, dict) or not data:
        print(f"     ⚠ Committee/{model_task}: Parse-Fehler", flush=True)
        return {}, False
    return data, True


def run_committee(con, candidate_row, direction: str, context: dict) -> dict:
    """
    Fuehrt Bull → Bear → Risk aus und schreibt eine Zeile nach committee_log.

    Args:
        con:           bestehende DB-Connection (DURCHGEREICHT, nie neu geoeffnet)
        candidate_row: sqlite3.Row aus der watchlist
        direction:     "LONG" | "SHORT"
        context:       dict mit mode/regime/macro/sector_exposure/
                       open_positions_text/current_price/atr/crabel/
                       ticker_sector/portfolio_value/drawdown_pct

    Returns:
        {"final_verdict": "APPROVE"|"REDUCE"|"VETO"|"ERROR_FAIL_OPEN",
         "size_factor": float, "log_id": int|None,
         "bull": dict, "bear": dict, "risk": dict}

    Wirft NIEMALS. Jeder Fehler → ERROR_FAIL_OPEN.
    """
    acc = {"tokens_in": 0, "tokens_out": 0, "models": []}
    today = _date.today().isoformat()
    mode = (context or {}).get("mode", "shadow")
    ticker = _row_get(candidate_row, "ticker") or "?"

    bull, bear, risk = {}, {}, {}
    final_verdict = "ERROR_FAIL_OPEN"
    size_factor = 1.0

    try:
        ensure_roles_schema(con)

        cand_text = _candidate_text(candidate_row, direction)
        market_text = _market_text(context)
        news_text = _fetch_news(ticker)
        portfolio_text = _portfolio_text(context)

        # ── Call 1: Bull Analyst ──────────────────────────────────────────
        p_bull = prompt_loader.load_prompt(
            "committee_bull_v1.md",
            direction=direction,
            candidate_data=cand_text,
            market_context=market_text,
            news_snippets=news_text,
        )
        if not p_bull:
            raise RuntimeError("Prompt committee_bull_v1.md nicht gefunden")
        bull, ok = _call_role(con, today, p_bull, "committee_bull", acc)
        if not ok:
            raise RuntimeError("Bull-Call fehlgeschlagen")

        # ── Call 2: Bear Analyst ──────────────────────────────────────────
        p_bear = prompt_loader.load_prompt(
            "committee_bear_v1.md",
            direction=direction,
            candidate_data=cand_text,
            market_context=market_text,
            news_snippets=news_text,
            bull_thesis=json.dumps(bull, ensure_ascii=False),
        )
        if not p_bear:
            raise RuntimeError("Prompt committee_bear_v1.md nicht gefunden")
        bear, ok = _call_role(con, today, p_bear, "committee_bear", acc)
        if not ok:
            raise RuntimeError("Bear-Call fehlgeschlagen")

        # ── Call 3: Risk Officer ──────────────────────────────────────────
        p_risk = prompt_loader.load_prompt(
            "committee_risk_v1.md",
            direction=direction,
            candidate_data=cand_text,
            market_context=market_text,
            portfolio_context=portfolio_text,
            bull_thesis=json.dumps(bull, ensure_ascii=False),
            bear_thesis=json.dumps(bear, ensure_ascii=False),
        )
        if not p_risk:
            raise RuntimeError("Prompt committee_risk_v1.md nicht gefunden")
        risk, ok = _call_role(con, today, p_risk, "committee_risk", acc)
        if not ok:
            raise RuntimeError("Risk-Call fehlgeschlagen")

        # ── Entscheidungsregel (deterministisch, Abschnitt 2.4) ───────────
        risk_verdict = str(risk.get("verdict", "APPROVE")).upper().strip()
        if risk_verdict not in ("APPROVE", "REDUCE", "VETO"):
            risk_verdict = "APPROVE"
        bear_dealbreaker = bool(bear.get("dealbreaker", False))

        if risk_verdict == "VETO" and bear_dealbreaker:
            final_verdict = "VETO"
            size_factor = 1.0          # nicht angewandt, VETO blockt komplett
        elif risk_verdict in ("VETO", "REDUCE"):
            # Ein Risk-VETO OHNE Bear-Dealbreaker wird zu REDUCE abgeschwaecht.
            final_verdict = "REDUCE"
            size_factor = _clamp(risk.get("size_factor", 0.5), 0.5, 1.0)
        else:
            final_verdict = "APPROVE"
            size_factor = 1.0

    except Exception as e:
        print(f"     ⚠ Committee ({ticker}): {e} → FAIL-OPEN", flush=True)
        try:
            log_msg = traceback.format_exc(limit=2)
            print(f"       {log_msg.splitlines()[-1]}", flush=True)
        except Exception:
            pass
        final_verdict = "ERROR_FAIL_OPEN"
        size_factor = 1.0

    # ── Audit-Log (auch im Fehlerfall) ────────────────────────────────────
    log_id = None
    try:
        cur = con.execute("""
            INSERT INTO committee_log
            (check_date, ticker, direction, mode, bull_json, bear_json, risk_json,
             final_verdict, size_factor, would_block, entry_happened,
             tokens_in, tokens_out, models_used)
            VALUES (?,?,?,?,?,?,?,?,?,?,0,?,?,?)
        """, (
            today, ticker, direction, mode,
            json.dumps(bull, ensure_ascii=False) if bull else None,
            json.dumps(bear, ensure_ascii=False) if bear else None,
            json.dumps(risk, ensure_ascii=False) if risk else None,
            final_verdict, round(float(size_factor), 3),
            1 if final_verdict == "VETO" else 0,
            acc["tokens_in"], acc["tokens_out"],
            ",".join(acc["models"]) if acc["models"] else None,
        ))
        log_id = cur.lastrowid
        con.commit()
    except Exception as e:
        print(f"     ⚠ committee_log Insert fehlgeschlagen ({ticker}): {e}", flush=True)

    return {
        "final_verdict": final_verdict,
        "size_factor": size_factor,
        "log_id": log_id,
        "bull": bull,
        "bear": bear,
        "risk": risk,
        "tokens_in": acc["tokens_in"],
        "tokens_out": acc["tokens_out"],
    }


def mark_entry_happened(con, log_id) -> None:
    """Setzt entry_happened=1 nach erfolgreichem INSERT INTO positions."""
    if not log_id:
        return
    try:
        con.execute(
            "UPDATE committee_log SET entry_happened=1 WHERE id=?", (log_id,)
        )
    except Exception as e:
        print(f"     ⚠ committee_log entry_happened-Update fehlgeschlagen: {e}",
              flush=True)
