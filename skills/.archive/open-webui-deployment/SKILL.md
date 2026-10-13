---
name: open-webui-deployment
description: Deploy Open WebUI chat against an isolated Hermes profile.
version: 1.0.0
author: Hermes Agent
license: MIT
category: devops
metadata:
  hermes:
    tags: [open-webui, docker, profile, api-server, web-chat]
    related_skills: [hermes-profile-management]
---

# Open WebUI Deployment (LAN-Chat für ein Hermes-Profil)

## When to Use
Sobald Nutzer (Familie, Schüler, Team) über ein **Browser-Chat-Interface** mit einem
**spezialisierten Hermes-Profil** sprechen sollen — mit getrennten Chatverläufen und
Bild-Upload. Architektur + User-Verwaltung, die 2026-09 für Martins Söhne (Lern-Profil)
erarbeitet und verifiziert wurde.

## Architektur

```
Browser (LAN) → Open WebUI :3000 → API-Server des Profils :8643 (isolierter Key)
                                        │
                                    hermes_learn-Profil (SOUL-Persona, eigenes Modell)
```

Open WebUI ist ein OpenAI-kompatibler Web-Chat (Docker). Es spricht den **API-Server
eines Hermes-Profils** an. Jedes Profil hat einen eigenen isolierten API-Server.

## Schritt 1 — Isolierten API-Server pro Profil einrichten (verifiziert)

Hermes erlaubt pro Profil einen eigenen `API_SERVER_PORT` + `API_SERVER_KEY`
(Default-Port ist 8642; Source-Doku: `hermes-agent/hermes_cli/profiles.py` —
"give each profile a distinct API_SERVER_PORT"). So kollidieren Profil-Chats nie
mit deinem Haupt-API-Server (Trading/News).

Im Profil-`.env` setzen (z.B. Port 8643, eigener Key):
```bash
API_SERVER_ENABLED=true
API_SERVER_HOST=0.0.0.0
API_SERVER_PORT=8643
API_SERVER_KEY=<eigener-wert>
```

Start: `sudo /root/.local/bin/hermes -p <profil> gateway install --system --run-as-user root`
(Lief „command not found" ohne vollen Pfad, weil `hermes` nicht im sudo-PATH liegt.)

Verify (401 ohne Key / 200 mit Key):
```bash
ss -tlnp | grep :8643
KEY=$(grep '^API_SERVER_KEY=' <profil>/.env | cut -d= -f2)
curl -s http://localhost:8643/v1/chat/completions \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"<modell>","messages":[{"role":"user","content":"Test"}]}'
```

## Schritt 2 — Open WebUI starten (Docker)

```bash
docker run -d --name open-webui -p 3000:8080 \
  -e OPENAI_API_BASE_URLS=http://host.docker.internal:8643/v1 \
  -e OPENAI_API_KEYS=sk-lern-lokal \
  -e OPENAI_API_MODELS=<modell> \
  -v open-webui:/app/backend/data \
  --add-host=host.docker.internal:host-gateway \
  --restart always \
  ghcr.io/open-webui/open-webui:main
```
- Bild ist ~3GB — **hintergrund ausführen** (`background=true`), sonst Timeout.
- Erster Boot: Health "starting" hochfahren lassen, bis `curl localhost:3000` HTTP 200 liefert.
- Version: `docker inspect --format '{{.State.Health.Status}}' open-webui`.

## Schritt 3 — User-Verwaltung (die Falle)

**Erster `POST /api/v1/auths/signup` wird zum Admin.** Danach ist Self-Signup **gesperrt**:
weitere User per `/signup` geben HTTP 403 ("contact your administrator"). Es gibt in
Open WebUI **keinen öffentlichen Admin-User-Create-REST-Endpoint** (users.py hat nur
update/status/settings; echte User-Erstellung läuft über SCIM, das **default disabled**
ist — Resource-Scan fand `ENABLE_SCIM`/`SCIM_TOKEN` Gate in routers/scim.py).

→ **Zusätzliche Nutzer robust über die Admin-UI** anlegen (Settings → Users → Create
User), nicht per API raten. Basis-Passwörter fürs Heimnetz ok, stärkere empfehlen.

## Modellwahl für Bild-Upload (Vision nötig)

Multi-User-Use-Case mit Foto-Upload braucht ein **vision-fähiges** Modell. Für
Schul-/Lern-/Alltagsnutzung ist `google/gemini-2.5-flash` (≈$0.30/M input, 1M Kontext,
starkes Reasoning) der Sweet-Spot. Günstigere Alternativen mit Vision:
`qwen/qwen3.7-flash` (≈$0.03/M) — gut aber schwächer im Reasoning; `deepseek-v4-flash`
hat Vision. PITFALL: `:batch`-Suffix-Modelle (z.B. `gemini-x:batch`) sind NUR
Batch-API und für Live-Chat unbrauchbar — non-batch-Variante nehmen.

## Sicherheits-Profil

- Nur LAN: bindet auf `0.0.0.0:3000`, kein Reverse-Proxy, kein Port ins Internet.
- Isolierter API-Server (eigener Port+Key) trennt Chat-Nutzer strikt von Haupt-Systemen.
- `--restart always` hält den Container über Reboots am Leben.