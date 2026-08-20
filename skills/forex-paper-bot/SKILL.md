---
name: forex-paper-bot
description: >-
  Forex-Paper-Bot — intraday 15m-Trendfolge auf den 5 Majors, Walk-Forward-
  optimiert, spread-bereinigt. Vollautomatisch via Hermes-Cron (London/NY-Session).
  Eigene SQLite-DB, komplett getrennt vom Aktien-Trading-System.
---

# Forex Paper Bot

Ein eigenständiger Forex-Trading-Bot im **Paper-Modus**. Intraday-Trendfolge auf
15-Minuten-Candles, selbstkalibrierend per Walk-Forward-Optimierung, mit
transparenter Spread-/Kostenrechnung. Getrennt vom Aktien-System (hermes_trading).

## Architektur-Überblick

```
/root/.hermes/skills/forex-paper-bot/
├── SKILL.md          ← diese Datei
├── config.json       ← Single Source of Truth (Paare, Spreads, Risiko, WF, Session)
├── venv/             ← eigenes venv (yfinance, pandas, numpy)
├── scripts/
│   ├── config.py     ← Config- + DB-Helper
│   ├── fetch.py      ← yfinance 15m/1h Daten
│   ├── forex_signal.py ← Trendfolge-Signal (15m + H1-Gate + Session)
│   ├── backtest.py   ← Walk-Forward-Optimierung (wöchentlich)
│   ├── trade.py      ← Paper-Positions-Management (SL/TP/Trailing, Drawdown-Gate)
│   └── daily_report.py ← Tagesend-Auswertung
├── data/forex.db     ← SQLite (trades, params_snapshots, portfolio, daily_reports)
└── reports/          ← Tagesreports als Markdown
```

**Wichtig:** Eigener Skill, eigene DB, eigenes venv. **KEINE** Kopplung an
`hermes_trading` (keine Importe, kein gemeinsames .env, kein gemeinsames Script).

## Konfiguration (config.json)

| Sektion | Schlüssel | Default | Bedeutung |
|---------|-----------|---------|-----------|
| `capital` | — | 10000.0 | Startkapital Paper (€) |
| `risk_per_trade_pct` | — | 0.02 | Max 2% Risk pro Trade |
| `max_drawdown_pct` | — | 0.50 | Drawdown-Stopp: ab 50% keine neuen Entries |
| `session_*` | — | 9–22 MEZ | London/NY-Session |
| `pairs` | spread_pips | 0.8–1.5 | Spread pro Paar (pips) — auf Entry+Exit gerechnet |
| `walk_forward` | lookback_weeks | 8 | Optimierungsfenster |
| `sl_tp` | sl/tp/trailing | 1.5/2.5/1.0 | ATR-Multiplikatoren |
| `signal` | ema_* | 20/50/8 | Trendfolge-Parameter (WF kann überschreiben) |

**Spreads (Defaults, konfigurierbar):** EUR/USD 0.8, GBP/USD 1.2, USD/JPY 1.0,
USD/CHF 1.5, AUD/USD 1.0 pips. Der Spread wird als Kosten auf **Entry UND Exit**
angerechnet → PnL ist immer **netto** (spread-bereinigt).

## Signal-Logik

1. **H1-Trendfilter (Gate):** EMA-20 auf 1h → bullish/bearish/neutral
2. **15m-Trend:** EMA-Kreuz (fast vs slow) + Momentum-Schwelle
3. **Signal** nur wenn 15m-Trend zur H1-Richtung passt:
   - H1 bullish + 15m EMA-Kreuz up + Momentum ↑ → **LONG**
   - H1 bearish + 15m EMA-Kreuz down + Momentum ↓ → **SHORT**
4. **Session-Gate:** Entries nur in London/NY-Session (Mo–Fr 09–22 MEZ).
   Außerhalb: nur offene Positionen verwalten (Trailing/SL), keine neuen Entries.

Die exakten Schwellen (ema_fast, ema_slow, momentum_lookback, sl/tp-mult) werden
durch die **Walk-Forward-Optimierung** pro Paar kalibriert.

## Walk-Forward-Optimierung

Läuft **sonntags 22:30** (`forex-walk-forward-weekly`). Für jedes Paar:
- Lookback 8 Wochen 15m-Daten
- Grid-Search über 108 Param-Kombinationen (ema_fast, ema_slow, momentum_lookback, sl_mult, tp_mult)
- Bewertung: kombinierter Score = PF×0.5 + WR×0.2 + Sharpe×0.3 (PF dominiert)
- Beste Paramgruppe → `params_snapshots`-Tabelle

