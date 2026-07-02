---
name: micro-saas-opportunity-scan
description: "Systematischer Pain-Scan für Micro-SaaS-Ideen mit multi-slot Quellenrotation, Wettbewerbsgate (GATE), Cluster-Store-Dedup und Action-Threshold. Findet echte, wiederkehrende Probleme die sich als Solo-SaaS (<3 Monate Build) lösen lassen — ohne Lösungen zu bauen."
category: productivity
---

# Micro-SaaS Opportunity Scan

Systematische Quellenrotation über mehrere Slots hinweg, die unabhängig voneinander
scannen aber in denselben 30-Tage Cluster-Store schreiben. Kombiniert qualitativen
Pain-Scan mit einem **Wettbewerbsgate** das verhindert, dass "leicht baubar" als
Pluspunkt zählt wenn der Markt besetzt ist.

---

## 1. Rotationssystem

Vier Slots wälzen unterschiedliche Quellen ab — die Rotation passiert über
welcher Prompt wann feuert, nicht über Code.

| Slot | Quellen | Frequenz | Begründung |
|------|---------|----------|------------|
| **A** | Reddit (Nischen-Subs) + Hacker News | Mo/Mi/Fr | billig, hohes Signal, aktualitätsgetrieben |
| **B** | G2/Capterra/Trustpilot (1-3⭐) | Di/Do | mehr Rauschen + Parsing → gezielt |
| **C** | IndieHackers + App/Play-Store-Reviews | Sa | langsam drehende Quellen |
| **Digest** | liest nur Cluster-Store | So | Wochenübersicht + Action-Schwelle |

Jeder Slot hat seine eigene Goal-Datei unter `~/hermes/goals/scan_X_*.txt`.
Die Cron-Jobs referenzieren die Dateien via `hermes goal --file`, nicht inline
— Prompt-Änderungen erfordern kein Cron-Job-Touching.

### Crontab (beispielhaft)

```cron
# Slot A — Reddit + HN
0 14 * * 1,3,5  hermes goal --file ~/hermes/goals/scan_A_reddit_hn.txt
# Slot B — Review-Sites
0 14 * * 2,4    hermes goal --file ~/hermes/goals/scan_B_reviews.txt
# Slot C — IndieHackers + App-Stores
0 14 * * 6      hermes goal --file ~/hermes/goals/scan_C_deep.txt
# Wochen-Digest
0 18 * * 0      hermes goal --file ~/hermes/goals/scan_digest.txt
```

### Dateien

- `~/hermes/goals/scan_A_reddit_hn.txt` — Reddit-Subs + HN (Scoring, Gate, Output)
- `~/hermes/goals/scan_B_reviews.txt` — Review-Sites (gleiche Struktur)
- `~/hermes/goals/scan_C_deep.txt` — IndieHackers + App-Stores
- `~/hermes/goals/scan_digest.txt` — Wochen-Digest (kein Scan, nur Analyse)

Der Cluster-Store liegt unter `~/hermes/reports/`. Reports landen als
`scan_{A,B,C}_YYYY-MM-DD.md` bzw. `digest_YYYY-WW.md`.

---

## 2. Scoring

Je 1-5: **SCHMERZ × MACHBARKEIT**

- **SCHMERZ** — wie laut/oft der Pain genannt wird, wie viele unabhängige Stimmen,
  wie konkret die Klage
- **MACHBARKEIT** — Solo baubar (<3 Monate)? Freie Datenquellen? Kein
  Enterprise-Albtraum? **Und: ist die Wettbewerbs-Lane offen?** (siehe 3.)

Alles < 3 in einer der beiden Achsen wird verworfen.

---

## 3. Wettbewerbsgate (GATE) — zentraler Filter

Das Gate **deckelt** die Machbarkeit, wenn eingegrabene Incumbents existieren —
statt einfach nur abzuwerten. "Leicht baubar" wird vom Plus- zum Minuspunkt,
sobald ein Incumbent den Kern-Use-Case besetzt.

### Pflicht-Recherche vor Score

Für jeden Kandidaten aktiv suchen:
- `Tool-Name + "alternative" / "vs" / "pricing"`
- Chrome Web Store, passende G2/Capterra-Kategorie
- Fertige n8n/Zapier-Templates
- Product Hunt, AlternativeTo

Festhalten:
- Etablierter Anbieter vorhanden?
- Wie eingegraben (Jahre am Markt, Nutzerbasis, Funding, Daten-Moat)?
- Reife Gratis-/DIY-Lösungen?

### Gate-Regeln (hart)

| Situation | Wirkung |
|-----------|---------|
| Incumbent (>2 Jahre ODER Nutzerbasis ODER Daten-Moat) besetzt Kern-Use-Case | **MACHBARKEIT MAX. 2** (= verworfen) — AUSSER es gibt einen klar benannten Keil |
| Reife kostenlose/DIY-Lösung deckt Bedarf | **SCHMERZ -1** (zahlbereit bleibt nur wer DIY nicht kann/will) |
| Kein Wettbewerb gefunden | Machbarkeit unverändert, aber markieren: "Wettbewerb: keiner gefunden — gegenprüfen" |
| Niedrige Eintrittsbarriere ohne Moat bei besetztem Markt | Zählt GEGEN die Idee, nicht dafür |

### Keil-Definition

Ein Keil ist ein klar verteidigbarer Winkel:
- Enge Nische die Incumbents ignorieren
- Struktureller Kostenvorteil
- Anderer Vertriebsweg

