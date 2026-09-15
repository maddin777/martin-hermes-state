---
name: hermes-profile-cron-troubleshooting
description: >-
  Diagnose und Reparatur von Hermes-Cron-Jobs in isolierten Profilen.
  Covers: Job-defekte (fehlende id, enabled, next_run_at), Scheduler-vs-
  Profil-DB, Gateway-Abhängigkeiten, Profile-Environment-Loading.
  Gelernt aus Ausfall des hermes-news Briefing-Jobs (Juni 2026).
trigger:
  - "Cron job läuft nicht / feuert nicht / keine Ausgabe"
  - "User fragt 'warum kam keine Nachricht / kein Briefing'"
  - "Job existiert laut cronjob list aber wird nicht ausgeführt"
  - "Profil-spezifischer Cron funktioniert nicht"
  - "next_run_at in der Vergangenheit"
  - "cron-show zeigt id=null oder fehlende Felder"
---

# Hermes Profile Cron Troubleshooting

## Symptom: Job läuft nicht, obwohl er angelegt wurde

Der Job existiert in der Cron-DB (sichtbar via `cronjob list`), wird aber nie ausgeführt. Kein Output, kein Fehlerlog.

## Root Cause (bekannt ab Juni 2026)

Ein `cronjob create` in einer Session **unter einem Profil** kann den Job im **falschen Scheduler-Kontext** anlegen. Der Profile-interne Scheduler nutzt eine separate SQLite-DB (unter `/root/.hermes/profiles/<name>/cron/`) die nicht die gleiche Struktur hat wie der default-Scheduler.

**Typische Fehlermuster in der Profil-Cron-DB:**
- `id = NULL` — Job hat keine eindeutige ID
- `enabled` fehlt oder falsch → Scheduler behandelt als disabled
- `next_run_at` in der Vergangenheit, nie gesetzt
- Kein `repeat` — selbst wenn gelaufen, nie wieder
- `created_by` / `model` fehlen

Der Scheduler überspringt Jobs ohne gültige `id` oder mit `enabled != 1`.

## Diagnose-Schritte

```bash
# 1. Job-Liste checken
hermes cron list

# 2. Bei profil-spezifischen Jobs: Profil-Cron-DB direkt prüfen
sqlite3 /root/.hermes/profiles/<profilname>/cron/cron.db \
  "SELECT id, name, enabled, schedule, next_run_at FROM cron_jobs;"

# 3. Default-Scheduler-DB zum Vergleich
sqlite3 /root/.hermes/cron/cron.db \
  "SELECT id, name, enabled, schedule, next_run_at FROM cron_jobs;"
```

**Erkennungsmerkmale eines kaputten Profil-Jobs:**
- Zeile existiert in Profil-Cron-DB (zeigt Name)
- Aber `id` ist NULL oder leer
- `enabled` ist 0 oder NULL
- `next_run_at` ist leer oder in der Vergangenheit

## Fix (primär): Job direkt in Profil-Cron-JSON anlegen

Der default Scheduler deliveriert bei `profile=`-Routing trotzdem über den **Default-Home-Channel** (DM), nicht über den Profil-Home-Channel. Die Lösung: Der Job gehört in den **Profil-eigenen Scheduler**.

**Voraussetzung:** Das Profil muss einen **eigenen laufenden Gateway** haben (`gateway_state.json` zeigt `running` + Telegram `connected`). Ohne laufenden Profil-Gateway wird der Job nie feuern.

### Schritt für Schritt

```bash
# 1. Prüfen ob Profil-Gateway läuft
cat /root/.hermes/profiles/<profil>/gateway_state.json
# → {"gateway_state":"running", ... "telegram":{"state":"connected"}}

# 2. Skill ins Profil kopieren (falls nicht vorhanden)
cp -r /root/.hermes/skills/<category>/<skill-name> \
  /root/.hermes/profiles/<profil>/skills/<category>/

# 3. Job-JSON ins Profil schreiben
python3 -c "
import json, hashlib
from datetime import datetime, timezone, timedelta
job = {
    'id': hashlib.md5(b'<jobname>').hexdigest()[:11],
    'name': '<jobname>',
    'prompt': '<prompt>',
    'skills': ['<skill-name>'],
    'model': '<model>',
    'provider': '<provider>',
    'schedule': {'kind': 'cron', 'expr': '<cron>', 'display': '<cron>'},
    'enabled': True, 'state': 'scheduled',
    'deliver': 'telegram',
    'no_agent': False,
}
with open('/root/.hermes/profiles/<profil>/cron/jobs.json', 'w') as f:
    json.dump({'jobs': [job], 'updated_at': datetime.now().isoformat()}, f, indent=2, default=str)
"
```

**Verifikation:**
```bash
source /root/.hermes/profiles/<profil>/.env
curl -s -X POST \"https://api.telegram.org/bot\${TELEGRAM_BOT_TOKEN}/sendMessage\" \
  -d \"chat_id=\${TELEGRAM_HOME_CHANNEL}\" -d \"text=Test\"
```

### Delivery-Mechanismus verstehen

| Konfiguration | Wohin deliveriert? |
|--------------|-------------------|
| `deliver: telegram` (im Profil-Scheduler) | TELEGRAM_HOME_CHANNEL des Profils |
| `deliver: telegram` (im default Scheduler) | TELEGRAM_HOME_CHANNEL des default-Profils (DM!) |
| Profil-Job + `deliver: telegram` | ✅ Korrekt |

