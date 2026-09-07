# Momentum-Swing Alternative + Volume-Confirmation Backtest (06.09.2026)

Context: A viral "full swing trading strategy" Twitter post was evaluated against the
current system. The strategy is momentum-swing of market leaders (strength → theme →
sector → stock, weekly context, tightness/Crabel, volume confirmation, multi-stage
scaling + EMA-trail exit). Documented for Martin as a FALLBACK only if current
strategy underperforms in coming weeks. Full copy lives in the live trading dir:
`/root/.hermes/profiles/hermes_trading/skills/trading/alternative-strategy-momentum-swing.md`.

## Mapping: post vs. current system

| Post principle | Current system | Gap |
|---|---|---|
| Market cycle / sit in cash | regime_history + graduated drawdown | none |
| Leader/top-down | theme-pipeline + sector cap 70% | none |
| Weekly = context gate | weekly_trend hard entry gate | none |
| Tightness (flags/bases/Crabel) | Crabel NR7/inside-day in tech_score | none |
| Volume confirmation | only a +1.5 score bonus, NOT a gate | **candidate** |
| Scaling out multi-stage | only 1 tranche (50% @ +1.5 ATR) | exit differs |
| EMA 8/21/50 trail | Donchian/Chandelier exit | different exit |

## Guardrail (important)

Do NOT adopt the post's exit structure (multi-stage scaling + breakeven + EMA trail).
It would re-introduce the parallel-exit-path pattern that the 09.08/16.08
`get_exit_config()` consolidation removed — the exact cause of the July -18% drawdown.
Any future adoption must be backtested first, never a live swap.

## Volume-confirmation backtest (the ONE tested gap)

Method: extended `scripts/backtest_variants.py` with a "Variant D" that checks, on the
REAL 84 closed positions, whether the entry-tag volume exceeded `boom_mult × 20-day-avg`
(breakout-confirmation rule). Blocked low-volume entries are removed and the PnL recomputed.

Result (84 real closed positions, boom_mult=1.5):
- 73 of 84 entries would have been BLOCKED by low volume.
- Those 73 carried real PnL **-1445 €** (44 losing trades avoided, 29 winners missed).
- The 11 volume-confirmed entries were **+184 €** (real PnL).
- Net: -1261 € → +184 € if the gate had been active (+1445 € swing).

Caveats / honest read:
- **Very thin sample**: only 11/84 survive → the 1.5× rule is far too strict for live use
  (would reject ~87% of candidates).
- +184 € over 11 trades is not statistically strong (huge CI). The Variante-C re-sim of
  those 11 shows WR 0% — the edge was not entry quality, it was that the 73 blocked ones
  happened to be the worst historical losers (retrospective bias).
- **Plausible next step if pursued:** sweep the threshold (1.1×/1.2×/1.3×/1.5×) and/or
  apply volume as a score-BOOST (not a hard gate) so it does not starve the pipeline.
- Lesson reused from backtest_variants.py: it tests ALTERNATIVE logic on real closed
  positions (no signal lookahead; ATR/1R at entry, OHLC simulated forward). To add a new
  variant: add a `simulate_variant_X()` returning (blocked/exit, reason), accumulate in
  the trade loop, and aggregate in main(). Bars now carry `volume`.

## Current tech_score volume treatment (the gap in one line)

Volume is: hard liquidity gate (min turnover) + score bonus (+1.5 if vol5 > 1.5×vol20,
+1.0 if >1.2×). It does NOT disqualify a low-volume breakout, and does NOT check that the
consolidation/base formed on falling volume. That is the specific, untested improvement
the post points at.
