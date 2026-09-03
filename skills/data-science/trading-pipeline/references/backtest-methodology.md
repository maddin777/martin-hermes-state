# Backtest-Methodik (robust, net-of-spread) — Stand 01.09.2026

Wiederverwendbare Prozedur, wie eine Trendfolge-Strategie validiert wird BEVOR
man Parameter am Live-Bot ändert (gelernt aus dem 15m→1D FX-Rebuild 28.08.–01.09.,
siehe `forex-paper-bot` Skill).

**Kernprinzip:** Ein Backtest, der den Spread NICHT auf Entry+Exit einrechnet,
testet das falsche System. Ergebnis: "profitabel" im Backtest, katastrophal live.

## Ablauf

1. **Spread netto modellieren**: Jeder Trade zahlt `2 x spread_pips` auf sein
   Pip-Ergebnis (Entry + Exit). Pflicht — sonst sind alle Gewinne Schein.
   - Ohne sie erscheinen brute Profit-Faktoren (PF 44–101 im FX-Fall).
   - Nach netto: real ~break-even/negativ.

2. **Grid-Search über 50 Kombis**: Random-Sample eines breiten Parameterraums
   (EMA fast/slow, Momentum-Schwelle, SL/Trailing-Multiplikatoren, Regime-Filter,
   Pyramiding). Ein Paar-monopolisiertes Ergebnis NICHT als Gewinn werten.

3. **Konzentrations-/Robustheit-Check**: Der erste 5-Paar-Run zeigte +1498 pips —
   aber 53% davon aus EINEM Paar (USDJPY, PF 21). Das ist ein Paar-Trend, kein
   Strategie-Edge. **Nur Kombis zählen, die in ALLEN geprüften Paaren positiv sind
   (nPos == N).** Das ist der Differenzierer zwischen Rauschen und echtem Effekt.

4. **Walk-Forward out-of-sample**: Parameter NUR auf Train-Fenster wählen, dann auf
   nie gesehene Test-Daten anwenden (60/40 + 40/60 Splits). Positive OOS = kein
   Überfit. 3-4/4 Paare positiv OOS ist das Ziel.

## Entscheidungs-Faustregel

| Symptom | Diagnose | Hebel |
|---------|----------|-------|
| Alle Kombis negativ nach Spread | Ziel-Bewegung zu klein relativ Spread | **Timeline rauf** (15m→1D), nicht Parameter-Feintuning. EMA-Wahl fast irrelevant; Trade-Frequenz ist der Hebel. |
| "+profitabel" ABER 1 Paar trägt alles | Konzentration, kein Edge | Robuster Regime-Filter (Weekly-Gate) + nur all-Positiv-Kombis |
| Grid-Ranking voller 1-2-Trade-"Gewinner" | Statistisches Rauschen | Mindest-Trade-Anzahl (>=8) als Gate |

## Pitfall-Lektionen
- **Pyramiding/mehr Nachkäufe hilft NICHT gegen Spread-Friktion** — erhöht nur die
  Trade-Zahl (mehr Spread).
- **Der erste "Gewinn" ist oft ein Fit**: immer OOS validieren.
- **Timeline ist der Hebel**: dieselbe EMA-Kreuz-Idee, die auf 15m strukturell verlor,
  wurde auf 1D positiv (größere Zielbewegung > fixer Spread). Kein Parameter-Sweep
  hätte das gefunden. Verwandt: Drawdown-Heilungs-Falle (→ Drawdown-Matrix im SKILL.md
  01.09., 15-25%-Zone 65%/75%) — eine "Bremse"-Konfiguration kann Heilung selbst
  verhindern, wenn sie Trades zu klein/zu selten macht.