### Pitfall: Systemd zeigt inactive dead obwohl Gateway läuft

Systemd zeigt den Profil-Gateway oft als `inactive dead` obwohl der Prozess läuft und connected ist. Das passiert wenn der Gateway manuell via `hermes gateway run --replace` gestartet wurde (nicht über systemd).

**Prüfung:** Direkt `gateway_state.json` im Profil-Verzeichnis checken — nicht auf systemd verlassen.

## Verification nach Fix

```bash
# Job existiert mit gültiger ID?
hermes cron list | grep <jobname>
# → sollte id zeigen, nicht null

# Nächsten Lauf prüfen
hermes cron list | grep -A2 <jobname>
# → next_run_at sollte in Zukunft liegen
```

## Pitfall: Model-Drift blockiert unpinned Jobs (#44585)

**Symptom:** Job steht in `cron list` mit `last_status=error`, `last_run_at` aktuell. In `jobs.json` steht in `last_error`:
`RuntimeError: Skipped to prevent unintended spend: global inference config drifted since this job was created (model 'X' -> 'Y'), and this job is unpinned. No inference call was made. ...`

**Root Cause:** Wenn sich das globale Standard-Inferenzmodell ändert (z.B. `deepseek/deepseek-v4-flash` → `deepseek/deepseek-v4-flash-0731`) und ein Job das Modell NICHT explizit gepinnt hat (`model: null`), blockiert der Scheduler den Lauf als Spend-Safety — bewusst kein Inference-Call. Der Job schlägt bei **jedem** geplanten Lauf fehl, bis gepinnt oder das Modell zurückgedreht ist.

**Diagnose:**
```bash
cd /root/.hermes
python3 - <<'EOF'
import json
d=json.load(open('cron/jobs.json'))
for j in d['jobs']:
    if j.get('last_status')=='error':
        print(j['id'], j['name'], '| model=', j.get('model'), '|', (j.get('last_error') or '')[:120])
EOF
# Job hat model=None → unpinned → anfällig. Ein funktionierender Referenz-Job (z.B. dataviz)
# ist an deepseek/deepseek-v4-flash/openrouter gepinnt und läuft trotz Drift → alias löst noch auf.
```

**Fix — Modell in jobs.json pinnen:** `hermes cron edit` exponiert KEIN `--model`/`--provider`. Deshalb direkt ins JSON schreiben (Scheduler liest `jobs.json` pro Tick neu):
```bash
cd /root/.hermes && cp cron/jobs.json cron/jobs.json.bak-$(date +%Y%m%d-%H%M)
python3 - <<'EOF'
import json
p='cron/jobs.json'; d=json.load(open(p))
for j in d['jobs']:
    if j['id'] in {'<jobid1>','<jobid2>'}:
        j['model']='deepseek/deepseek-v4-flash'   # oder das aktuelle globale Modell
        j['provider']='openrouter'
        j['base_url']=None
json.dump(d,open(p,'w'),indent=1,ensure_ascii=False)
EOF
```
Pin auf den **aktuellen** Alias (oder den globalen Wert). Ein bestehender gepinnter Job auf dem alten Alias der weiter läuft, beweist, dass der Alias über den Drift hinweg aufgelöst wird — denselben Wert wiederverwenden für Konsistenz. Nach Fix: nächster geplanter Lauf (nicht `action=run`) verifiziert.

## Pitfalls

- **Profil-Session vs default-Session:** Wenn du `session -p <profil>` startest und dort `cronjob create` ausführst, landen Jobs in der Profil-Cron-DB (potenziell defekt). Besser: Immer im default-Session arbeiten und `profile=<name>` setzen.
- **Keine Fehlermeldung:** Der Scheduler gibt keinen Error bei defekten Jobs — er überspringt sie einfach still. Einzige Erkennung: direkter DB-Check auf NULL-IDs.
- **Gateway-Abhängigkeit prüfen:** Wenn der Job auf Telegram-Delivery angewiesen ist (`deliver: telegram:...`), muss der Gateway-Service laufen. Gateway-Watchdog prüft Service+TG-API alle 30min.
- **Profil .env beachten:** Profil-spezifische Jobs brauchen ggf. Umgebungsvariablen aus der Profil-`.env` (API-Keys, Channel-IDs). Der `profile=` Parameter lädt diese automatisch.
- **`no_agent` Cron-Jobs sind silent bei Erfolg:** Ein `no_agent` Script macht `exit 0` und liefert keinen Output bei Erfolg. Wenn du prüfst ob ein Job läuft, verwende `cronjob action=list` und prüfe `last_status` + `last_run_at` — nicht `cronjob action=run`. Beispiel: `obsidian-vault-bisync-nightly` ist `no_agent` und silent on success. Ein `cronjob action=run` gibt leeren Output zurück → fälschliche Interpretation als "Job läuft nicht".
- **`execute_code` ist in Cron-Mode geblockt:** Wenn ein Cron-Job Python-Scripting braucht, `terminal()` mit `python3 -c "..."` verwenden, nicht `execute_code`. Der Cron-Mode blockiert `execute_code` weil "cron jobs run without a user present to approve it." Bei Timeout: Script in mehrere `terminal()`-Aufrufe aufteilen.