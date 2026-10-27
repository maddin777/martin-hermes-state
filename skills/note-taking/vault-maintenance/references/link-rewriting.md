# Link-Umbiegen nach Vault-Moves

Detail zu W3/W4 des Skills `vault-maintenance`. Ein Move ohne Link-Update lässt jede Seite, die auf die Datei zeigt, ins Leere laufen.

## Mechanik

Relativ neu berechnen, nicht Basename ersetzen:

```python
rel = os.path.relpath(neuer_vault_pfad, os.path.dirname(wiki_datei))
# ganzen Link-Ausdruck ersetzen, nicht nur den Namen
```

`str.replace(alter_name, neuer_name)` ändert nur den Namen, nicht die Pfadtiefe — die Relativbasis stimmt danach nicht mehr und es entstehen Muster wie `../../Clippings/../../Tech/…`.

## Regeln

- Alle Verweise auf das alte Ziel vor dem Batch sammeln (`grep -rl` nach dem Basename über den GANZEN Vault, nicht nur `wiki/`; sonst bleiben Links aus `Projekte/` oder `Clippings/` stehen).
- Wikilinks ohne `.md`, Markdown-Links mit `.md`: `[[pfad.md]]` löst Obsidian nicht auf. Endung beim Wikilink strippen, Alias (`|Text`) und Anker (`#…`) mitnehmen, schließendes `]]` nicht verschlucken.
- Neuen Link vor dem Schreiben aus der Quelldatei heraus auflösen (`normpath(join(dirname, link))`; Datei oder `.md` muss existieren). Löst er nicht auf: Zeile unverändert lassen und melden.
- Defekte Pfadmuster vor und nach dem Lauf zählen (`../../X/../../`, `.md.md`). Steigt die Zahl: sofort aus der Sicherung zurücksetzen, nicht weiterreparieren.
- Pro Datei eine Sicherung anlegen, bevor geschrieben wird.
- Mehrfachverweise zusammenfassen: derselbe kaputte Name steht oft in 5–30 Wiki-Seiten. Eine Entscheidung pro Ziel, dann auf alle Vorkommen anwenden — nicht pro Einzelfall nachfragen, wenn die Zielentscheidung steht.
- Zielordner vor dem Mapping prüfen (`os.path.isdir`): Umlaut vs. ASCII (`Börse/` vs. `boerse/`), Tippfehler. Zieldatei existiert? Nicht raten, melden.
- Duplikate nur nach Inhaltsvergleich löschen (`cmp` oder Frontmatter-Vergleich), vorher Sicherung in den Scratch-Ordner. Gleicher Titel heißt nicht gleicher Inhalt.
- Beim Entfernen eines kaputten Wikilinks den Linktext als Klartext stehen lassen — nie die ganze Zeile löschen, sonst verschwinden Sätze mit echtem Inhalt.
- Ein Regex-Lauf über Dateien mit ungeschlossenen Wikilinks (`[[Name` ohne `]]`) kann Zeilen verstümmeln. Nach jedem Batch alle Dateien auf gültiges Frontmatter prüfen (genau ein Block zwischen `---`-Zeilen), nicht nur Wikilinks zählen.
- Bei Ordner-Umbenennung gilt dieselbe Regel für jede enthaltene Datei und jeden Verweis, auch Pfad-Teile in Frontmatter (`source:`) und Wikilinks mit Ordnernamen. Vorher zählen (wie viele Dateien verweisen auf den Ordnernamen), nachher denselben Zähler gegen Null prüfen; Dateizahl im Ordner vor/nach als Gegenprobe.

## Reihenfolge im Batch

1. Verweise sammeln und Entscheidung pro Ziel treffen.
2. Sicherung der betroffenen Dateien.
3. Alle Vorkommen in einem Batch umschreiben.
4. Zähler der defekten Muster vor/nach vergleichen.
5. Bei Regression: zurücksetzen und melden statt weiterschreiben.
