# Sortable Table Pattern für das Dashboard

Das Trading-Dashboard ist ein Single-File Python HTTP Server. Tabellen mit clientseitiger Sortierung zu erweitern folgt einem festen Pattern.

## Pattern: Sortierbare Tabelle hinzufügen

### Schritt 1: `data-sort-*` Attribute auf jede `<tr>`

Im Python-Code, der die Zeilen generiert, jedem `<tr>` ein Set von `data-sort-*` Attributen geben. Verwende numerische Werte für Zahlen, lowercase für Strings:

```python
for item in items:
    sort_name = item["name"].lower()
    sort_value = f"{item['value']:.2f}"  # numerisch
    rows += f"""
<tr data-sort-name="{sort_name}"
    data-sort-value="{sort_value}"
    data-sort-status="{status_idx}">
    <td>{item["name"]}</td>
    <td>{item["value"]}</td>
</tr>"""
```

**Regeln:**
- Numerische Spalten → numerische String-Werte (z.B. `"0.7500"`, `"-29.50"`)
- String-Spalten → lowercase (z.B. `"ohne aktien wird schwer"`)
- Status-Spalten → ordinale Zahlen (`active=0, probation=1, candidate=2, ...`)
- Datums-Spalten → ISO-String (YYYY-MM-DD), Strings vergleichen funktioniert

### Schritt 2: `<thead>`/`<tbody>` Struktur

Der Header gehört in `<thead>`, die Daten in `<tbody>` — sonst sortiert die JS-Funktion die Header-Zeile mit:

```html
<table class="src-sortable" id="yt-table">
    <thead>
        <tr>
            <th class="src-sort" data-sort="name">Name</th>
            <th class="src-sort" data-sort="value" style="text-align:center">Value</th>
        </tr>
    </thead>
    <tbody>
        {rows}
    </tbody>
</table>
```

Jeder `<th>` braucht:
- `class="src-sort"` — für CSS + JS-Selektor
- `data-sort="<key>"` — entspricht dem Suffix in `data-sort-<key>` auf den `<tr>`-Elementen

### Schritt 3: JavaScript (ans Ende der Seite, vor `</script>`)

```javascript
function srcSortTable(tableId) {
    var table = document.getElementById(tableId);
    if (!table) return;
    var tbody = table.querySelector('tbody') || table;
    var headers = table.querySelectorAll('.src-sort');
    var current = { key: null, dir: 'asc' };

    headers.forEach(function(th) {
        th.style.cursor = 'pointer';
        th.addEventListener('click', function() {
            var key = this.dataset.sort;
            if (current.key === key) {
                current.dir = current.dir === 'asc' ? 'desc' : 'asc';
            } else {
                current.key = key;
                current.dir = 'asc';
            }
            headers.forEach(function(h) { h.classList.remove('sort-asc', 'sort-desc'); });
            this.classList.add('sort-' + current.dir);

            var rows = Array.from(tbody.querySelectorAll('tr'));
            rows.sort(function(a, b) {
                var va = a.getAttribute('data-sort-' + key) || '';
                var vb = b.getAttribute('data-sort-' + key) || '';
                var na = parseFloat(va), nb = parseFloat(vb);
                if (!isNaN(na) && !isNaN(nb)) {
                    return (na - nb) * (current.dir === 'asc' ? 1 : -1);
                }
                return va.localeCompare(vb) * (current.dir === 'asc' ? 1 : -1);
            });
            rows.forEach(function(r) { tbody.appendChild(r); });
        });
    });
}
srcSortTable('yt-table');
```

Wichtig: die `{{ }}` müssen im Python-f-String ggf. als `{{` und `}}` escaped werden. Beispiel aus der Live-Datei:

```python
f"""
<script>
function srcSortTable(tableId) {{
    ...
    var current = {{ key: null, dir: 'asc' }};
    ...
}}
srcSortTable('yt-table');
</script>"""
```

### Schritt 4: CSS für Sortier-Indikatoren

```css
.src-sort { cursor: pointer; user-select: none; }
.src-sort:hover { background: #1e1e38; }
.src-sort.sort-asc::after { content: " ▲"; color: #00d4ff; font-size:0.7em; vertical-align:middle; }
.src-sort.sort-desc::after { content: " ▼"; color: #00d4ff; font-size:0.7em; vertical-align:middle; }
```

## Live-Beispiel: YouTube-Quellen-Tabelle (Sources-Tab)

Im Quellen-Tab gibt es aktuell (seit 07.07.2026) eine sortierbare Tabelle mit:

| Spalte | data-sort | Typ | Wertebereich |
|--------|-----------|-----|-------------|
| Status | `status` | ordinal (0-4) | active=0, probation=1, candidate=2, suspended=3, rejected=4 |
| Name | `name` | string | lowercase Channel-Name |
| Win Rate | `wr` | number | 0.0000 – 1.0000 |
| Ø PnL | `pnl` | number | negative/positive |
| Weight | `weight` | number | 0.0 – 3.0 |
| Grund | `grund` | string | rejection_reason (lowercase) |
| Mentions | `mentions` | number | Count |
| Letzter | `last` | string | ISO-Date (YYYY-MM-DD) |

Die Tabelle hat `id="yt-table"`, `<thead>` + `<tbody>`, und `class="src-sortable"`.