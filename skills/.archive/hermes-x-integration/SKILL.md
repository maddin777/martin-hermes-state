---
name: hermes-x-integration
description: "X (Twitter) integration in Hermes via twitterapi.io — API-Key setup, account scans, and verification. Standard seit 01.09.2026 (Grok/xAI entfernt)."
version: 2.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [x, twitter, twitterapi.io, social-media]
    related_skills: [xurl, trading-pipeline]
---

# Hermes X Integration — twitterapi.io (Standard seit 01.09.2026)

X (Twitter)-Daten werden über **twitterapi.io** bezogen. Die frühere native
`x_search`-Integration (xAI/Grok, SuperGrok-Abo) wurde **komplett entfernt**
(01.09.2026, Dienst wird nicht mehr genutzt). Es gibt keinen OAuth, kein
Grok, keine SuperGrok-Abhängigkeit mehr.

## Prerequisites

- **twitterapi.io API-Key** (bezahltes Abo, `TWITTERAPI_IO_KEY`)
- Der Key liegt in `/root/.hermes/.env` (wird von Trade-Skripten via `env_loader`
  oder direkt geladen)

## Setup

### 1. API-Key setzen

`TWITTERAPI_IO_KEY` in `/root/.hermes/.env`:

```
TWITTERAPI_IO_KEY=xxx
```

Kein OAuth-Flow, kein Browser, kein `auth.json`-Token nötig — nur ein API-Key.

### 2. Nutzung (Enterprise-Search)

twitterapi.io `advanced_search` liefert Echtzeit-Tweets:

```python
import os, requests
key = os.environ["TWITTERAPI_IO_KEY"]
r = requests.get(
    "https://api.twitterapi.io/twitter/tweet/advanced_search",
    headers={"X-API-Key": key},
    params={"query": "AAPL since:2026-08-30_00:00:00_UTC", "queryType": "Latest"},
    timeout=20,
)
tweets = r.json().get("tweets", [])
```

**Query-Syntax (wie Twitter-Advanced-Search):**
- `from:handle -is:retweet since:<ts>` — Account-Scans (Trading-Watch)
- `<Ticker/Keyword> since:<ts>` — generische Keyword-Suche (Conviction-Boost)

## Wo twitterapi.io im Trading-System läuft

| Datei | Zweck |
|-------|-------|
| `scripts/social_scanner.py` | `fetch_twitter()` — Account-Scans (daily 02:00 Cron) |
| `scripts/xsearch_helper.py` | `x_search()` → twitterapi.io — `conviction_boost`, `breaking_news_check`, `contradiction_check` |

Beide richten sich an `TWITTERAPI_IO_KEY` und geben dieselben Daten-/JSON-Formate
zurück wie zuvor — der Grok-Umbau war nahtlos.

## Fehlerbehebung

| Symptom | Ursache | Fix |
|---------|---------|-----|
| `TWITTERAPI_IO_KEY nicht gesetzt` | Key fehlt in Env | In `/root/.hermes/.env` setzen |
| HTTP 401/403 | Key ungültig/abgelaufen | twitterapi.io Dashboard prüfen |
| HTTP 429 | Rate-Limit erreicht | Warten oder höheres Abo |
| Leere `tweets` | Kein Treffer im Zeitfenster/Account stumm | Normal, kein Fehler |
| `HTTP 400` | Query-Syntax falsch | `since:`-Format/Logik prüfen |

## Referenz-Files

- Setup-Details im `trading-pipeline` Skill unter "Twitter/X Integration — twitterapi.io".
- Das frühere `xai-oauth-token-management.md` (Grok-OAuth) wurde **entfernt** — nicht mehr gültig.
