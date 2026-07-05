---
name: obsidian
description: "Read, search, create, and maintain notes in the Obsidian vault. Includes linking strategy: content-based Wikilinks (not folder-based), Map-of-Content (MOC) creation, cross-vault connections, LLM Wiki (Karpathy) pattern, and cron-based knowledge maintenance."
---

# Obsidian Vault

**Location:** `OBSIDIAN_VAULT_PATH` env var, or defaults to `~/Documents/Obsidian Vault`.
For Martin: `/root/obsidian-vault` (root-owned, synced to GDrive).

## Read a note

```bash
VAULT="${OBSIDIAN_VAULT_PATH:-$HOME/Documents/Obsidian Vault}"
cat "$VAULT/Note Name.md"
```

## List notes

```bash
VAULT="${OBSIDIAN_VAULT_PATH:-$HOME/Documents/Obsidian Vault}"
find "$VAULT" -name "*.md" -type f
ls "$VAULT/Subfolder/"
```

## Search

```bash
VAULT="${OBSIDIAN_VAULT_PATH:-$HOME/Documents/Obsidian Vault}"
find "$VAULT" -name "*.md" -iname "*keyword*"   # by filename
grep -rli "keyword" "$VAULT" --include="*.md"   # by content
```

## Create a note

```bash
VAULT="${OBSIDIAN_VAULT_PATH:-$HOME/Documents/Obsidian Vault}"
cat > "$VAULT/New Note.md" << 'ENDNOTE'
# Title

Content here.
ENDNOTE
```

## Append to a note

```bash
VAULT="${OBSIDIAN_VAULT_PATH:-$HOME/Documents/Obsidian Vault}"
echo "
New content here.
">> "$VAULT/Existing Note.md"
```

---

## Wikilinks — Verknüpfungsstrategie

**Wichtig (User-Preference):** Verknüpfungen IMMER inhaltlich setzen, nie nach Ordnerstruktur.
Zwei Dateien zum selben Konzept gehören verlinkt, auch wenn sie in verschiedenen Ordnern liegen.
Nutze Cross-Vault-Pfade (`[[../Other/Note]]`) für thematische Überschneidungen zwischen Ordnern.

### Regeln

1. **Inhalt > Ordner.** Eine Trading-Datei in `/Geldverdienen` und eine in `/hermes` verlinken wenn sie dasselbe Konzept behandeln (z.B. Polymarket Bot).
2. **Cross-Vault-Links:** `[[../Geldverdienen/Note Name]]` wenn eine Datei im /hermes Ordner ein Thema mit /Geldverdienen teilt.
3. **Am Ende jeder Datei:** `## Verknüpfungen`-Sektion mit Liste der Wikilinks + Kurzbegründung:
   ```
   ## Verknüpfungen
   - [[Andere Notiz]] — Warum sie verwandt ist
   ```
4. **MOC bei Batch-Import:** Beim Einpflegen mehrerer neuer Dateien (z.B. nach GDrive-Sync) immer eine MOC (Map of Content) anlegen, die alle neuen Dateien clustert + zentrale Konzepte tabellarisch erfasst.
5. **Sprache:** Wikilinks im `[[Note Name]]`-Format, mit Beschreibung nach `—`. Keine Ordner als Link-Begründung — nur inhaltliche Beziehungen.

### Workflow für neue Dateien (Batch-Import, z.B. nach GDrive-Sync)

1. **Alle Dateien listen** — `ls -la` im Zielordner, Grösse + Datum prüfen (neue Dateien erkennen)
2. **Cluster bilden** — Alle neuen Dateien nach Thema gruppieren (thematische Analyse, nicht nach Ordnern)
3. **Theorien extrahieren** — Pro Cluster Kernerkenntnisse/Thesen/Architekturen/komplementäre Ideen identifizieren
4. **Widersprüche erfassen** — Gegensätzliche Positionen (z.B. RAG vs LLM Wiki, Cloud vs Local) als komplementäre Perspektiven verlinken, nicht ausblenden
5. **MOC erstellen** — Zentrale Map of Content mit Cluster-Übersicht, cross-cluster-concept-table + Links zu bestehenden Notizen
6. **Wikilinks setzen** — In `## Verknüpfungen`-Sektion pro Datei. Für große Batches (50+ Dateien): execute_code mit loop + read_file + write_file
7. **Bestehende Notizen patchen** — Rücklinks von bestehenden Dateien zu den neuen setzen

