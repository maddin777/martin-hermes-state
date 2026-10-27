# ATR-Plausibilität prüfen (read-only)

Zweck: prüfen, ob die gespeicherten `positions.atr_at_entry`-Werte und die Stop-Abstände plausibel sind. Keine Schreibzugriffe. Die DB immer mit `file:...?mode=ro` öffnen.

## Schritt 1: Verteilung und Sanity

Nur aggregierte Spalten lesen, nie `SELECT *` auf `positions` (JSON-Spalten blähen den Output).

- ATR in Prozent vom Entry: `atr_at_entry / entry_price * 100`.
- Erwartungswert bei Aktien: grob 1–10 %. Werte unter ~0.5 % oder über ~15 % prüfen.
- Harte Fehler: `atr <= 0`, `entry <= 0`, NULL-ATR bei Positionen mit Entry.
- Ausreißer nicht sofort als Fehler werten: Small-/Mid-Caps mit 10 %+ sind real.

## Schritt 2: Stop-Konsistenz

Stop-Abstand in ATR-Einheiten: `abs(entry_price - initial_stop_loss) / atr_at_entry`.

- Stop auf der falschen Seite: LONG mit `stop >= entry` oder SHORT mit `stop <= entry`. Das ist immer ein Fehler.
- Stop enger als ~0.5 ATR: Rauschen-Stop, prüfen.
- Stop weiter als ~4 ATR: nur plausibel, wenn der Exit-Modus das vorsieht. Vorher `exit_mode` lesen. Feste Prozent-Stops (z. B. `yt_fade_*`, Stop fest +40 % über Entry) ergeben große ATR-Abstände, die im Code so gewollt sind. Das ist eine Strategie-Frage, kein Datenfehler.

## Schritt 3: Stichprobe gegen Marktdaten

Quelle der Kurse: `utils.get_price_data_cached` nutzt yfinance, 2 Jahre Daily, `pandas_ta.atr(length=14)`. Die DB enthält keine Preishistorie.

Vergleich am ENTRY-DATUM, nicht mit dem heutigen ATR. Der heutige ATR weicht durch Marktbewegung ab (bei einer Stichprobe zeigte der heutige Vergleich −10 % bis +13 %, der Entry-Tag-Vergleich nur −5 % bis +1 %).

```python
import yfinance as yf, pandas_ta as ta
df = yf.download(t, period="2y", interval="1d", progress=False, auto_adjust=True).dropna()
cs = df["Close"].iloc[:,0] if df["Close"].ndim>1 else df["Close"]
hs = df["High"].iloc[:,0] if df["High"].ndim>1 else df["High"]
ls = df["Low"].iloc[:,0] if df["Low"].ndim>1 else df["Low"]
atr = ta.atr(hs, ls, cs, length=14)
# Index auf naive Datumswerte bringen, dann letzten Bar <= entry_date nehmen
```

- Erwartung: Abweichung am Entry-Tag typischerweise unter ~5 %.
- Größere Abweichung: Entry-Datum prüfen (Wochenende, Zeitzone), bevor ein Fehler angenommen wird.
- Die Stichprobe sollte offene Positionen und mindestens eine geschlossene umfassen.

## Was nicht geprüft ist

Die Kurse selbst kommen nur aus einer Quelle (yfinance). Ein Abgleich gegen eine zweite Quelle ist ein eigener Schritt.

## Abschluss

Ergebnis als Liste mit Verteilung, Befunden und offenen Punkten melden. Eine Änderung an Exit-Parametern nie aus diesem Check ableiten: dafür gilt das Backtest-Gate.
