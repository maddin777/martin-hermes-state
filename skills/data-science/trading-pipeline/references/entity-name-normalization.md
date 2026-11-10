# Entity-Name-Normalisierung (Regex + Alias-Map)

Copy-paste-Quelle für Namens-Normalisierung in Watchlist/Mentions-Tabellen. Die
Layer-Reihenfolge (Bracket-Notes → Legal-Suffixe → "The"-Präfix → Whitespace → Alias) steht
in `SKILL.md`; hier die konkreten Muster und die Alias-Kategorien.

## Legal-Suffix-Regex

```python
import re

LEGAL_SUFFIX_RE = re.compile(
    r"(?:\s*[,/]\s*)?"
    r"(?:"
    r"AG(?:\s+&?\s*Co\.?\s*(?:KGaA|KG|OHG))?"
    r"|SE|GmbH(?:\s*&\s*Co\.?\s*(?:KG|KGaA|OHG))?"
    r"|PLC|plc|Inc\.|Inc|Corporation|Corp\.?|Corp"
    r"|Ltd\.?|Limited|LLC|LLP|LP|NV|N\.V\.|SA|S\.A\.|AB|OY"
    r"|S\.p\.A\.|Sp\.? z\.?o\.?o\.?|JSC|PJSC|OJSC"
    r"|Holdings?|Group|Co\.|Company"
    r"|Class\s+[ABCDE]|Common\s+Stock"
    r")(?:\.|\s)*$",
    re.IGNORECASE
)
```

## Bracket-Note-Regex

```python
BRACKET_NOTE_RE = re.compile(
    r"\s*\((?:nicht\s+börsennotiert|Marke\s+von[^)]*|privat[^)]*|Teil\s+von[^)]*)\)\s*$",
    re.IGNORECASE
)
```

## Pipeline

```python
def normalize_company_name(name):
    n = BRACKET_NOTE_RE.sub("", name.strip())
    n = re.sub(r"\s*\([^)]*[?][^)]*\)\s*$", " ", n)   # "(bei Do?)"-Notizen
    prev = None
    while prev != n:                                    # iterativ, nested Formen
        prev = n
        n = LEGAL_SUFFIX_RE.sub("", n).strip()
    n = re.sub(r"^The\s+", "", n)
    n = re.sub(r"\s+", " ", n).strip()
    return NORMALIZE_ALIASES.get(n.lower(), n)
```

## Alias-Kategorien (130+ Einträge)

**LLM-Typos:** `palantier`/`palanteer` → Palantir · `reinmetall`/`reimmetall` → Rheinmetall ·
`corweef` → CoreWeave · `nebiuz` → Nebius · `enhropic`/`entropic`/`anropic` → Anthropic ·
`tüssenkrup` → ThyssenKrupp · `morgen stanley` → Morgan Stanley · `rocketlab` → Rocket Lab ·
`soundhoundai` → SoundHound AI · `albe male` → Alphabet.

**Varianten → Kanonisch:** `meta platforms[ inc.][, inc.]` → Meta · `nvidia corporation/corp.` →
NVIDIA · `alphabet inc. (google)` → Alphabet · `micron technology` → Micron · `cerebras systems`
→ Cerebras · `take two interactive` → Take-Two Interactive · `d-wave systems` / `d w v quantum`
→ D-Wave Quantum · `jp morgan[ chase]` → JPMorgan · `goldman sachs group` → Goldman Sachs ·
`costco wholesale[ corporation]` → Costco · `amazon.com[ inc.]` → Amazon · `münchener rück` /
`munich re` → Münchner Rück · `mara holdings` / `marathon digital holdings inc.` → MARA ·
`united health` → UnitedHealth.

**Rechtsform → Kurzform:** `siemens ag`/`siemens aktiengesellschaft` → Siemens · `infineon
technologies ag` → Infineon · `basf se` → BASF · `deutsche bank ag` → Deutsche Bank · `dws group
gmbh & co. kgaa` → DWS · `henkel ag & co. kgaa` → Henkel · `cts eventim ag & co. kgaa` →
CTS Eventim · `palo alto networks` → Palo Alto · `linde plc` → Linde · `arm holdings plc` → ARM ·
`salesforce inc.` → Salesforce · `pepsico inc.` → PepsiCo.

**Case-Varianten:** `nvidia` → NVIDIA · `amd` → AMD · `ibm` → IBM · `intc` → Intel · `msft` →
Microsoft · `googl` → Alphabet.

## SQL-Merge mit UNIQUE-Konflikt

```python
for orig in originals:
    if orig == canonical:
        continue
    try:
        con.execute("UPDATE watchlist_mentions SET name=? WHERE name=?", (canonical, orig))
    except sqlite3.IntegrityError:
        # UNIQUE(name, video_id): dasselbe Video hat den kanonischen Namen schon
        con.execute(
            "DELETE FROM watchlist_mentions WHERE name=? AND name != ? AND EXISTS "
            "(SELECT 1 FROM watchlist_mentions AS w2 WHERE w2.name=? "
            "AND w2.video_id=watchlist_mentions.video_id)",
            (orig, canonical, canonical))
```

Besser als try/except: **vor** dem UPDATE löschen (`DELETE … WHERE EXISTS`), weil ein
Massen-UPDATE bei einem einzigen UNIQUE-Konflikt komplett fehlschlägt und dann gar keine Zeile
ändert.

## Watchlist-Reste

Nach der Mentions-Normalisierung bleiben alte Duplikat-Zeilen in der aggregierten `watchlist`.
Entweder der nächste Aggregations-Lauf räumt sie auf, oder gezielt:

```sql
UPDATE watchlist SET status='dropped'
WHERE name IN ('Meta Platforms', 'Alphabet Inc. (Google)', 'D-Wave Systems')
AND status='watching';
```

Für die Pipeline-Variante (Ticker-Varianten, Ticker, Name in drei Phasen) siehe
`watchlist-table-dedup.md` und `watchlist-dedup-ticker-priority.md`.
