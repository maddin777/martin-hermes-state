# Änderungshistorie — Trading Skill

**Stand:** Paketen A–D + Sprints 1–7 + Bugfix-Sprint + Screener-Source + Watchlist-Performance-Fix + Rollen-Sprint R1–R4 + **Turtle-Konfluenz-Sprint** + **Phase 1+2 Fix (09.08.2026)** + **Watchlist-Cleanup-Archivierung (09.08.2026)** + **UK-Microcap-Gate (14.08.2026)** + **DQ-Isolation + Alarm-Crons (16.08.2026)** + **Drawdown-15-25-Zone auf 6 Pos (17.08.2026)** + **DQ-.L-Aufräumung im Cleanup + täglicher Cleanup (19.08.2026)**

## 19.08.2026 — DQ-.L-Aufräumung in watchlist_cleanup + Cleanup täglich

### Problem
Der UK-Liquidity-Gate (14.08.) blockierte korrekt neue tech_scores für `.L`-AIM/Nano-Caps, aber die Bestands-Einträge blieben als `watching` mit hoher Conviction dauerhaft in der DB (last_seen bleibt durch tägliche RSS-Zuflüsse frisch → 60d-Stale-Regel greift nie). DQ akkumulierte 1→8→14→17. Allein die Quelle **`rss:share talk`** lieferte **100% der DQ-Fälle** (67 von 81 Share-Talk-Einträgen sind `.L`), obwohl `signal_manager` **nie** eine `.L`-Position eröffnet hat (0 Trades) — die Quelle ist für das System faktisch wertlos.

### Fix
1. **`~/.hermes/scripts/watchlist_cleanup.py`** — neue Stufe 1b: `.L`-Ticker ohne tech_score (status `watching`) werden sofort auf `status='dropped', notes='no-liquidity-gate'` gesetzt. Bought-Positionen werden NICHT angefasst. Gedroppte wandern konservativ erst nach 180d ins Archiv (kein Datenverlust).
2. **Cron `7e364ce47b69`** (Name jetzt `watchlist-cleanup-daily`) — von wöchentlich (So 07:30) auf **Mo–Fr 22:30** umgestellt: nach dem Export (22:15), vor dem DQ-Alarm (22:40). Verhindert Akkumulation statt sie wöchentlich einmal zu räumen.

### Verifikation (19.08., Live-DB)
- DQ-Count vorher **17** (über Schwelle 10) → nachher **0**
- 34 `.L`-Einträge auf `dropped/no-liquidity-gate` gesetzt, davon 33 als Restbestand, keiner als bought
- `--apply`-Pfad sauber: 7 Artefakte archiviert, keine Fehler

### Hinweis
Die Quelle `rss:share talk` (weight 0.5, probation) bleibt aktiv und speist weiter neue `.L`-Caps ein — der Cleanup räumt sie jetzt täglich weg. Falls die Quelle langfristig nur Rauschen liefert, sollte sie auf `enabled=0`/`removed` geprüft werden (Source-Lifecycle 07.07.-Prinzip: lieber penalisieren als komplett rausschmeissen — aktuell nicht angefasst).

## 19.08.2026 — Quelle `rss:share talk` DEAKTIVIERT (0% Erfolgsquote)

### Hintergrund
Ergänzung zum DQ-Cleanup-Fix. Verifiziert am 19.08.: Die Quelle Share Talk (source_registry id=55, `https://www.share-talk.com/feed/`) hat über ihren gesamten Lebenszyklus (seit 07.06.) **keinen einzigen Trade generiert** — `total_mentions=0`, `total_bought=0`, `win_rate=0.0`, `avg_pnl_per_trade=0.0`. Sie lieferte 83% non-tradable `.L`-Microcaps und war damit die Wurzel der DQ-Akkumulation (1→8→14→17).

### Fix
`UPDATE source_registry SET enabled=0, status='removed', rejection_reason='0% Erfolgsquote ...' WHERE id=55;` — reversibel in der DB.

### Wirkung
- Stoppt den neuen `.L`-Zufluss an der Wurzel (Scan nur für enabled=1)
- Der watchlist-cleanup-Fix (19.08.) bleibt als Sicherheitsnetz für andere Quellen, die `.L`-Caps liefern (motley fool uk, seeking alpha)
- Cron `53f222b00811` (vault-insights-daily) Prompt nachgeschärft: SHORT sentiment-basiert zählen (bear>long), tech_direction=SHORT bei bought-LONG-Positionen NICHT als neue Bärenwelle darstellen; DQ-Zufluss aus anderen Quellen überwachen



## 17.08.2026 — Drawdown 15-25%-Zone: max_positions 4 → 6

### Problem
Hohe Cashquote (74.7%) trotz Bull-Regime + kein Cooldown. Grund: Portfolio lag bei **-18.5% Drawdown** vom ATH → die 15-25%-Bremszone setzte `max_positions: 4` (aus `check_drawdown()`). Da bereits 4 Positionen offen waren, wurden ALLE neuen Entries mit "Max. Positionen (4) erreicht" geblockt — obwohl 53 Watchlist-Kandidaten investierbar waren und `max_positions` global bei 8 liegt.

### Fix
In `check_drawdown()` (signal_manager.py): 15-25%-Zone `max_positions` von **4 → 6**. Size-Faktor 0.50 + min_confidence 0.80 bleiben unverändert (graduierte Bremse intakt) — es werden nur mehr Slots freigegeben, damit bei -18.5% wieder 2 zusätzliche Trades möglich sind.

### Drawdown-Matrix (aktuell)
| Drawdown | Size | Conf | Max Pos | Wirkung |
|----------|------|------|---------|---------|
| < 12% | 100% | 70% | 8 | Normalbetrieb |
| 12-15% | 75% | 75% | 6 | Warnzone |
| 15-25% | 50% | 80% | **6** (war 4) | Bremszone, aber handlungsfähig |
| ≥ 25% | close_all | 100% | 0 | Notbremse + 7d Cooldown |

### Verifiziert
`check_drawdown()` live bei -18.5% → Size 50%, Conf 80%, MaxPos 6. Syntax OK.

## 16.08.2026 — DQ-Isolation (Export) + DQ-Regressions-Alarm + Weekly-Exit-Review

### Problem
Der vault-insights-daily meldete drei Nächte in Folge DQ-Wachstum (1 → 8 → 14). `.L`-Microcaps (AIM/Nano-Caps) landeten über `rss:share talk` in der Conviction-Watchlist (≥76%) OHNE Tech-Score (der UK-Liquidity-Gate vom 14.08. blockt ihren Score). Sie wurden im Export-Filter-View als normale Signale gezählt und verzerrten Sektor-Verteilung, SHORT-Anteil und das `max 3 pro Sektor`-Constraint.

### Lösung
1. **`export_watchlist.py` — DQ-Isolation:** `.L`-Ticker mit fehlendem Tech-Score werden vor der Statistik-Berechnung in einen separaten **DQ-Block** ausgelagert. Sie zählen NICHT mehr in Gesamt/≥76%/Sektor/SHORT-Statistik und sind keine Entry-Kandidaten. Verifiziert: 11 DQ-Microcaps aussortiert, liquide `.L`-Large-Caps (ANTO, GLEN, AV, TSCO) bleiben korrekt als Signale.
2. **`refresh_tech_scores.py` — veraltete Scores clearen:** Wenn `get_technical_score` jetzt `None` liefert (Gate blockt), wird der ALTE Score `NULL` gesetzt (vorher blieb er stehen → Eintrag sah entry-fähig aus). Doku-Gotcha vom 14.08. behoben.
3. **`dq_alarm.py` (neu) + Cron `dq-alarm-daily` (37d505cbc47b, Mo–Fr 22:40, no_agent):** Watchdog zählt `.L`-Microcaps ohne Tech-Score (≥76%). Alarm NUR bei Regression (Schwelle überschritten ODER Anstieg über Schwelle), silent bei stabil. State-File `data/dq_alarm_state.txt`. Schwelle 10.
4. **`weekly_exit_review.py` (neu) + Cron `weekly-exit-review` (310dfa0df1a6, So 07:00, no_agent):** Offene Positionen vs Exit-Matrix (`get_exit_config`). Prämisse des Insights korrigiert: **0 offene Shorts** (alle 4 offenen = LONG). Zusätzlich Config-Drift-Check zwischen `get_exit_config` und `get_asset_multipliers`.

### ✅ Fix: Config-Drift `trailing_step` STANDARD (behoben 16.08.)
`active_exit_check.py` las den Trailing-Step aus **`get_asset_multipliers` (Legacy)**, wo `STANDARD.trailing_step = 0.5` steht — die Exit-Matrix `get_exit_config` hat `step = 0.75`. Das war exakt das 09.08.-Parallele-Pfad-Muster (signal_manager nutzte bereits get_exit_config, active_exit_check nicht). **Behoben:** `active_exit_check.py` auf `get_exit_config(asset_type, regime)` umgestellt — Regime wird einmal geladen (`get_current_regime` inline), `pos_mult` = Exit-Matrix. Key-Mapping `trailing_step`→`step`, `atr_sl`→`sl`. Verifiziert: STANDARD step jetzt 0.75 (vorher 0.5).

