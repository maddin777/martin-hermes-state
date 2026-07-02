---
name: agent-reach
description: "Agent Reach — Multi-Plattform-Zugang (Exa Search, Jina Reader, RSS, YouTube, GitHub, Twitter/Reddit mit Cookies). Tools für Recherche in MicroSaaS-Scans, DataViz-Ideen-Generierung und News-Briefings."
triggers:
  - recherche: Exa/Websuche/Jina/semantische Suche/Internet-Recherche
  - scan: MicroSaaS/DataViz/Pain-Scan/Wettbewerbscheck
  - channel_check: agent-reach doctor/health/Status
---

# Agent Reach — Internet-Recherche-Tools (DE)

Installiert unter `~/.agent-reach-venv/`. 7 Kanäle aktiv, Tools via `~/.local/bin/` verfügbar.

## Verfügbare Kanäle (Deutschland/EU-Fokus)

| Kanal | Status | Befehl |
|-------|--------|--------|
| **Exa Search** (semantisch) | ✅ aktiv | `mcporter call 'exa.web_search_exa(query: "...", numResults: 5)'` |
| **Jina Reader** (Webseiten) | ✅ aktiv | `curl -s "https://r.jina.ai/URL"` |
| **RSS/Atom Feeds** | ✅ aktiv | Python feedparser |
| **YouTube** | ✅ aktiv | `yt-dlp --dump-json URL` |
| **GitHub** | ✅ aktiv | `gh` CLI |
| **V2EX** | ✅ aktiv | `curl -s "https://www.v2ex.com/api/topics/hot.json"` |
| **Twitter/X** | ⏸ installiert (Cookies fehlen) | `twitter search "query" -n 10` |
| **Reddit** | ⏸ installiert (Login fehlt) | `rdt search "query" --limit 10` |

## Verwendung in den Pipelines

### Exa Search (Alternative zu Firecrawl/web_search)
```bash
mcporter call 'exa.web_search_exa(query: "Reddit pain points accounting software small business", numResults: 10)'
mcporter call 'exa.web_search_exa(query: "G2 QuickBooks alternative review pain", numResults: 5)'
```
Vorteil: keine Firecrawl-Credits nötig, semantische Suche, liefert strukturierte Ergebnisse.

### Jina Reader (Alternative zu web_extract)
```bash
curl -s "https://r.jina.ai/https://example.com/article"
```
Liefert sauberes Markdown — kein Firecrawl, kein API-Key.

### RSS per feedparser (Alternative zu curl | python3)
```python
python3 -c "
import feedparser, json
f = feedparser.parse('https://news.google.com/rss?hl=de&gl=DE&ceid=DE:de')
for e in f.entries[:5]:
    print(f'{e.title} ({e.source.title if hasattr(e,\"source\") else \"?\"})')
"
```

## Status-Prüfung
## Status-Prüfung
```bash
agent-reach doctor
```

## Hermes-Integration
Siehe `references/hermes-integration.md` — DDGS-Backend, Exa-Suche,
Jina-Reader-Extract, und Anwendung in den Scan-Pipelines.

## Wartung
```bash
# Nach Updates checken (alle ~2 Wochen)
agent-reach check-update

# Wöchentlicher Health-Check (Cron-ID f7b44ebca4ee, So 10:00)
# Läuft als no_agent-Script, meldet nur bei Änderungen
```