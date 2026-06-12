# Closed-Loop Trading Architecture

Implementiert 11.06.2026. Drei Feedback-Loops.

## DB-Tabelle: `segment_performance`

```sql
CREATE TABLE IF NOT EXISTS segment_performance (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sector          TEXT NOT NULL,          -- Technology, Financials, ...
    conviction_tier TEXT NOT NULL,          -- HIGH / NORMAL / LOW
    tech_direction  TEXT NOT NULL,          -- LONG / SHORT
    regime_at_entry TEXT,                   -- bull / bear / sideways
    trades_total    INTEGER DEFAULT 0,
    trades_won      INTEGER DEFAULT 0,
    trades_lost     INTEGER DEFAULT 0,
    sum_pnl_eur     REAL DEFAULT 0.0,
    avg_pnl_pct     REAL DEFAULT 0.0,
    avg_holding_days REAL DEFAULT 0.0,
    win_rate        REAL DEFAULT 0.0,
    updated_at      TEXT,
    UNIQUE(sector, conviction_tier, tech_direction, regime_at_entry)
);
CREATE INDEX IF NOT EXISTS idx_segment_perf_lookup
    ON segment_performance(sector, conviction_tier, tech_direction);
```

## Loop 1: update_segment_performance()

**File:** `nightly_eval.py`
**Trigger:** Täglich 05:00 in `main()`
**Query:** Aggregiert alle geschlossenen `positions` mit `entry_conviction_score IS NOT NULL`

Conviction-Tier Logik:
- `entry_conviction_score >= 0.8` → HIGH
- `entry_conviction_score >= 0.6` → NORMAL
- sonst → LOW

Regime wird aus `regime_history` zum Entry-Datum geladen. Fallback: 'sideways'.

**INSERT/UPDATE:** `ON CONFLICT(sector, conviction_tier, tech_direction, regime_at_entry) DO UPDATE`

## Loop 2: calibrate_conviction()

**File:** `nightly_eval.py`
**Trigger:** Direkt nach `update_segment_performance()`
**Erwartete Win Rates pro Tier:**
- HIGH: ≥ 70%
- NORMAL: ≥ 55%
- LOW: ≥ 40%

**Ausgabe:**
```
📐 Conviction-Kalibrierung:
  ✅ HIGH: WR 72% (erwartet 70%, Δ+2%) | 8 Segmente | Ø +1.8%
  ⚠️ NORMAL: WR 45% (erwartet 55%, Δ-10%) → Prior erhöhen (konservativer) | 5 Segmente
  📈 LOW: WR 52% (erwartet 40%, Δ+12%) → Prior senken (aggressiver) | 3 Segmente
```

**Aktion bei Abweichung >10 Prozentpunkte:** Log-Hinweis (noch keine automatische Config-Änderung).

## Loop 3: check_segment_performance()

**File:** `signal_manager.py`
**Called from:** `open_new_positions()` → candidate loop, nach Earnings-Blackout-Check, vor Grok-Check

**Gate-Logik:**
```python
if row["trades_total"] < 3:
    return True, None                    # Zu wenig Daten → durchlassen
if win_rate < 0.30 and trades >= 5:
    return False, reason                 # Hartes Gate
if win_rate < 0.35 and avg_pnl < -3.0:
    return False, reason                 # Weiches Gate bei negativem PnL
return True, None                        # Fail open bei Exception
```

**SHORT-Kandidaten:** Nutzen `conviction_score` statt `conviction_score_bear` für tier-Berechnung (konservativer — Shorts haben selten hohe Werte).

## Verifikation

Nach erstem nightly_eval-Lauf:
```bash
sqlite3 /root/.hermes/profiles/hermes_trading/skills/trading/data/trading.db \
  "SELECT * FROM segment_performance ORDER BY trades_total DESC;"
```

Gate-Wirkung prüfen (nach Pipeline-Lauf):
```bash
grep "Pre-Entry\|Segment\|🚫\|check_segment_performance" \
  /root/.hermes/profiles/hermes_trading/skills/trading/data/cron.log | tail -10
```