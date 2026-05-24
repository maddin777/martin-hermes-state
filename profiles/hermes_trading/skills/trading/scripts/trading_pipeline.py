"""
Trading Pipeline - Sequenzieller Ablauf Mo-Fr 04:00
Wartet auf Abschluss jedes Scripts bevor das naechste startet.
Verhindert Race Conditions zwischen den einzelnen Schritten.
"""
import subprocess
import os
from datetime import datetime

SCRIPTS = "/root/.hermes/profiles/hermes_trading/skills/trading/scripts"
LOG     = "/root/.hermes/profiles/hermes_trading/skills/trading/data/cron.log"
PYTHON  = "/usr/bin/python3"

def log(msg):
    print(msg, flush=True)

def run(script, label, args=""):
    log(f"\n{'='*60}")
    log(f"=== {datetime.now().strftime('%H:%M:%S')} {label} START ===")
    log(f"{'='*60}")
    cmd = [PYTHON, f"{SCRIPTS}/{script}"]
    if args:
        cmd += args.split()
    result = subprocess.run(cmd)
    status = "DONE" if result.returncode == 0 else f"ERROR (exit {result.returncode})"
    log(f"=== {datetime.now().strftime('%H:%M:%S')} {label} {status} ===")
    return result.returncode == 0

def main():
    log(f"\n{'='*60}")
    log(f"TRADING PIPELINE START: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"{'='*60}")

    steps = [
        ("yt_channel_monitor.py",  "YouTube Scan"),
        ("signal_extractor.py",    "KI Analyse"),
        ("watchlist_manager.py",   "Watchlist Update"),
        ("technical_validator.py", "Technical Analysis"),
        ("signal_manager.py",      "Signal Manager", "full"),
    ]

    results = []
    for step in steps:
        script = step[0]
        label  = step[1]
        args   = step[2] if len(step) > 2 else ""
        ok     = run(script, label, args)
        results.append((label, ok))
        if not ok:
            log(f"⚠️  {label} fehlgeschlagen - Pipeline laeuft weiter")

    log(f"\n{'='*60}")
    log(f"TRADING PIPELINE DONE: {datetime.now().strftime('%H:%M:%S')}")
    log(f"{'='*60}")
    for label, ok in results:
        icon = "✅" if ok else "❌"
        log(f"  {icon} {label}")

if __name__ == "__main__":
    main()
