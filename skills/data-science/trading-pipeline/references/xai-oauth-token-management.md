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

## Wie der Token gelesen wird (social_scanner.py, seit 04.08.2026)

Seit dem 04.08.2026 gibt es **keinen Session-Cache mehr** (`_XAI_TOKEN_CACHE` entfernt).
Jeder Call liest den Token frisch, damit ein via OAuth-Refresh aktualisierter
Token sofort erkannt wird.

```python
def _resolve_xai_token():
    # 1. resolve_xai_http_credentials() — Hermes' OAuth-Manager mit auto-refresh
    # 2. auth.json direkt (credential_pool.xai-oauth) — Fallback bei Namespace-Kollision
    # 3. XAI_API_KEY env var — letzter Fallback
```

### ⚠️ Namespace-Kollision (Trading-Profil)

`resolve_xai_http_credentials()` importiert `agent.credential_pool` → `hermes_cli.config`,
das wiederum `from utils import atomic_replace, fast_safe_load` versucht.

Im Trading-Profil shadowt das profil-eigene `utils.py` (`scripts/../utils.py`) das
Hermes-eigene `utils.py`. Weil der PYTHONPATH des Profils das Trading-Verzeichnis
als erstes setzt, importiert `hermes_cli.config` das **falsche** `utils` → `ImportError`.

**Symptom:** `resolve_xai_http_credentials()` returniert `{"provider": "xai", ...}`
(env-var-Fallback) statt `{"provider": "xai-oauth", ...}` (OAuth). Der Token ist
trotzdem vorhanden (wenn XAI_API_KEY gesetzt ist) oder fehlt.

**Lösung im Code:** 3-stufiger Fallback:
```python
def _resolve_xai_token() -> str:
    # Pfad 1: Hermes resolve_xai_http_credentials() mit auto-refresh
    try:
        from tools.xai_http import resolve_xai_http_credentials
        creds = resolve_xai_http_credentials()
        token = str(creds.get("api_key") or "").strip()
        if token:
            return token
    except Exception:
        pass

    # Pfad 2: auth.json direkt — ohne Cache, liest bei jedem Call frisch
    try:
        for candidate in ["/root/.hermes/auth.json", "~/.hermes/auth.json"]:
            if os.path.exists(candidate):
                with open(candidate) as f:
                    auth = json.load(f)
                # credential_pool.xai-oauth — aktuellster nach last_refresh
                entries = auth.get("credential_pool", {}).get("xai-oauth", [])
                valid = [e for e in entries if e.get("access_token")]
                valid.sort(key=lambda e: e.get("last_refresh", ""), reverse=True)
                if valid:
                    return valid[0]["access_token"]
                # providers.xai-oauth.tokens (legacy fallback)
                tokens = auth.get("providers", {}).get("xai-oauth", {}).get("tokens", {})
                if tokens.get("access_token"):
                    return tokens["access_token"]
    except Exception:
        pass

    return os.environ.get("XAI_API_KEY", "").strip()
```

**Prävention:** Kein Cache (`_XAI_TOKEN_CACHE`). Die Datei-Lese-Kosten sind
vernachlässigbar (max 3 Lesevorgänge pro Pipeline-Lauf).

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
| Response | `output`-Array (nicht `output_text`!), `citations` (Tweet-URLs) |

### Retry-Logik in `_call_x_search()` (seit 04.08.2026)

Angehoben auf das Niveau von `x_search_tool.py`:

| Kriterium | Verhalten |
|-----------|-----------|
| **429 Rate-Limit** | Exponential backoff: 1s → 2s → 4s |
| **5xx Server-Fehler** | Retry (max 2), mit `min(5.0, 1.5 * (attempt + 1))` delay |
| **Timeout (180s)** | Retry (max 2), gleicher delay |
| **Sonstige Exceptions** | Retry (max 2), gleicher delay |
| Abbruch nach 3 Versuchen | Log Warning, return None → Fallback twitterapi.io |

**Vorher:** 90s Timeout, undifferenzierte Retry-Logik (nur 429 + generischer `except`).

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