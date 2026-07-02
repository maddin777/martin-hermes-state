# Agent Reach → Hermes Integration

Wie Agent-Reach-Tools in Hermes web_search/web_extract und eigene Pipelines
eingebunden sind (Stand Juli 2026).

## DDGS (DuckDuckGo Search) — Hermes Search Backend

`search_backend: ddgs` in `config.yaml` — bereits gesetzt.

- Kein API-Key, kein Credit-Limit, keine Raten-Begrenzung
- Search-Only: web_extract braucht separaten Provider (Firecrawl oder Jina Reader)
- Installation: `pip install ddgs` (bereits geschehen)
- Hermes lazy-installiert ddgs beim ersten Aufruf falls fehlend

## Exa Search — via mcporter (Agent Reach)

Semantische Websuche. Verfügbar über mcporter, NICHT als native Hermes-Backend.

```bash
mcporter call 'exa.web_search_exa(query: "Suchbegriff", numResults: 5)'
```

- 1000 Suchanfragen/Monat im Free-Tier (kein API-Key nötig)
- Besser als DDGS für semantische/kontextuelle Suchen
- Schlechter als DDGS für aktuelle News/Trends

## Jina Reader — Extract-Fallback

```bash
curl -s "https://r.jina.ai/URL"
```

Liefert Webseiten-Inhalt als sauberes Markdown. Kein API-Key, kein Credit,
keine Raten-Begrenzung.

Verwendung als Fallback wenn Firecrawl-Credits leer:
- Statt `web_extract(urls=[...])`: `terminal("curl -s https://r.jina.ai/URL")`
- Statt `web_search`: DDGS (search_backend) + Jina Reader (extract)

## Anwendung in den Pipelines

### MicroSaaS Pain Scans (Slots A/B/C)

Die Goal-Dateien unter `~/hermes/goals/scan_{A,B,C}_*.txt` haben eine
`TOOLS & FALLBACKS`-Sektion die Exa und Jina als Ausweich-Tools dokumentiert:

```
TOOLS & FALLBACKS: Falls web_search/web_extract (Firecrawl) leer/fehlerhaft:
- Exa Search (semantisch, kein Credit): `mcporter call 'exa.web_search_exa(...)'`
- Jina Reader (kein Credit): `curl -s "https://r.jina.ai/URL"`
```

Wenn der Agent im Cron-Job Firecrawl-Probleme hat, sollte er zuerst DDGS
versuchen (ist bereits als search_backend gesetzt), dann Exa Search, dann
Jina Reader.

### DataViz Ideen Scan

`~/hermes/goals/dataviz_ideen.txt` hat Exa Search als Recherche-Quelle
ergänzt (neben Tagesschau, Handelsblatt, etc.).

## Channel-Status

```bash
agent-reach doctor    # Zeigt 7/15 aktive Kanäle
mcporter list         # Zeigt Exa (healthy)
```

Wöchentlicher Watchdog (So 10:00, no_agent) prüft ob sich der Status ändert.