### Vault Curation — Vollständiger Pipeline-Workflow

Nachdem neue Dateien ins Vault gelangt sind (Clippings, Syncs, manuelle Ergänzungen):

### 1. Scan & Duplicate Detection

```bash
# Alle Dateien + MD5 + Datum in Zielordnern
VAULT="/root/obsidian-vault"
find "$VAULT/Clippings" "$VAULT/hermes" "$VAULT/Geldverdienen" -name "*.md" -type f | \
  xargs md5sum | sort > /tmp/vault_files.txt

# Suche nach ` 1`-Suffix-Duplikaten (häufigster Fall)
find . -name "* 1.md" -type f
# Prüfe ob korrespondierende Datei ohne ` 1` existiert
# Neuere behalten, ältere löschen, ` 1` aus Name entfernen
```

**Bekannte Duplikat-Muster:**

| Muster | Beispiel | Entscheidung |
|--------|----------|-------------|
| `Name.md` + `Name 1.md` | Gleicher Inhalt, ` 1`-Suffix | Neuere behalten → ` 1` löschen, umbenennen |
| Gleicher Name in 2 Ordnern | `Clippings/` + `hermes/` | MD5 vergleichen. Identisch → einen löschen. Unterschiedlich → beide behalten |
| Gleicher Inhalt, anderer Name | `Praxisbeispiel Verein.md` vs `Verein - Praxisbeispiel.md` | Deskriptiveren Namen behalten |

**Vergleichslogik:** `md5sum datei1 datei2` — unterschiedliche MD5 = unterschiedliche Versionen, nie blind löschen.

### 2. Alle neuen Dateien lesen

Für jede neue Datei: `read_file` um Inhalt, Frontmatter (tags, source, author, published), und Kernaussage zu verstehen.

### 3. Relevanz klassifizieren

Dreistufiges Schema — in den Morning Report oder direkt ans User-Feedback:

| Stufe | Label | Bedeutung | Aktion |
|-------|-------|-----------|--------|
| 🔥 High | Direkt relevant | Enthält umsetzbare Ideen/Code/Patterns für aktive Projekte | Wiki-Seite anlegen, ggf. Handlungsoption vorschlagen |
| 📌 Medium | Kontext | Erweitert Verständnis, aber kein Sofort-Handlungsbedarf | In bestehende Wiki-Seite einarbeiten oder als Referenz notieren |
| ⏹ Low | Gelesen | Kein Handlungsbedarf (anderer Fokus, schon bekannt, zu vage) | Nur vermerken, keine Wiki-Seite |

### 4. Wiki-Seiten erstellen (für 🔥 + 📌)

Pro relevanter Quelle: neue Wiki-Seite in `wiki/concepts/` anlegen.

**Standard-Template:** (siehe auch `templates/gate-page.md` für Checklisten/Gate-Seiten)

```markdown
[[wiki/concepts|concepts]] → [[Seitenname]]

---
created: {{YYYY-MM-DD}}
updated: {{YYYY-MM-DD}}
tags: [concept, tag1, tag2]
type: enriched
source: {{Quellenangabe}} — {{Author}}
---

# Seitenname

Kurze Definition / 1-2 Sätze Kernaussage.

## Abschnitt 1
...
## Abschnitt 2
...
## Quellen
- [[../../Ordner/Quelldatei]] — Kontext
```

**Dabei beachten:**
- `source`-Frontmatter mit Link zur Original-Clipping-Datei
- `tags` passend setzen (concept + themenspezifisch)
- Backlink-Navigation (`[[wiki/concepts|concepts]] → [[Seitenname]]`)
- `## Quellen`-Sektion mit vollem Pfad zur Quelldatei
- Wikilinks zu verwandten Konzepten setzen

### 5. Bestehende Wiki-Seiten patchen

Wenn neue Inhalte ein bestehendes Konzept erweitern:
- `patch` auf die bestehende Wiki-Seite
- Neuen Abschnitt einfügen
- Quelle in `## Quellen` verlinken
- `updated`-Datum im Frontmatter aktualisieren

### 6. Index updaten

`wiki/concepts/index.md` und `wiki/index.md`:
- Neue Seiten eintragen mit Kurzbeschreibung
- Neue Quellen-Links in bestehenden Seiten ergänzen

---

## Health Check (Broken Links, Orphans, Stale Pages)