### ✅ Fix: signal_manager + crabel_shadow_eval auf get_exit_config (16.08.)
Der Weekly-Review deckte zusätzlich auf, dass der Skill seit 09.08. behauptete, signal_manager nutze get_exit_config — real nutzte es `get_asset_multipliers` an 4 Stellen. **Komplett migriert:**
- **`signal_manager.py`:** `compute_sl_tp` (Entry-SL/TP) bekommt `regime`-Parameter und nutzt die Matrix (`ec["sl"]`, `ec["tp"]`). Beide Aufrufer (log_blocked_entry, open_new_positions) reichen Regime durch. Zeile 741 Partial-TP `pos_mult` → Matrix (`partial_atr`). Zeile 1921 Sizing `sl_multiplier` → Matrix `["sl"]`. Toter `mult` (1960) entfernt. Import `get_asset_multipliers` entfernt.
- **`crabel_shadow_eval.py`:** `simulate_forward` nutzt Matrix (`step`, `sl`, `profit_lock_atr`) statt Legacy + cfg-Fallback (Default 2.0 → Matrix 1.0). `_get_regime` inline, Regime in main einmal geholt.
- **Wichtig:** Entry-SL/TP («compute_sl_tp») sind jetzt **regime-abhängig** (z.B. STANDARD bull tp=3.5× vs sideways 2.5×) — konsistent zu active_exit_check und adapt_strategy. Regime-Quelle überall: `get_current_regime(con)` (DB), nicht die JSON-Makrodatei.
- **Weekly-Review-Drift-Check** prüft jetzt alle drei Pfade (signal_manager, active_exit_check, crabel_shadow_eval) auf echte Legacy-Aufrufe `get_asset_multipliers(`.

### Verifikation (16.08.2026, Live-Daten)
- Export: `✅ Watchlist exportiert: 116 Einträge … 11 DQ .L-Microcaps aussortiert`
- DQ-Alarm: Count 11 (Schwelle 10) → Alarm bei Regression, silent bei stabil (State getestet)
- Exit-Review: 4 offene Positionen ✅, Drift `trailing_step STANDARD 0.75 vs 0.5` erkannt

### Geänderte Dateien
| Datei | Änderung |
|---|---|
| `scripts/export_watchlist.py` | DQ-Isolation: `_is_dq()` + DQ-Block im Output, Statistik ohne DQ |
| `scripts/refresh_tech_scores.py` | veraltete Scores werden gecleart (rowcount-gesteuert) |
| `scripts/dq_alarm.py` (neu) | DQ-Regressions-Watchdog (Schwelle 10, State) |
| `scripts/weekly_exit_review.py` (neu) | Positionen vs Exit-Matrix + Config-Drift-Check |
| `scripts/active_exit_check.py` | umgestellt auf `get_exit_config()` (trailing_step 0.5→0.75 Fix, Regime inline) |
| `scripts/signal_manager.py` | `compute_sl_tp`/Partial-TP/Sizing auf `get_exit_config` (Entry-SL/TP regime-abhängig), toter mult entfernt |
| `scripts/crabel_shadow_eval.py` | `simulate_forward` auf Matrix (step/sl/profit_lock statt Legacy+cfg-Fallback) |
| `~/.hermes/scripts/dq_alarm.sh`, `weekly_exit_review.sh` (neu) | Wrapper für Hermes no_agent-Crons |

## 14.08.2026 — UK-Microcap-Gate (Datenqualität `.L`-Ticker)

### Problem
RSS-Quelle `share talk` spült UK-AIM/Nano-Caps (AET.L, BSFA.L, HREE.L, KZG.L, SHOE.L, MAC.L …) in die Watchlist. Diese hatten trotz fehlender/geringer Kurshistorie und minimalem Tagesumsatz potenziell einen Tech-Score → sie tauchten als LONG/SHORT-Entry-Kandidaten auf und verpesteten die Conviction-Verteilung (DQ-Fälle in der Watchlist-Pflege).

### Lösung
Eindeutiges **Historie- + Liquiditäts-Gate** direkt in der einzigen Quelle `get_technical_score()` in `utils.py`:
```python
UK_MIN_BARS         = 200      # ~1 Jahr Handelstage
UK_MIN_TURNOVER_EUR = 500_000  # konsistent mit signal_manager min_liquidity_eur
```
Für `.L`-Ticker gilt: **kein Tech-Score**, wenn `len(df) < 200` **oder** 20-Tage-Ø-Tagesumsatz (aus dem bereits geladenen df, kein Extra-Call) `< 500k€`. Kein Score → kein `tech_score`/`tech_direction` → kein LONG/SHORT-Entry-Kandidat.

### Warum das Gate nicht überflüssig ist
`get_technical_score` verlangte zwar schon `len(df)≥50` und EMA200 (≈200 Bars), aber ein UK-Nano-Cap mit 200+ Bars bekam trotzdem einen Score, obwohl es als AIM-Microcap praktisch unhandelbar ist. Das Turnover-Kriterium ist der eigentliche Differenzierer.

### Verifikation (14.08.2026, Live-Daten)
- **Geblockt (20 `.L` bestätigt):** AET.L, BSFA.L, HREE.L, KZG.L, SHOE.L, MAC.L, 0UKI.L, ECR.L, FCM.L, POLB.L, FMET.L, BOOM.L, KEN.L, ORCP.L, TYM.L, HDD.L, ORR.L, HVO.L, SOU.L, TEK.L → veraltete `tech_score`/`tech_direction` aus der Watchlist gelöscht (refresh_tech_scores leert nicht, wenn `tech` None).
- **Durchgelassen (liquid, korrekt):** GLEN.L, ULVR.L, WISE.L, TATE.L, LGEN.L, RSW.L, AV.L, TSCO.L, ANTO.L, ATYM.L, KGF.L, HSX.L, VOD.L, BARC.L, BP.L u.a.
- **Position-Check:** `signal_manager` hat **0** Paper-Entries gegen sämtliche `.L`-Ticker je eröffnet — Entry-Gates (tech + Liquidität) hatten das bereits verhindert.

### Cron-/Ops-Hinweis
Das Gate wirkt automatisch beim nächsten `technical_validator.py`/`watchlist_manager.py`/`refresh_tech_scores.py`-Lauf. Kein Cron-Neustart nötig.

## 09.08.2026 — Watchlist Cleanup: Dropped-Archivierung

### Problem
`watchlist_cleanup.py` setzte `watching`>60d auf `dropped`, aber `dropped`-Einträge wurden **nie physisch entfernt/archiviert** → die `watchlist`-Tabelle wuchs unbegrenzt (1193 `dropped` bei nur 464 `watching`). Keine FK-Constraints/Trigger verweisen auf `watchlist`, daher war eine Bereinigung sicher.

### Lösung
`watchlist_cleanup.py` (`~/.hermes/scripts/`) erweitert um eine **Archivierungs-Stufe** (Stufe 4) — konservativ, kein Datenverlust:
- Neue Tabelle **`watchlist_archive`** (Migration per `CREATE TABLE IF NOT EXISTS`, alle `watchlist`-Spalten + `archived_at` + `archived_reason`).
- **Artefakte sofort archivieren**: `notes LIKE 'merged into%'` (Dedup-Merges), `'nicht börsennotiert%'` (privat), `'strukturiertes Produkt%'` (Zertifikate).
- **Altersbasiert**: alle übrigen `dropped` mit `last_seen` > 180 Tage (`ARCHIVE_AFTER_DAYS=180`).
- Archivieren = INSERT in `watchlist_archive` + DELETE aus `watchlist` (Rows bleiben als Historie abfragbar).
- Sauberkeit: `watching`/`bought` werden nie angefasst.

### 🔴 Pitfall: DELETE über `rowid`, nicht `id`
Die Dedup (`watchlist_dedup.py`) verwaltet Zeilen via `rowid` (`WHERE rowid=?`), wodurch die `id`-Spalte bei vielen Zeilen **NULL** ist (802 von 1637!). Ein `DELETE ... WHERE id=?` traf bei diesen Zeilen nichts → die Zeile wurde zwar ins Archiv kopiert, aber nicht aus der Watchlist entfernt (Duplikat-Bug, Archiv wuchs fälschlich). **Fix:** `SELECT rowid, *` + `DELETE ... WHERE rowid=?` — konsistent mit dem restlichen System.

