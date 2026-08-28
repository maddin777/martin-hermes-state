# Backtest-Variants: Selection vs. Exit isolieren

## Zweck
Wenn ein Trading-System monatelang negativ-EV ist, ist die entscheidende Frage
**"Ist die Selection (Entries) das Problem oder der Exit?"**. Parameter-Tuning
auf synthetischen Daten beantwortet das nicht. Die bewährte Methode: den
**counterfactual Backtest auf den REALEN geschlossenen Trades** fahren.

Script: `scripts/backtest_variants.py` (2026-08-27, im Trading-Profil).

## Methode
1. **Nimm die real gehandelten, geschlossenen Positionen** aus `positions`
   (ticker, direction, entry_date, entry_price, stop_loss, position_size,
   richtiger pnl_eur, exit_reason). JOIN `watchlist` für `mention_count`/`aged`.
2. **Kein Lookahead:** ATR & R werden aus Bars am Entry-Tag berechnet,
   OHLC-Pfade NACH dem Entry simuliert. Entry-Preis/SL bleiben die realen.
3. **Simuliere alternative Exit-/Signal-Logik** auf exakt denselben Entries und
   vergleiche reales vs. alternatives P&L auf **denselben** Trades.
4. Aggregiere: WR, Ø-Gewinn/Verlust in R, Payoff (avg_win/|avg_loss|),
   EV in R/Trade, Exit-Reason-Verteilung.

Da alle Varianten dieselben Entries nutzen, misst der Unterschied NUR die
Exit-Mathematik — Signal-Verzerrung ist eliminiert.

## Variante C — Exit-Asymmetrie (1R/3R + Zeitstopp + Chandelier)
- Ziel 3R, Risiko 1R; Zeit-Stopp ~7 Handelstage (Exit via `TIME_STOP` wenn das
  Ziel nicht erreicht wird); Peak-Chandelier-Trailing (ratcheting Stop vom
  laufenden Hoch/Tief minus `chandelier_mult × ATR`), profit_lock erst ab +1R.
- **07.08.2026-Befund (81 reale Trades):** C verbessert die 46 sauberen Trades
  um ~+700 € (−2.802 € → −2.088 €), Payoff 3.07 (avg_win 3.0R, avg_loss −1.0R).
  **ABER WR kollabiert auf 7 % — nur 3/46 erreichen +3R, 43× SL.**
- **Schlussfolgerung:** Der Exit ist NICHT das Kernproblem. Wenn selbst ein
  sauberer 1R/3R-Exit 93 % der Entries als SL enden lässt, hat das Signal
  keinen Selektions-Edge — unabhängig von der Exit-Mathematik. Das ist der
  Beweis, dass der **Umbau der Selection** vorgehen muss.

## Variante B — Crowd-Veto (mention_count ≥ 5)
- Entries mit hoher Mention-Count weglassen (Retail-Crowd-Veto).
- **Befund:** hilft nicht — crowded −482 € vs quiet −699 €, beide negativ.
  Crowd-Mention ist kein Differenzierer.

## Pflicht-Caveats (SONST falsches Ergebnis)
1. **NO_DATA/delisted:** Exoten-Suffixe (`.F`, `.MU`, `.SG`) und delistete
   Ticker haben keine Preisdaten → `NO_DATA`. Diese sind NICHT gleichmäßig
   verteilt: 36/82 historische Trades, überproportional GEWINNER (+1.620 € real
   in der 2026-08 Analyse). **Ohne Aufschlüsselung ist das C-Ergebnis
   verzerrt** — immer simuliert-vs-NO_DATA trennen.
2. **`mention_count` ist AKTUELL, nicht Point-in-Time** am Entry → Variante-B
   ist eine Näherung, keine echte Selektion.

## Verifikation
- Vor dem Urteil die Aufschlüsselung rechnen (simuliert vs. NO_DATA, reale
  P&L der NO_DATA-Trades), nicht nur den Gesamt-Wert.
- Standard-Fall: der "sauber" simulierten Trades unterscheiden von den
  NO_DATA-Trades — beide real-Spalte zeigen, welcher Satz das Signal trägt.
