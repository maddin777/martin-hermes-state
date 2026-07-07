# Live vs. State Backup — Two Copies of Trading Code

## Das Problem

Es gibt **zwei Kopien** der Trading-Skripts:

| Pfad | Zweck | Wird vom Dashboard verwendet? |
|------|-------|------|
| `/root/.hermes/profiles/hermes_trading/skills/trading/` | **Live-Profil** — vom Dashboard-Prozess geladen | ✅ Ja |
| `/root/martin-hermes-state/profiles/hermes_trading/` | **Git-Backup** — für State-Sync und History | ❌ Nein |

## Konsequenz

Wenn du `dashboard.py` (oder andere Scripts) nur im State-Backup (`martin-hermes-state`) änderst, läuft das Dashboard **weiter mit der alten Version** aus dem Live-Profil (`/root/.hermes/profiles/`).

## Workflow

### Option A: Direkt im Live-Profil editieren (schnell)

```bash
# Datei im Live-Profil editieren
# (patch/write_file auf /root/.hermes/profiles/...)
# Dashboard neustarten
kill $(pgrep -f dashboard.py)
cd /root/.hermes/profiles/hermes_trading/skills/trading && venv/bin/python scripts/dashboard.py &

# Optional: ins State-Backup kopieren für Git-Sync
cp /root/.hermes/profiles/hermes_trading/skills/trading/scripts/dashboard.py \
   /root/martin-hermes-state/profiles/hermes_trading/skills/trading/scripts/dashboard.py
```

### Option B: Im State-Backup editieren, dann kopieren

```bash
# 1. Im State-Backup editieren (patchen, schreiben)
# 2. Ins Live-Profil kopieren
cp /root/martin-hermes-state/profiles/hermes_trading/skills/trading/scripts/dashboard.py \
   /root/.hermes/profiles/hermes_trading/skills/trading/scripts/dashboard.py
# 3. Dashboard neustarten
kill $(pgrep -f dashboard.py)
cd /root/.hermes/profiles/hermes_trading/skills/trading && venv/bin/python scripts/dashboard.py &
```

## Prävention

- Vor dem Editieren von Trading-Skripts: IMMER prüfen welcher Pfad live ist
- `ps aux | grep dashboard.py` zeigt den tatsächlichen Pfad
- `.hermes/profiles/` = live, `martin-hermes-state/` = backup
- Nach dem Editieren: Dashboard neustarten und curl-Test machen