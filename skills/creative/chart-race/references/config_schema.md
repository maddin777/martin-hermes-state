# Config-Schema (render_engine.py)

Alle Felder einer Render-Config. Pflichtfelder sind markiert. Die Engine
validiert vor dem Rendern (`validate_config`) und warnt bei verdächtigen Daten
(`sanity_check`).

## Pflicht

| Feld | Typ | Beschreibung |
|------|-----|-------------|
| `chart_type` | string | `stacked_area` \| `line_race` \| `bar_race` |
| `data_file` | string | Pfad zur CSV (oder via `fetch` erzeugt) |
| `title` | string | Haupttitel (erste Zeile oben links) |

## Daten-Layout

| Feld | Default | Beschreibung |
|------|---------|-------------|
| `orientation` | `"wide"` | `wide`: Spalte 1 = Serie, Rest = Zeitpunkte. `long`: braucht die drei Spalten unten |
| `sep` | `","` | CSV-Trennzeichen |
| `date_col` | – | (nur long) Name der Datumsspalte |
| `series_col` | – | (nur long) Name der Serien-/Kategoriespalte |
| `value_col` | – | (nur long) Name der Wertspalte |
| `series` | alle | Liste: nur diese Serien, in dieser Reihenfolge (Stapel-Reihenfolge!) |

## Style

| Feld | Default | Beschreibung |
|------|---------|-------------|
| `theme` | `"dark"` | `dark` \| `light` |
| `colors` | auto | `{"Serienname": "#hex"}` — Rest aus Palette |
| `accent_color` | `#f0883e` | Farbe der Titel-Akzentzeile |
| `title_accent` | – | zweite, farbige Titelzeile |
| `subtitle` | – | graue Unterzeile |
| `y_label` | – | Achsentitel |
| `source` | – | Quellenzeile unten |
| `font_path` | DejaVu | Pfad zu .ttf/.otf (z.B. Inter für Katapult-Look) |
| `date_fmt` | `"%b %Y"` | Format des mitlaufenden Datums |

## Animation

| Feld | Default | Bereich | Beschreibung |
|------|---------|---------|-------------|
| `duration_sec` | `40` | 5–180 | Dauer des Durchlaufs |
| `fps` | `30` | 10–60 | Bildrate (24 = "filmisch/langsam") |
| `hold_end_sec` | `2` | – | Standbild am Ende |
| `crf` | `18` | 0–51 | H.264-Qualität (kleiner = besser/größer) |

## Typ-spezifisch

**stacked_area / line_race:**
| Feld | Beschreibung |
|------|-------------|
| `running_divisor` | Teiler für die mitlaufende Summenzahl (100 = ct→€) |
| `running_unit` | Einheit hinter der Summe (" €") |
| `running_fmt` | Zahlenformat (`.2f`) |
| `value_fmt` | Format der Legendenwerte (`"{:.2f} €"`) |

**bar_race:**
| Feld | Default | Beschreibung |
|------|---------|-------------|
| `top_n` | 10 | Anzahl sichtbarer Balken |
| `bar_value_fmt` | `.1f` | Format der Wertlabels am Balken |
| `show_legend` | `true` | bei bar_race meist `false` |

## Meilensteine

| Feld | Beschreibung |
|------|-------------|
| `milestones_file` | CSV `;`-getrennt: date;end;label;category |
| `milestones` | ODER inline: Liste von `{"date","label","category"}` |
| `milestone_labels` | nur diese Labels zeigen (sonst wird 9:16 zu voll) |

`category` steuert die Farbe: `krise`/`krieg`/`geopolitik` → rot,
`politik` → blau, `markt` → gelb, sonst grau.

## Plausibilität

| Feld | Beschreibung |
|------|-------------|
| `expected_max` | erwarteter Maximalwert. Überschreitung → Warnung (fängt Währungsfehler) |

## Self-Fetch (Modus B)

| Feld | Beschreibung |
|------|-------------|
| `fetch.script` | Fetcher in `scripts/fetchers/` |
| `fetch.args` | Argumentliste |
| `fetch.produces` | Pfad der erzeugten CSV → wird zu `data_file` |

## Sonderfall verschiedene Größenordnungen

Wenn Serien stark unterschiedliche Skalen haben (z.B. Tankstellenpreis ~1,8 €/l
vs. Rohöl ~0,4 €/l vs. Rohöl in USD/Barrel ~80), NICHT in einen line_race mischen —
die kleine Serie wird zur flachen Linie. Entweder auf eine gemeinsame Einheit
bringen (siehe fuel-Projekt: Brent in €/l) oder getrennte Videos rendern.