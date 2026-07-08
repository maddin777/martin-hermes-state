# Live vs. State Backup — Two Copies of Trading Code

## Das Problem

Es gibt **zwei Kopien** der Trading-Skripts:

| Pfad | Zweck | Wird vom Dashboard verwendet? |
|------|-------|------|
| `/root/.hermes/profiles/hermes_trading/skills/trading/` | **Live-Profil** — vom Dashboard-Prozess geladen | ✅ Ja |
| `/root/martin-hermes-state/profiles/hermes_trading/` | **Git-Backup** — für State-Sync und History | ❌ Nein |

## Konsequenz

Wenn du `dashboard.py` (oder andere Scripts) nur im State-Backup (`martin-hermes-state`) änderst, läuft das Dashboard **weiter mit der alten Version** aus dem Live-Profil (`/root/.hermes/profiles/`).

## Workflow — Systemd beachten!

Das Dashboard läuft **unter systemd** (`trading-dashboard.service`), nicht als `nohup`-Background-Prozess. Ein manuelles `kill` + `python dashboard.py &` legt einen zweiten Prozess an, der beim nächsten systemd-Restart überschrieben wird.

### Option A: Direkt im Live-Profil editieren (schnell)

```bash
# 1. Datei im Live-Profil editieren
# (patch/write_file auf /root/.hermes/profiles/...)

# 2. Dashboard per systemd neustarten
systemctl restart trading-dashboard.service

# 3. Warten + Testen
sleep 3
curl -s -o /dev/null -w "%{http_code}" http://192.168.178.16:8081

# 4. Optional: ins State-Backup kopieren für Git-Sync
cp /root/.hermes/profiles/hermes_trading/skills/trading/scripts/dashboard.py \
   /root/martin-hermes-state/profiles/hermes_trading/skills/trading/scripts/dashboard.py
```

### Option B: Im State-Backup editieren, dann kopieren + systemd

```bash
# 1. Im State-Backup editieren (patchen, schreiben) — Hermes' Default-Pfad
# 2. Ins Live-Profil kopieren
cp /root/martin-hermes-state/profiles/hermes_trading/skills/trading/scripts/dashboard.py \
   /root/.hermes/profiles/hermes_trading/skills/trading/scripts/dashboard.py

# 3. Dashboard per systemd neustarten
systemctl restart trading-dashboard.service
sleep 3
curl -s -o /dev/null -w "%{http_code}" http://192.168.178.16:8081
```

### 🚨 Fallstrick: Hintergrund-Prozess blockiert systemd

Wenn du versehentlich `python dashboard.py &` (ohne systemd) gestartet hast, crasht systemd beim nächsten Restart mit `Address already in use`. **Immer beide killen:**

```bash
pgrep -f dashboard.py | xargs kill -9 2>/dev/null
sleep 2
systemctl restart trading-dashboard.service
```

## `load_dotenv()` — DASHBOARD_BIND wirkt nur bei geladener .env

Seit 07.07.2026 lädt `dashboard.py` im `__main__`-Block die `.env` aus dem Trading-Profil:

```python
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(os.path.join(SCRIPTS_DIR, "..", ".env"))
    ...
```

Das bedeutet: `DASHBOARD_BIND=0.0.0.0` funktioniert jetzt **auch ohne** den Watchdog-Workaround (`export $(grep -v '^#' .env | xargs)`). Der `__main__`-Block kümmert sich selbst darum. Der systemd-Service hat `Environment=DASHBOARD_BIND=0.0.0.0` im override.conf als Fallback.

**Prüfen ob DASHBOARD_BIND aktiv ist:**
```bash
ss -tlnp | grep 8081  # Sollte 0.0.0.0:8081 zeigen, nicht 127.0.0.1:8081
```

## Prävention

- Vor dem Editieren von Trading-Skripts: IMMER prüfen welcher Pfad live ist
- `ps aux | grep dashboard.py` zeigt den tatsächlichen Pfad
- `.hermes/profiles/` = live, `martin-hermes-state/` = backup
- Nach dem Editieren: `systemctl restart trading-dashboard.service` + curl-Test
- Nicht `kill` + `python &` — das legt einen orphaned Prozess an der systemd blockiert