# Open WebUI „keine Modelle auswählbar" — Troubleshooting & Start-Pitfalls (2026-09)

Live erarbeitet beim Open-WebUI-Deploy gegen ein isoliertes Hermes-Lern-Profil.
Drei unabhängige Fallstricke können dazu führen, dass Open WebUI keine Modelle zeigt
oder die Verbindung still mit 401/0 scheitert.

## Start-Befehle (korrekt, mit allen drei Fixes eingebaut)

```bash
WEBUI_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
docker run -d --name open-webui -p 3000:8080 \
  -e WEBUI_SECRET_KEY="$WEBUI_SECRET" \
  -e OPENAI_API_BASE_URLS=http://host.docker.internal:8643/v1 \
  -e OPENAI_API_KEYS=<echter-api_server_key> \
  -e OPENAI_API_MODELS=<profilname> \
  -v open-webui:/app/backend/data \
  --add-host=host.docker.internal:host-gateway \
  --restart always \
  ghcr.io/open-webui/open-webui:main
```

## PITFALL 1 — `OPENAI_API_MODELS` = PROFILNAME, nicht Modellname

Der Hermes-API-Server serviert `/v1/models` unter der **Profil-ID** (z.B. `hermes_learn`),
nicht unter dem echten Modell (`google/gemini-2.5-flash`). Das darf man nicht verwechseln.

- FALSCH: `OPENAI_API_MODELS=google/gemini-2.5-flash` → Open WebUI zeigt 0 Modelle
  (Filter matcht keine der gelieferten IDs → nichts in der Auswahl).
- RICHTIG: `OPENAI_API_MODELS=hermes_learn` (die id, die der API-Server liefert).

Erst prüfen, welche id der API-Server wirklich sendet:
```bash
KEY=$(grep '^API_SERVER_KEY=' <profil>/.env | cut -d= -f2)
curl -s http://localhost:<port>/v1/models -H "Authorization: Bearer $KEY"
# → data[].id ist der Wert für OPENAI_API_MODELS
```

## PITFALL 2 — `WEBUI_SECRET_KEY` ist Pflicht

Open WebUI bricht mehrere Auth-/Config-Pfade, wenn `WEBUI_SECRET_KEY` fehlt —
die App druckt eine harte Warnung beim Start und die Modell-Config lädt inkonsistent.
Immer mit einem frischen Zufallswert setzen.

## PITFALL 3 — OpenAI-Key wird in der DB persistiert und überschreibt die Env-Var

Den Fiesesten: Open WebUI schreibt beim **allerersten Container-Boot** den damals
aktiven `openai.api_keys` in seine eigene SQLite-DB (`/app/backend/data/webui.db`,
Tabelle `config`). Danach hat die **DB Vorrang** — spätere `-e OPENAI_API_KEYS=`
Änderungen werden **ignoriert**. Symptom: Verbindung still 401, 0 Modelle, obwohl der
Container mit dem richtigen Key neu gestartet wurde (Verhalten wirkt „uneindeutig",
weil Login funktioniert aber Models leer sind).

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
print('DB-Key:', json.loads(conn.execute(text(
    \"SELECT value FROM config WHERE key='openai.api_keys'\")).fetchone()[0])[0][:8], '...')
conn.close()"
```

### Diagnose-Pfad „0 Modelle" (in dieser Reihenfolge)

1. Prüfen, dass der API-Server selbst liefert:
   `curl localhost:<port>/v1/models -H "Authorization: Bearer $KEY"` → muss `data[]`
   mit der Profil-id enthalten. Wenn leer → API-Server-Problem, nicht Open WebUI.
2. Prüfen, dass Open WebUI die OpenAI-Verbindung aktiv hat:
   ```bash
   docker exec open-webui python3 -c "
   from open_webui.internal.db import engine; from sqlalchemy import text
   conn=engine.connect()
   for row in conn.execute(text(\"SELECT key,value FROM config WHERE key IN ('openai.enable','openai.api_keys','openai.api_base_urls')\")):
       print(row.key,'=',str(row.value)[:60])
   conn.close()"
   ```
   `openai.enable` muss `true` sein, `api_base_urls` auf die Ziel-URL zeigen.
3. Container-Logs: `docker logs open-webui | grep -i get_all_models` — zeigt, ob der
   OpenAI-Poll überhaupt läuft. Ein `Connection error ... 11434` zu Ollama ist dabei
   harmlos/unschädlich (kein Ollama installiert), NICHT die Ursache.
4. Ist der gespeicherte Key ≠ dem echten API-Server-Key → PITFALL 3 anwenden.

Danach kann ein `curl .../api/v1/models` (mit einem frischen Session-Token aus
`/api/v1/auths/signin`) die zwei Modelle zeigen: das echte Profil-Modell + ein
harmloses internes `arena-model` (LM-Arena-Platzhalter, ignorierbar).

## Weiterführende Projekt-Pitfalls (Kontext)

- API-Server-Verifikation „401 ohne Key / 200 mit Key" gehört zum isolierten
  Profil-API-Server-Setup (siehe SKILL.md Schritt 1).
- Zusätzliche Nutzer (Magnus/Rasmus) werden über die Admin-UI angelegt, nicht per
  REST (Self-Signup ist nach dem ersten Admin gesperrt; kein öffentlicher
  Admin-User-Create-Endpoint; SCIM default disabled) — siehe SKILL.md Schritt 3.