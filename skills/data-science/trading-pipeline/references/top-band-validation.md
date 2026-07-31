# Top-Band-Validierung

Seit 30.07.2026. Validiert die Top-3/5/10 der Watchlist separat — nicht nur den
Durchschnitt. Der Post-Insight der das motivierte: "you validate the top of the
ranking specifically, not the average. Since the top band is all that ever ships,
that's the only place quality matters."

## Funktion: `calc_top_band_metrics(con)`

Läuft im `nightly_eval.py`-Main-Loop und prüft für die Top N Watchlist-Einträge
(nach `conviction_score DESC`):

- **bought_count**: Wieviele wurden in den letzten 30 Tagen gekauft?
- **win_rate**: Win Rate der gekauften (geschlossene Trades)
- **sum_pnl**: Summe P&L der gekauften

## DB-Migration

`eval_metrics`-Tabelle hat 9 zusätzliche Spalten (idempotent via `PRAGMA table_info`):

| Spalte | Typ | Beschreibung |
|--------|-----|-------------|
| `top3_win_rate` | REAL | Win Rate der Top 3 |
| `top5_win_rate` | REAL | Win Rate der Top 5 |
| `top10_win_rate` | REAL | Win Rate der Top 10 |
| `top3_bought` | INTEGER | Wieviele Top 3 wurden gekauft |
| `top5_bought` | INTEGER | Wieviele Top 5 wurden gekauft |
| `top10_bought` | INTEGER | Wieviele Top 10 wurden gekauft |
| `top3_pnl` | REAL | Summe P&L Top 3 |
| `top5_pnl` | REAL | Summe P&L Top 5 |
| `top10_pnl` | REAL | Summe P&L Top 10 |

## Output im Nightly Eval

```
📊 Top-Band-Validierung...
  Top 3: 2 gekauft, WR 50%, P&L +124€
  Top 5: 3 gekauft, WR 67%, P&L +89€
  Top 10: 5 gekauft, WR 60%, P&L +45€
```

## Timings

- Läuft im selben `nightly_eval.py`-Run (05:00 Mo–Fr, 06:00 So)
- Werte werden per UPDATE in denselben `eval_metrics`-Row geschrieben (nach dem initialen INSERT)

## Query-Logik

```python
d30 = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
for n in [3, 5, 10]:
    top = con.execute("""
        SELECT ticker, name, conviction_score
        FROM watchlist
        WHERE status = 'watching' AND ticker IS NOT NULL
        ORDER BY conviction_score DESC LIMIT ?
    """, (n,)).fetchall()
    for t in top:
        pos = con.execute("""
            SELECT pnl_eur, status FROM positions
            WHERE ticker = ? AND entry_date >= ?
              AND status IN ('closed', 'open')
            ORDER BY entry_date DESC LIMIT 1
        """, (t["ticker"], d30)).fetchone()
        if pos:
            bought += 1
            if pos["status"] == "closed" and pos["pnl_eur"] is not None:
                if pos["pnl_eur"] > 0: wins += 1
                else: losses += 1
                sum_pnl += pos["pnl_eur"]
```