### Modi
- `python3 watchlist_cleanup.py` → **Dry-Run** (zeigt nur, was archiviert würde)
- `python3 watchlist_cleanup.py --apply` → tatsächliche Verschiebung. **Cron ruft den Wrapper `watchlist_cleanup_apply.sh` mit `--apply`** (siehe unten), damit die Archivierung automatisch greift.

### Erstlauf (09.08.2026, nach rowid-Fix)
Alle 119 Artefakt-Drops (94 mit gültiger `id` beim ersten Lauf + 25 `id=NULL`-Zeilen via `rowid`) archiviert. Verbleibend: 0 Artefakt-Drops in der Watchlist. Watchlist 1662→**1637** (464 watching, 76 bought, 1097 dropped — die 1097 sind <180d alt, werden in späteren Sonntags-Läufen automatisch archiviert). Offene Positionen (4) unberührt, keine Überlappung zwischen Archiv und offenen Positionen. Lauf ist **idempotent** (2. Lauf = 0 neue).

### Cron
Job `watchlist-cleanup-weekly` (07:30 So) zeigt jetzt auf den Wrapper **`~/.hermes/scripts/watchlist_cleanup_apply.sh`**, der `watchlist_cleanup.py --apply` aufruft → automatische Archivierung.

## 09.08.2026 — Phase 1+2 Fix (Exit-Strategie + Signal-Rauschen)

### Auslöser
Review des Trading-Skills ergab: 77 geschlossene Trades netto -1.230€, 82% SL_HIT, 0% Win Rate über 30 Tage, 100% SL-Exits (0% TP), -8.6% YTD vs SPY +13.1%. 464 Watchlist-Einträge mit Ø 0.27 Conviction = Rauschen. Top-Band (Top 3/5/10) 0 gekauft. 30 Tage lang kein einziger Take-Profit.

### Root Cause #1 — Exit-Strategie mathematisch kaputt
- `signal_manager.py check_open_positions()` zog den Chandelier-Trailing **ohne profit_lock-Gate** nach (Zeile `if atr and not _donchian_primary:`). Der stündliche Check hob den SL bei jedem minimalen Hoch an → Trades wurden vor dem TP gestoppt. Der 15.07.-Fix (`profit_lock_atr`) existierte NUR in `active_exit_check.py`, nicht im stündlichen `signal_manager.py`.
- **Config-Drift:** Die Regime-Adaption (`adapt_strategy()`) schrieb in `trailing_step_atr`, aber der Exit-Check liest `profit_lock_atr` → der Trailing-Delay war komplett wirkungslos.
- `profit_lock_atr = 2.0` > SL (1.5x ATR) → im Sideways war der Wert unerreichbar → 0% TP-Hits.

### Fixes Phase 1
1. **`signal_manager.py`**: profit_lock-Gate in `check_open_positions()` eingebaut (Chandelier-Trailing nur noch ab `pnl_atr >= profit_lock_atr`).
2. **`active_exit_check.py`**: Default `profit_lock_atr` 2.0 → 0.5.
3. **`config.py`**: `ASSET_TYPE_MULTIPLIERS[].profit_lock_atr` alle 2.0/2.5/1.5 → 0.5.
4. **`signal_manager.py` `adapt_strategy()`**: schreibt jetzt in `profit_lock_atr` statt `trailing_step_atr` (Config-Drift behoben).
5. **Donchian-Primary-Exit aktiviert**: `donchian_exit_enabled: true`, `donchian_exit_mode: "primary"` (Turtle-Exit gibt Trends Raum; Initial-SL bleibt harter Floor).
6. `strategy_config.json`: `profit_lock_atr 2.0→0.5`, `trailing_step_atr 2.0→0.75`, `min_confidence 0.8→0.70` (Entry-Starvation behoben), `min_conviction 0.6→0.65`.

### Fixes Phase 2 — Signal-Rauschen
7. **`config.py`**: `MIN_CONVICTION` 0.55 → 0.60.
8. **`watchlist_manager.py`**: Tech-Score-Kandidaten-Schwelle `MIN_CONVICTION*0.5` (0.30) → `MIN_CONVICTION` (0.60) — nur solide Kandidaten bekommen Tech-Scores.
9. **`source_lifecycle.py`**: `min_trades_for_eval` 5→3, `promote_min_trades` 5→3, `remove_no_mention_days` 90→60 (aggressiveres Quellen-Management).
10. **`backtest_gate.py`** (neu): Backtest vor Config-Änderungen — GO/GEDULD/NO-GO basierend auf Sharpe, WR, Trade-Anzahl.

### Erwartung
Exit-Quote von 0% TP auf 20-30% heben. Weniger Rauschen in der Watchlist. Wenn nach 4 Wochen keine Verbesserung → Phase 3 (radikaler Umbau, siehe Cron `phase-3-review-trading` am 06.09.).

## 09.08.2026 — glm-5.2-Review: Exit-Matrix + Konsolidierung + Winrate-Messung

### Auslöser
Zweites Review mit dem unabhängigen Modell `z-ai/glm-5.2`. Deckte einen Widerspruch im Phase-1-Fix auf: Der Regime-Override in `adapt_strategy()` trimmte `profit_lock_atr` auf 1.5–2.5 nach oben und machte die 0.5-Senkung (Phase 1A) im Sideways wirkungslos. Außerdem drei überlagerte Trail-/Exit-Quellen mit unklarer Präzedenz.

### Root Cause #2 — Drei überlagerte Exit-Quellen
1. `ASSET_TYPE_MULTIPLIERS` (config.py) — asset-type-spezifisch
2. `regime_configs` (in signal_manager.py) — Regime-Override, überschrieb profit_lock_atr nach oben
3. `strategy_config.json` `profit_lock_atr` — manueller Wert, wurde vom Regime-Override gekillt
Zusätzlich: `active_exit_check.py` kannte Donchian-Primary nicht → zog den ATR-Chandelier parallel zum Donchian-Trail → zwei konkurrierende Stops.

### Fixes
1. **`get_exit_config(asset_type, regime)`** in config.py — deterministische Exit-Matrix (9 Kombinationen STANDARD/TECH/DEFENSIVE × bull/sideways/bear), einzige Quelle für SL/TP/partial/profit_lock.
2. **`adapt_strategy()`** konsolidiert: nutzt die Matrix, entfernt den profit_lock-Tripping-Block (profit_lock_atr bleibt jetzt konstant aus der Matrix = 1.0).
3. **`profit_lock_atr` = 1.0** überall (Matrix + ASSET_TYPE_MULTIPLIERS) — Kompromiss: niedriger als 2.0 (unerreichbar im Sideways), höher als 0.5 (Intraday-Noise).
4. **`active_exit_check.py` AKTION 3**: respektiert Donchian-Primary-Präzedenz (überspringt den Chandelier wenn Donchian fährt), profit_lock aus pos_mult.
5. **`signal_manager.py` `check_open_positions()`**: profit_lock aus pos_mult statt globaler cfg.
6. **`min_confidence` 0.70 → 0.80** — glm hat recht: keine Entry-Starvation (76 bought), die Senkung war fehldiagnostiziert.
7. **`signal_source` beim Entry setzen** (`_derive_signal_source`, aus Kanal-Präfixen rss/x_social/screener/youtube) + **Winrate-nach-Quelle** im nightly_eval-Report (`build_signal_source_line`).

### Wichtige Korrektur zu glm
glm behauptete "10.4% Winrate, Break-Even 21.5%". **FALSCH** — glm verwechselte TARGET_HIT-Zahl (8) mit der Winrate. Reale Winrate: **30/77 = 39%**. Das wahre Problem ist Payoff: Gewinner Ø +62.88€, Verlierer Ø -66.31€ → Payoff 0.95 < 1. Bei 39% WR braucht man Break-Even-WR von 51%. **Die Verluste sind größer als die Gewinne** — fehlende R:R-Asymmetrie in der Durchschnitts-Realisierung (TP 2.5x konfiguriert, aber real nur ~+63€; SL-Verluste bis -364€ durch Gaps/Execution). Das verlagert den Fokus von reiner Winrate auf die Verlustseite verkleinern.

### Erwartung
Exit-Matrix eliminiert die Config-Drift. profit_lock 1.0 erreichbar im Sideways. Winrate-nach-Quelle zeigt ab 09.08. welche Komponente (RSS/X/YouTube/Screener) trägt. min_confidence 0.80 filtert schwache Signale raus (weniger, bessere Trades).

## 09.08.2026 — (a) Gewinner-Exit + (b) Earnings/Makro-Schutz (glm-5.2-Gegencheck)

### Auslöser
Datenanalyse der Verlustseite + Gegencheck durch glm-5.2. Ergebnis: Das Hauptproblem ist NICHT die Winrate (sie ist 39%), sondern dass Gewinner zu früh abgeschnitten werden (Payoff 0.95 statt benötigtem 1.56). Zusätzlich Tag-0-Verluste durch Overnight-Earnings-/Makro-Gaps (05.06.2026: 4 gleichzeitige Tag-0-Stopps = NFP-Tag). WICHTIG: historische Daten liefen mit dem ALTEN Chandelier-System, Turtle-Donchian-Primary ist erst seit heute aktiv.

