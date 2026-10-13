# Open WebUI „keine Modelle auswählbar" — Troubleshooting & Start-Pitfalls (2026-09)

Live erarbeitet beim Open-WebUI-Deploy gegen ein isoliertes Hermes-Lern-Profil.
Drei unabhängige Fallstricke können dazu führen, dass Open WebUI keine Modelle zeigt
oder die Verbindung still mit 401/0 scheitert.

## Start-Befehl (mit allen drei Fixes)

```bash
WEBUI_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
docker run -d --name open-webui -p 3000:8080 \
  -e WEBUI_SECRET_KEY="$WEBUI_SECRET" \
  -e OPENAI_API_BASE_URLS=http://host.docker.internal:8643/v1 \
  -e OPENAI_API_KEYS=<echter-api_server_key> \
  -e OPENAI_API_MODELS=<profil-id> \
  -v open-webui:/app/backend/data \
  --add-host=host.docker.internal:host-gateway \
  --restart always \
  ghcr.io/open-webui/open-webui:main
```

## PITFALL 1 — `OPENAI_API_MODELS` = PROFIL-ID, nicht Modellname

Der Hermes-API-Server serviert `/v1/models` unter der **Profil-ID** (z.B. `hermes_learn`),
nicht unter dem echten Modell (`google/gemini-2.5-flash`).

- FALSCH: `OPENAI_API_MODELS=google/gemini-2.5-flash` → 0 Modelle (Filter matcht nichts).
- RICHTIG: `OPENAI_API_MODELS=hermes_learn` (die id, die der API-Server liefert).

Erst prüfen:
```bash
KEY=$(grep '^API_SERVER_KEY=' <profil>/.env | cut -d= -f2)
curl -s http://localhost:<port>/v1/models -H "Authorization: Bearer $KEY"
# → data[].id ist der Wert für OPENAI_API_MODELS
```

## PITFALL 2 — `WEBUI_SECRET_KEY` ist Pflicht

Fehlt er, bricht Open WebUI mehrere Auth-/Config-Pfade (harte Start-Warnung, Modell-Config
lädt inkonsistent). Immer mit frischem Zufallswert setzen.

## PITFALL 3 — OpenAI-Key wird in der DB persistiert und überschreibt die Env-Var

Beim **allerersten Container-Boot** schreibt Open WebUI den damals aktiven `openai.api_keys`
in seine eigene SQLite-DB (`/app/backend/data/webui.db`, Tabelle `config`). Danach hat die
**DB Vorrang** — spätere `-e OPENAI_API_KEYS=` werden **ignoriert**. Symptom: still 401, 0
Modelle, obwohl mit richtigem Key neu gestartet (Login klappt, Models leer).

### Fix — Key direkt in der DB setzen (Volume + User bleiben erhalten)

```bash
docker exec open-webui python3 -c "
from open_webui.internal.db import engine
from sqlalchemy import text
import json
conn=engine.connect()
conn.execute(text(\"UPDATE config SET value=:v WHERE key='openai.api_keys'\"),
             {'v': json.dumps(['<echter-key>'])})
conn.commit()
conn.close()"
```

### Diagnose-Pfad „0 Modelle" (in dieser Reihenfolge)

1. API-Server selbst liefert: `curl localhost:<port>/v1/models -H "Authorization: Bearer $KEY"`
   → muss `data[]` mit der Profil-id enthalten. Leer → API-Server-Problem, nicht Open WebUI.
2. Open WebUI OpenAI-Verbindung aktiv:
   ```bash
   docker exec open-webui python3 -c "
   from open_webui.internal.db import engine; from sqlalchemy import text
   conn=engine.connect()
   for row in conn.execute(text(\"SELECT key,value FROM config WHERE key IN ('openai.enable','openai.api_keys','openai.api_base_urls')\")):
       print(row.key,'=',str(row.value)[:60])
   conn.close()"
   ```
   `openai.enable` muss `true` sein, `api_base_urls` auf die Ziel-URL zeigen.
3. Logs: `docker logs open-webui | grep -i get_all_models`. `Connection error ... 11434`
   zu Ollama ist harmlos (kein Ollama installiert), NICHT die Ursache.
4. Gespeicherter Key ≠ echter API-Server-Key → PITFALL 3 anwenden.

Danach zeigt `curl .../api/v1/models` (mit Session-Token aus `/api/v1/auths/signin`) das
Profil-Modell + ein harmloses internes `arena-model` (LM-Arena-Platzhalter, ignorierbar).

## Kontext

- API-Server-Verifikation (401/200) und das Anlegen weiterer User (Admin-UI, Self-Signup
  gesperrt) gehören zur Deploy-Prozedur in `references/open-webui-deployment.md`.