# UK-Microcap-Gate (.L Datenqualität) — 14.08.2026

## Problem-Symptom
RSS-Quelle `share talk` spülte UK-AIM/Nano-Caps (AET.L, BSFA.L, HREE.L, KZG.L, SHOE.L, MAC.L, AMRQ.L, SNDA.L …) in die `watchlist`. In der Watchlist-Pflege (vault-insights/export) tauchten sie als **DQ-Fälle** auf: `conviction_score ≈ 0.76` aber `tech_score`/`tech_direction` leer (`–`). Ihre Konviction konnte theoretisch in die Entry-Pipeline rutschen und verpestete die Conviction-Verteilung.

## Warum ein reiner Bar-Count-Gate scheitert
`get_technical_score()` verlangt bereits `len(df) >= 50` und berechnet `ema200` (≈ 200 Bars) — ein Ticker OHNE 200 Bars liefert ohnehin `None`. Ein UK-Nano-Cap MIT 200+ Bars bekam also trotzdem einen Score, obwohl es als AIM-Microcap praktisch unhandelbar ist. **Der eigentliche Differenzierer ist Tagesumsatz (Turnover), nicht Bar-Anzahl.**

## Implementierter Fix (utils.py, einzige Quelle get_technical_score)
```python
UK_MIN_BARS         = 200      # ~1 Jahr Handelstage
UK_MIN_TURNOVER_EUR = 500_000  # konsistent mit signal_manager min_liquidity_eur
```
```python
_, _, df = get_price_data_cached(ticker)
if df is None or df.empty or len(df) < 50:
    return None
if str(ticker).endswith(".L"):
    if len(df) < UK_MIN_BARS:
        return None
    _c = df["Close"].iloc[:,0] if df["Close"].ndim > 1 else df["Close"]
    _v = df["Volume"].iloc[:,0] if df["Volume"].ndim > 1 else df["Volume"]
    _turnover = turnover_to_eur(float(_c.tail(20).mean()), float(_v.tail(20).mean()), ticker)
    if _turnover < UK_MIN_TURNOVER_EUR:
        return None
```
Kein Extra-Netzwerk-Call: der Turnover wird aus dem bereits geladenen `df` berechnet (TTL-Cache von `get_price_data_cached`). `turnover_to_eur` berücksichtigt GBp (÷100) + FX über `price_to_eur`.

Kein Score → kein `tech_score`/`tech_direction` in der Watchlist → `signal_manager`-Entry-Queries (`tech_score >= threshold` + `tech_direction='LONG/SHORT'`) finden den Kandidaten nicht.

## Verifikations-Rezept (Live-Daten, 14.08.)
```python
import sys; sys.path.insert(0, ".")
import env_loader
from utils import get_technical_score
for t in ["AET.L","BSFA.L","HREE.L","KZG.L","SHOE.L","MAC.L","GLEN.L","AV.L","TSCO.L","ULVR.L","VOD.L","BARC.L","BP.L","ANTO.L"]:
    r = get_technical_score(t)
    print(f"{t:8} -> " + ("None (geblockt)" if r is None else f"conf={r['confidence']} dir={r['direction']}"))
```
- Geblockt (AIM-Microcaps): AET, BSFA, HREE, KZG, SHOE, MAC, SNDA, 0UKI, ECR, FCM, POLB, FMET, BOOM, KEN, ORCP, TYM, HDD, ORR, HVO, SOU, TEK
- Durchgelassen (liquide Large-Caps korrekt): GLEN, AV, TSCO, ULVR, VOD, BARC, BP, ANTO, ATYM, KGF, HSX, WISE, TATE, LGEN, RSW, FRAS
- AMRQ.L (Amaroq) bleibt drauf — echtes, liquides Minen-Listing, kein Fehlverhalten.

## Gotcha: refresh_tech_scores.py leert keine veralteten Scores
`refresh_tech_scores.py` macht `if tech: UPDATE watchlist SET tech_score=?, tech_direction=?`. Wenn `get_technical_score` jetzt `None` liefert, bleibt der ALTE (vor-Gate-)Score stehen → der Microcap sähe weiter entry-fähig aus. **Manuell clearen:**
```python
from utils import get_technical_score
from config import db_connect
con = db_connect()
for r in con.execute("SELECT ticker FROM watchlist WHERE ticker LIKE '%.L' AND tech_score IS NOT NULL").fetchall():
    t = r["ticker"]
    if get_technical_score(t) is None:
        con.execute("UPDATE watchlist SET tech_score=NULL, tech_direction=NULL, weekly_trend=NULL WHERE ticker=?", (t,))
        con.commit()
```

