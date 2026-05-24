# Profile-Cron-Ausfall-Diagnose

Wenn ein User fragt "warum läuft Cron X nicht mehr seit Datum Y" und der Job im globalen Scheduler nicht existiert:

## Architektur: Two-Tier Cron System

Hermes hat **zwei unabhängige Cron-Systeme**:

| Scheduler | Jobs-Pfad | Läuft nur wenn... |
|---|---|---|
| Default/Global | `/root/.hermes/cron/jobs.json` | Default-Gateway aktiv |
| Profil-eigen | `/root/.hermes/profiles/{profil}/cron/jobs.json` | **Profil-Gateway aktiv** |

**Kardinalregel:** Der Profil-Scheduler läuft im Gateway-Prozess des Profils. Gateway down = kein Tick = keine Cron-Runs.

## Diagnose-Kette

### Schritt 1: Profil-Gateway-Status prüfen
```bash
hermes profile list           # Zeigt running/stopped/failed
hermes profile status <name>
systemctl status hermes-gateway-<profilname>.service
```

### Schritt 2: Profil-Cron-Jobs prüfen
```bash
cat /root/.hermes/profiles/{profil}/cron/jobs.json
```
Achtung: `last_run_at` und `next_run_at` sind die Schlüsselfelder. Wenn `next_run_at` in der Vergangenheit liegt, läuft der Scheduler nicht.

### Schritt 3: systemd-Logs für Todesursache
```bash
journalctl -u hermes-gateway-{profil}.service --no-pager -n 50
```

Häufige Todesursachen:
- `telegram connect timed out after 30s` → Telegram-Fallback-IPs (siehe gateway-fallback-timeout)
- `Start request repeated too quickly` → systemd StartLimitBurst erschöpft
- `Main process exited, code=exited, status=1/FAILURE` → Gateway gestartet, Telegram-Verbindung fehlgeschlagen, sofort gecrasht

### Schritt 4: systemd-Limit prüfen
```bash
systemctl cat hermes-gateway-{profil}.service | grep -E "StartLimit|Restart"
```
Typisch: `StartLimitBurst=5`, `StartLimitIntervalSec=600`. Nach 5 Crashes in 10min gibt systemd auf.

## Recovery

### 1. Umgebungsvariable setzen (falls Telegram-Timeout)
```bash
echo "HERMES_TELEGRAM_DISABLE_FALLBACK_IPS=true" >> /root/.hermes/profiles/{profil}/.env
```

### 2. systemd zurücksetzen + neu starten
```bash
systemctl reset-failed hermes-gateway-{profil}.service
systemctl start hermes-gateway-{profil}.service
sleep 10
systemctl status hermes-gateway-{profil}.service --no-pager -l
```

### 3. Verifizieren: Scheduler tickt
```bash
cat /root/.hermes/profiles/{profil}/cron/jobs.json | python3 -c "
import json,sys
d=json.load(sys.stdin)
for j in d['jobs']:
    print(j['name'], '| nächster:', j.get('next_run_at','?')[:19], '| runs:', j['repeat']['completed'], '| Status:', j['last_status'])"
```

Nach Gateway-Start sollte `next_run_at` aktualisiert sein (vom Scheduler neu berechnet für den nächsten planmäßigen Termin). **Versäumte Runs werden nicht nachgeholt** — der Scheduler springt auf den nächsten Turnus.

## Pitfalls

- **Nicht im globalen jobs.json suchen** wenn der Job per `--profile X` erstellt wurde. Profil-Jobs sind unsichtbar für den globalen Scheduler.
- **.env nicht vergessen**: Profile haben ihre eigene `.env`. Ein Fix in `/root/.hermes/.env` wirkt NICHT auf Profil-Gateways. Jedes Profil braucht eigene env-Vars.
- **systemd gibt lautlos auf**: Nach StartLimitBurst wird der Service auf "failed" gesetzt ohne sichtbare Warnung. Erst `systemctl status` oder `journalctl` zeigt es.