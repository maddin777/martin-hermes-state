# Frontmatter-Schema für den Vault

Gilt für alle Markdown-Dateien im Vault (ohne `claude/index.md` und `claude/log.md`). Bilder, PDFs und andere Nicht-Markdown-Dateien tragen kein Frontmatter.

## Pflichtfelder

| Feld | Werte |
|---|---|
| `kind` | `source`, `concept`, `entity`, `recipe`, `note`, `index` |
| `origin` | `hermes`, `claude`, `clipping`, `manuell` |
| `topic` | `exil`, `nebengewerbe`, `krebsfoerden`, `trading`, `geld`, `ernaehrung`, `sprachen`, `tech`, `sonstiges` |

Das Feld `type` ist abgeschafft. Nicht wieder einführen, auch nicht in Templates.

## Regeln

- `index.md` und Ordnerübersichten: `kind: index`, `topic` aus dem Ordner, nie aus dem Inhalt.
- `topic: trading` nur für Anlage und Aktien. Plan-B, Auswanderung und Grundstück gehören nie dorthin.
- `origin: claude` nur für Inhalte aus Claude-Code-Sessions.
- Ingest-Scripte setzen `origin: clipping` für Clippings und `origin: hermes` für Wiki-Seiten, die sie selbst anlegen.
- `topic: sonstiges` ist der sichere Default. Nur setzen, wenn Ordner oder mehrere klare Inhaltstreffer eindeutig sind.

## Ordner zu Thema (Default vor der Inhaltsprüfung)

| Ordner | topic |
|---|---|
| `Projekte/Krefö/`, `Garten/`, `Clippings/Garten/` | krebsfoerden |
| `Exil/`, `Clippings/Exil/` | exil |
| `Nebengewerbe/` | nebengewerbe |
| `Geldverdienen/` | geld (Inhalt entscheidet bei Nebengewerbe-Bezug) |
| `Trading/`, `boerse/`, `Projekte/Paper-Trading/` | trading |
| `Rezepte/`, `Clippings/Rezepte/` | ernaehrung |
| `Lernen/` | sprachen |
| `Tech/`, `hermes/` | tech |
| `wiki/` | Inhalt, sonst `sonstiges` |

## Migrationsmapping alt zu neu

| alter `type` | `kind` | `origin` |
|---|---|---|
| source, youtube-transcript, x-post, web_clipping, github-repo | source | clipping |
| recognized, entity | entity | clipping bzw. hermes |
| concept, enriched | concept | hermes |
| recipe | recipe | clipping |
| index | index | hermes |
| note, manuscript_chapter, manuscript_correction, manuscript_review | note | manuell |
