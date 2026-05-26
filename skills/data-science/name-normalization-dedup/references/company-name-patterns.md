# Company Name Normalization Reference

Concrete regex patterns and alias entries from the Hermes Trading watchlist cleanup (May 2026). Use as copy-paste source for new implementations.

## Legal Suffix Regex

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

## Bracket Notes Regex

```python
BRACKET_NOTE_RE = re.compile(
    r"\s*\((?:nicht\s+börsennotiert|Marke\s+von[^)]*|privat[^)]*|Teil\s+von[^)]*)\)\s*$",
    re.IGNORECASE
)
```

## Normalize Pipeline

```python
def normalize_company_name(name):
    n = name.strip()
    n = BRACKET_NOTE_RE.sub("", n)
    # 'bei Do?' style question marks in bracketed notes
    n = re.sub(r"\s*\([^)]*[?][^)]*\)\s*$", " ", n)
    # Iterative suffix stripping
    prev = None
    while prev != n:
        prev = n
        n = LEGAL_SUFFIX_RE.sub("", n).strip()
    n = re.sub(r"^The\s+", "", n)
    n = re.sub(r"\s+", " ", n).strip()
    lower = n.lower()
    if lower in NORMALIZE_ALIASES:
        return NORMALIZE_ALIASES[lower]
    return n
```

## Alias Map Categories (130+ entries)

### LLM Typos
```
palantier/palanteer       → Palantir
reinmetall/reimmetall     → Rheinmetall
corweef                   → CoreWeave
nebiuz                    → Nebius
enhropic/entropic/anropic → Anthropic
tüssenkrup/tüssengrup     → ThyssenKrupp
morgen stanley            → Morgan Stanley
rocketlab                 → Rocket Lab
soundhoundai/soundhound   → SoundHound AI
albe male                 → Alphabet
```

### Name Variants → Canonical
```
meta platforms / meta platforms inc. / meta platforms, inc. → Meta
nvidia corporation / nvidia corp.                           → NVIDIA
alphabet inc. / alphabet inc. (google)                      → Alphabet
micron technology                                           → Micron
intel corporation                                           → Intel
cerebras systems / cerebras systems inc.                    → Cerebras
take two interactive                                        → Take-Two Interactive
d-wave systems / d-wave systems inc. / d w v quantum       → D-Wave Quantum
jp morgan / jp morgan chase                                 → JPMorgan
goldman sachs group                                         → Goldman Sachs
berkshire hathaway inc.                                     → Berkshire Hathaway
costco wholesale / costco wholesale corporation             → Costco
amazon.com / amazon.com inc.                                → Amazon
münchener rück / munich re                                  → Münchner Rück
mara holdings / marathon digital holdings inc.              → MARA
united health                                               → UnitedHealth
```

### Legal Entity → Simple
```
siemens ag / siemens aktiengesellschaft  → Siemens
infineon technologies ag                 → Infineon
basf se                                   → BASF
deutsche bank ag                          → Deutsche Bank
commerzbank ag                            → Commerzbank
dws group gmbh & co. kgaa                → DWS
henkel ag & co. kgaa                      → Henkel
cts eventim ag & co. kgaa                → CTS Eventim
palo alto networks                        → Palo Alto
linde plc                                 → Linde
arm holdings plc                          → ARM
walmart inc.                              → Walmart
salesforce inc.                           → Salesforce
pepsico inc.                              → PepsiCo
```

### Case Variants
```
nvidia → NVIDIA
amd    → AMD
ibm    → IBM
cisco  → Cisco
intc   → Intel
msft   → Microsoft
googl  → Alphabet
```

## SQL Merge with UNIQUE Handling

```python
for orig in originals:
    if orig == canonical:
        continue
    try:
        con.execute(
            "UPDATE watchlist_mentions SET name=? WHERE name=?",
            (canonical, orig)
        )
        merged += 1
    except sqlite3.IntegrityError:
        # UNIQUE(name, video_id) conflict — same video already has canonical
        # Delete the now-redundant duplicate row
        deleted = con.execute(
            "DELETE FROM watchlist_mentions WHERE name=? AND "
            "name != ? AND EXISTS (SELECT 1 FROM watchlist_mentions AS w2 "
            "WHERE w2.name=? AND w2.video_id=watchlist_mentions.video_id)",
            (orig, canonical, canonical)
        ).rowcount
        if deleted:
            merged += 1
```

## Watchlist Stale Entry Cleanup

After normalizing the mentions table, old duplicate rows in the aggregated watchlist table remain. Clean them up:

```sql
UPDATE watchlist SET status='dropped'
WHERE name IN ('Meta Platforms', 'Alphabet Inc. (Google)', 'D-Wave Systems', '...')
AND status='watching';
```

Or just run the next full aggregation — old entries get updated/overwritten by the GROUP BY name query.