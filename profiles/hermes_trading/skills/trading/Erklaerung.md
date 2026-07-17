# Änderungshistorie — Trading Skill

## 16.07.2026 — Crabel-Instrumentierung (Stufe 1: Messen)

### Warum kein Auto-Tuning für das Crabel-Gate

Naheliegende Idee: `crabel_gate_mode` und `crabel_stretch_len` ins `PARAM_GRID` des `strategy_optimizer` werfen und mitoptimieren lassen. **Das funktioniert prinzipiell nicht.**

`backtest_params()` resimuliert SL/TP auf Trades, die **stattgefunden haben** — für einen gelaufenen Trade existiert der Preispfad, also lässt sich fragen „was wäre bei SL 2.0 statt 1.5 passiert?". Das Crabel-Gate ist aber ein **Entry-Filter**: es verändert, *welche* Trades überhaupt existieren. Was es blockt, landet nie in `positions`. Der Optimizer sähe ausschließlich die Trades, die der Filter durchgelassen hat, und sollte daraus lernen, ob der Filter gut ist — **Survivorship Bias in Reinform**. Die Antwort ist nicht in den Daten, egal wie groß das Grid.

Dazu das Sample-Problem: 69 geschlossene Trades. `adjust_from_eval_metrics()` schraubt bereits an `min_confidence` auf Basis von 7-Tage-Fenstern (bei aktueller Frequenz eine Handvoll Trades). Der Mai/Juni-Befund (+1.179€ → −1.480€ beim Regime-Flip) zeigt, wie solche Tuner Regimewechseln hinterherlaufen. Weitere Auto-Knöpfe auf derselben dünnen Basis machen das System nicht schlauer, nur schneller im Kreis.

**Konsequenz — zweistufiges Vorgehen:**
- **Stufe 1 (dieser Sprint):** Counterfactual-Datensatz aufbauen. Reines Messen, keine Entscheidungen, keine Config-Änderungen.
- **Stufe 2 (~2–3 Monate, bei N≥30 pro Kohorte):** Adaption mit Guardrails — erst wenn die Daten existieren, die es heute nicht gibt.

### Änderung 1: Migration `migrate_add_crabel_tracking.py` (neu)

| Objekt | Zweck |
|--------|-------|
| Tabelle `blocked_entries` | Shadow-Log jedes vom Gate verhinderten Entries inkl. der SL/TP-Level, die gegolten hätten |
| Spalte `positions.crabel_at_entry` | Pattern-State beim Entry als JSON → Kohorten-Split gelaufener Trades |

**Dedup-Index** `UNIQUE(ticker, direction, block_date, gate)`: `signal_manager` kann mehrfach täglich laufen — ohne den Index würde derselbe geblockte Kandidat pro Lauf erneut geloggt und das Sample künstlich aufblähen. Insert läuft als `INSERT OR IGNORE`.

Idempotent, mehrfach ausführbar. **Zusätzlich defensiv in `signal_manager.init_db()` dupliziert** — ohne die Spalte crasht der `positions`-INSERT, das darf nicht von einem manuell angestoßenen Migrationslauf abhängen.

### Änderung 2: `signal_manager.py`

**`compute_sl_tp()` — neuer zentraler Helper.** Die SL/TP-Formel wird jetzt an drei Stellen gebraucht (Live-Entry, `would_sl`/`would_tp` beim Block, Shadow-Simulation). Läge sie mehrfach vor, würden Live- und Shadow-Pfad bei der nächsten Änderung auseinanderdriften und die Kohorten-Auswertung wäre **still falsch**. Der Live-Entry nutzt jetzt denselben Helper — Formel unverändert, nur zentralisiert.

**`log_blocked_entry()` — Shadow-Logger.** Schreibt beim Block: Kurs, `would_entry` (inkl. Slippage), `would_sl`/`would_tp`, ATR, asset_type, Conviction, tech_score, Crabel-State, verfehltes Breakout-Level. Reines Logging; breites `except`, damit ein Logging-Fehler nie den Entry-Loop stoppt.

**Gate umgebaut:** `get_crabel_patterns()` wird jetzt **immer** aufgerufen — auch bei `crabel_gate_mode="off"`. Der State wandert als `crabel_at_entry` in `positions` und ist die Basis der Kohorten-Auswertung. Kostet nichts (Preis-Cache ist durch `get_current_price_and_atr()` bereits gefüllt).

