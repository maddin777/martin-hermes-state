---
name: gateway-watchdog
description: "Überwachung + Restart des Hermes Gateway via systemd + Cron-Watchdog. Zweistufiger Schutz: systemd (3x/10min Limit) + no_agent Cron (alle 30min), Eskalation bei >2x gleichem Fehler in 60min."
category: devops
---

# Gateway Watchdog

Schutz für Hermes Gateway (Telegram) gegen Ausfälle.

## Architektur

**Stufe 1 — systemd (dummer Schutz)**
- `Restart=on-failure` statt `always`
- `StartLimitBurst=3` / `StartLimitIntervalSec=600` — max 3 Restarts in 10min
- Verhindert Endlos-Loop bei permanentem Fehler

**Stufe 2 — Cron-Watchdog (intelligenter Schutz)**
- Alle 30min via `no_agent=True` Cron
- Script: `~/.hermes/scripts/gateway-watchdog.py`
- Prüft: Service aktiv? Telegram API antwortet (`getMe`)?
- Beides OK → stiller Exit (kein Log, keine Nachricht)
- Fehler → Service restart + Log-Eintrag
- Gleicher Fehler >2x in 60min → CRITICAL (kein Restart, manuelles Eingreifen nötig)

## Setup bei frischer Installation

1. systemd Drop-In anlegen:
   ```
   mkdir -p /etc/systemd/system/hermes-gateway.service.d
   cat > /etc/systemd/system/hermes-gateway.service.d/99-restart-limit.conf << 'CONF'
   [Service]
   Restart=on-failure
   StartLimitBurst=3
   StartLimitIntervalSec=600
   CONF
   systemctl daemon-reload
   systemctl restart hermes-gateway.service
   ```

2. Watchdog-Script: `/root/.hermes/scripts/gateway-watchdog.py`

3. Cron-Job (no_agent=True, alle 30min):
   Script-Pfad: `gateway-watchdog.py`
   deliver: `local`

## Fehlerbehandlung

**Watchdog-Log:** `/root/.hermes/logs/gateway-watchdog.log`

**CRITICAL im Log** = Service wurde >2x in 60min wegen gleichem Fehler restartet.
Manuell prüfen:
```
systemctl status hermes-gateway.service
cat ~/.hermes/logs/gateway-watchdog.log | tail -10
cat ~/.hermes/logs/gateway.log | tail -20
```

**Nach Behebung:** Watchdog-Tracking zurücksetzen:
```
rm -f /tmp/hermes-gateway-watchdog-track
systemctl reset-failed hermes-gateway.service
systemctl restart hermes-gateway.service
```

## Telegram-Fallback-Problem

Falls `telegram connect timed out` auftritt, obwohl `api.telegram.org` erreichbar ist:
- `HERMES_TELEGRAM_DISABLE_FALLBACK_IPS=true` in `~/.hermes/.env` setzen
- Service restarten

**Multi-Profile:** Der Fix muss in JEDER Profil-`.env` gesetzt werden, die einen eigenen Telegram-Gateway hat.
Siehe `references/gateway-fallback-timeout-2026-05-11.md` für die vollständige Diagnose- und Reparatur-Rezeptur
inklusive aller Profile, Bot-Token und Service-Namen.

## Systemd Drain Timeout Mismatch

Bei `systemctl restart` des Gateways kann der Service im **"deactivating"**-Zustand hängen bleiben.

**Symptom in Logs:**
```
WARNING gateway.run: Stale systemd unit detected: ...
has TimeoutStopSec=60s but drain_timeout=60s
(expected >=90s). systemd may SIGKILL the gateway mid-drain.
Run `hermes gateway service install --replace` to regenerate the unit.
```

**Fix (einmalig):**
```bash
# 1. Gateway killen wenn er in deactivating hängt
systemctl kill hermes-gateway-{profil}.service

# 2. systemd Reset
systemctl reset-failed hermes-gateway-{profil}.service

# 3. Unit neu generieren (behebt TimeoutStopSec/drain Mismatch)
hermes --profile {profil} gateway service install --replace

# 4. Starten
systemctl start hermes-gateway-{profil}.service
```

Danach hängt der Gateway beim Restart nicht mehr — die regenerierte Unit hat korrekte TimeoutStopSec.

## Post-Reboot Health Check

Nach LXC/VM-Restart **nicht** darauf verlassen, dass alle Gateway-Services automatisch starten. Ein Service kann eine Unit-Datei haben (`/etc/systemd/system/hermes-gateway-{profil}.service`) aber **disabled** sein → läuft nach Reboot nicht an.

### Checkliste nach Neustart

```bash
# 1. Alle hermes-gateway-Services prüfen (running + enabled)
systemctl list-units --type=service --all | grep hermes-gateway

# 2. Enabled-Check: gefolgt von L nach dem Service-Namen?
#    enabled → [●] hermes-gateway-XXX.service loaded active running
#    disabled → [○] hermes-gateway-XXX.service loaded inactive dead

# 3. Alle deaktivierten Services explizit starten + enable
systemctl start hermes-gateway-{profil}.service
systemctl enable hermes-gateway-{profil}.service

# 4. Cronjobs prüfen (alle enabled + scheduled)
hermes cron list

# 5. Sonstige Dauerprozesse prüfen (Dashboard etc.)
ps aux | grep -iE 'dashboard|watchdog|bot'
```

### Bekannte Fälle

- `hermes-gateway-hermes_trading.service` war **vorhanden aber disabled** — nach LXC-Restart nicht gestartet. Lösung: `systemctl enable --now hermes-gateway-hermes_trading.service`

## Cron-Integration — Two-Tier System

Der Scheduler läuft **im Gateway-Prozess**. Gateway down = Cron läuft nicht.

Hermes hat zwei unabhängige Cron-Systeme:
- **Globaler Scheduler** (`/root/.hermes/cron/jobs.json`) — Default-Profil
- **Profil-eigener Scheduler** (`{profile}/cron/jobs.json`) — je Gateway-Profil

Ein Profil-Cron-Job läuft NUR, wenn das zugehörige Gateway aktiv ist. Gateway gestoppt/systemd-failed → kein Tick → alle Jobs bleiben liegen.

**Diagnose bei "Cron läuft nicht mehr seit Datum X":**
1. `hermes profile list` → Gateway running/stopped?
2. `systemctl status hermes-gateway-{profil}.service` → systemd tot?
3. `journalctl -u hermes-gateway-{profil}.service -n 50` → Todesursache?
4. `cat {profile}/cron/jobs.json` → next_run_at in Vergangenheit?

Siehe `references/profile-cron-outage-diagnosis.md` für die vollständige Diagnose- und Recovery-Rezeptur inklusive systemd-Reset, env-Fix und Verifikation.

Der Watchdog schützt indirekt auch die Cron-Zuverlässigkeit.