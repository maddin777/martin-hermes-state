# Änderungshistorie — Trading Skill

**Stand:** Paketen A–D + Sprints 1–7 + Bugfix-Sprint + Screener-Source + Watchlist-Performance-Fix + **Rollen-Sprint R1–R4**

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
"committee_bull":    "deepseek/deepseek-v4-flash",
"committee_bear":    "qwen/qwen3.5-flash-02-23",
"committee_risk":    "google/gemini-2.5-flash-lite",
"devils_advocate":   "deepseek/deepseek-v4-flash",
"extractor_analyst": "deepseek/deepseek-v4-flash"
```
Bull und Bear MÜSSEN verschiedene Provider sein — sonst widerlegt sich das Modell nur selbst mit denselben Biases. `grok-lite` bewusst NICHT fürs Committee (wird vom Breaking-News-Check genutzt, Rate-Limits schonen).

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
- Backtest der neuen Parameter auf historischen Daten (Mai vs Juni)
- Short-Trade-Regel: aktuell 28,6% WR — prüfen ob Shorts im Sideways pausiert werden sollen