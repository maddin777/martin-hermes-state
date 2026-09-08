# Sektor-abhängige Regime — Implementierungs-Referenz (07.09.2026)

Vollständige technische Details zur Sektor-Regime-Architektur. Die konzeptionelle
Zusammenfassung steht in `trading-pipeline/SKILL.md` → "🗂️ Sektor-abhängige Regime".

## Modul-Layout (WICHTIG — wo lebt was)

- **`config.py`** enthält die Sektor-Regime-*Helper*: `SECTOR_TO_ETF`, `sector_to_etf()`,
  `sector_regime_key(sector, industry)`, `get_sector_regime(sector, con)`,
  `init_sector_regimes_table(con)`, `PRECIOUS_METAL_INDUSTRIES`, `REGIME_ETF_UNIVERSE`.
- **`get_current_regime()` ist NICHT in config.py** — es lebt in `scripts/signal_manager.py`
  (Z.342) und `scripts/active_exit_check.py` (Z.36, eigene inline-Kopie zur Import-Entkopplung).
  `from config import get_current_regime` → **ImportError**. Fürs globale Regime immer
  `get_current_regime` aus `signal_manager` importieren.
- Nach dem Hinzufügen eines Helpers in `config.py` IMMER den Import in den Konsumenten
  (`signal_manager.py` Z.26, `active_exit_check.py` Z.26) ergänzen — sonst NameError.

## Tabelle `sector_regimes`

```sql
CREATE TABLE IF NOT EXISTS sector_regimes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sector TEXT NOT NULL,
    etf_ticker TEXT NOT NULL,
    regime TEXT NOT NULL,          -- bull | sideways | bear
    date TEXT NOT NULL,            -- YYYY-MM-DD
    ret_20d REAL,
    UNIQUE(sector, date)
)
```
Migration idempotent via `init_sector_regimes_table()` (CREATE IF NOT EXISTS).
`get_sector_regime(sector, con)` liest neuesten Eintrag je sector, Fallback `"sideways"`.

## Sektor→ETF-Map + Edelmetall-Sonderfall

`SECTOR_TO_ETF`: Tech=XLK, Comm=XLC, ConsumerCyclical=XLY, ConsumerDefensive=XLP,
Healthcare=XLV, FinancialServices=XLF, Energy=XLE, Industrials=XLI, BasicMaterials=XLB,
Utilities=XLU, RealEstate=XLRE. Fallback `"SPY"`.

**Edelmetall-Lücke (war der kritische Feinschliff):** yfinance-`companies`-Sektor für
Gold-Minen ist `"Basic Materials"`, NICHT `"Basic Materials (Gold)"`. `XLB` wäre der falsche
Regime-Proxy (Chemie/Stahl). `sector_regime_key(sector, industry)` mappt
`Basic Materials` + Edelmetall-Industries (Gold/Silver/Other Precious Metals & Mining/…)
→ `"Basic Materials (Gold)"`, wo fundamental_data das `GDX`-Regime speichert.
```python
sector_regime_key("Basic Materials", "Gold")     -> "Basic Materials (Gold)"  # → GDX
sector_regime_key("Basic Materials", "Chemicals")-> "Basic Materials"          # → XLB
```

## detect_market_regime-Erweiterung (fundamental_data.py)

Nach dem `regime_history`-INSERT wird je Sektor-ETF (gleiche Z-Score-Methode wie SPY/DAX)
ein Regime berechnet und in `sector_regimes` geschrieben. Download-Universum:
`set(SECTOR_TO_ETF.values()) | {"GDX", "SPY"}` — GDX ist NICHT in der Map (nur Sonderfall),
deshalb explizit zum Download hinzufügen, sonst schlägt der GDX-Zweig leise fehl.
Makro-Overlay (VIX/HYG/DXY) wird als Nudge auf die Sektor-Regime angewendet.

## Hybrid-Umsetzung (signal_manager + active_exit_check)

| Sektor-Regime | LONG | SHORT |
|---------------|------|-------|
| bull | volle Größe | kein Short |
| sideways | 50% Size (`sector_size_factor=0.5`) | 50% Size |
| bear | kein Long (geblockt) | erlaubt |

- **Entry (`open_new_positions`):** `ticker_sector` wird je Kandidat aus
  `companies` geladen (`SELECT sector, industry`), `regime_key = sector_regime_key(...)`,
  `sector_regime = get_sector_regime(regime_key, con)`. bear-Long → skip + blocked_entries-Log
  mit gate `"sector-regime-bear"`. sideways → `sector_size_factor=0.5`.
  WICHTIG: `sector_size_factor` wird im Sizing-Block (Zeile ~2015) via
  `if sector_size_factor < 1.0: pct *= sector_size_factor` angewendet.
- **Sizing SL-Multiplikator** nutzt das Sektor-Regime statt global (`regime=sector_regime`).
- **Exit (`active_exit_check` + `check_open_positions` in signal_manager):** get_exit_config
  bekommt `regime=pos_regime` (Sektor-Regime der Position, Fallback global).
  Beide Pfade müssen identisch patcht werden — das ist der bekannte Parallele-Pfade-Risiko-Punkt.

## Verifikations-Rezept

```python
from config import get_sector_regime, sector_regime_key, db_connect
con = db_connect()
print(get_sector_regime("Energy", con))            # bull
print(get_sector_regime("Basic Materials (Gold)", con))  # bull (GDX)
sector_regime_key("Basic Materials", "Gold")       # "Basic Materials (Gold)"
```
Gold-Mine (industry=Gold) → GDX bull = volle LONG-Größe; Chemie in Basic Materials → XLB
sideways = 50%. Live-Stand 07.09.: SPY=sideways (−0.4%), Energy(XLE)=bull (+11.4%),
Gold(GDX)=bull (+10.4%), Healthcare(XLV)=bull.