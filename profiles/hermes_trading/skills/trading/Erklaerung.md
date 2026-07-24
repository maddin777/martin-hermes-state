# Änderungshistorie — Trading Skill

**Stand:** Paketen A–D + Sprints 1–7 + Bugfix-Sprint + Screener-Source + Watchlist-Performance-Fix + Rollen-Sprint R1–R4 + **Turtle-Konfluenz-Sprint**

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
"devils_advocate":   "deepseek/deepseek-v4-flash",
"extractor_analyst": "deepseek/deepseek-v4-flash"
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
- Backtest der neuen Parameter auf historischen Daten (Mai vs Juni)
- Short-Trade-Regel: aktuell 28,6% WR — prüfen ob Shorts im Sideways pausiert werden sollen