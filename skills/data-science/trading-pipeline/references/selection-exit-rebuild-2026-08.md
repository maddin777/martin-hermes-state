# Selection + Exit Rebuild (2026-08-27) — Review-Findings, Architektur, Pitfalls

## Warum (6-Monats-Review-Befund, aus Live-DB)

Bot lief 6 Monate mit ~0 Profit. Root-Cause aus `positions`-DB (81 geschlossene):
- WR 40,7 % / **Payoff 0,91 (<1 = Killer)** / EV −14,4 €/Trade
- 66 SL_HIT vs 9 TARGET_HIT → SL_HIT-Quote 81 %
- Alpha vs SPY YTD: **−20 pp** (SPY +12,7 % bei Portfolio −7,3 %)
- Regime-Detektor monatelang "bull" obwohl Juni/Juli real Chop → Label war self-fulfilling
- `signal_source` bei 80/81 Trades leer → P&L keiner Quelle zuordenbar (Feedback-Loop kaputt)

**Kern-Aussage (durch Backtest belegt):** Die Selection aus LLM-extrahiertem
Influencer-Sentiment ist **negativ-EV unabhängig vom Exit**. Ein Exit-Fix allein macht
den Bot NICHT profitabel; er verbessert nur die Verluste.

## Varianten-Backtest auf realen Trades (`scripts/backtest_variants.py`)

Neues Script: simuliert alternative Exit-/Signal-Logik auf den **tatsächlich gehandelten**
geschlossenen Positionen (kein Lookahead — ATR/R am Entry-Tag, OHLC danach).
- **Variante C (1R/3R + 7d-Zeitstopp + Peak-Chandelier 2×ATR ab +1R):** verbessert die
  46 sauberen Trades um ~+700 € (−2.802 → −2.088 €), Payoff 3.07. **ABER WR kollabiert auf
  7 %: nur 3/46 erreichen +3R, 43× SL** → der Exit ist NICHT das Kernproblem, die Selection ist es.
- **Variante B (Crowd-Veto via mention_count ≥ 5):** hilft nicht — crowded −482 € vs quiet
  −699 €, beide negativ. Crowd-Mention ist NICHT der Differenzierer. → NICHT als Gate bauen.
- **Caveat:** 36/82 Trades NO_DATA (delisted/Exoten-Suffixe .F/.MU/.SG), die fehlenden waren
  überproportional Gewinner (+1.620 € real) → C-Ergebnis ist **konservativ**.
  `mention_count` ist AKTUELL, nicht Point-in-Time.

## Umsetzung (in 2 Finn-loop Tasks, beide review-approved)

**Task 1 — Selection/Momentum-Gate** (`selection-momentum-gate.md`):
- `signal_manager.entry_gate_reason()`: LONG verlangt `weekly_trend='bullish'` UND
  `tech_direction='LONG'`, SHORT analog bearish+SHORT → sonst `momentum-gate`.
  Wird VOR allen nachgelagerten Entry-Checks via `log_blocked_entry()` persistiert.
- **News-Sentiment degradiert**: von Entry-Auslöser zu Ranking-Stärke NACH Gate-Pass.
- **Liquiditätsfilter strikt**: `get_technical_score()` verlangt ≥200 Bars + ≥500k€
  20-Tage-Ø-Turnover (auf ALLE Ticker vereinheitlicht, vorher nur `.L`); Exoten-Suffixe
  nicht gemappt = `liquidity-gate`.
- Historische Näherung: **~80 % der LONG-SL_HITs wären eliminiert worden.**

**Task 2 — Exit-Asymmetrie** (`exit-asymmetry.md`):
- TP-Matrix überall **exakt 3:1** (SL unverändert, TP=3×SL) — Martins Entscheidung.
- 7-Handelstage-Zeitstopp (`TIME_STOP`), Peak-/Trough-Chandelier (ratchet nur in
  Gewinnrichtung), `profit_lock` armt erst ab +1R.
