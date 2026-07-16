# Subprocess PYTHONPATH — Fix für Pipeline-Import-Fehler

## Problem

Die `trading_pipeline.py` startet Subprozesse via `subprocess.run()`.
Crontab-Umgebungen setzen kein `PYTHONPATH`. Die Kind-Prozesse finden
weder `config.py` noch das richtige `utils.py`.

## Symptome

| Log-Eintrag | Ursache |
|-------------|---------|
| `ModuleNotFoundError: No module named 'config'` | Trading-Verzeichnis fehlt im PYTHONPATH |
| `ImportError: cannot import name 'get_technical_score' from 'utils' (/root/.hermes/hermes-agent/utils.py)` | Hermes-eigenes `utils.py` wird gefunden (weil `/root/.hermes/hermes-agent/` irgendwo im Pfad liegt), aber das Trading-`utils.py` nicht |

## Unterscheidung zu DB-Lock

- **DB-Lock:** WAL-Checkpoint im Log fehlt oder zeigt Fehler. Mehrere Pipeline-Schritte ❌.
- **PYTHONPATH-Fehler:** WAL-Checkpoint ✅ im Log. `ModuleNotFoundError` oder `ImportError` in den Subprozess-Logs.

## Fix

In `trading_pipeline.py` `run()`-Funktion:

```python
def run(script, label, args=""):
    ...
    env = os.environ.copy()
    path = "/root/.hermes/profiles/hermes_trading/skills/trading"
    if "PYTHONPATH" in env:
        env["PYTHONPATH"] = f"{path}:{env['PYTHONPATH']}"
    else:
        env["PYTHONPATH"] = path
    result = subprocess.run(cmd, env=env)
    ...
```

## Prävention

Jedes neue Script das per `trading_pipeline.py` gestartet wird:
- Muss `from config import ...` verwenden
- Darf KEIN `sys.path.insert(0, ...)` benötigen — der PYTHONPATH muss reichen
- Prüfung: `grep -c "sys.path.insert" scripts/*.py` sollte nur in `trading_pipeline.py` Matches geben