### Änderung 3: `crabel_shadow_eval.py` (neu) — Forward-Pricing

Läuft täglich nach der Trading-Pipeline und bepreist geblockte Kandidaten vorwärts, sobald sie den Horizont erreicht haben (`crabel_shadow_horizon_days`, Default 21 Kalendertage ≈ 15 Handelstage — deckt die im Post-Mortem produktive Haltedauer von 8–14 Tagen ab).

**Die Simulation spiegelt die Live-Exit-Logik aus `active_exit_check`:**
- AKTION 2 (Profit-Lock ab `profit_lock_atr`) und AKTION 3 (Trailing ab `profit_lock_atr`) sind nachgebildet. **Ohne das würden die Shadow-Trades ihre Gewinner zu oft bis zum vollen TP laufen lassen und systematisch besser aussehen als die echten Trades → Bias *gegen* das Gate.**
- SL/TP-Treffer auf Intrabar-Extremen (High/Low), SL-Nachführung auf Close-Basis — wie das EOD-laufende `active_exit_check`.
- **Intrabar-Ambiguität** (SL *und* TP im selben Tagesbar getroffen): SL gewinnt. Tagesbars sagen nicht, was zuerst kam; die konservative Annahme verhindert geschönte Shadow-Ergebnisse.
- `pnl_pct_sim` ohne Commission — konsistent zu `positions.pnl_pct`. Größen-invariant, damit keine Sizing-Annahmen nötig sind.

**Bekannte Vereinfachungen (bewusst):** kein Partial-TP, keine Thesis-Exits, kein Breaking-News-Exit. Der Vergleich ist **richtungsweisend, nicht exakt**.

**`later_entered` — der eigentlich interessante Teil.** Das Gate wirft den Kandidaten nicht weg, er bleibt auf der Watchlist. Die echte Alternative zum geblockten Entry ist also nicht „kein Trade", sondern „Entry ein paar Tage später zum bestätigten Kurs". Genau das misst das Feld (Entries nur innerhalb des Horizonts zählen — ein Entry drei Monate später hat mit dem Setup nichts mehr zu tun).

### Änderung 4: `weekly_review.py` — `crabel_cohort_review()`

Drei Kohorten:

| Kohorte | Quelle |
|---------|--------|
| **A)** Breakout bestätigt (real) | `positions` mit `crabel_at_entry.contraction = true` |
| **B)** Kein Pattern (real) | `positions`, Gate war nicht scharf |
| **C)** Vom Gate geblockt (Shadow) | `blocked_entries` mit `eval_status='evaluated'` |

Die Kernfrage beantwortet **C**: Hätten die geblockten Trades Geld verdient → Gate kostet Performance. Verloren sie → Gate hilft.

