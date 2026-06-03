"""
Zentraler .env-Loader fuer Trading-Skill.
Import: `import env_loader` (one-shot side-effect).
Cron-safe, kein PYTHONPATH-Setup noetig.
"""
import os
from pathlib import Path

_LOADED = False

def _load() -> None:
    global _LOADED
    if _LOADED:
        return
    try:
        from dotenv import load_dotenv
        for p in (Path("/root/.hermes/profiles/hermes_trading/.env"),
                  Path("/root/.hermes/.env")):
            if p.is_file():
                load_dotenv(p, override=False)
    except ImportError:
        # Fallback: minimaler Parser wie in xsearch_helper.py
        for p in ("/root/.hermes/profiles/hermes_trading/.env",
                  "/root/.hermes/.env"):
            if os.path.exists(p):
                with open(p) as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            os.environ.setdefault(k.strip(), v.strip())
    _LOADED = True

_load()
