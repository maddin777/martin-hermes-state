# Export Watchlist — Canonical Merge Sector Bug

## Symptom

In der exportierten Watchlist (`Watchlist.md`, `/root/obsidian-vault/Trading/Watchlist.md`) zeigt ein Ticker den Sector **"Other"**, obwohl die `companies`-Tabelle den korrekten Sektor (z.B. "Technology") hat.

**Betroffen:** Ticker mit Canonical-Merge (z.B. `ARMK→ARM`).

## Root Cause

`export_watchlist.py` macht einen `LEFT JOIN companies c ON c.ticker = w.ticker`.

- **Canonical Ticker (ARM):** `companies.ticker='ARM'` → findet `Technology`
- **Alias Ticker (ARMK):** `companies.ticker='ARMK'` → **nicht gefunden** → `COALESCE(c.sector, 'Other')` gibt `'Other'`

Dann merged der Code via `canonical_tickers`-Tabelle: `ARMK` + `ARM` → merged zu `ARM`.

**Das Problem:** Der Merge übernimmt blind die Daten des höheren Conviction-Scores:
```python
if current_conv > existing_conv:
    existing["company_sector"] = w["company_sector"]  # überschreibt Technology mit 'Other'
```

Da ARMK (neuer, daher höhere Conviction 1.0) vor ARM (älter, 0.883) kommt, gewinnt ARMK — und sein `'Other'` überschreibt `'Technology'`.

## Fix

In der Merge-Logik (`export_watchlist.py`, Zeile ~49-51): Sektor vom neuen Eintrag nur übernehmen wenn er **nicht 'Other'** ist, ODER der bestehende Sektor ebenfalls 'Other' ist:

```python
if current_conv > existing_conv:
    ...
    # Sektor vom Canonical-Ticker bevorzugen (Alias-Ticker wie ARMK
    # haben oft 'Other' weil nicht in companies-Tabelle)
    if w["company_sector"] != 'Other' or existing["company_sector"] == 'Other':
        existing["company_sector"] = w["company_sector"]
    ...
```

### Wirkung

- ARM (Technology) + ARMK (Other) → behält **Technology** ✅
- ARMK (Other) + ARM (Technology) → überschreibt mit **Technology** ✅
- Echter Unknown (Other) + anderer Unknown (Other) → bleibt **Other** (korrekt)
- Echter Unknown (Other) + bekannter Sektor → übernimmt **bekannten Sektor**

## Verifikation

```bash
cd /root/.hermes/profiles/hermes_trading/skills/trading
source venv/bin/activate
python3 scripts/export_watchlist.py
# Prüfen ob ARM jetzt Technology zeigt statt Other:
grep "ARM Holdings" /root/obsidian-vault/Trading/Watchlist.md
```

## Betroffene Ticker (identifiziert)

| Alias | Canonical | Reason | Fix-Status |
|-------|-----------|--------|------------|
| ARMK | ARM | ARM Holdings | ✅ Gefixt (23.06.) |
| YDX.MU | NBIS | Nebius | Nicht betroffen (NBIS existiert in companies) |
| 639.F | SPOT | Spotify | Nicht betroffen (SPOT existiert) |
| 6MK.F | MRK | Merck & Co | Nicht betroffen (MRK existiert) |

## Grundsätzliche Lehre

Immer wenn zwei Einträge per `canonical_tickers` gemerged werden und einer alias-basiert ist, hat der Alias potentiell keinen `companies`-Eintrag. Metadaten (Sektor, Branche) sollten **immer vom Canonical-Ticker** stammen, nicht vom Alias mit höherer Conviction.