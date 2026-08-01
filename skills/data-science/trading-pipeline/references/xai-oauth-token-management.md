# xAI OAuth Token Management

## Token-Lebenszyklus

| Token | Lifetime | Refresh-Mechanismus |
|-------|----------|---------------------|
| Access Token | ~6 Stunden | Automatisch via Refresh Token |
| Refresh Token | ~30 Tage | Manueller OAuth-Flow (`hermes auth add xai-oauth`) |

## Wo der Token lebt

**Primär:** `~/.hermes/auth.json` → `credential_pool.xai-oauth` → **aktuellster Eintrag** (sortiert nach `last_refresh` desc)
**Fallback:** `~/.hermes/auth.json` → `providers.xai-oauth.tokens.access_token`
**Env-Fallback:** `XAI_API_KEY` (nur für API-Key-Nutzer, nicht OAuth)

⚠️ Es gibt meist MEHRERE xai-oauth-Einträge im credential_pool (jeder `hermes auth add` erzeugt einen neuen). Der älteste (index 0) ist oft abgelaufen. `_resolve_xai_token()` sortiert nach `last_refresh` und nimmt den frischesten.

Das Trading-Profil hat eine eigene Kopie in `/root/.hermes/profiles/hermes_trading/auth.json`.
Beide müssen denselben Token haben — der `social_scanner.py` liest aus der `~/.hermes/auth.json`.

## Wie der Token gelesen wird (social_scanner.py)

```python
def _resolve_xai_token():
    # 1. credential_pool.xai-oauth (primary)
    # 2. providers.xai-oauth.tokens (legacy)
    # 3. XAI_API_KEY env var
    # Gecached für die Session
```

## Symptome eines abgelaufenen Tokens

- HTTP 403: `"The OAuth2 access token could not be validated."`
- HTTP 401: `"unauthenticated:bad-credentials"`
- `_call_x_search()` gibt `None` zurück → Fallback auf twitterapi.io

## Token-Refresh

### Automatisch (empfohlen)

Hermes' `resolve_xai_http_credentials()` (in `tools.xai_http.py`) handled den
Refresh automatisch via OIDC Discovery + Refresh-Token-Grant:

1. Ruft `https://auth.x.ai/.well-known/openid-configuration` auf
2. Extrahiert `token_endpoint` (z.B. `https://auth.x.ai/oauth2/token`)
3. Sendet Refresh-Request mit `grant_type=refresh_token` + `client_id=b1a00492-073a-47ea-816f-4c329264a828`
4. Updated `auth.json` mit neuem Access + Refresh Token

### Manuell

```python
import httpx, json

AUTH_PATH = "/root/.hermes/auth.json"
CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"

# 1. Discovery
disc = httpx.get("https://auth.x.ai/.well-known/openid-configuration", timeout=15).json()
token_endpoint = disc["token_endpoint"]

# 2. Token laden
with open(AUTH_PATH) as f:
    auth = json.load(f)
entry = auth["credential_pool"]["xai-oauth"][0]
refresh_token = entry["refresh_token"]

# 3. Refresh
resp = httpx.post(
    token_endpoint,
    headers={"Content-Type": "application/x-www-form-urlencoded"},
    data={
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "refresh_token": refresh_token,
    },
    timeout=20,
)

# 4. Token speichern
data = resp.json()
entry["access_token"] = data["access_token"]
entry["last_refresh"] = datetime.now(timezone.utc).isoformat()
if data.get("refresh_token"):
    entry["refresh_token"] = data["refresh_token"]

with open(AUTH_PATH, "w") as f:
    json.dump(auth, f, indent=2)
```

## Kompletter Reset (wenn Refresh-Token auch abgelaufen)

Wenn `hermes auth add xai-oauth` >30 Tage zurückliegt, ist der Refresh-Token
invalid. Dann hilft nur:

```bash
hermes auth add xai-oauth
```

Dies startet einen Device-Code-Flow: im Terminal erscheint ein Code, den du
auf https://auth.x.ai/activate eingibst. Danach ist der OAuth-Flow frisch.

## xAI Responses API Referenz

| Property | Wert |
|----------|------|
| Endpoint | `POST https://api.x.ai/v1/responses` |
| Model | `grok-4.5` (grok-2-latest funktioniert NICHT im Responses API) |
| Auth | `Authorization: Bearer <token>` |
| Content-Type | `application/json` |
| Tool | `{"type": "x_search"}` mit optionalen Filtern |
| Response | `output_text` (Antwort), `citations` (Tweet-URLs) |

### Request-Format

```json
{
  "model": "grok-4.5",
  "input": [{"role": "user", "content": "Search X for tweets from @handle..."}],
  "tools": [{
    "type": "x_search",
    "allowed_x_handles": ["handle"],
    "from_date": "2026-07-31"
  }],
  "store": false
}
```

### Response-Format

⚠️ **`output_text` ist auf Top-Level `None`!** Die Antwort steckt im `output`-Array.

```json
{
  "id": "resp_...",
  "object": "response",
  "output": [
    {"type": "reasoning", ...},
    {"type": "custom_tool_call", "name": "x_search", "input": {...}},
    {"type": "reasoning", ...},
    {"type": "message",
     "content": [{"type": "output_text", "text": "{\"companies\": [...]}"}],
     "annotations": [{"type": "url_citation", "url": "https://x.com/..."}]}
  ],
  "output_text": null,
  "citations": ["https://x.com/handle/status/123"],
  "usage": {"input_tokens": 100, "output_tokens": 50}
}
```

**Extraktion-Pattern (Python):**
```python
parts = []
for item in data.get("output", []) or []:
    if item.get("type") != "message":
        continue
    for content in item.get("content", []) or []:
        if content.get("type") in ("output_text", "text"):
            text = (content.get("text") or "").strip()
            if text:
                parts.append(text)
answer = "\n\n".join(parts).strip()
```