## Bedien-/Ops-Hinweis
- Gate wirkt automatisch beim nächsten `technical_validator.py` / `watchlist_manager.py` / `refresh_tech_scores.py`-Lauf. Kein Cron-Neustart.
- Nicht-`.L`-Ticker sind unberührt (keine Kollateral-Effekte auf US/EU-Namen).
- `signal_manager` hatte historisch **0** Paper-Entries gegen jegliche `.L`-Ticker — die Entry-Gates (tech + `passes_liquidity_filter` ≥500k€) schützten bereits; das Gate schließt das DQ / Conviction-Pollution-Loch davor.
- Schwelle justierbar über `UK_MIN_TURNOVER_EUR` in `utils.py`; 500k€ = konsistent mit `signal_manager` `min_liquidity_eur`.

## Folge-Fix 16.08.: DQ-Isolation im Export + Alarm-Crons
Das Gate blockt neue Scores, aber Bestands-`.L`-Einträge (mit NULL tech_score) blieben in der Conviction-Watchlist und zählten im Export-Filter-View als echte Signale → verzerrten Sektor/SHORT/`–`-Statistik. Vault-insights meldete DQ-Wachstum 1→8→14.

**Fixes (16.08.):**
1. **`export_watchlist.py`** — DQ-Isolation: `.L`-Ticker ohne tech_score werden vor der Statistik in einen separaten `## ⚠️ DQ (Data Quality)`-Block ausgelagert. Zählen nicht in Gesamt/≥76%/Sektor/SHORT.
2. **`refresh_tech_scores.py`** — cleart veraltete Scores jetzt (der frühere `if tech:`-Guard ließ sie stehen). Doku-Gotcha behoben.
3. **`dq_alarm.py`** (Cron `37d505cbc47b`, Mo–Fr 22:40, Wrapper `~/.hermes/scripts/dq_alarm.sh`) — Regressions-Watchdog: zählt `.L`-Microcaps ohne tech_score (≥76%), Alarm bei Überschreiten von Schwelle 10 ODER Anstieg über Schwelle; State-File `data/dq_alarm_state.txt`. Silent bei stabil.
4. **`weekly_exit_review.py`** (Cron `310dfa0df1a6`, So 07:00, Wrapper `~/.hermes/scripts/weekly_exit_review.sh`) — offene Positionen vs `get_exit_config`-Matrix + Config-Drift-Check.
5. **`active_exit_check.py`** — auf `get_exit_config()` umgestellt (Regression-Drift-Fix): vorher nutzte es Legacy `get_asset_multipliers`, STANDARD trailing_step=0.5× vs Matrix step=0.75×. Jetzt konsistent zu signal_manager. `get_current_regime` inline (kein signal_manager-Import).
6. **`signal_manager.py`** — `compute_sl_tp` (Entry-SL/TP) + Partial-TP (`partial_atr`) + Sizing (`sl`) auf `get_exit_config` umgestellt, `regime`-Parameter durchgereicht. Entry-SL/TP sind damit **regime-abhängig** (STANDARD bull tp=3.5× vs sideways 2.5×) — konsistent zum Exit. Toter `mult`-Rest entfernt, Legacy-Import entfernt.
7. **`crabel_shadow_eval.py`** — `simulate_forward` auf Matrix umgestellt (`step`/`sl`/`profit_lock_atr` statt Legacy + cfg-Fallback Default 2.0 → Matrix 1.0). `_get_regime` inline, Regime in main einmal geholt. Shadow- und Live-Pfad teilen dieselbe Formel (DRY-Docstring).

**Weekly-Review-Drift-Check (16.08.)** prüft alle drei Pfade (signal_manager, active_exit_check, crabel_shadow_eval) auf echte Legacy-Aufrufe `get_asset_multipliers(` — schlägt Alarm falls jemand still zurückfällt.

**Verifiziert 16.08.:** 11 `.L`-Microcaps aussortiert, liquide Large-Caps (ANTO/GLEN/AV/TSCO) bleiben Signale; DQ-Alarm feuert nur bei Regression; alle 3 Exit-/Entry-/Shadow-Pfade nutzen get_exit_config (kein Legacy-Drift); compute_sl_tp liefert matrix-konsistente SL/TP (Regime bull STANDARD tp=3.5×).

## WICHTIG — Gate blockt, aber Einträge AKKUMULIEREN (Root-Cause-Fix 19.08.)
**Der 16.08.-Fix (DQ-Isolation im Export) war ein Symptom-Band-Aid.** Das Gate blockt zwar korrekt neue tech_scores, aber die Bestands-`.L`-Einträge bleiben als `watching` mit hoher Conviction dauerhaft in der DB: `last_seen` bleibt durch tägliche RSS-Zuflüsse frisch → die 60d-Stale-Regel des Cleanup greift NIE → DQ akkumuliert (1→8→14→17).

