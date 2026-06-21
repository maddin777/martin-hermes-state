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

## Fix: Job löschen und im Default-Scheduler neu anlegen mit `profile:`-Feld

**Nicht versuchen den kaputten Job zu reparieren** — die Profil-Cron-DB hat kein Migrationsschema und der Scheduler erwartet bestimmte Felder. Stattdessen:

```
1. Kaputten Job aus Profil-DB löschen:
   sqlite3 /root/.hermes/profiles/<name>/cron/cron.db \
     "DELETE FROM cron_jobs WHERE id IS NULL AND name='<jobname>';"

2. Job im **default Scheduler** neu anlegen, mit profile=<profilname>:
   cronjob action=create \
     name="<name>" \
     schedule="..." \
     prompt="..." \
     profile="<profilname>"
```

Wichtig: `profile` muss **als Parameter** an cronjob übergeben werden, nicht durch Auswahl des Profils im Session-Kontext. Der default Session-Scheduler legt dann einen korrekt strukturierten Job-Eintrag an.

## Verification nach Fix

```bash
# Job existiert mit gültiger ID?
hermes cron list | grep <jobname>
# → sollte id zeigen, nicht null

# Nächsten Lauf prüfen
hermes cron list | grep -A2 <jobname>
# → next_run_at sollte in Zukunft liegen
```

## Pitfalls

- **Profil-Session vs default-Session:** Wenn du `session -p <profil>` startest und dort `cronjob create` ausführst, landen Jobs in der Profil-Cron-DB (potenziell defekt). Besser: Immer im default-Session arbeiten und `profile=<name>` setzen.
- **Keine Fehlermeldung:** Der Scheduler gibt keinen Error bei defekten Jobs — er überspringt sie einfach still. Einzige Erkennung: direkter DB-Check auf NULL-IDs.
- **Gateway-Abhängigkeit prüfen:** Wenn der Job auf Telegram-Delivery angewiesen ist (`deliver: telegram:...`), muss der Gateway-Service laufen. Gateway-Watchdog prüft Service+TG-API alle 30min.
- **Profil .env beachten:** Profil-spezifische Jobs brauchen ggf. Umgebungsvariablen aus der Profil-`.env` (API-Keys, Channel-IDs). Der `profile=` Parameter lädt diese automatisch.