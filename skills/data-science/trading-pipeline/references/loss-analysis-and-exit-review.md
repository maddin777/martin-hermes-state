# Verlustanalyse & Exit-Review (09.08.2026) — Methode + Zahlen

## Warum diese Analyse
Der Trading-Skill lief historisch mit 77 geschlossenen Trades bei -1.230€. Mehrere
Fixes wurden daraus abgeleitet. Diese Datei konsolidiert die METHODE (nicht nur das
Ergebnis) plus die verifizierten Zahlen, damit zukünftige Reviews vor denselben
Analyseschritten nicht neu erfinden müssen.

## Analyseschritte (Methode — reproduzierbar)
1. **Exit-Verteilung** zuerst:
   `SELECT exit_reason, COUNT(*), AVG(pnl_eur), SUM(pnl_eur) FROM positions WHERE exit_date IS NOT NULL GROUP BY exit_reason`
2. **Gewinner vs. Verlierer trennen** (nicht Exit-Reason verwechseln!):
   `CASE WHEN pnl_eur>0 THEN ... ELSE ... END`
3. **Winrate NIE aus der TARGET_HIT-Zahl ableiten** — die echte Winrate ist
   `Gewinner/alle geschlossenen`, nicht `TARGET_HIT/alle`.
4. **Payoff = Ø Gewinn / Ø Verlust** — vergleiche mit nötigem
   `BreakEvenueWR = 1/(1+Payoff)`. Ist Payoff < 1, ist der Fokus auf "Verluste
   verkleinern" (Payoff erhöhen) oder "Gewinner laufen lassen" — NICHT auf Winrate
   jagen.
5. **Slippage pro Trade**: bei LONG `(stop_loss-exit)/stop_loss*100`, bei SHORT
   `(exit-stop_loss)/stop_loss*100`. Hohe Slippage (>3%) = Gap-Exit (Overnight),
   nicht normaler SL.
6. **Tag-0-Exits** (`date(exit)=date(entry)`): verdächtig auf Earnings-/
   Makro-Event-Gap am Einstiegstag.

## Verifizierte Zahlen (Stand 09.08.2026)
- **Reale Winrate: 30/77 = 39%** (NICHT 10.4% — 10.4% = nur TARGET_HIT-Zahl 8/77)
- Gewinner: 30, Ø +62.88€
- Verlierer: 47, Ø -66.31€
- **Payoff = 0.95 < 1** → Break-Even-WR nötig ≈ 51% bei diesem Payoff. Bei 39% WR
  ist der Fokus auf Gewinner-Exit (Payoff erhöhen), nicht auf Winrate.
- Slippage-Anteil am Verlust ca. 36% (geschätzt), konzentriert auf wenige Gaps:
  Korea-ADRs (000660.KS), Crypto-Miner (MARA), hochvolatile (CRWD, ANET).
- 8 echte TARGET_HIT-Winner erreichten alle ~100-130% ihres TP → das TP ist
  erreichbar; Winner wurden durch zu enges Trailing/Breakeven abgewürgt.

## Kern-Ursachen (Rang)
1. **Gewinner abgeschnitten**: Partial-TP bei 1.5x ATR nahm 50%, zog SL auf
   Breakeven → der Rest wurde am BE ausgestoppt bevor Donchian-Trail/TP griff.
   Fix: im Donchian-Primary-Modus bleibt der initiale SL stehen (kein BE-Zug).
2. **Overnight-Gaps / Makro-Events** verursachten Tag-0-Verluste (05.06.2026:
   NFP-Tag, 4 gleichzeitige Stopps). Fix: NFP-entry-Block + Overnight-Gap-Filter.
3. **Exit-Config-Drift**: profit_lock wurde vom Regime-Override überschrieben.

## WICHTIG — Turtle-Artefakt-Falle
Donchian-Primary (Turtle) ist erst seit 09.08.2026 aktiv. ALLE historischen
Trades liefen mit dem ALTEN Chandelier-System (ohne profit_lock-Gate, engeres
Trailing). **Aus alten Daten darf man keine Schlüsse aufs neue System ziehen.**
Historische SL_HIT-"Gewinner" (AMD, NVDA, LITE) sind Artefakte, keine Aussage
über das neue Verhalten. Wirkung der Fixes erst nach Tagen/Wochen messbar.

## Schlussfolgerung für künftige Reviews
- Bevor du am Rule-Set drehst, trenne Gewinner/Verlierer und berechne Payoff.
- `profit_lock_atr = 0.5` war zu aggressiv (trailt nach <1 Tages-ATR beim Swing);
  `2.0` unerreichbar im Sideways. Kompromiss = 1.0x ATR (volle Tages-ATR Raum).
- Partial-TP-Schwelle (1.5x ATR) + Breakeven sind mit einem weiten Donchian-Trail
  kontraproduktiv — sie übersteuern den Turtle. Wer Schritte mitnimmt, muss den
  Rest ausschließlich per Donchian (nicht BE) trailen.
