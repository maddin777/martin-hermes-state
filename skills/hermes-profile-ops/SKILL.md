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

## Cron-Jobs: Toolset und Prompt müssen zusammenpassen

Ein Cron-Job, dessen Prompt ein Werkzeug verbietet (z.B. "keine Terminal-Befehle"), darf dieses Toolset nicht mehr enthalten. Der Widerspruch lässt das Modell einen Befehl absetzen, der hängt, und erzeugt dann eine erfundene Begründung statt Output. Vor dem Anlegen oder Ändern eines Cron-Jobs: Prompt-Verbote gegen `enabled_toolsets` abgleichen. Daten, die ein Pre-Run-Script liefert, brauchen kein Terminal im Job.

## Cron-Health muss `last_status` anderer Jobs prüfen

Ein Health-Check, der nur ein Log auswertet, sieht Jobs nicht, die in ein anderes Log schreiben, und meldet dann "ok" bei einem Dauerfehler. Der Check liest `last_status` jedes kritischen Jobs direkt aus `jobs.json` (Job-ID fest) und meldet alles außer `ok` als Fehler. Ein Sync-Job, der seit mehreren Läufen `error` steht, muss im Health-Output auffallen.

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

## Open WebUI Deployment (LAN-Chat für ein isoliertes Profil)

Nutzer per Browser-Chat gegen ein spezialisiertes Profil sprechen lassen (getrennte
Verläufe, Bild-Upload). Architektur: Browser → Open WebUI (Docker :3000) → API-Server
des Profils (:8643, eigener Port+Key) → Profil.

- **Isolierter API-Server pro Profil**: im Profil-`.env` `API_SERVER_ENABLED=true`,
eigener `API_SERVER_PORT` (Default 8642, z.B. 8643) + eigener `API_SERVER_KEY` — sonst
kollidiert der Chat mit dem Haupt-API-Server. Start via `sudo /root/.local/bin/hermes -p
<profil> gateway install --system --run-as-user root` (voller Pfad nötig, `hermes` fehlt
im sudo-PATH). Verify: 401 ohne Key / 200 mit Key auf `/v1/chat/completions`.
- **Docker**: `ghcr.io/open-webui/open-webui:main`, `-p 3000:8080`,
`--add-host=host.docker.internal:host-gateway`, `--restart always`. Image ~3GB → im
Hintergrund starten. **`WEBUI_SECRET_KEY` ist Pflicht** (sonst inkonsistente Config-Pfade).
- **`OPENAI_API_MODELS` = PROFIL-ID, nicht Modellname** (z.B. `hermes_learn`); vorher mit
`curl /v1/models` prüfen. Falscher Wert → 0 Modelle.
- **User-Verwaltung**: der erste `POST /api/v1/auths/signup` wird Admin, danach ist
Self-Signup gesperrt (403). Kein öffentlicher Admin-User-Create-Endpoint (SCIM default
disabled) → weitere User über die Admin-UI anlegen.
- **Vision-Modell nötig** für Bild-Upload (`google/gemini-2.5-flash` Sweet-Spot;
`qwen/qwen3.7-flash` günstig). PITFALL: `:batch`-Suffix-Modelle sind nur Batch-API →
für Live-Chat unbrauchbar.
- Nur LAN, kein Internet-Port.

Details: `references/open-webui-deployment.md` (Deploy-Prozedur) und
`references/no-models-troubleshooting.md` („0 Modelle"-Diagnose: Key in DB persistiert,
WEBUI_SECRET_KEY, MODELS=Profil-ID).