# Vault-Wide Content Linking — 2026-05-11

## Scope
359 Dateien verarbeitet, 143 mit neuen `## Verknüpfungen`-Sektionen.
Ausgeschlossen: Projekte/Bücher (283 Dateien).

## Batch-Strategie

Statt 359 Dateien einzeln zu lesen, wurde in thematischen Batches gearbeitet:

| Batch | Ordner | Ansatz | Dateien |
|---|---|---|---|
| 1 | Trading, boerse, Geldverdienen | Cluster-intern + Cross-Vault | 28 |
| 2 | raw, Mindset, Lernen, Reisen, Rezepte, Sport, Personen, Stuff, Inbox, Root, Clippings | Ordner-intern + Cluster-inhaltlich | 74 |
| 3 | Projekte (ohne Bücher) | Ordner-intern | 14 |
| 4 | Cross-Vault (hermes ↔ Rest) | Inhaltliche Brücken | 12 |

## Tooling

- **`execute_code`** wurde für Massen-Lese- und Schreiboperationen genutzt (21 Dateien in einem Durchgang)
- **`delegate_task`** für die vollständige Inhaltsanalyse aller 27 neuen hermes-Dateien (Themen-Cluster + Widersprüche)
- **Keyword-Overlap via Python** war ein Fehlschlag (fand nur Frontmatter-Ähnlichkeiten) — durch thematische Cluster-Analyse ersetzt

## Cross-Vault Linking (wichtigste Verbindungen)

| Von | Nach | Begründung |
|---|---|---|
| hermes/28 tools Polymarket | Trading/Watchlist, boerse/Information Theory, Geldverd./Quant Roadmap | Trading-Infrastruktur |
| hermes/trading strategies | Trading/Watchlist, Geldverd./Quant Roadmap | Strategie-Execution |
| hermes/RAG is a Lie | Lernen/Polnisch/01, Mindset/Transurfing/01 | Lernparadigmen |
| hermes/SOUL.md | Hermes Idee | Agent Constitution ↔ Praxis |
| hermes/Obsidian-Artikel | Ideen | Wissensmanagement |
| Trading/Watchlist | hermes/28 tools, hermes/trading strategies, hermes/Analyst | Trading-Ökosystem |
| Geldverd./OnlyFans | hermes/How to Build Autonomous Agent | AI-Business Pattern |

## Gelerntes

1. **Keyword-Overlap via Python funktioniert nicht** für inhaltliche Verbindungen — zu viele Frontmatter-False-Positives. Themen-Cluster per LLM-Analyse ist zuverlässiger.
2. **execute_code mit read_file loop + write_file** ist der effizienteste Weg für Massen-Patches (21 Dateien in 20s).
3. **Cross-Vault-Links brauchen relativen Pfad** (`[[../Geldverdienen/Note]]`) — absolute Pfade funktionieren nicht in Obsidian.
4. **Bestehende `## Verknüpfungen` erkennen** und überspringen (keine Duplikate).
5. Bei 600+ Dateien: zuerst Scope checken (`find | wc -l`), dann thematische Batches priorisieren, nicht alphabetisch vorgehen.