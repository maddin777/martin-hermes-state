"""
Thematic Pipeline — Taeglicher Ablauf 03:00 (Mo-Fr).
Sequenziell, jeder Schritt wartet auf Vorgaenger.
Enthaelt Prediction-Market-Scanner + Theme-Discovery + gesamte Pipeline.
"""
import subprocess
import os
from datetime import datetime

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
PYTHON = "/usr/bin/python3"


def log(msg):
    print(msg, flush=True)


def run(script, label):
    log(f"\n{'='*60}")
    log(f"=== {datetime.now().strftime('%H:%M:%S')} {label} START ===")
    log(f"{'='*60}")
    script_path = os.path.join(SCRIPTS, script)
    result = subprocess.run([PYTHON, script_path])
    status = "DONE" if result.returncode == 0 else f"ERROR (exit {result.returncode})"
    log(f"=== {datetime.now().strftime('%H:%M:%S')} {label} {status} ===")
    return result.returncode == 0


def main():
    log(f"\n{'='*60}")
    log(f"THEMATIC PIPELINE START: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"{'='*60}")

    steps = [
        ("prediction_market_scanner.py", "PM Scanner"),
        ("theme_discovery.py",          "Theme Discovery"),
        ("beneficiary_mapper.py",       "Beneficiary Mapping"),
        ("fundamental_screener.py",     "Fundamental Screen"),
        ("factor_ranker.py",            "Factor Ranking"),
        ("timing_validator.py",         "Technical Timing"),
        ("thesis_monitor.py",           "Position Thesis Check"),
        ("briefing.py",                 "Daily Briefing"),
    ]

    results = []
    for script, label in steps:
        ok = run(script, label)
        results.append((label, ok))
        if not ok:
            log(f"⚠️  {label} fehlgeschlagen - Pipeline laeuft weiter")

    log(f"\n{'='*60}")
    log(f"THEMATIC PIPELINE DONE: {datetime.now().strftime('%H:%M:%S')}")
    log(f"{'='*60}")
    for label, ok in results:
        icon = "✅" if ok else "❌"
        log(f"  {icon} {label}")


if __name__ == "__main__":
    main()