**`MIN_COHORT_N = 30`:** Unterhalb wird ausgegeben, aber **nicht interpretiert** („Sample x/30 – keine belastbare Aussage"). Keine automatische Config-Anpassung — bei N<30 wäre jede Parameter-Änderung Rauschen-Verfolgung.

`crabel_cohort_review(con)` ist in `main()` verdrahtet.

### Deployment

```bash
# Zielpfade
utils.py, config.py               → trading root
signal_manager.py, weekly_review.py, crabel_shadow_eval.py,
migrate_add_crabel_tracking.py    → trading/scripts/

cd /root/.hermes/profiles/hermes_trading/skills/trading
python3 scripts/migrate_add_crabel_tracking.py
```

**Neuer Cron-Eintrag** (nach der Trading-Pipeline, mit Puffer):
```
30 6 * * 1-5  cd /root/.hermes/profiles/hermes_trading/skills/trading && \
              python3 scripts/crabel_shadow_eval.py >> data/cron.log 2>&1
```

**Neue Config-Keys:**

| Key | Default | Bedeutung |
|-----|---------|-----------|
| `crabel_shadow_horizon_days` | `21` | Kalendertage Reifezeit vor Auswertung |

### Erwartung
Nach ~8 Wochen liegen ~30+ ausgewertete Shadow-Entries vor. Dann ist **gemessen** beantwortbar, ob das Gate hilft — und Stufe 2 (Auto-Adaption mit Mindest-N, Effektstärke-Schwelle und Hysterese gegen wöchentliches Hin-und-Her) hat eine Datenbasis. Bis dahin: Zwischenstand im `weekly_review`-Output beobachten.

### Nebenbefund (nicht angefasst)
`weekly_review.run_exit_quality_review()` (Zeile ~193) ist definiert, wird aber von `main()` **nie aufgerufen** — Dead Code. Die Funktion schreibt LLM-basierte Exit-Verdicts in eine Reporting-Tabelle. Falls gewollt, wäre ein Einzeiler in `main()` nötig; bewusst nicht in diesem Sprint mitgeändert.

---

## 16.07.2026 — Crabel-Patterns Sprint

### Hintergrund
Adaption der Kontraktions-Patterns aus Toby Crabel, *"Day Trading with Short Term Price Patterns and Opening Range Breakout"* (1990). Kernprinzip: **Volatilitäts-Kontraktion führt zu Expansion** — enge Tage sagen mit erhöhter Wahrscheinlichkeit einen Trendtag voraus. Das Buch ist Intraday-orientiert (ORB mit Buy-Stops ab Eröffnung); Hermes läuft EOD mit Tagesdaten, daher wurden die Patterns auf Daily Bars adaptiert und der ORB als **Bestätigungsprüfung zum Scan-Zeitpunkt** umgesetzt. Passt direkt zum Post-Mortem-Befund vom 15.07.: die 0–3-Tage-Verlusttrades (-1.867€) waren überwiegend Entries ohne Momentum-Bestätigung.

### Pattern-Definitionen (Tagesbasis, letzter ABGESCHLOSSENER Bar)

| Pattern | Definition | Interpretation |
|---------|-----------|----------------|
| **NR4** | Range < min(Range der 3 Vortage) | Kontraktion |
| **NR7** | Range < min(Range der 6 Vortage) | starke Kontraktion |
| **Inside Day (ID)** | High < Vortages-High UND Low > Vortages-Low | Kompression |
| **ID/NR4** | Inside Day + NR4 | Crabels stärkstes Setup |
| **2Bar NR** | engste 2-Tages-Range der letzten 20 Tage | mehrtägige Kompression |
| **Wide Spread (WS)** | Range > 2× 10-Tage-Ø-Range | Expansion **bereits erfolgt** → Entry zu spät |
| **Stretch** | 10-Tage-Ø der Distanz Open → *näheres* Tagesextrem, `min(O−L, H−O)`, geclippt auf ≥0 (Gaps) | Rausch-Puffer für Breakout-Level |

**Breakout-Level (EOD-ORB-Adaption):**
- LONG: `ref_high + stretch` (Vortages-High + Stretch)
- SHORT: `ref_low − stretch` (Vortages-Low − Stretch)

Alle Level in **Heimwährung des Tickers** — konsistent zu `current_price` aus `get_current_price_and_atr()`, keine FX-Umrechnung nötig.

### Änderung 1: `get_crabel_patterns()` in `utils.py`

Neue zentrale Funktion, gibt Dict mit allen Pattern-Flags, `patterns`-Liste (aktive Pattern-Namen für Logging), `stretch`, `ref_high/ref_low` und beiden Breakout-Leveln zurück (oder `None` bei <30 Bars / fehlendem Open / Fehler).

**Wichtige Implementierungs-Details:**
- Nutzt `get_price_data_cached()` → bei bereits geladenem Ticker (z.B. direkt nach `get_technical_score`) **null zusätzliche API-Calls**
- **Partial-Bar-Handling:** Läuft der Handelstag noch (letzter Bar-Index = heute), wird der unfertige Bar für die Pattern-Erkennung verworfen — Range/High/Low eines laufenden Tages sind nicht final und würden NR7/ID verfälschen. Die Breakout-Level referenzieren damit immer den letzten *abgeschlossenen* Tag
- Alle Rückgabewerte sind reine Python-Typen (`bool()`/`float()`-Casts) — numpy-Bools wären **nicht JSON-serialisierbar** und würden `technical_validator.py` beim `json.dump` crashen
- Verifiziert mit synthetischen OHLC-Tests: ID/NR4, WS, 2Bar-NR, neutraler Tag, Stretch-Clip bei Gap-Open

### Änderung 2: Crabel-Bonus als 8. Indikator in `get_technical_score()` (`utils.py`)

Nach dem ADX-Block, **vor** der Normalisierung:

| Bedingung | Score-Wirkung |
|-----------|---------------|
| ID/NR4 | ±1.5 |
| NR7 | ±1.0 |
| NR4 / Inside Day / 2Bar NR | ±0.5 |
| WS-Tag | ∓1.0 (Dämpfung Richtung neutral) |

**Richtungslogik:** Bonus wird nur bei klarem EMA-Stack vergeben (Crabel: Kontraktion *in Trendrichtung* handeln). Bullisher Stack (20>50>200) → Bonus positiv (pro LONG), bearisher Stack → negativ (pro SHORT). **Ohne Stack: kein Bonus** — Kompression ohne Trend ist Rauschen. WS dämpft entsprechend entgegen der Trendrichtung.

**`max_score` bleibt bewusst 10:** Die Summe der Maximal-Gewichte lag schon vorher bei ~9.5 (nicht exakt 10), `confidence` wird ohnehin auf 0–1 geclampt. `max_score` anzuheben würde *alle* Confidences Richtung 0.5 stauchen und die kalibrierten `tech_score`-Schwellen im `signal_manager` (Query-Filter + Regime-Confidence-Tabelle) brechen.

Das `crabel`-Dict wird zusätzlich im Rückgabe-Dict von `get_technical_score()` mitgeliefert (Key `"crabel"`) — landet damit automatisch in `trading_signals_validated.json` und steht Dashboard/Auswertungen zur Verfügung. `watchlist_manager` liest weiterhin nur `confidence` + `direction`, keine Anpassung nötig.

### Änderung 3: Crabel Breakout-Gate in `signal_manager.py` (`open_new_positions`)

**Einbaupunkt:** Nach dem Preis/ATR-Fetch (+ NaN-Check), **vor** VIX-Halving/Sizing — der teuerste Filter läuft damit erst, nachdem alle billigen Gates (Sektor, Korrelation, Liquidität, Earnings, Segment) passiert sind, und nutzt den bereits gefüllten Preis-Cache.

**Logik:**
```
gate_mode == "contraction" (Default):
    Gate greift NUR wenn der letzte abgeschlossene Bar ein
    Kontraktions-Pattern war (contraction == True).
    → verhindert Entries MITTEN in der Kompression:
      LONG  nur wenn current_price >= ref_high + stretch
      SHORT nur wenn current_price <= ref_low  − stretch
    Nicht bestätigt → skip mit 📏-Log; Kandidat bleibt auf der
    Watchlist und wird beim nächsten Lauf erneut geprüft.
gate_mode == "always": Gate bei JEDEM Entry (restriktiv, senkt Frequenz)
gate_mode == "off":    deaktiviert
```

Bei bestätigtem Breakout nach Kontraktion wird `📏 Crabel-Breakout bestätigt nach [Pattern] ✓` geloggt — auswertbar für spätere Performance-Analyse (Crabel-bestätigte vs. normale Entries).

**Neue Config-Keys** (`strategy_config.json`, Defaults in `DEFAULT_CONFIG`):

| Key | Default | Bedeutung |
|-----|---------|-----------|
| `crabel_gate_mode` | `"contraction"` | `off` / `contraction` / `always` |
| `crabel_stretch_len` | `10` | Lookback für Stretch-Berechnung (Tage) |

`load_config()` merged fehlende Keys automatisch aus `DEFAULT_CONFIG` — **keine Migration nötig**, bestehende `strategy_config.json` funktioniert unverändert.

### Erwartung & Verifikation
- Weniger Entries in Seitwärts-Kompression (die 22,9%-WR-Kohorte der 0–3-Tage-Trades), Entries dafür mit Momentum-Bestätigung
- Kontrollpunkte: 📏-Zeilen in `cron.log`; Verhältnis "warte auf Bestätigung" vs. "Breakout bestätigt"; nach ~4 Wochen WR-Vergleich Crabel-bestätigter Entries
- Backtest über `backtester.py` empfohlen (Mai vs. Juni wie beim Post-Mortem)
- Rollback jederzeit ohne Deployment: `"crabel_gate_mode": "off"` in `strategy_config.json` (Score-Bonus in `get_technical_score` bleibt dann trotzdem aktiv)

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
- Backtest der neuen Parameter auf historischen Daten (Mai vs Juni)
- Short-Trade-Regel: aktuell 28,6% WR — prüfen ob Shorts im Sideways pausiert werden sollen