### Fix (a) — Gewinner-Exit entkoppelt
- **Breakeven-Zug nach Partial-TP entfernt im Donchian-Primary-Modus.** Vorher: nach 50% Partial-TP bei 1.5x ATR wurde der SL auf Breakeven gezogen → der 50%-Rest wurde am BE ausgestoppt bevor der Donchian-Trail/TP greifen konnte. Jetzt: im Donchian-Primary-Modus bleibt der initiale SL stehen, der Donchian-Turtle übernimmt das Stopp-Handling. (Chandelier-Modus behält altes BE-Verhalten.)
- Freigabe zum Laufenlassen: die 8 echten TARGET_HIT-Winner erreichten alle ~100-130% ihres TP — das Ziel ist erreichbar, es wurde nur durch zu enges Trailing/BE abgewürgt.

### Fix (b) — Earnings/Makro-Schutz
1. **`is_macro_event_day()`**: blockt Entries am ersten Freitag (NFP/US-Arbeitsmarkt) — der verlässlichste wiederkehrende Makro-Termin. FOMC/CPI bewusst NICHT per Tageregel (variieren zu stark → falsch-positive Blöcke).
2. **`has_overnight_gap(cur, atr, prev)`**: blockt Entry wenn letzter Close > 60% einer Tages-ATR vom Vortag entfernt ist (Overnight-Earnings-/News-Gap). Fail-open ohne Referenz.
3. **`get_prev_close_ratio(ticker)`**: liefert (current, prev_close) aus dem gecachten df — kein Extra-API-Call.
4. Beide Filter im Entry-Loop integriert (nach Earnings-Blackout, vor Crabel-Gate).

### Wichtige Nuance (Turtle ist erst 1 Tag aktiv)
Historische SL_HIT-„Gewinner" (AMD, NDA, LITE, NVDA) stammen vom defekten Chandelier-System — sie sagen NICHTS über das neue Donchian-Primary-Verhalten aus. Wir dürfen aus alten Daten keine Schlüsse aufs neue System ziehen. Die neuen Exit-Fixes gelten ab heute, die Wirkung zeigt sich erst in den nächsten Wochen.

### Erwartung
- Gewinner laufen weiter (kein BE-Abwürgen im Donchian-Modus) → Payoff steigt Richtung 1.5+
- Keine Tag-0-Entries an NFP + keine Overnight-Gap-Entries → weniger -100€+ Verlusttrades
- Nächster Check nach 4 Wochen (Cron phase-3-review-trading) mit den neuen Daten.

## 09.08.2026 — Top-5-Signale im Tages-Report (Telegram)

### Was
Der `nightly_eval.py` Tages-Report (Mo–Fr 05:00) und Wochen-Report (So 06:00) enthalten jetzt einen **🎯 Top-Signale-Block** mit den 5 besten Watchlist-Kandidaten.

### Implementierung
- `calc_top_signals(con, limit=5)` — Query: `status='watching'` + `ticker IS NOT NULL`, sortiert nach `conviction_score_aged DESC, tech_score DESC, conviction_score DESC`
- `build_top_signals_line(con, limit=5)` — HTML-Formatierung für Telegram: Name, Ticker, Conviction (aged), Tech-Score, tech_direction (📈/📉/➖), Mention-Count
- Integration in beide msg-Formate (täglich + Sonntag) via `signals_line`

### Warum conviction_score_aged
Die rohen `conviction_score`-Werte sind oft 1.0 bei 1 Mention (frisch, aber unbestätigt). `conviction_score_aged` ist alterungsbereinigt (14d-Halbwertszeit) und zeigt etablierte Kandidaten wie Allianz (13x Mentions, 81%) statt 1-Mention-Zufallstreffer.

### Delivery
Kein neuer Cron nötig — nightly_eval sendet bereits täglich. Ziel: `TELEGRAM_HOME_CHANNEL` = `-1003918757178` (Ch_hermster_trade).

## 20.07.2026 — Turtle-Konfluenz-Sprint (Donchian + Asymmetrie)

### Prinzip
Ausgewählte Bausteine des Turtle-Systems (Dennis/Eckhardt 1983) übernommen — bewusst NICHT als Standalone-System. Das Original handelte einen diversifizierten Futures-Korb; Hermes handelt einen korrelierten Aktien-Basket (DAX/MDAX/S&P100), wo der reine Breakout-Edge dünn und diversifikationsschwach ist (Studien: ~5–7% p.a. auf Aktien vs. Futures; Sharpe-Verfall post-2005). Übernommen wurden daher nur die assetklassen-robusten Teile: Donchian-Breakout als Konfluenz-Signal, Donchian-Trailing-Exit (opt-in) und die Asymmetrie-Denkweise im Optimizer. Deterministischer Backbone und bestehende Exit-Pfade bleiben per Default unverändert.

### Punkt 1 — ATR-Risk-Parity-Sizing: bereits vorhanden, NICHT dupliziert
`signal_manager.open_new_positions()` (Vol-Adj-Block) rechnet bereits:
```
risk_amount     = portfolio_value × risk_pct_per_trade   (1.5%)
sl_distance_eur = sl_multiplier(asset_type) × ATR_eur
position_size   = (risk_amount / sl_distance_eur) × price_eur
```
Ein SL-Hit verliert damit exakt `risk_pct_per_trade` des Portfolios — über die ECHTE SL-Distanz (asset-type × ATR), nicht nur „1 ATR". Das ist die korrektere Form der Turtle-N-Idee, FX-aware. Kein Code-Change nötig.

### Punkt 2 — Donchian-Breakout als Konfluenz (`utils.py`)
Neuer Helfer `get_donchian_breakout(ticker, entry_period=20, exit_period=10, slow_period=55)`:
- Nutzt `get_price_data_cached()` → KEINE zusätzlichen API-Calls (df ist nach `get_technical_score` bereits im 5-min-TTL-Cache; gleiche Mechanik wie `get_crabel_patterns`).
- Schließt den laufenden (unfertigen) Tagesbar aus der Kanal-Referenz aus → ein Ausbruch kann sich nicht selbst maskieren.
- Rückgabe: `upper_20/lower_20`, `upper_55/lower_55`, `exit_low/exit_high` (Trailing-Referenz), Breakout-Flags (`breakout_long`, `breakout_short`, `breakout_long_slow`, `breakout_short_slow`).

Integriert als **Score-Komponente 9** in `get_technical_score()`:

| Bedingung | Score |
|---|---|
| 55-Tage-Hoch (S2-Ausbruch) | +1.0 |
| 20-Tage-Hoch (S1-Ausbruch) | +0.5 |
| 20-Tage-Tief (S1-Ausbruch) | −0.5 |
| 55-Tage-Tief (S2-Ausbruch) | −1.0 |

`max_score` bleibt bewusst **10** (wie beim Crabel-Bonus) — sonst würden alle Confidences Richtung 0.5 gestaucht und die kalibrierten `tech_score`-Schwellen im `signal_manager` brechen. Das `donchian`-Dict landet im Return und fließt automatisch in `technical_validator.py`.

### Punkt 3 — Donchian-Trailing-Exit (`signal_manager.py`, `check_open_positions()`)
Config-gated, **Default `off`** (Verhalten unverändert bis manuell aktiviert). Neue Keys in `DEFAULT_CONFIG`:
```python
"donchian_exit_enabled": False,
"donchian_exit_mode":    "off",    # off | ratchet | primary
"donchian_exit_period":  10,       # Turtle S1-Exit: 10-Tage-Gegen-Extrem
```
- **`ratchet`**: Donchian-Extrem als ZUSÄTZLICHER Verengungs-Floor über dem ATR-Chandelier (konservativ; bindet selten, nie riskanter).
- **`primary`**: Donchian-Extrem ERSETZT den Chandelier als Trail (echter Turtle-Exit, gibt Trends Raum). Der Chandelier-Block wird dann übersprungen; der Initial-SL aus `compute_sl_tp` bleibt harter Floor.

Beide Modi **monoton**: heben den Stop für LONG nur an / senken ihn für SHORT nur ab — lockern nie. Damit bleiben Ist-Risiko und Drawdown-Circuit-Breaker (mark-to-market) konsistent. Fixe TP + Partial-TP bleiben unangetastet (Donchian = Zusatz, kein Ersatz). Log-Marker: `🐢 Donchian-Trail`.