**Echte Root-Cause:** In der Praxis kam **100% der DQ-Akkumulation aus EINER Quelle** (`rss:share talk`, weight 0.5, probation): 67 von 81 Share-Talk-Einträgen sind `.L`-Nano-Caps, und `signal_manager` hat **nie** eine `.L`-Position eröffnet (0 Trades) — die Quelle ist fürs System faktisch wertlos, wird aber weiter gescannt.

**Fix (19.08.):**
1. `~/.hermes/scripts/watchlist_cleanup.py` — neue Stufe 1b: `.L`-Ticker ohne tech_score (status `watching`) → `status='dropped', notes='no-liquidity-gate'`. Bought-Positionen werden NICHT angefasst. Gedroppte wandern konservativ erst nach 180d ins Archiv (kein Datenverlust, rowid-Regel beachten).
2. Cron `7e364ce47b69` (`watchlist-cleanup-daily`) — von wöchentlich (So 07:30) auf **Mo–Fr 22:30** umgestellt: nach dem Export (22:15), vor dem DQ-Alarm (22:40). **Wöchentlich reicht NICHT** — die Quelle speist täglich nach, sonst kehrt die Akkumulation zurück.
3. DQ-Alarm `dq_alarm.py` (Schwelle 10) bleibt als Regressions-Watchdog.

**Verifiziert 19.08. live:** DQ-Count vorher 17 (über Schwelle) → nachher 0. 34 `.L` gedroppt, `--apply`-Pfad sauber (7 Artefakte archiviert, keine Fehler). Changelog-Eintrag in `Erklaerung.md` ergänzt.

**Lehre:** Bei DQ-Wachstum nicht nur das Gate prüfen — prüfen ob die Einträge AKTUALISIERT/aufgeräumt werden. Ein Filter der "nicht als Signal zählt" verhindert keine DB-Akkumulation. Gegenfrage: welche einzelne Quelle spült das Rauschen rein → ggf. penalisieren/deaktivieren.

## Quelle-Deaktivierung bei 0% Erfolgsquote (19.08.) — das Entscheidungsmuster

Nach dem Cleanup-Fix bleibt die Frage: **soll die rausch-erzeugende Quelle bleiben?** Antwort bei einer Quelle die NUR non-tradable Output liefert: **nein — an der Wurzel deaktivieren, nicht nur downstream filtern.**

**Erfolgsquote in `source_registry` prüfen (nicht raten):**
```sql
SELECT display_name, status, weight, enabled, total_bought,
       win_rate_alltime, win_rate_90d, avg_pnl_per_trade, total_wins, total_losses
FROM source_registry WHERE id=<id>;
```
**Trennung von Trade-Beitrag vs. bloßer Erwähnung:** Eine Position deren Ticker irgendwo von der Quelle erwähnt wurde (JOIN auf `channels LIKE '%<quelle>%'`) ist KEIN Quellen-Trade — Large-Caps (AAPL, VOD) kommen aus Dutzenden Quellen. Der echte Beitrag ist `total_bought`/`total_wins` aus der `source_registry`-Zeile der Quelle selbst. (Schema vorher mit `PRAGMA table_info(source_registry)` prüfen — nicht alle Spalten existieren immer.)

**Befund Share Talk (19.08., live):** `total_mentions=0, total_bought=0, win_rate=0.0, avg_pnl=0.0` über den ganzen Lebenszyklus (seit 07.06.) → **0% Erfolgsquote**, liefert zu 83% non-tradable `.L`-Microcaps. Kein einziger Trade je generiert.

**Fix (reversibel):**
```sql
UPDATE source_registry
SET enabled=0, status='removed',
    rejection_reason='0% Erfolgsquote: 0 Trades seit <datum>, 83% non-tradable .L-Microcaps, Quelle der DQ-Akkumulation'
WHERE id=<id>;
```
Scan läuft nur für `enabled=1` → stoppt den neuen Zufluss an der Wurzel. Reversibel in der DB (kein Löschen). Der Cleanup-Fix bleibt als Sicherheitsnetz für ANDERE Quellen, die ebenfalls `.L`-Caps liefern können (z.B. `rss:the motley fool uk`, `rss:seeking alpha`).

**Abwägung vs. Source-Lifecycle-Prinzip (07.07.):** Das 07.07.-Prinzip sagt "lieber penalisieren (weight=0.3) als komplett rausschmeissen" für schlechte Performance. ABER: eine Quelle mit **0 Trades über den ganzen Lebenszyklus** UND die Wurzel einer bekannten Datenqualitäts-Akkumulation ist kein "schlechter Performer" — sie ist ein reiner Rauschen-Produzent ohne je einen verwertbaren Beitrag. Martin bestätigt explizit: bei 0%-Quote entfernen. Deaktivieren (enabled=0) statt Löschen respektiert beides — reversibel, aber gestoppt.
