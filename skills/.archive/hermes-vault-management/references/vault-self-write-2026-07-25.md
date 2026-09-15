# Vault Self-Write Health — 2026-07-25

Durchgeführt am Sa 25.07.2026 03:00 nach GDrive-Sync.

## Summary

- **87 Broken Links** gefunden, 4 in trading-index.md behoben
- **426 Orphans** >30 Tage (erwartet, Clippings-Ingest läuft täglich)
- **138 Stale Sources** (58 echte, Rest Manuskript-Kapitel)
- **2 neue Entity-Seiten** angelegt: Aktien (KI Zulieferer), OpenClaw Profit Guide
- **4 Wikilinks** in trading-index.md gefixt
- **entities/index.md** aktualisiert
- **Keine Synthesis-Seite** nötig — alle Cluster bereits gut vernetzt

## Noise-Patterns die der Scanner erkennen muss

### 1. `wiki/index.md` → `[[entities/Name]]` etc.
`wiki/index.md` und `wiki/entities/index.md` nutzen relative Links ohne `wiki/`-Prefix:
- `[[entities/Alex Finn]]` → muss als `wiki/entities/Alex Finn.md` aufgelöst werden
- `[[concepts/Loop Engineering]]` → `wiki/concepts/Loop Engineering.md`
- Gleiches gilt für `sources/`, `tasks/`, `reports/`, `ideas/`

### 2. Bekannte Ordner-Namen
Folgende werden als Link-Targets in Source-Pages verwendet, sind aber keine Wiki-Seiten:
```
boerse, Geldverdienen, Clippings, Mindset, Lernen, Personen, Haus, Gemeinnütziger Verein
```

### 3. Twitter-Handles
`@itsmichaelluu`, `@thestockwhale`, `@grkportfolio`, `@aimikoda` — werden als `[[@handle]]` in Source-Seiten referenziert

### 4. Manuskript-Kapitel
Roman-Manuskript-Kapitel (Keltenstein, Bernstein-Kern, etc.) haben Dateien in `wiki/sources/` aber sind keine Wiki-Konzepte. Siehe `MANUSCRIPT_PREFIXES` im Script.

## Behobene Broken Links

| Datei | Alter Link | Fix |
|-------|-----------|-----|
| trading-index.md | `[[OpenClaw]]` → existiert nicht | `[[OpenClaw Profit Guide]]` (neue Entity) |
| trading-index.md | `[[boerse Clippings]]` → existiert nicht | `[[../boerse/\|boerse Clippings]]` (Folder-Ref) |
| trading-index.md | `[[Information Theory (Polymarket)]]` → existiert nicht | `[[wiki/sources/Information Theory on Polymarket\|...]]` |
| trading-index.md | `[[Aktien (KI Zulieferer)]]` → existiert nicht | Neue Entity-Seite angelegt |

## Neue Seiten

### `wiki/entities/Aktien (KI Zulieferer).md`
NVIDIA, KI-Infrastruktur-Titel. Quellen: KI Zulieferer, optics/memory/rare earth, quantum stocks, Marvell Optical DSP.

### `wiki/entities/OpenClaw Profit Guide.md`
Krypto-Arbitrage-Bot Strategien. Quellen: OpenClaw Profit, 28 tools Polymarket Bot.

## Entities/index.md aktualisiert
- Tools & Services: `OpenClaw Profit Guide` hinzugefügt
- Assets: `Aktien (KI Zulieferer)` hinzugefügt