### Punkt 4 — Asymmetrie-Denkweise im Optimizer (`strategy_optimizer.py` + `backtester.py`)
**Composite-Score neu** — kein eigenständiger Win-Rate-Term mehr:
```
Expectancy 35% | Payoff-Ratio 20% | Profit Factor 20% | Sharpe 15% | −MaxDD 10%
```
mit `expectancy = WR × avg_win − (1−WR) × avg_loss` und `payoff_ratio = avg_win / avg_loss`. Begründung: ein Trendfolge-Profil (WR ~35–40%, große Winner) darf nicht dafür bestraft werden, oft falsch zu liegen, solange der Erwartungswert stimmt. **BEIDE** `calculate_metrics`-Kopien angepasst — sonst optimiert der Walk-Forward-Pfad (nutzt `backtester`) weiter auf Win-Rate.

**`adjust_from_eval_metrics` entschärft** (zwei anti-asymmetrische Auto-Regeln):

| Alt | Neu |
|---|---|
| WR < 40% → `min_confidence` +5% | nur wenn ZUSÄTZLICH PF < 1.1 (echter Edge-Verlust) |
| TP-Hits < 20% → `atr_tp_multiplier` −0.25 | nur wenn ZUSÄTZLICH PF < 1.2 (weite Ziele zahlen sich nicht aus) |

Bei gesundem Profit Factor ist eine niedrige TP-Hit-Quote ERWARTET — die Gewinne kommen aus dem Trailing, nicht aus dem Fix-TP. `payoff_ratio` + `expectancy` zusätzlich im Metrics-Return und im Optimizer-Log.

**Verifikation** (`verify_turtle.py`, standalone): Turtle-Profil (35% WR, Payoff 3.75, Exp +2.65%/Trade) vs. Mean-Reverter (70% WR, Payoff 0.5, Exp +0.20%/Trade) → NEU-Composite **0.786 vs. 0.221** (alt: 0.503 vs. 0.461, kaum getrennt — der Win-Rate-Term stützte den Mean-Reverter künstlich).

### Deploy-Hinweis
Die erweiterte `get_technical_score`-Rückgabe (`donchian`-Key) + der neue Score-Anteil verschieben die Confidence-Verteilung minimal. Da `max_score` bei 10 bleibt, sollten die Schwellen halten. Nach Deploy einmal `refresh_tech_scores.py` laufen lassen und Watchlist-Confidences gegenprüfen.

### Geänderte Dateien
| Datei | Änderung |
|---|---|
| `utils.py` | `get_donchian_breakout()` neu; Score-Komponente 9 + `donchian`-Key in `get_technical_score()` |
| `signal_manager.py` | Donchian-Trailing in `check_open_positions()`; 3 Config-Keys; Import `get_donchian_breakout` |
| `strategy_optimizer.py` | Composite auf Expectancy/Payoff; `adjust_from_eval_metrics` asymmetrie-bewusst; Expectancy/Payoff im Log |
| `backtester.py` | Composite in `calculate_metrics` konsistent umgestellt |

---

## 17.07.2026 — Hedgefonds-Rollen-Sprint (R1–R4)

### Prinzip
Der deterministische Pipeline-Backbone bleibt unangetastet. LLM-Rollen werden ausschließlich an Urteils-Stellen eingefügt — als kontrollierte, geloggte, budgetierte Bausteine mit Fail-Open-Fallback auf das heutige Verhalten. Exit-Pfade (`check_open_positions`, SL/TP, `_emergency_close_all`) wurden NICHT angefasst.

### Neues Paket `roles/` (Trading-Root)

| Datei | Zweck |
|---|---|
| `roles/__init__.py` | `ensure_roles_schema(con)` — idempotente Migration (`llm_budget_log`, `committee_log`), prozessweit gecacht |
| `roles/budget.py` | Harte Tages-Token-Budgets pro Rolle. `check_and_reserve()` / `record_spend()` / `remaining()` |
| `roles/committee.py` | Investment Committee: Bull → Bear → Risk |
| `roles/devils_advocate.py` | Devil's Advocate (Thesis-Monitor Stufe 2) |

Nutzt den bestehenden `thematic/lib/llm_client.py` und `thematic/lib/prompt_loader.py` (DRY — kein zweiter HTTP-Wrapper). Neue Prompts liegen in `thematic/prompts/`.

**Budgets** (Konstanten in `budget.py`, bewusst NICHT in der Strategy-Config — der `strategy_optimizer` soll daran nicht drehen):
```python
DAILY_TOKEN_BUDGET = {
    "committee":       150_000,
    "devils_advocate":  60_000,
    "extractor_analyst": 400_000,
}
```
Überschreitung → `check_and_reserve()` liefert `False` → Aufrufer geht in den Fail-Open-Pfad + `⚠ Budget`-Zeile.

### Modell-Konfiguration (`thematic/config/thematic_config.json`)
```json
"committee_bull":    "deepseek/deepseek-v4-pro",
"committee_bear":    "openai/gpt-5.4-nano",
"committee_risk":    "google/gemini-2.5-flash-lite",
"devils_advocate":   "deepseek/deepseek-v4-flash-0731",
"extractor_analyst": "deepseek/deepseek-v4-flash-0731"
```
Bull, Bear und Risk sind DREI verschiedene Provider (DeepSeek / OpenAI / Google) — Bull und Bear MÜSSEN verschieden sein, sonst widerlegt sich dasselbe Modell nur mit denselben Biases. `grok-lite` bewusst NICHT fürs Committee (wird vom Breaking-News-Check genutzt, Rate-Limits schonen).

**Modellwahl-Historie (20.07.2026, live per Sonde `probe_model.py` verifiziert):**
- **Bear: Qwen3.5-flash → gpt-5.4-nano.** Qwen ist ein Reasoning-Modell und verbrannte ~5400 nicht-abschaltbare Reasoning-Tokens pro Call — bei `max_tokens=800` lief der Denkprozess voll und lieferte `content=""` (`finish_reason=error`), was jeden Bear-Call in Fail-Open trieb. `reasoning:{exclude:true}` unterdrückt nur die Ausgabe, nicht die Abrechnung. gpt-5.4-nano ist denkfrei (`reasoning_tokens=0`) und liefert die inhaltlich schärfste Gegenanalyse der getesteten Kandidaten (benennt konkrete fehlende Trigger statt höflicher Relativierung).
- **Bull: DeepSeek-flash → DeepSeek-pro.** Bessere Argumentationsqualität, ebenfalls denkfrei.
- Ergebnis: **~3500 Tokens pro 3-Rollen-Check** statt ~9000 mit Qwen. 150k-Committee-Budget trägt damit ~40 Checks/Tag.
- **Verworfen:** tencent/hy3 (nur höfliche Relativierung, kein scharfer Angriff), grok-4-fast (bei OpenRouter deprecated → Grok 4.3), gemini-3.1-flash-lite & deepseek-v4-pro-als-Bear (Provider-Kollision mit Risk bzw. Bull).
- **Bekannter Rest-Ausreißer:** DeepSeek-pro (Bull) läuft in ~1 von 7 Calls in einen Longtail und stößt an den 800er-Deckel → Truncation → Fail-Open. Im Shadow-Mode kosmetisch (Trade läuft durch wie ohne Committee). JSON-Repair-Fallback erst bauen, wenn echte Läufe eine Ausreißerquote >5 % zeigen.

---

### R1 — Investment Committee (Pre-Entry Gate, Shadow-Mode)

**Datei:** `scripts/signal_manager.py`, `open_new_positions()`

**Einbaupunkt:** im Kandidaten-Loop NACH dem Crabel-Gate, VOR dem VIX-Halving-Block. Begründung: das Committee ist das teuerste Gate und darf nur Kandidaten sehen, die alle billigen deterministischen Gates (Weekly Trend, Allokation, Sektor, Korrelation, Liquidität, Earnings, Segment, Breaking News, Crabel) passiert haben. So zahlen wir LLM-Kosten nur für Kandidaten, die sonst tatsächlich gekauft würden.

**Neue Config-Keys** (in `DEFAULT_CONFIG`):
```python
"committee_enabled":            True,
"committee_mode":               "shadow",   # shadow | active
"committee_max_checks_per_run": 6,
```
Der Loop läuft nach `priority_score` absteigend → das Committee prüft automatisch die besten Kandidaten zuerst. Nach Erreichen des Limits laufen weitere Kandidaten OHNE Committee (Fail-Open + Log-Zeile).

**Drei sequenzielle Calls** (Bear braucht Bulls These, Risk braucht beide — kein Threading, kein Async):
1. **Bull Analyst** → `{"thesis", "conviction", "key_assumptions"}`
2. **Bear Analyst** → erhält die Bull-These und MUSS sie angreifen → `{"counter_thesis", "severity", "dealbreaker", "dealbreaker_reason"}`
3. **Risk Officer** → erhält beide Thesen + Portfolio-Kontext, bewertet die POSITION (Klumpenrisiko, Regime-Fit), nicht die Aktie → `{"verdict", "size_factor", "rationale"}`

