"""
Zentraler .env-Loader fuer Trading-Skill.
Wird beim ersten Import beliebiger Client-Module ausgefuehrt.
Cron-safe: arbeitet unabhaengig von Shell-Environment.
"""
import os
from pathlib import Path

_LOADED = False

def load() -> None:
    global _LOADED
    if _LOADED:
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        _LOADED = True
        return

    # Reihenfolge: profil-spezifisch ueberschreibt global NICHT (override=False)
    candidates = (
        Path("/root/.hermes/profiles/hermes_trading/.env"),
        Path("/root/.hermes/.env"),
    )
    for env_path in candidates:
        if env_path.is_file():
            load_dotenv(env_path, override=False)
    _LOADED = True


# Beim Import sofort laden
load()
