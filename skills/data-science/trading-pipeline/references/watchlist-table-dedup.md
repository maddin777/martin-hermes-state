# Watchlist-Table-Level Dedup

Nachdem `normalize_mentions()` die `watchlist_mentions`-Tabelle bereinigt hat, bleiben in der aggregierten `watchlist`-Tabelle oft Duplikate zurück (gleiche Firma, unterschiedliche Ticker/Schreibweisen). Diese werden nicht automatisch gemerged, weil `INSERT ... ON CONFLICT(name) DO NOTHING` Case-Varianten als verschiedene Einträge passieren lässt.

## ⚠️ ES GIBT ZWEI KOPIEN (beide patchen!)

| Kopie | Wer ruft sie auf? |
|-------|-------------------|
| `/root/.hermes/scripts/watchlist_dedup.py` | **Wöchentlicher Hermes-Cron** (`472ace6fe18a`, So 05:30) |
| `/root/.hermes/profiles/hermes_trading/skills/trading/scripts/watchlist_dedup.py` | **Nacht-Pipeline** `trading_pipeline.py` (03:30, Schritt "Watchlist Dedup" — lädt per `SCRIPTS_DIR`) |

**Falle vom 11.08.2026:** Nur die `/root/.hermes/scripts`-Kopie zu fixen reicht NICHT — die Nacht-Pipeline nutzt die Skill-Kopie. Wenn Duplikate trotz Dedup-Cron bestehen bleiben, IMMER beide Dateien prüfen und beide auf denselben Stand bringen. `grep -n "def dedup_ticker" /root/.hermes/scripts/watchlist_dedup.py /root/.hermes/profiles/hermes_trading/skills/trading/scripts/watchlist_dedup.py` zum Vergleich.

## Root-Causes: Warum Duplikate NIE gemerged wurden (11.08.2026)

Der Insights-Report meldete Unilever (UL/ULVR.L) + Eli Lilly (LLY/LLYCL.SN) 5 Tage lang als ungelöst. Fünf unabhängige Bugs:

1. **`dedup_name` lief nur bei `ticker IS NULL`** → Einträge MIT Ticker (Unilever, Lilly) wurden von der Name-Phase nie erfasst. Fix: alle `status IN ('watching','bought')` Einträge einbeziehen, mit UND ohne Ticker.
2. **`watchlist.id` ist oft NULL** → `UPDATE/DELETE ... WHERE id=?` matchte ins Leere. Nur der Drop der Nicht-Canonical-Zeile lief (der nutzte rowid bereits in der Skill-Kopie) → Ergebnis sah wie ein Merge aus, war aber nur ein Verlust. **Fix: `SELECT rowid, *` + `WHERE rowid=?` IMMER für watchlist-Schreibzugriffe.**
3. **`merge_group` setzte hardcoded `status='watching'`** → hätte echte Paper-Positionen (`bought`) zerstört. Fix: `if any(r["status"] == "bought" ...): merged_status="bought"`.
4. **Name-Vergleich case/&-sensitiv** → "ELI LILLY & COMPANY" ≠ "Eli Lilly and Company". Fix: `name_compare_key()` = lowercase + `&`→`and` + Stopword-Wegfall (`and|the|of|for|in|on|co|de|sa|plc`) + Suffix-Strip.
5. **Conviction wurde SUMMIERT statt MAX** → 0.62+0.76=1.38 (künstliche Verdopplung). Fix: Counts summen, `conviction_score(_bear/_aged)` als MAX.

Zusätzlich: ALL-CAPS-Namen gewannen die Canonical-Wahl → `_upper_ratio`-Penalty (×50) in `_name_score()`.

## Phasen (Stand 11.08.2026, beide Kopien)

1. **Ticker-Varianten** — bekannte Paare derselben Firma (UL↔ULVR.L, LLY↔LLYCL.SN, NVDA↔NVD.DE; `TICKER_GROUPS` in der scripts-Kopie, `_ticker_priority()` US>EU>LSE in der Skill-Kopie)
2. **Ticker-basiert** — gleicher Ticker → merge (`status IN ('watching','bought')`)
3. **Name-Fuzzy** — `name_compare_key()`-Gruppierung, Guard: Key < 5 Zeichen überspringen (False-Positive-Schutz)

Merge: canonical Name = `_name_score()` (min), Update über `rowid`, Conviction MAX, bought erhält Vorrang.

## Verifikation / Idempotenz

```bash
# Zweiter Lauf muss 0 Dropped zeigen (idempotent)
python3 /root/.hermes/scripts/watchlist_dedup.py

# Ergebnis prüfen: je Firma nur 1 aktiver Eintrag
cd /root/.hermes/profiles/hermes_trading/skills/trading
python3 -c "
import sqlite3; con = sqlite3.connect('data/trading.db'); con.row_factory = sqlite3.Row
for t in ['UL','ULVR.L','LLY','LLYCL.SN']:
    print([dict(r) for r in con.execute('SELECT name,ticker,status,conviction_score,mention_count FROM watchlist WHERE ticker=?', (t,))])
"
```

**Backup vor Dedup:** `cp data/trading.db data/trading.db.bak-$(date +%Y%m%d-%H%M%S)` — der erste (halb-fixe) Lauf am 11.08. droppte die falsche Zeile (LLY statt LLYCL.SN), weil canon_row über den falschen Namen ging. Restore + gefixtes Script = sauberer Zustand.

Danach Export neu bauen: `/root/.hermes/scripts/export_watchlist.sh` (aktualisiert `Trading/Watchlist.md` im Vault).

## Cron

- **Schedule**: Sonntags 05:30 (Cron-ID: `472ace6fe18a`)
- **Script**: `/root/.hermes/scripts/watchlist_dedup.py`
- Die Nacht-Pipeline ruft zusätzlich die Skill-Kopie auf (03:30)

## Bekannte Einschränkungen

- `canonical_tickers`-Tabelle (DB) erweitern für neue Cross-Listing-Paare: `INSERT INTO canonical_tickers (source_ticker, target_ticker, reason) VALUES ('ULVR.L','UL','Unilever: London → NYSE ADR')` — der Export merkt so auch neue Duplikate in der Ansicht.
- **HALO.L-Fall:** Ticker mit <200 Bars Historie (EMA200 nicht berechenbar) → `get_technical_score()` liefert None → DQ-Fall. Nicht mit Fake-Werten füllen; `status='removed'` + DQ-Note setzen (aus Filter-View aussortieren).