Ohne benannten Keil greift das Gate **hart**. Der Keil muss EXPLIZIT im Output
genannt werden.

### Gate-Kalibrierung

- Kommt nichts mehr durch → Keil-Definition zu streng. Machbarkeit-Deckel auf 3 lockern
- Kommt offensichtlicher Schrott durch → Wettbewerbssuche um konkrete Quellen erweitern

---

## 4. Validierung: Pain-Definition

Ein Pain zählt nur wenn er ALLE Kriterien erfüllt:

- **Wiederkehrend** — kein Einzelfall, mehrere unabhängige Quellen nennen ihn
- **Kostet Zeit/Geld/Nerven** — spürbarer Verlust
- **Schlechte Workarounds** — Excel-Frickelei, Tool-Ketten, teures Overkill-Tool
- **Erreichbare Nische** — nicht "bessere CRM-Software" sondern "CRM für
  Kleinsthandwerker ohne Monatsabo"
- **Zahlungsbereitschaft-Signal** — idealerweise: Leute zahlen bereits für
  schlechtere Lösungen

---

## 5. Cluster-Store & Dedup

Alle Slots schreiben in DENSELBEN 30-Tage-Store unter `~/hermes/reports/`.

- Dedup-Schwelle: >70% Ähnlichkeit → bestehenden Cluster-Counter erhöhen
- Kein neuer Eintrag wenn der Pain bereits im Cluster existiert
- Startwert 70%, nach ein paar Wochen prüfen:
  - Zu viele "NEU"-Einträge für denselben Pain → Schwelle senken
  - Alles klumpt in einen Cluster → Schwelle anheben

### Output pro Cluster

Jeder Cluster-Eintrag enthält:
- Titel · Nische · Schmerz/Machbarkeit
- 2-3 Original-Zitate mit Link
- MVP-Skizze (1-2 Sätze)
- Monetarisierungs-Hypothese (wer zahlt, ~€/Monat)
- **WETTBEWERB** (Incumbents + wie eingegraben; Keil falls vorhanden)
- Status (NEU / +X Stimmen)

---

## 6. Action-Schwelle (Digest)

Der Wochen-Digest markiert Cluster als "READY TO VALIDATE" wenn:
- Schmerz >= 4
- Machbarkeit >= 4 (d.h. Wettbewerbsgate bestanden — kein Incumbent ODER Keil benannt)
- >= 8 Stimmen über >= 14 Tage

Das liefert pro Woche 0-2 echte Kandidaten — nicht 20.

### Digest-Blöcke

1. TOP 5 nach Schmerz×Machbarkeit (Gesamtstand)
2. TOP 5 MOVER der letzten 7 Tage
3. Action-Schwelle: READY-TO-VALIDATE-Markierungen
4. **Wettbewerb-Recheck**: Cluster mit "keiner gefunden — gegenprüfen"
   oder fehlendem WETTBEWERB-Feld (manueller Markt-Check nötig BEVOR Zeit
   reinfließt)
5. Abklingende Cluster (>14 Tage ohne Zuwachs)

---

## 7. Output & Speicherung

Jeder Slot speichert seinen Report getrennt:
- `~/hermes/reports/scan_A_YYYY-MM-DD.md`
- `~/hermes/reports/scan_B_YYYY-MM-DD.md`
- `~/hermes/reports/scan_C_YYYY-MM-DD.md`
- `~/hermes/reports/digest_YYYY-WW.md`

Alle Reports header-taggen mit `[SLOT A/B/C]` bzw. `[DIGEST]`.

Top 5 jedes Scans gehen als Telegram-Nachricht. Wenn nichts über der Schwelle
ist: ehrlich sagen.

---

## 8. Fehlermodi & Tuning

### Output zu leer / zu voll
- **Zu leer**: Dedup-Schwelle zu niedrig → alle Stimmen klumpen. Gate zu streng → Keil-Definition zu aggressiv.
- **Zu voll**: Dedup-Schwelle zu hoch → jeder Fund ist "NEU". Gate zu lasch → zu viele Ideen mit besetztem Markt.

### Quellenliste anpassen
Die Quellen pro Slot sind die Stellschraube für die Nische. Subs, Tool-Kategorien,
und Regionen gegen den Zielmarkt austauschen (z.B. deutschsprachige Foren ergänzen).

### Blick ins Cluster-Store
```bash
ls -lt ~/hermes/reports/scan_*.md | head -10
less ~/hermes/reports/cluster_index.json  # falls existiert
```

### Referenzen
Die vier Goal-Dateien unter `~/hermes/goals/` sind die laufenden Prompts.
Dieser Skill beschreibt die METHODIK dahinter. Änderungen an Quellen oder
Scoring-Parametern gehören in die Goal-Dateien, nicht in den Skill.

### Exa Search & Jina Reader als Fallback

Seit Juli 2026 ist in allen Goal-Dateien eine `TOOLS & FALLBACKS`-Sektion
ergänzt. Wenn web_search/web_extract (Firecrawl) keine Ergebnisse liefern:

- **Exa Search** (semantisch, kein Credit): `mcporter call 'exa.web_search_exa(query: "...", numResults: 5)'`
- **Jina Reader** (kein Credit): `curl -s "https://r.jina.ai/URL"`

Zusätzlich läuft web_search bereits über **DDGS (DuckDuckGo)** als
`search_backend` in der Hermes-Config — kein Firecrawl-Credit mehr für
einfache Websuchen. Nur noch web_extract braucht Firecrawl oder den Jina-Fallback.

Siehe Skill `research/agent-reach` für Details zu den Tools.