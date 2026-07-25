---
name: last30days
description: "Recherchiert zu einem Thema die letzten 30 Tage aus Reddit, X, HN, GitHub und Web — synthetisiert einen Report mit Engagement-Scores und Quellen-Clustern. Nutzbar als manuelles Command oder via Cron."
---

# Last30days — Research über die letzten 30 Tage

Recherchiert zu einem Thema die letzten 30 Tage aus öffentlichen Quellen ohne API-Keys: Reddit, Hacker News, X, GitHub, und allgemeines Web. Synthetisiert einen Report mit Clustern, Engagement-Scores und Kernaussagen.

## Trigger

### Manuell
Sag "last30days [Thema]" oder führe den Skill aus. Ich interviewe nicht, ich suche sofort.

### Cron (wöchentlich)
Vordefinierte Themen aus `~/hermes/goals/` — MicroSaaS-Trends, Weekly Briefing.

## Workflow

### 1. Queries generieren
Aus dem Thema 3-5 Such-Query-Varianten ableiten:
- Original-Thema
- Kurzform / Akronym
- Problem-basierte Form ("Problem mit X")
- Vergleichsform ("X vs Y" wenn relevant)
- Deutsch + Englisch wo sinnvoll

### 2. Parallel suchen (alle Quellen gleichzeitig)
Pro Query:
- **Reddit**: `web_search(query="site:reddit.com <query>")`
- **HN**: `web_search(query="site:news.ycombinator.com <query>")`
- **Web**: `web_search(query="<query>")`
- **X**: `x_search(query="<query>")`
- **GitHub**: `web_search(query="site:github.com <query>")`

Limit: 5 Ergebnisse pro Query-Quelle-Kombination, max 30 Ergebnisse gesamt.

### 3. Clustern
Ergebnisse thematisch gruppieren:
- **Cluster 1**: Breaking News / Aktuelle Entwicklung
- **Cluster 2**: Community-Diskussion (Reddit/HN)
- **Cluster 3**: Social Media Reaktionen (X)
- **Cluster 4**: Technische Details / Code (GitHub/Web)
- **Cluster 5**: Vergleich / Kontroverse

Jeder Cluster bekommt:
- **Engagement-Score**: Summe aus Upvotes/Likes/Views (wo verfügbar)
- **Momentum-Label**: 🔥 exploding / 📈 rising / ➡️ stable / 📉 fading
- **Kernaussage**: 1-2 Sätze destilliert

### 4. Synthese
Schreibe einen Report im Format:

```
📡 Last30days: [Thema] (Stand: [Datum])

## Zusammenfassung
2-3 Sätze: Was ist in den letzten 30 Tagen passiert?

## 🔥 Top-Cluster
### [Cluster-Name] — [Engagement-Score]
[Kernaussage]
- [Quelle 1] — [Link] (Upvotes/Likes)
- [Quelle 2] — [Link] (Upvotes/Likes)

### [Cluster-Name] — [Engagement-Score]
...

## 📊 Gesamtbild
- Reddit: N Threads, Σ X upvotes
- X: N Posts, Σ Y likes
- HN: N Threads, Σ Z points
- GitHub: N Repos/Issues
- Web: N Artikel

## 💡 Fazit
Was bedeutet das für Martin? 1-3 Sätze mit Handlungsempfehlung.
```

### 5. Delivery
- Manuell: Direkt als Antwort in den Chat
- Cron: Als Datei unter `~/.hermes/cron/output/last30days/` + Telegram

## Cron-Konfiguration
Der wöchentliche Cron-Job lädt diesen Skill mit einem Thema aus `~/hermes/goals/scan_*.txt` und führt den Workflow aus. Ergebnisse landen als Telegram-Report.

## Known Limits
- Reddit/HN: Nur öffentliche Posts, keine Kommentar-Tiefensuche
- X: via xAI's x_search, abhängig von verfügbaren Credentials
- GitHub: Nur öffentliche Repos/Issues/PRs
- Kein YouTube/TikTok/Instagram ohne API-Keys