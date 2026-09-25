---
name: hermes-profile-ops
description: "Hermes profiles: cron, bot mode, vault, management."
trigger:
  - "Hermes profile"
  - "Cron jobs not running"
  - "Bot mode"
---

# Hermes Profile Operations

Unified skill for Hermes profile operations, cron troubleshooting, vault management, and bot mode.

## Subsections

- **hermes-profile-cron-troubleshooting** — Diagnose/fix broken cron jobs in profiles
- **hermes-bot-mode-roster** — Build Hermes Bot Mode role bots
- **hermes-vault-management** — Obsidian vault lifecycle
- **hermes-profile-management** — End-to-end profile management

## Duplicate Telegram Credential Triage (Doctor)

Der Doctor meldet oft identische „Duplicate platform credential across profiles"-Warnungen (TELEGRAM_BOT_TOKEN). Die sind NICHT automatisch echte Konflikte:
nur **aktive Gateways**, die denselben Token halten, streiten real um den Bot.
Brachliegende Tokens in Profilen ohne laufendes Gateway (Roster-/Delegation-Profile)
sind harmlos und der Doctor meldet sie weiter, bis man sie anfasst.

**Triage:** 1) Token-Hash je Profil vergleichen (sha256, nie Secret ausgeben),
2) nur `systemctl list-units | grep hermes-gateway` running-Services zählen.
Nur bei 2+ aktiven Gateways mit gleichem Token handeln: Token+CHAT_ID aus dem
Überschuss-Profil (API-Server-only) per sed entfernen, dann **BEIDE** Gateways
restarten — der geparkte Gateway reconnected nicht von selbst, er bleibt degraded.
Verify: `grep telegram ~/.hermes/logs/gateway.log | tail` → '✓ telegram connected'.
Roster-Profile ohne laufenden Gateway NICHT anfassen.

Siehe vollständige Prozedur in `references/duplicate-token-triage.md`.

## Cron Job Prompt Editing

Ein Cron-Job's `prompt` IST seine Skill-Definition (neben optionalen `--skill`-Verknüpfungen). Um zu ändern, was ein Cron tut / worauf er achtet, editiere den Prompt — es gibt oft kein separates Skill-File (z.B. vault-insights-daily existiert nur als Cron-Prompt, obwohl Memory von einem „Skill" spricht).

**Prozedur:**
1. Aktuellen Prompt aus `/root/<profil>/.hermes/cron/jobs.json` extrahieren: Python-laden, verschachtelte Dicts gehen, das Dict mit `id == <job_id>` finden, `job['prompt']` in eine Datei schreiben.
2. Die Text-Änderung mit `open(..., encoding='utf-8')` lesen + gezieltem replace. Den Replace-Anker auf den EXAKTEN on-disk-Text stützen (vorher die tatsächlichen Bytes lesen) — nie Umlaute/Wörter aus dem Kopf nachtippen; ein transliterierter Match (`geaenderte` vs `geänderte`) lässt den Assert stillschweigend fehlschlagen.
3. Anwenden: `hermes cron edit <job_id> --prompt "$(cat /tmp/newprompt.txt)"`.
4. Verifizieren: jobs.json neu laden und per Count/`in` prüfen, dass das Alte weg / das Neue drin ist — nicht nur dem „Updated job" des CLIs trauen.

## Change-Detection Baseline Markers (find -newer / Sync-Scans)

Jeder Cron, der „Dateien seit letztem Lauf neu/geändert" scannt (vault insights, Watchlist-Diff, Sync-Checks), steht und fällt mit seiner Baseline-Markierdatei. Zwei Regeln:
- **Marker persistieren, nie in /tmp.** `/tmp` ist ephemär; ein verlorener Marker wird beim Scan neu erzeugt und markiert alles als „alt“ → ein ganzes Intervall an Änderungen geht stillschweigend verloren. Persistenter Pfad wie `~/.hermes/cache/<marker>` + `mkdir -p` + Bootstrap.
- **Mit dem BESTEHENDEN Marker ZUERST finden, DANN touchen.** `touch`-dann-`find -newer` setzt die Baseline auf „jetzt“ und findet nichts. Richtige Reihenfolge: `find ... -newer <persistierter-marker>` zuerst, danach `touch`, um die Baseline für den nächsten Lauf vorzurollen. Beim Erstlauf mit `-mtime -N` statt `-newer` bootstrappen, damit nicht alles als neu eingepaukt wird.

See archived devops/ skills for detailed procedures.