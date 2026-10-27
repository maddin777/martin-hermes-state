# Frontmatter-Schema und Themen-Zuordnung

Gilt für alle Markdown-Dateien im Vault außer `claude/index.md` und `claude/log.md`. Bilder, PDFs und andere Nicht-Markdown-Dateien tragen kein Frontmatter.

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
- `topic: sonstiges` ist der sichere Default. Nur abweichen, wenn Ordner oder mehrere klare Inhaltstreffer eindeutig sind.
- Personen, Creator und Autoren sind kein Thema.
- Bei mehr als einem Drittel `sonstiges` ist die Regel zu grob, nicht die Datei zu schwer.

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

## Themen-Entscheidungstabelle (Grenzfälle)

Projektzugehörigkeit (Ordner unter `Projekte/`) schlägt jede Themenzuordnung.

| Thema | Gehört hin | Gehört NICHT hin | Hinweis |
|---|---|---|---|
| Trading / Anlage | `Trading/`, `boerse/` | Exil, Nebengewerbe, Grundstück | Nur Aktien- und Anlagebezug. Ein Keyword wie „Börse“ allein reicht nicht. |
| Auswanderung / Exil | `Exil/`, Wiki `concepts/Exil-*` | `Trading/` | Plan-B-Clippings, Länder- und Steuerthemen (z. B. Irland), auch wenn sie Geld betreffen. |
| Nebengewerbe / One-Person-Business | `Nebengewerbe/`, `Geldverdienen/` | `Trading/` | Plan-B-Strategiedokumente liegen in `Nebengewerbe/`. |
| Grundstück / Krebsförden | `Projekte/Krefö/`, `Garten/` | `Trading/` | Behausung, Garten, Carport, Solar. Der Ordner heißt `Krefö`, nicht `Krebsförden`. Ordnernamen vor dem Mapping prüfen. |
| Rezepte / Ernährung | `Rezepte/` | `Lernen/` | Ernährungspläne und Rezept-Clippings. |
| Sprachen | `Lernen/Polnisch/` u. a. | `Rezepte/` | Lektionen und Tagebücher liegen unter `Lernen/`. |
| Tech / KI-Tools | `Tech/` | `Geldverdienen/` | Ausnahme: reine Geldverdienen-Methoden bleiben in `Geldverdienen/`. |
| Manuskripte | `Projekte/Bücher/manuskript-<name>/` | Themenordner | Eigene Projekte nicht auflösen. Umbenennung nur mit vollständigem Verweis-Update über den ganzen Vault (W3). |
| Claude-Protokolle | `claude/index.md`, `claude/log.md` (nur lesen) | überall | Übrige Claude-Inhalte sind in die Struktur integriert (`origin: claude`). |

## Entscheidungsregeln bei Grenzfällen

- Ist die Zuordnung nicht eindeutig, Datei nicht verschieben — in die Entscheidungsliste aufnehmen.
- Ordnernamen vor dem Mapping mit `os.path.isdir` prüfen (`boerse/` vs. `Börse/`). Nicht erfinden.
- Einmal zugeordnete Themen nicht still umdeuten. Änderungen an der Tabelle nur nach Freigabe.
- Ordner-Vorrang geht der Inhaltsentscheidung voraus: längster Ordner-Präfix zuerst prüfen.
- Stichwort-Score nur bei Score ≥ 2 UND klarem Vorsprung des Siegers; sonst `sonstiges`. Vor dem Schreiben Stichprobe (10 Zufälle pro Gruppe) prüfen.

## Migrationsmapping alt zu neu

| alter `type` | `kind` | `origin` |
|---|---|---|
| source, youtube-transcript, x-post, web_clipping, github-repo | source | clipping |
| recognized, entity | entity | clipping bzw. hermes |
| concept, enriched | concept | hermes |
| recipe | recipe | clipping |
| index | index | hermes |
| note, manuscript_chapter, manuscript_correction, manuscript_review | note | manuell |
