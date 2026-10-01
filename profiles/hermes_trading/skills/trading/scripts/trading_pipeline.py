"""
Trading Pipeline - Sequenzieller Ablauf Mo-Fr 04:00
Wartet auf Abschluss jedes Scripts bevor das naechste startet.
Verhindert Race Conditions zwischen den einzelnen Schritten.

Reihenfolge (fachlich korrekt):
  1. YouTube Scan          – Transkripte holen
  2. KI Analyse            – LLM-Extraktion
  2b. Screener Source      – deterministische Quelle (Momentum+Quality+Regime)
  3. Watchlist Update      – Conviction berechnen
  4. Watchlist Dedup       – Duplikate bereinigen
  5. Technical Analysis    – Tech-Score schreiben (nach Watchlist!)
  6. Signal Manager        – Portfolio-Entscheidungen
  7. Shadow Selection      – konkurrierende Selektions-Hypothesen (nur messen)
"""
import subprocess
import os
import sys
from datetime import datetime

# Sicherstellen dass utils/config aus dem richtigen Verzeichnis geladen werden
sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")
import env_loader  # noqa: F401

from utils import get_logger
from config import SCRIPTS_DIR, CRON_LOG_PATH

PYTHON = "/usr/bin/python3"

# Eigener Logger – KEIN lokales def log() das ihn überschreibt
_log = get_logger("trading_pipeline")


def _validator_enabled() -> bool:
    """N1 (30.09.2026): technical_validator.py braucht ~8 Minuten pro Nacht und schreibt nur
    trading_signals_validated.json, die kein Modul liest (nur der Pfad wird importiert; keine DB-Schreibzugriffe,
    der tech_score kommt aus watchlist_manager/refresh_tech_scores). Schalter `technical_validator_enabled` in
    strategy_config.json, Voreinstellung AUS."""
    try:
        import json
        from config import STRATEGY_CONFIG_PATH
        with open(STRATEGY_CONFIG_PATH, encoding="utf-8") as f:
            return bool(json.load(f).get("technical_validator_enabled", False))
    except Exception:
        return False


def _print(msg):
    """Schreibt gleichzeitig nach cron.log und stdout."""
    print(msg, flush=True)
    _log.info(msg)


def run(script, label, args=""):
    _print(f"\n{'='*60}")
    _print(f"=== {datetime.now().strftime('%H:%M:%S')} {label} START ===")
    _print(f"{'='*60}")
    cmd = [PYTHON, f"{SCRIPTS_DIR}/{script}"]
    if args:
        cmd += args.split()
    # PYTHONPATH an Subprozesse vererben — sonst finden Scripts config.py nicht
    # (crontab setzt kein PYTHONPATH, und sys.path wird nicht vererbt)
    env = os.environ.copy()
    path = "/root/.hermes/profiles/hermes_trading/skills/trading"
    if "PYTHONPATH" in env:
        env["PYTHONPATH"] = f"{path}:{env['PYTHONPATH']}"
    else:
        env["PYTHONPATH"] = path
    result = subprocess.run(cmd, env=env)
    status = "DONE" if result.returncode == 0 else f"ERROR (exit {result.returncode})"
    _print(f"=== {datetime.now().strftime('%H:%M:%S')} {label} {status} ===\n")
    return result.returncode == 0


def main():
    _print(f"\n{'='*60}")
    _print(f"TRADING PIPELINE START: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    _print(f"{'='*60}")

    # WAL-Checkpoint: Offene Transaktionen von vorgelagerten Prozessen
    # (fundamental_data, social_scanner) aufräumen, damit die Pipeline
    # nicht auf einen stale Lock läuft
    import sqlite3
    try:
        from config import DB_PATH, db_connect
        con = db_connect()
        con.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        con.close()
        _print("✅ WAL-Checkpoint: offene Transaktionen bereinigt")
    except Exception as e:
        _print(f"⚠️  WAL-Checkpoint: {e} (nicht kritisch)")

    steps = [
        ("yt_channel_monitor.py",  "YouTube Scan"),
        ("signal_extractor.py",    "KI Analyse"),
        ("screener_source.py",     "Screener Source"),   # NEU: deterministische Quelle VOR Watchlist
        ("watchlist_manager.py",   "Watchlist Update"),
        ("watchlist_dedup.py",     "Watchlist Dedup"),
        ("technical_validator.py", "Technical Analysis"),  # NACH watchlist_manager!
        # 28.09.2026 wieder aktiv: muss ZWISCHEN watchlist_manager und
        # signal_manager laufen — der Watchlist Manager setzt conviction_score
        # jede Nacht auf den Rohwert zurueck, ein eigener Cron-Termin nach der
        # Pipeline waere bis zum naechsten Entry ueberschrieben. NACH dem
        # technical_validator, weil der Validator tech_score >= 0.50 filtert.
        ("llm_validator.py",       "LLM Validator"),
        ("signal_manager.py",      "Signal Manager", "full"),
        # NACH dem Signal Manager: das Baseline-Buch soll denselben Watchlist-
        # Zustand sehen, den der Live-Entry gesehen hat. Rein messend — der
        # Schritt aendert weder Config noch positions (siehe Modul-Docstring).
        ("shadow_selection.py",    "Shadow Selection"),
    ]

    results = []
    for step in steps:
        script = step[0]
        label  = step[1]
        args   = step[2] if len(step) > 2 else ""
        if script == "technical_validator.py" and not _validator_enabled():
            _print(f"⏭ {label} übersprungen (technical_validator_enabled=false)")
            results.append((f"{label} (übersprungen)", True))
            continue
        ok     = run(script, label, args)
        results.append((label, ok))
        if not ok:
            _print(f"⚠️  {label} fehlgeschlagen - Pipeline laeuft weiter")

    _print(f"\n{'='*60}")
    _print(f"✅ TRADING PIPELINE DONE: {datetime.now().strftime('%H:%M:%S')}")
    _print(f"{'='*60}")
    for label, ok in results:
        icon = "✅" if ok else "❌"
        _print(f"  {icon} {label}")


if __name__ == "__main__":
    main()
