---
name: vault-insights-daily
description: "Vault-Insight-System: Nach Sync (02:00) um 02:45: (A) Wiki einsortieren. (B) Weiterdenken OUT-OF-THE-BOX — Side Hustles, Steuern, Ausland, Skills, Unternehmensaufbau. (C) Proaktive Vorschlaege (max 3, mit 'Soll ich umsetzen?'). Cron ID 53f222b00811. Ausgeschlossen: Projekte/Buecher. Hinweis: SuperGrok als Provider im news-agent integriert (xAI). A2-X-Bookmarks-Pfad weiter pausiert bis Martin Zugang fuer Bookmarks klaert."
category: devops
---

# Vault-Insights-Daily

Taegliche Pipeline nach GDrive-Sync.

**User-Preference (wichtig):** Beides, nicht entweder/oder.
Wenn ein Artikel neue Erkenntnisse bringt (weiterdenken) UND neue Wiki-Eintraege noetig macht (einsortieren) — mach BEIDES.
Nicht das eine gegen das andere abwaegen. Martin erwartet sowohl Einsortierung als auch Weiterdenken parallel.

## Ablauf

```
02:00  obsidian-vault-bisync-nightly (GDrive→local)
02:45  vault-insights-daily (Cron ID 53f222b00811)
```

## Drei Aufgaben parallel

### Vorgelagerte Prüfung — Sync-Health

**Wichtig: Der echte Sync läuft via Cron-Job, nicht via sync.sh!**
Der Bisync-Cron (f5eb3bfaf65e) nutzt direkt `rclone bisync gdrive: ~/obsidian-vault --drive-root-folder-id 1aY8QQ6Sw8ljGhvEV0rayQpxRgCQw9Vj4`.
Nicht fälschlich melden dass der Sync defekt sei, nur weil sync.sh einen anderen Pfad hat.

Prüfe den tatsächlichen Sync-Status via:
1. **Cron-Output checken**: `ls -t /root/.hermes/cron/output/f5eb3bfaf65e/ | head -3` — recent log existiert? Letzter Run ok?
2. **Cron-Job Status**: `cronjob action=list` und prüfe `last_status` von Job f5eb3bfaf65e
3. **sync.sh VAULT_PATH** (optional): `grep 'VAULT_PATH=' /root/obsidian-vault/sync.sh` — Warnung wenn falsch, aber KEIN "Sync defekt"-Alarm daraus ableiten

Der Cron läuft auch bei korrektem sync.sh separat und unabhängig.

**A — Einsortieren (Wiki pflegen)**
Scanne Trading-relevante neue Dateien: boerse/, Trading/, Geldverdienen/Trading-Teil, hermes/Trading-Teil.
- Neue Erkenntnisse in bestehende Wiki-Seiten einarbeiten (concepts/, entities/, sources/)
- Bei neuen Konzepten: neue Wiki-Seite anlegen
- Wikilinks pflegen

**A2 — X Bookmarks (PAUSIERT)**
SuperGrok ist als Provider im news-agent integriert, aber X-Bookmarks-Zugang
via SuperGrok ist noch nicht geklärt. Solange pausiert.
Überspringen bis auf weiteres.

**B — Intention weiterdenken (OUT OF THE BOX)**
Scanne ALLE neuen Dateien in: Geldverdienen/, boerse/, hermes/, Trading/, Clippings/, raw/
- Kernidee des Artikels (1 Satz)
- Intention des Autors ("Autor will sagen: mach X, weil Y")
- **OUT OF THE BOX denken** — nicht nur auf Trading/KDP/Amazon Merch beschränken!
  Pflicht-Scan auf folgende Opportunity-Bereiche:
  - **Nebenverdienst/Side Hustles:** SaaS, Affiliate, Digital Products, Automatisierung die Martin verkaufen kann, Beratung, KI-gestützte Dienstleistungen
  - **Steuern optimieren:** Auslandsstrukturen, Freibeträge, Holding, Wegzug, länderübergreifende Modelle
  - **Ausland/ortsunabhängig:** Länder mit niedrigen Lebenshaltungskosten, Steuervorteile, Visa-Programme (Digital Nomad, Passive Income), Immobilien im Ausland
  - **Skill-Weiterentwicklung:** Was könnte Martin als nächstes lernen was Cash bringt? (Celonis, BW, KI-Agenten-Beratung, SAP SAC Nischen)
  - **Unternehmensaufbau:** Strukturen die passive Einkommen ermöglichen, Automatisierung die skaliert
- Uebersetzung auf Martins Infrastruktur:
  - Hat er schon ein Profil/Skill/Cron dafuer?
  - Was fehlt? (Neuer Cron? Skill? Config-Aenderung? Neue Plattform?)
  - Aufwandschaetzung in Minuten/Stunden
  - Endet mit: "Soll ich das jetzt umsetzen?"

**C — Proaktive Vorschlaege (max 3)**
Jeder Vorschlag muss enden mit:
- Konkretem naechsten Schritt
- Aufwandschaetzung
- "Soll ich das jetzt umsetzen?"
Nicht theoretisch bleiben.
**Auch hier: OUT OF THE BOX denken** — Vorschlaege duerfen ausserhalb Trading/KDP/Amazon Merch liegen.
Nutze die 5 Opportunity-Bereiche aus Aufgabe B als Inspirationsquelle.

## Cron-Job

```
hermes cron run 53f222b00811   # Manuell triggern
```