**Entscheidungsregel — deterministisch im Code, nicht im LLM:**
```python
if risk_verdict == "VETO" and bear_dealbreaker:
    final = "VETO"
elif risk_verdict in ("VETO", "REDUCE"):
    final = "REDUCE"; size_factor = clamp(risk_size_factor, 0.5, 1.0)
else:
    final = "APPROVE"; size_factor = 1.0
```
Ein VETO braucht ZWEI unabhängige Stimmen (Risk + Bear-Dealbreaker) — ein einzelnes Modell darf nie allein einen Trade killen. Ein Risk-VETO ohne Bear-Dealbreaker wird zu REDUCE mit `size_factor=0.5` abgeschwächt. Ein unbekanntes/unparsbares Verdict → APPROVE.

**Shadow-Mode (Default):** ändert NICHTS am Verhalten, schreibt nur `committee_log` (`would_block=1` bei VETO). Aktivierung erst nach 2–4 Wochen Auswertung (R4).

**Kontext-Beschaffung:** Die offenen Positionen werden mit EINER Query VOR dem Loop geladen (`committee_positions_text`), nicht pro Kandidat — zusätzliche Queries unter der äußeren Connection sind in diesem Projekt eine bekannte Lock-Quelle. `regime`, `macro`, `sector_exposure`, `portfolio_value`, `drawdown_pct`, `current_price`, `atr`, `crabel` sind bereits im Scope. News via `tavily_client.fetch_ticker_news(ticker, days=1)`, max. 5 Snippets à 200 Zeichen; Tavily-Fehler → `"Keine News verfügbar."`, kein Abbruch.

**Fail-Open:** Jeder Exception-Pfad in `run_committee()` → `{"final_verdict": "ERROR_FAIL_OPEN", "size_factor": 1.0}` + Log-Eintrag. Es wird NIE eine Exception in den Entry-Loop propagiert. Zusätzlich umschließt der Aufrufer den ganzen Block mit `try/except`.

**Audit-Trail:** `committee_log.entry_happened` wird nach erfolgreichem `INSERT INTO positions` per `mark_entry_happened()` auf 1 gesetzt → Join-Basis für R4.

---

### R2 — Devil's Advocate im Thesis Monitor

**Datei:** `scripts/thesis_monitor.py`

**Problem:** Stufe 1 stellt mit einem einzigen Gemini-Prompt die Frage „ist die These intakt?" — das erzeugt Bestätigungsbias. Verlustpositionen bleiben zu lange INTACT.

**Trigger für Stufe 2** (sonst 0 Zusatzkosten):
- Stufe-1-Verdict ist `INTACT` oder `UNCERTAIN` **UND**
- die Position steht ≥3 % im Minus (`DEVIL_PNL_TRIGGER = -0.03`)

PnL richtungssicher in `_unrealized_pnl_pct()`:
```
LONG:  (price − entry) / entry
SHORT: (entry − price) / entry
```
Preis über `get_price_data_cached()` aus `utils`. Preis nicht ermittelbar → Stufe 2 entfällt. Preis und `entry_price` sind beide in Heimwährung → keine FX-Umrechnung nötig, das Verhältnis ist währungsneutral.

**Merge-Regel — deterministisch, konservativ:**
```python
if kill_probability >= 0.70 and verdict in ("INTACT", "UNCERTAIN"):
    verdict = "WEAKENING"
    rationale = f"[Devil's Advocate p={p:.2f}] " + "; ".join(kill_reasons) + " | " + rationale
```
Bewusst NUR Downgrade auf WEAKENING, nie direkt BROKEN: der bestehende, getestete 3-Tage-WEAKENING-Streak (`_check_weakening_streak`) übernimmt die Eskalation. **Es wird kein neuer Exit-Pfad gebaut** — das minimiert das Risiko neuer Short-/Exit-Bugs auf null.

Ab `kill_probability >= 0.85` zusätzlich sofortige Telegram-Info mit den 3 Gründen (reine Information, keine Aktion).

**Schema:** idempotente Migration `_migrate_devil_columns()` (Muster `PRAGMA table_info`):
```sql
ALTER TABLE thesis_status_log ADD COLUMN devil_kill_prob REAL;
ALTER TABLE thesis_status_log ADD COLUMN devil_reasons TEXT;  -- JSON-Array
```
Beide Felder im bestehenden INSERT mitgeschrieben (NULL wenn Stufe 2 nicht lief). News werden aus Stufe 1 wiederverwendet — kein zweiter Tavily-Call. Budget erschöpft → Stufe 2 entfällt, Stufe-1-Verdict gilt.

Zusätzlich: `busy_timeout=30000` in `main()` gesetzt (`_db_connect()` nutzt raw `sqlite3.connect`).

---

### R3 — 2-Pass-Extractor

**Datei:** `scripts/signal_extractor.py`

**Problem:** EIN Mega-Prompt pro 15k-Chunk erledigte gleichzeitig Firmenerkennung, Namens-Normalisierung, Sentiment, Stärke, Preisziele und Action-Hint. Die Erkennungsleistung ist gut, aber Sentiment/Stärke sind Nebenprodukte eines überladenen Prompts.

**Pass A — „Scout"** (pro Chunk, `deepseek-v4-flash` wie heute): NUR Erkennung. Erkennungsregeln wortgleich zum Legacy-Prompt übernommen — die Erkennungsleistung soll sich durch den Umbau NICHT ändern. Zusätzlich pro Firma `context_snippet` (wörtliches Zitat, max 300 Zeichen) und `rough_sentiment`.

**Pass B — „Analyst"** (EIN Call pro Video, Modell `extractor_analyst`): erhält NICHT das Transkript, sondern nur die deduplizierte Firmenliste mit Snippets (max. 3 pro Firma, `MAX_SNIPPETS_PER_COMPANY`). Liefert das fundierte Urteil.

**Kompatibilität:** Das Ergebnis-Objekt pro Video bleibt feldkompatibel (`name/sentiment/strength/reason/mentioned_price/price_target/action_hint` + `market_outlook`, `key_themes`, `source`). `catalyst` ist rein additiv. **`watchlist_manager.py` wurde NICHT angefasst** — Katalysator-Nutzung in der Conviction ist Out-of-Scope (späterer Sprint, erst wenn Daten vorliegen).

Der Name kommt IMMER aus dem Scout — der Analyst darf ihn nicht umschreiben, sonst bricht das Matching im `company_normalizer`. Ungültige Enum-Werte (sentiment/strength/action_hint/catalyst) werden auf sichere Defaults normalisiert.

**Fallback-Kaskade:**
1. Analyst schlägt fehl (Retries/Parse/Budget/Netzwerk) → Firmen aus Pass A mit `sentiment = rough_sentiment`, `strength = "moderate"`, `reason = context_snippet[:150]`, `action_hint = "watch_for_reversal"`, `catalyst = "none"`. Die Pipeline liefert damit NIE weniger als heute.
2. Auch pro Firma: lässt der Analyst eine Firma aus, kommt sie über den Scout-Fallback rein → die Firmenmenge des 2-Pass-Pfads ist garantiert die des Scouts.
3. Umschalter `EXTRACTOR_MODE` via Environment (Default `two_pass`, `legacy` = heutiger Code-Pfad vollständig erhalten). Rollback ist ein Einzeiler in der Crontab/Env, kein Deploy.

**Refactoring:** `call_api` → generisches `_call(model, system_prompt, user_content)` + `_call_cascade()`, die Legacy-, Scout- und Analyst-Pfad teilen.

> ⚠️ **Wichtiges Detail im Fehlerverhalten von `_call_cascade()`:** Nur ein `json.JSONDecodeError` eskaliert auf die nächste Kaskaden-Stufe. Alle anderen Exceptions (Netzwerk, `KeyError`) propagieren nach oben — genau wie im bisherigen `call_api()`. `main()` setzt das Video dann auf `status='error'` + `error_count+1` → Retry beim nächsten Lauf. Würde die Kaskade sie schlucken, wäre das Video `status='done'` mit 0 Firmen und käme nie wieder → stiller Datenverlust. Einzige Ausnahme: der Analyst-Call fängt selbst ab und fällt auf die Scout-Daten zurück, weil Pass A da bereits gelaufen und bezahlt ist.

---

### R4 — Auswertung & Aktivierung

**Datei:** `scripts/nightly_eval.py` → neue Funktion `calc_committee_shadow(con, days)`

Join `committee_log` × `positions` über (Ticker, Richtung, Entry-Datum). Nur Zeilen mit `entry_happened=1` sind auswertbar. Ausgabe im Tages-Report (14d) bzw. Wochen-Report (30d):
- Checks gesamt, aufgeschlüsselt nach APPROVE / REDUCE / VETO / Fehler
- **`veto_hit_rate`**: Anteil der VETO-Trades, die im Minus endeten. >50 % = das Committee hat überwiegend Verlierer erwischt
- P&L der VETO- und APPROVE-Kohorte, noch offene VETO-Trades