Durchführung für den `vault-self-write-health` Cron (Sa 03:00):

### Broken Link Detection — Noise-Filter-Technik

Nicht jeder `[[Wikilink]]` der auf keine Seite zeigt ist ein Broken Link. MOC-Pages enthalten Navigation-Links wie `[[wiki]]`, `[[wiki/concepts]]`, `[[wiki/entities]]`, `[[wiki/index]]` — das sind **Selbstreferenzen** der Navigationsleiste, keine Broken Links.

**Filter-Schritte:**

1. Alle `[[target]]`-Links aus Wiki-Dateien extrahieren
2. Build a set of all existing wiki page names (without `.md`, with and without path prefix)
3. **Noise-Prefixe rausfiltern:** `wiki`, `wiki/`, `wiki/concepts`, `wiki/entities`, `wiki/sources`, `wiki/index`
4. Übrige Links prüfen: existiert ein Wiki-Page mit dem Namen (exakt oder als Dateiname ohne Pfad)?
5. Bei `../../`-Links: vom Datei-Pfad aus auflösen — `os.path.normpath(os.path.join(os.path.dirname(fpath), target))` — und prüfen ob die Datei existiert

**Häufige False Positives:**
- `[[../../Trading/Watchlist]]` → Datei existiert, nur relativer Pfad — kein Broken Link
- `[[../../hermes/dateiname]]` → Datei existiert im hermes/ Ordner — prüfen vor Meldung
- `[[../Trading/Erklaerung]]` → Auflösung von wiki/ aus funktioniert (wiki/../Trading/ = Trading/)

**Kritische Pitfall — `../../` Auflösung aus `wiki/`:**
Aus `wiki/trading-index.md`: `[[../../Trading/Erklaerung]]` → `/root/Trading/Erklaerung` (geht 2 Ebenen hoch: wiki→vault-root→vault-parent).
Aus `wiki/concepts/X.md`: `[[../../Trading/Erklaerung]]` → `/root/obsidian-vault/Trading/Erklaerung` (geht 2 Ebenen hoch: concepts→wiki→vault-root).
**Merke:** `wiki/` ist 1 Level tief, `wiki/concepts/` ist 2 Level tief. Gleicher Link-Text kann je nach Quell-Tiefe valide oder broken sein. Immer mit `os.path.normpath(os.path.join(os.path.dirname(fpath), target))` auflösen.
Referenz: `references/broken-link-detection-script.py` implementiert die vollständige Logik.