- Gemeinsame Regeln in neuem `exit_rules.py`; alle 3 Pfade
  (signal_manager/active_exit_check/crabel_shadow_eval) konsistent — kein paralleler-Pfad-Drift.
- AC-7-Regression: C-PnL −2.094 € auf 47 Trades vs Grenze −2.088 € → −6 € ist **Rausch**
  (47 vs 46 saubere Trades / delisted Ticker). Martin gab ±10 € Rauschtoleranz.
  Merke: Backtest-Variante-C-Zahl hängt an Datenabdeckung; kleine Abweichung ≠ Code-Regression.

## Guardrail-Punkt (Punkt 1 des Reviews)

- **Der Bot hat KEINEN Echtgeld-Pfad** (kein Broker-Modul, schreibt nur Positions-Tabelle = Paper).
  Guardrail explizit: `strategy_config.json` → `"operating_mode": "paper_experiment"`.
- Regelbasierte Trend-Edge-Systeme (Amumbo-SMA200-Cron, Forex-Paper-Bot) laufen parallel.

## Pitfalls (neu dokumentiert)

1. **profit_lock_atr Drift (orphan display drift):** Execution war konsolidiert (alle 3 Pfade
   lesen `get_exit_config`, Matrix 1.0 — geprüft: KEINE echten `get_asset_multipliers(`-Aufrufe),
   ABER `profit_lock_atr` lebte verwaist als `0.5` in `strategy_config.json` UND `DEFAULT_CONFIG`
   (signal_manager). `backtest_gate.py`/Dashboard zeigten "0.5×". Fix: beide → 1.0 (SSOT=Matrix).
   **Bei Exit-Parameter-Fragen IMMER alle 4 Quellen greppen**: `strategy_config.json`,
   `DEFAULT_CONFIG`, `DEFAULT_EXIT_CONFIG`, `_EXIT_CONFIG_MATRIX`.
2. **Telegram parse_mode=HTML scheitert an nackten `<`/`>`**: "SL_Quote < 60%" → "Unsupported
   start tag at byte offset …" HTTP 400. Fix: `html.escape()` der rohen Daten + Formulierung
   "unter/über" statt `<`/`,`>`. Betrifft nightly_eval + Trading-Report-Crons gleichermaßen.
3. **Ratios normalisieren, bevor man eine Matrix "aggressiv" nennt:** Der coder-Bot hob TECH
   bear TP auf 7.5× ATR — das sah alarmierend aus, ist aber 3× des SL (2.5) = exakt 3:1, der
   validierte Punkt. Beim Bewerten von TP-Werten IMMER durch den SL normalisieren (eigentlich
   Entscheidungs-Framing-Fehler des Orchestrators, kein Code-Bug).
4. **Finn-loop auf Trading-Änderungen anwenden:** Strategie-Umbauten (Entry/Exit/Selection)
   als Spec→Build→Review (finn-spec/build/review) laufen lassen statt direkt in den Live-Exit zu
   patchen — verhindert parallelen-Pfad-Drift-Wiederholung (09.08./16.08.-Muster).

## Nächster Schritt (Task 3, in-progress)

**Nasdaq-Screener** (`screener-nasdaq.md`): erweitert `screener_source.py`-Universum
(Nasdaq-100 + ~500 liquide US-Growth/Mid-Caps, ca. 600 Ticker als `data/us_universe.csv`),
mit **2-stufigem Liquiditäts-Prefilter**: Stage 1 (billig) ~600→≤400, Stage 2 (voller Screen) nur
Überlebende. Neue Quelle `screener_nasdaq` in source_registry/watchlist_mentions, damit P&L nach
Quelle messbar. Grund: bestehender Screener scannt nur DAX40+MDAX+SP100+DB-Unternehmen (~340,
gecapped 250) — kein Nasdaq, genau die Momentum-Hotspots die Social zu spät/crowded liefert.
Momentum-Scan wird Primary-Source, Social nur Bestätigung.