Fehlt `committee_log` (Sprint nicht deployed) → `None`, kein Fehler.

**Aktivierung** nur, wenn die Shadow-Daten zeigen, dass VETOs überwiegend Verlusttrades getroffen hätten: `committee_mode` in der persistierten Strategy-Config auf `active` — über `save_config()`, damit die Config auf Disk landet (bekannte Persistenz-Bug-Klasse).

---

### Explizit Out-of-Scope (unverändert)
- Keine autonome Agenten-Orchestrierung, kein LLM entscheidet über Pipeline-Ablauf
- Keine Änderungen an Exit-Logik, SL/TP, Drawdown-Mechanik, `watchlist_manager`, Dashboard
- Keine neuen Cronjobs, keine neuen Daemons
- Katalysator-Feld fließt NICHT in Conviction/Scoring (nur Datensammlung)
- Kein Multi-Turn-Debattieren zwischen den Rollen (genau eine Runde Bull → Bear → Risk)

---

## 15.07.2026 — Post-Mortem Umbau

### Auslöser
Systematische Analyse der 69 geschlossenen Trades ergab:
- Total P&L: -839,95€, Win Rate: 43,5%
- **75% aller Trades enden im SL** (SL_HIT), **0% erreichen TP** (TARGET_HIT)
- **0-3 Tage Haltedauer: -1.867€** (51% aller Trades, 22,9% WR)
- **8-14 Tage Haltedauer: +363€** (76,9% WR)
- Mai: +1.179€ (70,8% WR) vs Juni: -1.480€ (31,3% WR) — Regime-Wechsel Bull→Sideways

### Änderung 1: Trailing erst ab +2x ATR aktivieren

**Datei:** `scripts/active_exit_check.py` — AKTION 3 (Trailing Stop)

**Vorher:** Trailing wurde ab Entry aktiv — bei jedem normalen Pullback (0.75x ATR) triggert der Trailing Stop, noch bevor der Trade +2x ATR erreicht. Folge: 75% SL_HIT, 0% TP_HIT.

**Nachher:** Trailing wird erst aktiv wenn der Trade mindestens +2x ATR (`profit_lock_atr`) im Plus ist. Bis dahin läuft der Trade ungestört mit dem initialen Stop-Loss.

**Änderung:**
```python
# ALT: Trailing läuft sofort ab Entry
trailing_step = pos_mult["trailing_step"]
if direction == "LONG":
    ...

# NEU: Trailing erst aktiv ab +2x ATR im Plus
trailing_step = pos_mult["trailing_step"]
profit_lock_threshold = cfg.get("profit_lock_atr", 2.0)
if pnl_atr >= profit_lock_threshold:
    if direction == "LONG":
        ...
```

**Erwartung:** SL_HIT von 75% → ~50%, TP_HIT von 0% → ~20%

---

### Änderung 2: Quellen-Weighting nach P&L statt Win Rate

**Datei:** `scripts/source_lifecycle.py` — `adjust_weights()`

**Vorher:** Gewicht wurde basierend auf `win_rate_90d` angepasst. Folge: Quellen mit hoher WR aber negativem P&L (z.B. beating beta: 67% WR, -18€/Trade) wurden hoch gewichtet.

**Nachher:** Gewicht wird basierend auf `avg_pnl_per_trade` angepasst. Quellen mit positivem P&L werden hochgesetzt (≥ +10€ → +15% Weight), Quellen mit negativem P&L runtergesetzt (≤ -10€ → -20% Weight).

**Neue Thresholds:**
| Threshold | Alt (WR) | Neu (P&L) |
|-----------|----------|-----------|
| Boost | `win_rate_90d >= 60%` | `avg_pnl_per_trade >= +10€` |
| Penalize | `win_rate_90d < 35%` | `avg_pnl_per_trade <= -10€` |

**Effekt:** `ticker symbol: you` (+108€/Trade) → hoch, `financial education` (-113€/Trade) → runter.

---

### Änderung 3: Regime-Adaptive Parameter

**Datei:** `scripts/signal_manager.py` — `adapt_strategy()`

**Vorher:** Die Funktion passte nur SL/TP und Confidence an, ohne klare Regime-Basis. Trailing-Step war global 0.75x ATR.

**Nachher:** Die Funktion setzt zuerst eine **Regime-Basis** (überschreibt die Default-Werte aus strategy_config.json), DANN kommen die Trade-basierten Anpassungen.

| Regime | SL Multi | TP Multi | Trailing ab | Min. Confidence |
|--------|----------|----------|-------------|-----------------|
| **Bull** | 1.5x | 3.5x | +1.5x ATR | 0.65 |
| **Sideways** | 1.5x | 2.5x | +2.0x ATR | 0.70 |
| **Bear** | 2.0x | 3.0x | +2.5x ATR | 0.75 |

**Regime-Erkennung:** Läuft bereits in `fundamental_data.py` (US-Regime 60% + EU-Regime 40% Gewichtung) und wird in `regime_history`-Tabelle gespeichert. `get_current_regime()` in `signal_manager.py` liest den letzten Eintrag.

**Regime-Basis-Logik:**
```python
regime_configs = {
    "bull":     {"sl": 1.5, "tp": 3.5, "trailing_atr": 1.5, "confidence": 0.65},
    "sideways": {"sl": 1.5, "tp": 2.5, "trailing_atr": 2.0, "confidence": 0.70},
    "bear":     {"sl": 2.0, "tp": 3.0, "trailing_atr": 2.5, "confidence": 0.75},
}
```

---

### Offene Punkte / Nächste Schritte
- Regime-Erkennung verbessern: aktuell 60/40 US/EU, könnte um VIX-Term-Structure ergänzt werden

---

## 23.07.2026 — PnL-Update für offene Positionen

### Problem
Offene Positionen hatten `pnl_eur = NULL` in der DB, weil das PnL zwar im `check_open_positions`-Loop berechnet (`pnl_pct * position_size - commission`), aber nie zurück in die DB geschrieben wurde. Geschlossene Positionen bekamen ihren PnL beim Exit-Code (Routine 5), offene blieben NULL.

### Fix
`signal_manager.py` Zeile 639–646: Direkt nach der PnL-Berechnung wird jetzt ein UPDATE in die DB geschrieben:

```python
con.execute(
    "UPDATE positions SET pnl_eur=?, pnl_pct=? WHERE id=?",
    (round(pnl_eur, 2), round(pnl_pct * 100, 2), pos["id"])
)
con.commit()
```

Das Update läuft **vor** den Exit-Checks (SL/TP/Trailing/Partial-TP). Wenn ein Exit triggert, überschreibt der Exit den PnL mit dem finalen Wert. Das ist Absicht — der Zwischenstand wird pro Tick erfasst, der finale Wert beim Close.

### Aktuelle Positionen (23.07., nach Fix)
| Ticker | Entry | Jetzt | P&L |
|--------|-------|-------|-----|
| AAPL | 314.47 | 325.89 | +8.60€ (+3.6%) |
| PANW | 326.35 | 335.28 | +19.44€ (+2.7%) |
| ANET | 186.26 | 174.87 | -43.44€ (-6.1%) |
| DIS | 95.85 | 95.87 | -0.20€ (-0.0%) |

### Nächster Pipeline-Lauf
Ab morgen 03:30 aktualisiert der signal_manager das PnL automatisch bei jedem Tick.

---

## 23.07.2026 — Finn-loop (Hermes-Adaption)

### Was ist der Finn-loop?
3-Skill-System von Alex Finn (finna) für deterministische Agent-Workflows:
**Spec → Build → Review, Humans merge.**

Adaptiert von Claude Code + Linear auf Hermes + Obsidian Vault.

### Skills (3 neue)
| Skill | Datei | Zweck |
|-------|-------|-------|
| `finn-spec` | `~/.hermes/skills/meta/finn-spec/SKILL.md` | Interviewt Martin, schreibt Task-Spec mit ACs + NGs |
| `finn-build` | `~/.hermes/skills/meta/finn-build/SKILL.md` | Claimt agent-ready Task, implementiert, reviewed |
| `finn-review` | `~/.hermes/skills/meta/finn-review/SKILL.md` | Reviewt gegen Spec, 3-stufiges Verdict |

### Queue
- Tasks: `/root/obsidian-vault/wiki/tasks/<name>.md`
- Queue: `/root/obsidian-vault/wiki/tasks/README.md`
- Martin setzt `agent-ready: true` im Frontmatter — das ist das Approval-Gate

### Workflow
```
Idee → finn-spec → Spec-Datei → Martin: agent-ready
  → finn-build → Implementierung → needs-review
  → finn-review → Verdict
    → approved → Martin merged
    → changes-requested → Build fix → Re-Review
    → needs-human-review → Martin entscheidet
```
- Wiki-Seite: `wiki/concepts/Finn-loop (Hermes Adaption).md`