- Schedule: `45 2 * * *` (02:45 taeglich, nach GDrive-Sync um 02:00)
- Deliver: `telegram` (an Ch_hermster)
- Toolsets: file, terminal, web
- Keine Skills noetig (Agent arbeitet eigenstaendig)
- Ausgeschlossene Ordner: Projekte/Buecher/, .obsidian/

## Verwandte Crons (Vault Maintenance Pipeline)

| Cron | Schedule | Zweck |
|------|----------|-------|
| `obsidian-vault-bisync-nightly` (f5eb3bfaf65e) | 02:00 täglich | GDrive-Bisync (lokal↔Cloud) |
| `vault-insights-daily` (53f222b00811) | 02:45 täglich | Wiki pflegen + Weiterdenken (DIESER) |
| `vault-self-write-health` (326343c87149) | Sa 03:00 | Health Check, Backward Integration, Gap Detection, Synthesis |
| `weekly-review` (beb26022a5d9) | So 19:00 | Wochenrückblick: Trading, Sync, Projekt-Status, Empfehlungen |

In Vorschlag C (`max 3`) können diese Crons als Ausgangspunkt für Verbesserungen dienen (z.B. "Der Health Check hat X Broken Links gefunden").

## News-Briefing-Format

Falls ein Vorschlag den daily-news-briefing Cron (hermes-news Profil, 06:00) betrifft:
Das kanonische Format ist in `references/daily-news-briefing-format.md` dokumentiert.
Goal-Struktur (/goal + /subgoal) wurde getestet und vom User verworfen — nicht vorschlagen.

## Beispiele: Weiterdenken in der Praxis

### Beispiel 1 — Trading-Fokus (traditionell)
Siehe `references/llm-stock-selection-research.md`:
1. **Artikel gefunden**: AI Finance Labs verwaltet $150M+ mit Grok/ChatGPT/DeepSeek/Claude
2. **Intention verstanden**: Der Autor zeigt wie LLMs als Portfolio-Manager eingesetzt werden
3. **Weitergedacht**: Martins Trading-Profil hat signal_extractor — ein Multi-LLM-Ensemble-Ansatz wuerde denselben Prompt an mehrere Modelle senden und die Schnittmenge als Signal nutzen
4. **Abgelegt als Wiki-Seite**: wiki/concepts/LLM Stock Selection.md

### Beispiel 2 — Out-of-the-Box (neuer Ansatz, 18.05.2026)
Aus Gespräch über SuperGrok und x_search/X-Bookmarks ergab sich:
1. **Anlass**: Martin fragt, ob SuperGrok als Provider taugt
2. **Weitergedacht**: Nicht nur "ja/nein" — sondern Schnittstelle zu x_search/X Bookmarks entdeckt
3. **Opportunity-Bereich getroffen**: Side Hustles + Skill-Aufbau — SuperGrok erschliesst X-Suche OHNE $100/Monat X-API-Key
4. **Stand 21.05.**: SuperGrok/xAI ist als Provider im news-agent integriert. X-Bookmarks-Pfad weiter offen (noch nicht getestet).
5. **Abgelegt als**: wiki/entities/SuperGrok.md

## Wiki Struktur (Stand 23.05.2026, 37 concepts + 17 entities + ~125 sources)

```
/root/obsidian-vault/
├── wiki/
│   ├── concepts/         # Abstrakte Konzepte (Market Regime, Kelly, Out-of-the-Box Opportunity Scan, …)
│   ├── entities/         # Konkrete Entitaeten (Polymarket, SuperGrok, Quant Roadmap, …)
│   ├── sources/          # Quellen mit Verweisen auf Originale
│   └── trading-index.md  # MOC
├── 00-CAPTURE/           # Schnelle Notizen, kein Ordner-Denken (Anti-Breakdown)
├── boerse/               # Rohdaten (boerse-Clippings)
├── Trading/              # Watchlist
├── Geldverdienen/        # Trading-Anteil: Polymarket, Quant, BTC, OpenClaw
├── hermes/               # Trading-Anteil: Polymarket, KIMI Prompts, Analyst
├── Clippings/            # Web-Clippings
└── raw/                  # Rohdaten (wird automatisch befuellt)
```

## Cross-Vault-Verknuepfungen

~160 Dateien im gesamten Vault (ausser Projekte/Buecher) mit ## Verknuepfungen versehen.
Prinzip: **Inhalt > Ordner.** Cross-Vault-Links gesetzt zwischen:
- hermes/ ↔ Trading/, boerse/, Geldverdienen/ (Trading-Cluster)
- hermes/ ↔ Hermes Idee (Agent Identity)
- hermes/RAG ↔ Lernen/Polnisch, Mindset/Transurfing (Lernparadigmen)
- Obsidian-Vault-Artikel ↔ Ideen
- wiki/concepts/Out-of-the-Box Opportunity Scan ↔ wiki/entities/SuperGrok (Bookmarks-Pfad pausiert, Provider aktiv)
- 00-CAPTURE/ ↔ alle Themenordner (Capture-first, einsortieren später)

## Trigger beim erstmaligen Setup

Wenn du diesen Skill laedst und der Cron noch nicht existiert:
1. Pruefe ob Cron `53f222b00811` existiert (`hermes cron list`)
2. Wenn nicht: lege ihn neu an mit Schedule `45 2 * * *`, deliver telegram, toolsets file+terminal+web
3. Prompt: siehe Referenz `references/cron-prompt-2026-05-11.md`
4. Wiki-Struktur anlegen falls nicht vorhanden (concepts/, entities/, sources/, trading-index.md)