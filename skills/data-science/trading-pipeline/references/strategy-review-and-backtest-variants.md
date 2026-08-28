# Strategy Review & Backtest-Varianten auf realen Trades

Entstanden aus dem 6-Monats-Review (2026-08-27): Der Bot war negativ-EV
(−1.165 € auf 81 Trades, WR 40,7 %, Payoff 0.91 <1 = Killer). Die Analyse
hat zwei wiederverwendbare Werkzeuge/Patterns hervorgebracht.

## 1. `backtest_variants.py` — Exit-/Signal-Varianten auf den REAL gehandelten Positionen

Statt die Backtesting-Engine auf synthetischen Signalen laufen zu lassen,
simuliert dieses Script alternative Exit-/Signal-Logik auf den **tatsächlich
gehandelten** (geschlossenen) Positionen aus `positions`.

- **Eingabe:** echte `entry_price`, `stop_loss`, `position_size`, `direction`
- **Kein Lookahead:** ATR(14) wird am Entry-Tag aus Bars VOR dem Entry berechnet;
  OHLC-Pfad (high/low/close) danach simuliert.
- **1R** = geplantes Risiko `|entry − stop_loss|`. Ziel `rr × 1R`, Zeit-Stopp,
  Peak-/Trough-Chandelier.
- **Verwendung:** welcher Anteil der historischen Verluste wäre eliminiert
  worden / welchen Payoff hätte eine bessere Exit-Mathematik auf DENSELBEN
  Entries erzielt (testet Exit, nicht Signal — die Selection bleibt separat).

```bash
cd /root/.hermes/profiles/hermes_trading/skills/trading
PYTHONPATH=. /root/.pyenv/versions/3.12.13/bin/python3 scripts/backtest_variants.py
```

**Caveat (wichtig!):** Viele historische Trades (36/82) fallen als `NO_DATA`
heraus (delisted / Exoten-Suffixe `.F`/`.MU`/`.SG`) und die fehlenden waren
**überproportional Gewinner** → das C-Ergebnis war konservativ. Bei kleinen
Stichproben (46-47 Trades) ist die Zahl rauschanfällig: Ein Trade mehr mit
`NO_DATA`-Status verschiebt das Ergebnis um ~6 €. **Regressions-Grenzen immer
mit ±10 € Rauschtoleranz ansetzen**, nicht scharf.

## 2. `weekly_strategy_review.py` + Cron — Post-Umbau-Performance-Tracking

Wöchentlicher Report der Kennzahlen, die entscheiden ob ein Strategie-Umbau
echten Edge erzeugt:
- SL_HIT-Quote (Ziel < 60 %), Payoff (Ziel > 1.5), EV/Trade, Win-Rate
- Momentum-Gate-Blockaden (COUNT aus `blocked_entries WHERE gate='momentum-gate'`)
- Vergleich "vor/nach" dem Umbau-Cutoff

**Datenquelle:** `positions` live ausrechnen — NICHT `eval_metrics.avg_r_multiple`
(das ist 0.0/unbrauchbar und wird nie gepflegt).

**Cron:** Hermes-Cron `weekly-strategy-review` (b907fdfdba5c), So 09:00, no_agent,
Wrapper `~/.hermes/scripts/weekly_strategy_review.sh` (Konvention: chdir +
PYTHONPATH + `.env`-export, fester pyenv-Python).

## 3. Finn-loop-Muster für Trading-Änderungen

Der 6-Monats-Review-Umbau lief sauber über den Finn-loop als **zwei getrennte
Tasks** (Selection/Momentum-Gate und Exit-Asymmetrie), NICHT als ein
Riesen-Task. Grund: beide fassen `signal_manager.py` an. Sequenz Build von
Task 2 erst nach review-approval von Task 1 (Überlappung vermeiden).

Für Strategie-Änderungen am Trading gilt: Erst mit `backtest_variants.py` /
`backtest_gate.py` validieren, dann Finn-loop-Spec (mit AC-Regressions-Grenzen
+ Rauschtoleranz), Build via coder-Bot, Review via reviewer-Bot. Merge-Entscheid
liegt bei Martin; der coder schreibt direkt in die Live-Profil-Dateien (kein
Branch/PR-Repo) → "review-approved" = effektiv live in der Nacht-Pipeline.

## 4. Payoff-Ratio IMMER durch den SL normalisiert betrachten

Die TP-Matrix des coder-Bots zeigte "bis 7.5× ATR" — alarmierend, bis man
erkennt: 7.5 = `3 × SL(2.5)` = exakt **3:1**. Absolute TP-Multiplikatoren ohne
SL-Normalisierung sind irreführend. Bei Review von Exit-Parameter-Änderungen
immer das **TP:SL-Verhältnis** prüfen bzw. so kommunizieren, nie nur die
absoluten TP-Zahlen.
