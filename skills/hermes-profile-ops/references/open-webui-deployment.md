# Open WebUI Deployment gegen ein isoliertes Hermes-Profil (verifiziert 2026-09)

Browser-Chat für Familien-/Team-Nutzer gegen ein **spezialisiertes Profil** (SOUL-Persona,
eigenes Modell), mit getrennten Chatverläufen und Bild-Upload.

```
Browser (LAN) → Open WebUI :3000 → API-Server des Profils :8643 (isolierter Key)
                                        │
                                    <profil> (SOUL-Persona, eigenes Modell)
```

Open WebUI ist ein OpenAI-kompatibler Web-Chat (Docker); er spricht den **API-Server eines
Hermes-Profils** an. Jedes Profil hat seinen eigenen isolierten API-Server.

## Schritt 1 — Isolierten API-Server pro Profil

Hermes erlaubt pro Profil einen eigenen `API_SERVER_PORT` + `API_SERVER_KEY` (Default-Port
8642; Doku `hermes_cli/profiles.py`). So kollidiert der Profil-Chat nie mit dem Haupt-API-Server.

Im Profil-`.env`:
```bash
API_SERVER_ENABLED=true
API_SERVER_HOST=0.0.0.0
API_SERVER_PORT=8643
API_SERVER_KEY=<eigener-wert>
```
Start: `sudo /root/.local/bin/hermes -p <profil> gateway install --system --run-as-user root`
(ohne vollen Pfad „command not found", `hermes` liegt nicht im sudo-PATH).

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
  -e WEBUI_SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" \
  -e OPENAI_API_BASE_URLS=http://host.docker.internal:8643/v1 \
  -e OPENAI_API_KEYS=<echter-api_server_key> \
  -e OPENAI_API_MODELS=<profil-id, z.B. hermes_learn> \
  -v open-webui:/app/backend/data \
  --add-host=host.docker.internal:host-gateway \
  --restart always \
  ghcr.io/open-webui/open-webui:main
```
- Image ~3GB — **im Hintergrund ausführen**, sonst Timeout. Erster Boot bis `curl localhost:3000`
  HTTP 200 liefert.
- `OPENAI_API_MODELS` = die id, die `/v1/models` liefert (Profil-id), **NICHT** der Modellname.
- `WEBUI_SECRET_KEY` ist Pflicht (sonst inkonsistente Auth-/Config-Pfade).

## Schritt 3 — User-Verwaltung (die Falle)

Der erste `POST /api/v1/auths/signup` wird **Admin**; danach ist Self-Signup gesperrt (403,
"contact your administrator"). Es gibt **keinen öffentlichen Admin-User-Create-REST-Endpoint**
(SCIM default disabled). → Weitere Nutzer robust über die **Admin-UI** anlegen
(Settings → Users → Create User), nicht per API raten.

## Modellwahl für Bild-Upload (Vision nötig)

`google/gemini-2.5-flash` (≈$0.30/M input, 1M Kontext) = Sweet-Spot; günstiger:
`qwen/qwen3.7-flash` (≈$0.03/M, schwächeres Reasoning). PITFALL: `:batch`-Suffix-Modelle
sind NUR Batch-API → für Live-Chat unbrauchbar.

## Sicherheits-Profil

- Nur LAN: bindet `0.0.0.0:3000`, kein Reverse-Proxy, kein Port ins Internet.
- Isolierter API-Server (eigener Port+Key) trennt Chat-Nutzer strikt vom Haupt-System.
- `--restart always` hält den Container über Reboots am Leben.

## Troubleshooting

Bei „keine Modelle auswählbar" / stillem 401 siehe `references/no-models-troubleshooting.md`.