#!/usr/bin/env python3
"""
pipeline_timing_check.py — Check: War die KI-Analyse/Pipeline nach dem
Haertungs-Fix (Task 4) rechtzeitig fertig?

Prueft im Trading cron.log den heutigen Lauf:
  - wann "KI Analyse DONE" (heute)
  - wann "TRADING PIPELINE DONE"
Meldet per stdout (no_agent-Cron): nur wenn etwas relevant (DONE fehlt oder > 05:00),
sonst silent (Watchdog-Muster).

Usage:
    python3 scripts/pipeline_timing_check.py
"""
from __future__ import annotations
import os, re
from datetime import datetime

CRON_LOG = os.path.join(
    "/root/.hermes/profiles/hermes_trading/skills/trading", "data", "cron.log")
DONE_BY = "05:00:00"   # nightly_eval feuert um 05:00 -> KI-Analyse muss davor fertig sein


def _read_today() -> list:
    today = datetime.now().strftime("%Y-%m-%d")
    if not os.path.exists(CRON_LOG):
        return []
    lines = []
    with open(CRON_LOG, errors="ignore") as f:
        for line in f:
            if today in line:
                lines.append(line.rstrip())
    return lines


def _find_time(lines, needle):
    for ln in lines:
        if needle in ln:
            m = re.search(r"(\d{2}:\d{2}:\d{2})", ln)
            if m:
                return m.group(1)
    return None


def main():
    lines = _read_today()
    if not lines:
        return  # kein Lauf heute (Build-Tag/Wochenende) -> silent
    ki_done = _find_time(lines, "KI Analyse DONE")
    pipe_done = _find_time(lines, "TRADING PIPELINE DONE")
    out = []
    if ki_done:
        late = ki_done > DONE_BY
        status = "⏱ ZU SPÄT (>05:00)" if late else "✅ rechtzeitig"
        out.append(f"[Pipeline-Timing] KI-Analyse DONE heute {ki_done} -> {status}")
        out.append("AC-7-Beweis fuer Task 4 (KI-Analyse-Haertung).")
        if late:
            out.append("Empfehlung: Parallelworker pruefen / Laufzeit weiter druessen.")
    else:
        out.append("[Pipeline-Timing] Heute KEINE 'KI Analyse DONE' — ggf. kein Pipeline-Lauf (Wochenende) oder Fehler.")
    if pipe_done:
        out.append(f"[Pipeline-Timing] TRADING PIPELINE DONE heute {pipe_done}")
    if out:
        print("\n".join(out))


if __name__ == "__main__":
    main()