---

## 24.07.2026 — Last30days Integration ins Trading

### Was
Zwei Integrationen des Last30days-Skills in den Trading-Agenten:

**Option A: Weekly Cron** `last30days-trading-weekly` (fc93e6e82376)
- Sonntag 08:00, Telegram
- Analysiert Top-5 Watchlist-Kandidaten über Reddit, HN, X, GitHub, Web
- Report mit Sentiment, Risikofaktoren, Kauf-Empfehlung pro Kandidat

**Option B: Pre-Trade Gate** (signal_manager.py, nach Zeile 1582)
- `last30days_gate.py` — Standalone Python-Script, Google News RSS (kein API-Key)
- Keyword-basierte Sentiment-Analyse: 32 negative + 18 positive Keywords
- Drei Stufen: `ok` (exit 0), `warning` (exit 1), `block` (exit 2)
- Nur für HIGH-Conviction Kandidaten (≥0.80)
- Shadow-Validator: block → kein Entry, warning → Log, ok → kein Eingriff
- Fail-Open: Fehler im Gate stoppen den Entry nicht

### Relevante Dateien
- `scripts/last30days_gate.py` — Pre-Trade Gate Script
- `scripts/signal_manager.py` — Integration als letzter Filter vor Entry
- `~/.hermes/skills/meta/last30days/SKILL.md` — Hermes Skill
- Backtest der neuen Parameter auf historischen Daten (Mai vs Juni)
- Short-Trade-Regel: aktuell 28,6% WR — prüfen ob Shorts im Sideways pausiert werden sollen
|
|---
|
|## 30.07.2026 — Sector-Blacklist (Probation-Mechanismus)
|
|### Problem
|Der Industrials-Sektor war 19 Tage geblockt, aber der Probation-Trade wurde nie ausgeführt. Der Blacklist-Mechanismus war nur ein statischer Hinweis in `strategy_config.json` — keine echte Blockade-Logik.
|
|### Lösung
|**Neue DB-Tabelle `sector_blacklist`** (idempotent in `watchlist_manager.py`):
|```sql
|sector TEXT PK, blocked_at, cooldown_days (14), probation_status (NULL/active/success/failed),
|probation_entry_ticker, probation_opened_at, probation_pnl
|```
|
|**Helper `get_sector_blockade_info(con)`** in `watchlist_manager.py`:
|- Berechnet Cooldown-Resttage und Probation-Status
|- Cooldown abgelaufen + kein Probation-Status → Fenster OFFEN
|- Ausgabe im Watchlist Manager Output
|
|**`export_watchlist.py`**: Liest jetzt aus DB statt `strategy_config.json`. Zeigt echten Status: Cooldown-Resttage, Probation-Fenster, aktive Trades.
|
|**Dashboard**: Sektor-Status aus DB statt JSON. Farbcodiert: 🚫 Cooldown, 🟡 Fenster offen, 🟢 aktiv, ✅ bestanden, ❌ fehlgeschlagen.
|
|**Migration**: Alte `sector_blacklist` aus `strategy_config.json` wird einmalig in DB überführt.
|
|**Industrials-Reset**: `blocked_at = 2026-07-11` (vor 19 Tagen) → Cooldown (14d) endete 25.07. → Probation-Fenster ist offen, ein Trade möglich.
|
|### Geänderte Dateien
|| Datei | Änderung |
||---|---|
|| `watchlist_manager.py` | `get_sector_blockade_info()` neu; Migration + Output; Import STRATEGY_CONFIG_PATH |
|| `export_watchlist.py` | DB-Ladung statt JSON; echter Status in Markdown |
|| `dashboard.py` | DB-Ladung statt JSON; farbcodierte Anzeige mit Resttagen |
|
|---
|
|## 30.07.2026 — Signal-Kalibrierung + Top-Band-Validierung
|
|### Auslöser
|Post über Pattern-Detection-Pipeline: zwei Probleme identifiziert — (1) keine Kalibrierung zwischen lauten und leisen Signalquellen, (2) keine separate Validierung der Top-Band-Einträge.
|
|### Punkt 1: Signal-Kalibrierung nach avg_pnl_per_trade
|
|**Neue Funktion `get_channel_calibration(con)`** in `watchlist_manager.py`:
|Liest `avg_pnl_per_trade` aus `source_registry` und wandelt in Faktor [0.3, 2.0]:
|| avg_pnl | Faktor | Bedeutung |
||---------|--------|-----------|
|| ≥ +50€  | 1.5x   | Starke Quelle |
|| ≥ +20€  | 1.2x   | Gute Quelle |
|| ≥ -5€   | 1.0x   | Neutral |
|| ≥ -20€  | 0.7x   | Schwache Quelle |
|| < -20€  | 0.3x   | Schlechte Quelle |
|| Keine Daten | 1.0x | Unbekannt |
|
|**Integration**: `calculate_conviction()`, `calculate_conviction_bear()`, `calculate_conviction_aged()` — alle drei akzeptieren jetzt optionalen `calibration`-Parameter. Der Faktor multipliziert das Channel-Weight pro Mention. Eine Quelle mit +50€/Trade bekommt 1.5x Gewicht, eine mit -30€/Trade nur 0.3x.
|
|**Effekt**: Eine leise, präzise Quelle (z.B. 5 Mentions, +50€/Trade) überstimmt eine laute, mittelmäßige Quelle (100 Mentions, -10€/Trade) nicht mehr.
|
|### Punkt 2: Top-Band-Validierung
|
|**Neue Funktion `calc_top_band_metrics(con)`** in `nightly_eval.py`:
|Validiert separat die Top-3/5/10 der Watchlist (nach conviction_score):
|- Wieviele wurden gekauft (bought_count)
|- Win Rate der gekauften
|- Sum P&L
|- Zeitfenster: 30 Tage
|
|**Migration**: `eval_metrics` Tabelle um Spalten `top3_win_rate`, `top5_win_rate`, `top10_win_rate`, `top3_bought`, `top5_bought`, `top10_bought`, `top3_pnl`, `top5_pnl`, `top10_pnl` erweitert.
|
|**Output**: Tägliche Ausgabe im Nightly Eval — separate Metriken für das Top-Band, nicht nur den Durchschnitt.
|
|### Geänderte Dateien
|| Datei | Änderung |
||---|---|
|| `watchlist_manager.py` | `get_channel_calibration()` neu; Kalibrierung in allen 3 Conviction-Funktionen |
|| `nightly_eval.py` | `calc_top_band_metrics()` neu; Migration + INSERT; Tägliche Ausgabe |
| `social_scanner.py` | `fetch_twitter_grok()`, `fetch_x_search_grok()`, `_call_x_search()`, `_resolve_xai_token()`, `_parse_grok_json()` neu; Grok primär, twitterapi.io Fallback; `get_active_x_search_queries()` für generische X-Searches |

## 31.07.2026 — Grok Twitter Integration

### Problem
Twitter/X-Daten flossen ausschließlich über `twitterapi.io` (Drittanbieter, limitierte Credits). Grok (xAI) hat nativen X-Zugriff via `x_search`-Tool in der Responses API.

### Lösung
- Neue `fetch_twitter_grok()` in `social_scanner.py` — Single-Call: Grok sucht + extrahiert Unternehmen in einem xAI API-Call
- Fallback auf twitterapi.io bei Fehler (Fail-Open) mit Telegram-Benachrichtigung im Trading-Channel
- `_resolve_xai_token()` liest OAuth-Token aus `auth.json` (credential_pool.xai-oauth, sortiert nach `last_refresh` statt nur erstem Eintrag — 3 parallel existierende Tokens möglich)
- `_call_x_search()` nutzt xAI Responses API (`/v1/responses`) mit `x_search`-Tool
  - Antwort-Parsing aus `output[].content[].text` (nicht `output_text` — das ist bei Responses API `None`)
  - Citations aus inline `url_citation`-Annotations
- Model: `grok-4.5` (grok-2-latest existiert nicht mehr auf xAI, nur Responses API Models wie grok-4.5/grok-3 funktionieren)
- `fetch_x_search_grok()` für generische X-Searches (Keyword/Thema, `source_type='x_search'`)
- `_send_telegram_alert()` für Fallback-Benachrichtigungen via `TELEGRAM_CHAT_ID`
- `beneficiary_a` in `thematic_config.json` von `grok-lite` auf `deepseek/deepseek-v4-flash-0731` umgestellt

### Geänderte Dateien
| Datei | Änderung |
|---|---|
| `scripts/social_scanner.py` | +170 Zeilen: 5 neue Funktionen, `main()` priorisiert Grok, Telegram-Alert bei Fallback |
| `thematic/config/thematic_config.json` | `beneficiary_a: grok-lite` → `deepseek/deepseek-v4-flash-0731` |