**Echte Broken Links sind:**
- Wikilinks zu nicht-existierenden Wiki-Seiten (z.B. `[[KI-Sicherheit]]`, `[[Aktien (KI Zulieferer)]]` → kein Konzept angelegt)
- `../../`-Links deren Datei nicht existiert (z.B. falscher Zielordner, falscher Dateiname)
- `../skills/...` Links aus Wiki-Seiten (skills/ ist kein Wiki-Ordner)
- Links mit doppelter `.md.md`-Extension (z.B. `[[wiki/concepts/SOUL.md.md]]` — korrekt ist `.md`)
- Links mit abschließendem `\`-Escape (z.B. `[[Exil-Polen\\|Polen]]` — das `\\` ist ein Syntax-Fehler, korrekt ist `[[Exil-Polen|Polen]]`)

**Zusätzliche Noise-Patterns (häufige False Positives):**

| Pattern | Beispiel | Begründung |
|---------|----------|-----------|
| `wiki/concepts/Seitenname.md` als Self-Link | `[[wiki/concepts/Automation.md]]` in `Automation.md` | Obsidian rendert das als Fettdruck — kein Broken Link |
| `./` Präfix | `[[./Multi-LLM Ensemble]]` in `LLM.md` | Relativer Link zum selben Ordner |
| `wiki/concepts/Seitenname` (ohne `.md`) als Self-Link | `[[wiki/concepts/Automation]]` in `Automation.md` | Gleiches Prinzip — Navigation, kein Broken Link |

**Pitfall — Self-Link Detection:**
Beim Filtern von Self-Links muss der Dateiname (ohne Pfad) mit dem Link-Target (nach Strip von `wiki/concepts/`, `wiki/entities/`, `./`) case-insensitive verglichen werden. Der Link `[[wiki/concepts/Pre-Mortem]]` in `Pre-Mortem.md` ist valide. Der gleiche Link in `Automation.md` wäre broken.

**Pitfall — Trailing Backslash `\\`:**
In Obsidian-Markdown wird `[[Exil-Polen\\|Polen]]` als Link zu `Exil-Polen\` (mit Backslash im Namen) interpretiert — der Backslash ist escaped, aber Obsidian matcht ihn nicht als existierende Seite. Wenn der Scanner `\\` im Link findet → fast immer ein Broken Link durch escaped Pipe.

Referenz: `references/broken-link-detection-script.py` implementiert die vollständige Logik inklusive dieser Noise-Patterns.

### Orphan Detection

Orphans = Dateien >30 Tage alt, in relevanten Dirs (Geldverdienen/, boerse/, hermes/, Trading/, Clippings/, raw/), die von KEINER Wiki-Seite verlinkt sind.

**Prüfung:** Für jede Kandidaten-Datei: suche in allen Wiki-Dateien nach `[[../../path/to/datei]]` (mit und ohne `.md`). Wenn kein Treffer → Orphan.

**Nicht scannen:** `.obsidian/`, `Projekte/Buecher/`, `CACHE.txt`, sowie persönliche Ordner (Rezepte, Lernen, Reisen, Sport, Exil, System, Tools, Personen, etc.)

### Stale Source Detection

Quellen in `wiki/sources/` die von keinem Wiki-Concept/Entity verlinkt werden. Kapitel-Dateien aus Manuskript-Projekten (Kapitel_X, Verleger-Gutachten, Änderungsprotokoll etc.) zählen nicht — sie sind Archiv, keine Wissensquellen.

---

## Gap Detection — Fehlende Wiki-Seiten aus Rohdaten

Nachdem der Health Check läuft: welche Konzepte tauchen in Rohdaten auf, haben aber keine Wiki-Seite?

### Extraktions-Technik

1. Finde Dateien aus den letzten 7 Tagen in hermes/, boerse/, Geldverdienen/, Trading/, Clippings/
2. Extrahiere aus jeder Datei: **Headings** (`^#{1,3}\s+(.+)`) und **bold terms** (`\*\*(.+?)\*\*`)
3. Normalisiere und dedupliziere die Terme
4. Kreuze gegen existierende `wiki/concepts/` und `wiki/entities/` an (case-insensitive Dateiname ohne `.md`)
5. Übrig: Kandidaten für neue Wiki-Seiten

### Seiten-Anlage-Kriterien

- **Max 2 neue Seiten** pro Durchlauf
- **Nur anlegen wenn genug Substanz:** 3+ Absätze Content möglich (nicht nur "[...] ist ein Tool")
- **Concept oder Entity?** Abstrakte Idee → `concepts/`. Konkrete Sache (Modell, Person, Tool, Ort) → `entities/`
- **Template:** Frontmatter (`created`, `updated`, `tags`, `type`, `source`) + `[[wiki/concepts|concepts]] → [[Seitenname]]` Navigation + Body + `## Quellen`-Sektion mit vollen Pfaden zu Quellen

---

## Synthesis — Übergreifende Analyse / MOC

Wenn 3+ verwandte Quellen zu einem Thema existieren, die noch keine übergreifende Analyse haben, eine MOC-Seite anlegen.

### Kriterien für MOC

- **3+ unabhängige Quellen** (nicht Duplikate, nicht unterschiedliche Versionen derselben Quelle)
- **Thematischer Cluster** vorhanden (alle handeln vom selben Konzept)
- **Noch keine übergreifende Seite** die den Cluster synthetisiert

### MOC-Format

Die MOC ist ein Concept-Page das die Quellen synthetisiert:
- Kern-These oder Definition
- Vergleichstabelle (wenn unterschiedliche Ansätze/Meinungen)
- Strukturierte Abschnitte die die Quellen zusammenführen
- `## Quellen` mit allen 3+ Quellen
- `## Verbindungen` zu bestehenden Wiki-Seiten

**Ziel:** Ein Leser der nur die MOC liest, versteht das Thema vollständig ohne alle Quellen einzeln lesen zu müssen.

---

## Backward Integration — Neue Verbindungen aus Rohdaten

Nachdem neue Dateien ins Wiki eingepflegt wurden: fehlende Rücklinks in bestehenden Wiki-Seiten ergänzen.

### Ansatz

