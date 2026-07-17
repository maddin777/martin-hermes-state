# PEAD-Signal (Post-Earnings Announcement Drift)

## Konzept
Long nach EPS BEAT (EPS actual > Estimate), short nach MISS (EPS actual < Estimate).
Theorie: der Markt unterreagiert auf Earnings-Surprises → die Aktie driftet 4-5 Tage
in die Überraschungsrichtung.

## Datenquelle
yfinance `Ticker.earnings_dates` — komplett kostenlos, kein API-Key nötig.
BEAT/MISS wird selbst berechnet: `diff = Reported - Estimate`, BEAT wenn > 0.

| yfinance-Spalte | Verwendung |
|----------------|------------|
| `EPS Estimate` | Erwarteter EPS-Wert |
| `Reported EPS` | Tatsächlicher EPS-Wert |
| (Index) | `filing_date` — wann die Info veröffentlicht wurde |

## Implementierung (Backtesting — `backtesting/signals/pead.py`)

**Klasse:** `PEADModel(QuantModel)` — implementiert AlphaModel-Interface

**Parameter:**
- `earnings_limit=8` — Wieviele Earnings-Events laden
- `signal_window_days=4` — Nur innerhalb von X Tagen nach Filing feuern

**Signal:**
- `+1.0` bei BEAT innerhalb des Fensters
- `-1.0` bei MISS innerhalb des Fensters
- `0.0` — keine View (abgelaufen, kein Event, oder neutral)

**Filter:**
- 45-Day-Retrospective-Cutoff: Events deren filing_date weit nach
  report_period liegt werden verworfen
- Source-Priorität: 8-K > 10-Q > 10-K (8-K ist die eigentliche Ankündigung)
- Pro report_period wird nur der beste Eintrag behalten

## Implementierung (Live Pipeline — `scripts/pead_signal.py`)

Seit 11.07.2026 ist PEAD als Booster im Watchlist Manager aktiv.

**Eingebaut in:** `watchlist_manager.py` (nach Thesis-Boost, vor Grok-Boost)

**Funktionen:**
- `get_pead_boost(ticker)` — Holt yfinance-Daten, berechnet BEAT/MISS
- `get_pead_boost_cached(ticker, con)` — Gecachte Version (6h TTL)
- `ensure_pead_cache_table(con)` — Erstellt `pead_cache`-Tabelle (idempotent)

**Boost-Werte:**
| Event | Effekt | Betroffene Conviction |
|-------|--------|----------------------|
| BEAT | `+0.05` | `conviction_score` (Long) |
| MISS | `+0.05` | `conviction_score_bear` (Short) |

**Cache:** `pead_cache`-Tabelle in trading.db, TTL 6h. Ein Ticker = 1 yfinance-Call
alle 6h, nicht pro Pipeline-Lauf.

**Kosten:** 0 €. yfinance liefert EPS Estimate + Reported EPS. Keine Paid-API
nötig. Der Boost ist bewusst klein (+0.05): genug um Grenzfälle zu entscheiden,
aber nicht stark genug um den Conviction-Score zu dominieren.

## Backtest-Ergebnisse (10 Tech-Ticker, 2025)

| Metrik | Wert |
|--------|------|
| Trades | 37 (32L / 5S) |
| Return | -5.39% |
| Sharpe | -0.88 |
| Max DD | 8.60% |
| Win Rate | 46% |

PEAD ist ein schwacher Einzelfaktor — in Isolation nicht profitabel. Er
entfaltet Wert erst in Kombination mit anderen Filtern (Conviction, Technicals,
Regime).

## Usage (Backtesting)

```python
from backtesting import BacktestEngine
from backtesting.data_client import YFinanceDataClient
from backtesting.signals import PEADModel

client = YFinanceDataClient()
model = PEADModel(earnings_limit=8, signal_window_days=4)
engine = BacktestEngine(capital=100_000, per_trade=10_000)

result = engine.run_alpha(
    model, ["AAPL", "MSFT"], client,
    "2025-01-01", "2025-12-31", holding_days=5,
)
print(result.metrics)
```

## Manueller Test (Live Pipeline)

```bash
cd /root/.hermes/profiles/hermes_trading/skills/trading
python3 scripts/pead_signal.py AAPL
```

## Conviction-Boost-Kette (Watchlist Manager)

Die Reihenfolge der Boosts im watchlist_manager.py ist wichtig:

1. **Roh-Conviction** aus Mentions (Kanal-Gewichtung, Sentiment, Stärke)
2. **Thesis-Boost** — +0.02 bis +0.08 bei aktiver Thesis
3. **PEAD-Boost** — +0.05 bei BEAT/MISS (nach Thesis, vor Grok) ← hier
4. **Grok-Boost** — +10% bei bullishem X-Sentiment (nur Top 20)

## Bekannte Einschränkungen
- **report_period:** yfinance liefert kein explizites report_period-Datum.
  Wird auf filing_date gesetzt — für den 45-Day-Retrospective-Filter weniger
  genau, aber für den Anwendungsfall ausreichend.
- **source_type:** Immer "10-Q", da yfinance keine Unterscheidung liefert
  (8-K vs 10-Q vs 10-K). Der Source-Priority-Mechanismus im PEADModel
  (8-K > 10-Q > 10-K) wird dadurch umgangen.
- **Nur US-Ticker:** yfinance earnings_dates funktioniert zuverlässig für
  US-Ticker. Für DE/EU-Ticker (z.B. .DE, .PA) sind die Daten oft unvollständig.