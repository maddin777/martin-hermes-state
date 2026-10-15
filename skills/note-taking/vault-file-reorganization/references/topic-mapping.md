# Themen-Zuordnung im Vault

Entscheidungstabelle für Move-Batches. Vor jedem Move die Datei gegen diese Tabelle prüfen. Projektzugehörigkeit (Ordner unter `Projekte/`) schlägt jede Themenzuordnung.

| Thema | Gehört hin | Gehört NICHT hin | Hinweis |
|---|---|---|---|
| Trading / Anlage | `Trading/`, `boerse/` | Exil, Nebengewerbe, Grundstück | Nur Aktien- und Anlagebezug. Ein Keyword wie "Börse" allein reicht nicht. |
| Auswanderung / Exil | `Exil/`, Wiki `concepts/Exil-*` | `Trading/` | Plan-B-Clippings, Länder- und Steuerthemen (z. B. Irland) gehören hierher, auch wenn sie Geld betreffen. |
| Nebengewerbe / One-Person-Business | `Nebengewerbe/`, `Geldverdienen/` | `Trading/` | Plan-B-Strategie-Dokumente liegen in `Nebengewerbe/`. |
| Grundstück / Krebsförden | `Projekte/Krefö/` (Grundstücks-Projekt), `Garten/` (Garten-Clippings) | `Trading/` | Behausung, Garten, Carport, Solar. Der Ordner heißt `Krefö`, nicht `Krebsförden`. Ordnernamen vor dem Mapping prüfen. |
| Rezepte / Ernährung | `Rezepte/` | `Lernen/` | Ernährungspläne und Rezept-Clippings. |
| Sprachen | `Lernen/Polnisch/` u. a. | `Rezepte/` | Lektionen und Tagebücher liegen unter `Lernen/`. |
| Tech / KI-Tools | `Tech/` | `Geldverdienen/` | Allgemeine IT- und KI-Themen. Ausnahme: reine Geldverdienen-Methoden bleiben in `Geldverdienen/`. |
| Manuskripte | `Projekte/Bücher/manuskript-<name>/` | Themenordner | Eigene Projekte nicht auflösen. Umbenennung nur mit vollständigem Verweis-Update über den ganzen Vault (siehe Schritt 12). |
| Claude-Protokolle | `claude/index.md`, `claude/log.md` (nur lesen) | überall | Übrige Claude-Inhalte sind in die Struktur integriert (`origin: claude`). |

## Entscheidungsregeln bei Grenzfällen

- Ist die Zuordnung nicht eindeutig, Datei nicht verschieben. Stattdessen in die Entscheidungsliste aufnehmen.
- Ordnernamen vor dem Mapping mit `os.path.isdir` prüfen (`boerse/` vs. `Börse/`). Nicht erfinden.
- Einmal zugeordnete Themen nicht still umdeuten. Änderungen an der Tabelle nur nach Freigabe.