1. Neue/geänderte Dateien der letzten 7 Tage in relevanten Dirs scannen
2. Themen/Hauptaussagen extrahieren (Titel + Headings reichen meist)
3. Prüfen welche bestehenden Wiki-Seiten darauf verweisen sollten
4. **Max 5 Änderungen** pro Durchlauf — nur die wertvollsten/missingsten Ergänzungen
5. Priorisierung: Konzepte/Entities mit erkennbarer Lücke > Perfektionismus

### Typische Muster

| Rohdaten-Thema | Sollte verlinkt werden von |
|----------------|---------------------------|
| Trading-System-Doku | `Trading Pipeline Architecture` |
| Neue Prompt-Vorlagen | `prompt.md` / `Hermes Prompt Recipes` |
| Fable 5 / Claude 5 | `prompt.md` / agent.md |
| Obsidian-Theorie | `entities/Obsidian.md` |
| Agent-Loops / Autonomy | `agent.md` / `Automation.md` |
| MCP-Setup | `MCP Trading Setup` |

### Pitfalls

- **Nicht nur Datum prüfen:** Dateien können durch Sync unterschiedliche Timestamps haben. MD5 ist der verlässliche Duplikat-Indikator.
- **` 1`-Suffixe prüfen:** Bei Obsidian-Clipping-Imports entstehen oft ` 1`-Duplikate (gleicher Name, neuere Version). Immer MD5 vergleichen.
- **Cross-Dir-Duplikate:** Gleicher Dateiname in `/Clippings/` und `/hermes/` = nicht automatisch Duplikat. Inhalt prüfen.
- **Wiki nicht aufblähen:** ⏹-Dateien brauchen keine Wiki-Seite. Nur 🔥- und 📌-Inhalte landen im Wiki.
- **Backlinks nicht vergessen:** Neue Wiki-Seiten in die `## Quellen`-Sektion bestehender Seiten verlinken, sonst sind sie Orphans.

Referenz: `references/vault-curation-2026-06-11.md` für ein vollständiges Durchlaufbeispiel (13 Dateien, 8 Duplikate, 7 Wiki-Änderungen).

---

## Cross-Vault Linking (ordnerübergreifend)

Nach dem Batch-Import: gezielt die thematischen Überschneidungen zu bestehenden Ordnern suchen:

| Ausgangsordner | Zielordner bei thematischer Überschneidung |
|---|---|
| `/hermes/` (Agent-Themen) | `../Hermes Idee`, `../Geldverdienen/` (AI-Business) |
| `/hermes/` (Trading-Themen) | `../Trading/Watchlist`, `../boerse/`, `../Geldverdienen/` (Quant) |
| `/hermes/` (RAG/Learning) | `../Lernen/Polnisch/`, `../Mindset/Transurfing/` |
| `/Geldverdienen/` | `../hermes/` (bei AI-Money-Content) |
| `/boerse/` | `../hermes/` (Trading), `../Trading/Watchlist` |

Cross-Vault-Links nutzen relativen Pfad: `[[../Zielordner/Note Name|Anzeigename]]`

---

## LLM Wiki (Karpathy-Pattern) — Knowledge Compounding

Ein persistentes Wiki zwischen Rohdaten und LLM-Agent, das Wissen kompoundiert statt nur zu retrieven.

### Ordnerstruktur

```
vault/ (00-CAPTURE, boerse, Clippings, Geldverdienen, hermes, Inbox, Projekte, raw, Trading, wiki)
├── 00-CAPTURE/        # Schnelle Notizen, kein Ordner-Denken (Anti-Breakdown-Pattern)
├── raw/              # Rohdaten (Clippings, Artikel, Transkripte — unverändert)
├── wiki/             # LLM-gepflegtes, kompoundiertes Wissen
│   ├── concepts/     # Abstrakte Konzepte
│   ├── entities/     # Konkrete Entitäten
│   ├── sources/      # Quellen
│   └── trading-index.md
└── ...
```

### Wiki-Seiten-Format

Jede Wiki-Seite folgt einem klaren Schema:

```markdown
[[wiki/concepts|concepts]] → [[Seitenname]]

# Seitenname

Kurze Definition des Konzepts.

## Kernkonzept

Die Essenz in 2-3 Sätzen.

## Quellen

- [[../../boerse/Quelldatei]] — Kontext
- [[../../hermes/Quelldatei]] — Kontext

## Verbindungen

- [[Anderes Konzept]] — Beziehung
- [[../../Trading/Watchlist|Watchlist]] — Praktische Anwendung
```

