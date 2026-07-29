"""KI-Blase Risiko-Indikator für Trading-Dashboard.
Läuft als Cron und schreibt Ergebnis in data/ki_blase_alert.json.
Output: Nur bei Medium/High Alert (für no_agent cron delivery)."""
import json
import sqlite3
import os
from datetime import datetime
from config import DB_PATH, DATA_DIR

con = sqlite3.connect(DB_PATH)
con.row_factory = sqlite3.Row

# KI-Blase relevante Ticker
hyperscaler = ['NVDA', 'MSFT', 'GOOGL', 'ORCL', 'AMZN', 'META']
klumpen_ticker = ['NVDA','MSFT','GOOGL']
results = []
total_watchlist = 0
klumpen_conviction_sum = 0.0
klumpen_count = 0
klumpen_bought = 0

for t in hyperscaler:
    row = con.execute("""
        SELECT w.ticker, w.name, w.conviction_score, w.status,
               COALESCE(c.sector, 'Other') AS company_sector
        FROM watchlist w
        LEFT JOIN companies c ON c.ticker = w.ticker
        WHERE w.ticker = ?
    """, (t,)).fetchone()
    if row:
        results.append({
            'ticker': row['ticker'],
            'name': row['name'],
            'conviction': round(row['conviction_score'] or 0, 4),
            'status': row['status'],
            'sector': row['company_sector']
        })
        total_watchlist += 1
        if row['ticker'] in klumpen_ticker:
            klumpen_conviction_sum += row['conviction_score'] or 0
            klumpen_count += 1
            if row['status'] == 'bought':
                klumpen_bought += 1

wl_total = con.execute(
    "SELECT COUNT(*) as cnt FROM watchlist WHERE status IN ('watching','bought')"
).fetchone()['cnt']
tech_total = con.execute("""
    SELECT COUNT(*) as cnt FROM watchlist w
    LEFT JOIN companies c ON c.ticker = w.ticker
    WHERE COALESCE(c.sector, 'Other') = 'Technology'
    AND w.status IN ('watching','bought')
""").fetchone()['cnt']

# Risiko-Score
risk_score = 0.0
if total_watchlist >= 4:
    risk_score += 0.3
elif total_watchlist >= 2:
    risk_score += 0.15
if klumpen_bought >= 1:
    risk_score += 0.3
if klumpen_conviction_sum >= 1.5:
    risk_score += 0.25
elif klumpen_conviction_sum >= 1.0:
    risk_score += 0.15
tech_ratio = tech_total / max(wl_total, 1)
if tech_ratio > 0.30:
    risk_score += 0.2
elif tech_ratio > 0.20:
    risk_score += 0.1
risk_score = min(risk_score, 1.0)

alert_level = 'none'
if risk_score >= 0.7:
    alert_level = 'high'
elif risk_score >= 0.4:
    alert_level = 'medium'
elif risk_score >= 0.2:
    alert_level = 'low'

alert = {
    'timestamp': datetime.now().isoformat(),
    'risk_score': round(risk_score, 2),
    'alert_level': alert_level,
    'hyperscaler_in_watchlist': total_watchlist,
    'klumpen_ticker_count': klumpen_count,
    'klumpen_bought': klumpen_bought,
    'klumpen_conviction_sum': round(klumpen_conviction_sum, 2),
    'tech_ratio': round(tech_ratio, 2),
    'tech_total': tech_total,
    'wl_total': wl_total,
    'tickers': results,
    'message': ''
}

if alert_level == 'high':
    alert['message'] = 'Kritisches KI-Hyperscaler-Klumpenrisiko in der Watchlist.'
elif alert_level == 'medium':
    alert['message'] = 'Erhöhte KI-Hyperscaler-Konzentration in der Watchlist.'
elif alert_level == 'low':
    alert['message'] = 'KI-Hyperscaler in Watchlist vorhanden, aber nicht kritisch.'
else:
    alert['message'] = 'Kein KI-Blasen-Risiko erkannt.'

os.makedirs(DATA_DIR, exist_ok=True)
with open(os.path.join(DATA_DIR, 'ki_blase_alert.json'), 'w') as f:
    json.dump(alert, f, indent=2)

if alert_level in ('medium', 'high'):
    print(f'[{alert_level.upper()}] KI-Blase Alert: {alert["message"]}')
    print(f'Score: {risk_score:.0%} | KI-Hyperscaler: {total_watchlist} | Tech-Anteil: {tech_ratio:.0%}')
    print(f'Klumpen gekauft: {klumpen_bought} | Conviction-Summe: {klumpen_conviction_sum:.2f}')
    for r in results:
        print(f'  {r["ticker"]}: {r["conviction"]:.0%} ({r["status"]})')

con.close()