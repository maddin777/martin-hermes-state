# Alternative Swing-Strategie (Momentum Swing — Stand 06.09.2026)

**Quelle:** Twitter-Post (Momentum-Swing-Trader). **Status:** Doku/Alternative — NICHT implementiert.
Wird nur als Fallback herangezogen, falls die aktuelle Strategie in einigen Wochen schlecht performt.

## Kern-These
Handel die **stärksten Aktien** in den **stärksten Themen** in den **stärksten Markt-Umgebungen**.
Strength → Momentum → Continuation. Nicht jeden Tag handeln — in CASH sitzen wenn Markt choppt.

## Die 5 Schritte

### 1. Market Cycle (Regime)
4 Stadien: Basing/Accumulation → Advancing/Markup (Stage 2 = Geld verdienen) → Topping → Declining.
Stage 2 ist wo man aggressiv ist. Wenn Breakouts scheitern / kein Follow-through / Markt choppt → CASH.
"Du wirst nicht dafür bezahlt, wie viele Trades du nimmst."

### 2. Leader finden (Top-Down)
Starker Markt → starkes Thema → starker Sektor → führende Aktie → bestes Setup.
Geld folgen, WO es schon fließt, nicht WO es hingehen könnte. TradingView Industries-Sortierung:
Sektor/Industrie in Top-10 auf Monats UND Wochen-Basis = starkes Thema validieren.

### 3. Weekly → Daily (Context zuerst)
Weekly = KONTEXT: große Basen, Preis nahe Hochs, wenig Widerstand, starke relative Stärke, gesunde Trends.
Daily = Setup. Größte Moves kommen aus Aktien die in massiven Weekly-Basen aufbauen (Institutions-Akkumulation).
**TIGHTNESS ist der Schlüssel:** Flags, Wedges, Inside Days, Basen, MA-Pullbacks, Breakout/Retests.
Volatilität kontrahiert VOR Expansion. Ziel: das "Fleisch" des Moves fangen, nicht Bottom/Top timen.

### 4. Volume (Qualitäts-Urteil)
- EXPANSION → hohes Volumen
- CONSOLIDATION → niedrigeres Volumen (gesunde Basis)
- BREAKOUT → Volumen kehrt zurück
Price sagt was passiert, Volume wie gut. Sieben Wahrscheinlichkeits-Stapel VOR Entry:
✓ Markt günstig ✓ starkes Thema ✓ Leader ✓ starkes Weekly ✓ tight Daily ✓ gesunder Trend ✓ Volumen-Bestätigung

### 5. Trade Plan + Scaling out
Plan VOR Position: Trigger, wo falsch, Risiko, Profit-Ziele. Nie ganzen Slot auf einmal verkaufen:
1. **Trim 25%** in erstes Ziel (auf Stärke, an Widerstand)
2. **Stop auf Breakeven** → Trade risikofrei
3. **Trim auf Extension** (~3× ATR von der 8-EMA)
4. **Trail die EMAs** (8/21/50): Stück verkaufen bei Schluss unter MA (Daily)
Wichtig: Bei Breakouts soll Aktie NICHT zum Entry zurückkommen (stärkste Namen "locken aus").

## Mapping zum aktuellen System (06.09.2026)
| Post | Unser System | Lücke? |
|------|--------------|--------|
| Market Cycle / CASH | ✅ regime_history + Drawdown-Graduierung | — |
| Leader/Top-Down | ✅ Theme-Pipeline + Sektor-Cap 70% | — |
| Weekly Kontext-Gate | ✅ weekly_trend harter Entry-Gate | — |
| Tightness (Crabel) | ✅ Crabel NR7/inside-day im Tech-Score | — |
| Volume Bestätigung | ⚠️ nur Score-Bonus (+1.5), kein Breakout-Gate | **mögliche Lücke** |
| Scaling out | ⚠️ nur 1 Tranche (50% @ +1.5 ATR) | **Exit anders als Post** |
| EMA 8/21/50 Trail | ❌ nutzt Donchian/Chandelier | **anderer Exit** |

**Wichtig:** Der Exit-Teil des Posts (mehrstufiges Scaling + Breakeven + EMA-Trail) würde die konsolidierte
`get_exit_config()`-Struktur aufbrechen (parallele-Pfade-Risiko). Deshalb NUR als Alternative dokumentiert,
nicht eingebaut. Sollten wir die Alternative testen: zuerst als eigener Backtest, nicht Live-Swap.
