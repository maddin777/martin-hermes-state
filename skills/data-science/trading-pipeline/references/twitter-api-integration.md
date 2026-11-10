# Twitter/X Integration (twitterapi.io)

twitterapi.io is the **only** X data source since 01.09.2026. The former Grok/xAI
`x_search` path was removed completely; there is no fallback and no generic keyword
search — only per-account scans.

## Setup

- Key `TWITTERAPI_IO_KEY` lives in the main `.env` `/root/.hermes/.env`. `env_loader.py`
  loads the profile `.env` first, then the main `.env` via `setdefault`, so the profile
  env does not need its own copy.
- Auth header: `X-API-Key: <TWITTERAPI_IO_KEY>`
- Endpoint: `GET https://api.twitterapi.io/twitter/tweet/advanced_search`

## Data flow (`social_scanner.py`)

| Step | What happens |
|------|--------------|
| 1 | `get_active_twitter_accounts(con)` — `source_type='twitter'`, active + probation |
| 2 | `fetch_twitter(con, accounts)` — query `from:@handle -is:retweet since:<24h>` |
| 3 | twitterapi.io returns tweets (`id`, `text`, `createdAt`) |
| 4 | `extract_companies(text, ...)` via OpenRouter (DeepSeek) extracts companies + sentiment |
| 5 | Rows written to `external_mentions` with `source_type='twitter'` |

## Registering an account

```sql
INSERT INTO source_registry (source_type, source_key, display_name, enabled, status)
VALUES ('twitter', 'TheChartReport', 'The Chart Report', 1, 'probation');
```

`source_key` is the handle **without** `@` (the code strips it anyway). `x_search` rows in
`source_registry` are obsolete and ignored.

## Failure modes

| Fehler | Ursache | Fix |
|--------|---------|-----|
| `TWITTERAPI_IO_KEY nicht gesetzt` | Key fehlt in der Env | Key in `/root/.hermes/.env` prüfen |
| HTTP 4xx | Key ungültig / Limit | twitterapi.io Dashboard prüfen |
| Keine Tweets in 24h | Account hat nichts gepostet | Normal, kein Fehler |