### Cron-basierte Wartung

Drei Cron-Jobs pflegen das Wiki automatisch:

1. **vault-insights-daily** (02:45 täglich) — Rohdaten scannen, Erkenntnisse extrahieren, Wiki updaten, Wikilinks pflegen, Bericht
2. **vault-self-write-health** (Sa 03:00) — Health Check (Broken Links, Orphans), Backward Integration (neue Wikilinks), Gap Detection (fehlende Wiki-Seiten), Synthesis (MOC-Seiten)
3. **weekly-review** (So 19:00) — Wochenrückblick: Trading-Check, Projekt-Status, Sync-Health, Empfehlungen

1. **Rohdaten scannen** — Neue/modifizierte Dateien in Trading/, boerse/, Geldverdienen/ prüfen
2. **Erkenntnisse extrahieren** — Neue Trading-Erkenntnisse, Marktregime, Risikohinweise
3. **Wiki updaten** — Neue Erkenntnisse in bestehende Wiki-Seiten einarbeiten, bei neuen Themen neue Seiten anlegen
4. **Wikilinks pflegen** — Querverweise zwischen Wiki-Seiten und Rohdaten aktualisieren
5. **Bericht** — Kurze Zusammenfassung was geupdated wurde (oder [SILENT] wenn nichts Neues)

Regeln:
- Keine manuell erstellten Wiki-Inhalte überschreiben — nur ergänzen
- Quellen immer als relativen Pfad referenzieren
- Wiki-Seiten kompakt halten (max 500 Wörter pro Konzept)
- Bei nichts Neuem: [SILENT] (unterdrückt Delivery)

### Proaktive Vorschläge aus Cron — Trace-Pattern

Wenn der User sagt "Bau X / Aktualisier Y aus meinen proaktiven Vorschlägen" und X/Y nicht auffindbar sind:

1. **Die Vorschläge kamen aus dem vault-insights CRON** (02:45 täglich, Abschnitt C — "Proaktive Vorschläge max 3")
2. **Trace:** `session_search(query="Proaktive Vorschläge", sort="newest", limit=1)` um den heutigen vault-insights Report zu finden
3. **Die genauen Vorschläge identifizieren:** Der Report listet 3 Vorschläge mit konkreten nächsten Schritten, Aufwand und "Soll ich das jetzt umsetzen?"
4. **Bauen:** Vorschlag 1 = Verifier Gate (Wiki-Seite anlegen), Vorschlag 2 = Cron/Code-Bau, Vorschlag 3 = Doku-Update (oft umgekehrt: Wiki ist Quelle, Erklaerung.md muss aktualisiert werden)

**Wichtig:** Bei "Aktualisier die erklaerung.md" schauen ob die Wiki-Seite neuer ist als die Quelle — dann ist die Quelle veraltet und muss mit dem Wiki-Stand gefixt werden (nicht andersrum).

Referenz: `references/vault-wide-content-linking-2026-05-11.md` für das vollständige Protokoll der 143-link Vault-Restrukturierung.

---

## GDrive Sync

1. **Bisync Cron** (nightly): `cronjob run f5eb3bfaf65e` — nutzt `rclone bisync gdrive: ~/obsidian-vault --drive-root-folder-id [...]` (direkt, nicht via sync.sh)
2. **sync.sh** (für manuelle Nutzung): `/root/obsidian-vault/sync.sh {push|pull|bisync|status}` — Remote-Path ist `gdrive:hermes-obsidian-vault` (mit Hyphen, gefixt 23.05.)
3. **One-way GDrive → Local**:  \n   `rclone copy gdrive: /root/obsidian-vault/ --drive-root-folder-id 1aY8QQ6Sw8ljGhvEV0rayQpxRgCQw9Vj4 --verbose --transfers=8 --progress`\n   (copy statt sync — kein Risiko lokale Dateien zu loeschen)
4. **Verify**: `ls -la /root/obsidian-vault/ | grep -i pattern` or `search_files path=/root/obsidian-vault/ pattern=keyword`
3. **Verify**: `ls -la /root/obsidian-vault/ | grep -i pattern` or `search_files path=/root/obsidian-vault/ pattern=keyword`

**Pitfall**: Path `/Hermes/` often empty/missing post-sync; `/hermes/` (lowercase) has 20+ clippings. Check `/Projekte/Hermes/config.yaml`, `/Projekte/Paper-Trading/Watchlist.md`.