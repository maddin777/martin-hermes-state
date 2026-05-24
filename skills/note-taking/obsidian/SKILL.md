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

### Cross-Vault Linking (ordnerübergreifend)

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

Referenz: `references/vault-wide-content-linking-2026-05-11.md` für das vollständige Protokoll der 143-link Vault-Restrukturierung.

---

## GDrive Sync

1. **Bisync Cron** (nightly): `cronjob run f5eb3bfaf65e` — nutzt `rclone bisync gdrive: ~/obsidian-vault --drive-root-folder-id [...]` (direkt, nicht via sync.sh)
2. **sync.sh** (für manuelle Nutzung): `/root/obsidian-vault/sync.sh {push|pull|bisync|status}` — Remote-Path ist `gdrive:hermes-obsidian-vault` (mit Hyphen, gefixt 23.05.)
3. **One-way GDrive → Local**:  \n   `rclone copy gdrive: /root/obsidian-vault/ --drive-root-folder-id 1aY8QQ6Sw8ljGhvEV0rayQpxRgCQw9Vj4 --verbose --transfers=8 --progress`\n   (copy statt sync — kein Risiko lokale Dateien zu loeschen)
4. **Verify**: `ls -la /root/obsidian-vault/ | grep -i pattern` or `search_files path=/root/obsidian-vault/ pattern=keyword`
3. **Verify**: `ls -la /root/obsidian-vault/ | grep -i pattern` or `search_files path=/root/obsidian-vault/ pattern=keyword`

**Pitfall**: Path `/Hermes/` often empty/missing post-sync; `/hermes/` (lowercase) has 20+ clippings. Check `/Projekte/Hermes/config.yaml`, `/Projekte/Paper-Trading/Watchlist.md`.