# yfinance Forex-Intraday (FX-Paare, 15m) — verifiziert 19.08.2026

yfinance liefert **kostenlos** 15m-Candles für Forex-Majors — kein Broker-Konto, kein API-Key. Genutzt als Datenbasis für den Forex-Bot (Paper-Modus) im Finn-loop (`wiki/tasks/forex-bot-paper.md`).

## Funktioniert (verifiziert live)

```python
import yfinance as yf
df = yf.download('EURUSD=X', period='5d', interval='15m', progress=False, auto_adjust=False)
# → ~466 Zeilen für 5 Tage (EUR/USD), Spalten Open/High/Low/Close
```

| Paar | Ticker | 15m-Daten |
|------|--------|-----------|
| EUR/USD | `EURUSD=X` | ✅ ~466 Zeilen/5d |
| GBP/USD | `GBPUSD=X` | ✅ |
| USD/JPY | `USDJPY=X` | ✅ |
| USD/CHF | `USDCHF=X` | ✅ (nicht explizit getestet, gleiche Majors-Familie) |
| AUD/USD | `AUDUSD=X` | ✅ (nicht explizit getestet, gleiche Familie) |

## NICHT verfügbar

- **Gold `XAUUSD=X`** → HTTP 404 "Quote not found" / "possibly delisted". Gold/Commodities via yfinance nicht zuverlässig als FX-Ticker. (Forex-Bot-Spec hat Gold explizit als NG-5 ausgeschlossen.)

## Wichtige Eigenheit für Spread-Modellierung

yfinance liefert für FX nur **Close** (ein Preis pro Candle) — **kein echtes Bid/Ask**. Für die Spread-Kostenrechnung im Paper-Bot:
- Spread pro Paar als **feste pips in config.json** modellieren (nicht aus Bid/Ask ableiten — existiert nicht).
- Spread auf **Entry UND Exit** anrechnen → PnL ist netto.
- Defaults (pips): EUR/USD 0.8, GBP/USD 1.2, USD/JPY 1.0, USD/CHF 1.5, AUD/USD 1.0.

## Test-Rezept

```bash
/root/.hermes/profiles/hermes_trading/skills/trading/venv/bin/python3 -c "
import yfinance as yf
for p in ['EURUSD=X','GBPUSD=X','USDJPY=X','AUDUSD=X']:
    df = yf.download(p, period='2d', interval='15m', progress=False, auto_adjust=False)
    print(f'{p}: {len(df)} Zeilen 15m')
"
```