`trade.py` lädt die **letzte** Paramgruppe je Paar; ohne Snapshot → Fallback auf config.json-Signal.

## Paper-Positions-Management (trade.py)

Läuft alle 15 min Mo–Fr 09:00–21:45 (`forex-trade-check`):
1. Session-Status prüfen (außerhalb → nur Positionen verwalten)
2. Drawdown-Gate: `drawdown_pct >= max_drawdown_pct` (50%) → keine neuen Entries
3. Signale prüfen → Paper-Trade eröffnen (SL/TP aus ATR, Position Sizing aus 2% Risk)
4. Offene Positionen: Trailing-Stop nachziehen, SL/TP prüfen, Exit verbuchen

PnL-Berechnung beim Exit:
- gross = Preisbewegung × size_units (LONG: (exit-entry)/entry; SHORT invertiert)
- **netto = gross − spread_cost** (spread auf Entry+Exit)
- Portfolio: cash += pnl_net, equity_peak-Update, realized_pnl

## Tagesend-Auswertung (daily_report.py)

Läuft **Mo–Fr 22:15** (`forex-daily-report`), deliver → Martins Telegram-DM.
Report: Geschlossene Trades des Tages, PnL gross/netto, Win-Rate, Profit-Faktor,
Drawdown-Stand, offene Positionen. Speichert als `reports/report_<datum>.md`.

## Crons

| Cron-ID | Name | Schedule | Zweck |
|---------|------|----------|-------|
| `866647ef510c` | forex-trade-check | `*/15 9-21 * * 1-5` | Trade-Check alle 15 min |
| `8ff7a0161d44` | forex-daily-report | `15 22 * * 1-5` | Tagesreport → Telegram DM |
| `4151bc36d2f6` | forex-walk-forward-weekly | `30 22 * * 0` | Sonntag-Optimierung |

Alle drei sind `no_agent` Hermes-Crons → Wrapper in `~/.hermes/scripts/forex_*.sh`.

## Quick Debug

```bash
cd /root/.hermes/skills/forex-paper-bot
./venv/bin/python3 scripts/fetch.py --test              # Daten-OK (5 Paare)
./venv/bin/python3 scripts/forex_signal.py --all        # aktuelle Signale
./venv/bin/python3 scripts/backtest.py --pair EURUSD=X  # WF einzelnes Paar
./venv/bin/python3 scripts/trade.py --test              # Signal-Test ohne DB-Writer
./venv/bin/python3 scripts/daily_report.py --test       # Report-Test

# DB-Übersicht
./venv/bin/python3 -c "import sys; sys.path.insert(0,'scripts'); import config as c; con=c.db_connect(); \
[print(r['pair'],r['status'],r['pnl_net']) for r in con.execute('SELECT * FROM trades')]"
```

## Pitfalls

- **`signal.py` kollidiert mit Python-Stdlib** — Datei heißt `forex_signal.py`, NICHT `signal.py` (stdlib `signal` via subprocess bricht Import).
- **numpy `.item()`** — bei pandas/numpy-Werten IMMER `_scalar()`/`_npf()` nutzen, `float()` scheitert an manchen 0-dim Arrays.
- **MultiIndex-Close** — yfinance liefert manchmal MultiIndex-Spalten; `fetch.py` flacht mit `iloc[:,0]` ab.
- **XAUUSD (Gold) liefert yfinance NICHT** — nur die 5 Fiat-Majors sind konfiguriert.
- **Backtest-Performance** — Grid-Search ist numpy-vektorisiert; voller Lauf (5 Paare) dauert ~100s. Kein pandas `.iloc` im heißen Loop.
- **Session-Zeiten** — Entries nur 09–22 MEZ Mo–Fr. Wochenend-Gap: kein Handel Fr-Session-Ende bis Mo-Open.
- **Drawdown 50%** (19.08.: Martin hat von 10% erhöht) — Gate blockt nur NEUE Entries, offene Trades laufen aus.

## Verifikation

Siehe Spec `wiki/tasks/forex-bot-paper.md`. Kern-Gates: Daten-OK (5 Paare), Signal-Logik,
PnL netto (Spread abgezogen, E2E getestet: +0.1% LONG → gross 34.25€, Spread 2.74€, netto 31.51€),
Walk-Forward (Snapshots je Paar), Tagesreport (Markdown + Telegram).
