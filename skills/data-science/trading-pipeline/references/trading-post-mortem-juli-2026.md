# Trading Post-Mortem — 25.04. bis 15.07.2026

## Ausgangsdaten
- 75 Trades gesamt (69 geschlossen, 6 offen)
- Zeitraum: 25.04.2026 – 15.07.2026
- Total P&L: -839,95€ | Win Rate: 43,5%
- Avg Win: +62,88€ | Avg Loss: -69,91€ | G/L Ratio: 0,9x

## Killer #1: Haltedauer
| Haltedauer | Trades | Total P&L | Win Rate |
|------------|--------|-----------|----------|
| 0-3 Tage | 35 | -1.867€ | 22,9% |
| 4-7 Tage | 21 | +664€ | 57,1% |
| 8-14 Tage | 13 | +363€ | 76,9% |

35 von 69 Trades (51%) werden innerhalb von 3 Tagen geschlossen. 77% davon sind Verluste. Der Trailing Step triggert zu früh.

## Killer #2: Exit-Verteilung
| Exit Reason | Anteil | Avg P&L |
|-------------|--------|---------|
| SL_HIT | 75% | +1,21€ |
| TECH_BROKEN | 6% | stark negativ |
| TARGET_HIT | 1,5% | +74€ |

75% der Trades enden im SL. 0% TP_HIT ist abnormal. Bei 1,5x SL / 2,5x TP sollten ~40% TP erreichen.

## Killer #3: Monats-Effekt (Regime)
| Monat | Trades | Total P&L | Win Rate |
|-------|--------|-----------|----------|
| April | 6 | -79€ | 50% |
| Mai | 24 | +1.179€ | 70,8% |
| Juni | 32 | -1.480€ | 31,3% |
| Juli | 7 | -459€ | 0% |

Mai (Bull) profitabel, Juni (Sideways) katastrophal. Strategie hat Regime nicht erkannt.

## Quellen-Qualität
**Top (positiver P&L):**
- ticker symbol: you (+108€/Trade, 53% WR)
- markus koch closing bell (+73€/Trade, 57% WR)
- techaktien (+17€/Trade, 58% WR)

**Flop (negativer P&L):**
- financial education (-113€/Trade, 16% WR)
- meet kevin (-64€/Trade, 21% WR)
- moritz hessel (removed, -88€/Trade, 0% WR)

## Umsetzung (15.07.2026)
1. **Trailing-Delay:** Trailing erst ab +2x ATR (active_exit_check.py)
2. **P&L-Weighting:** adjust_weights() auf avg_pnl_per_trade (source_lifecycle.py)
3. **Regime-Adaptive:** adapt_strategy() setzt Regime-Basis vor Trade-Anpassungen (signal_manager.py)