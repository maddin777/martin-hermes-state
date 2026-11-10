# Manual operations (Backfill, Force-Refresh, manuelle Einträge)

## YouTube-Kanal manuell nachziehen (außerhalb der Pipeline)

Wenn ein Kanal neu in `source_registry` steht, die Pipeline aber erst um 03:30 läuft:

1. Videos scannen und einfügen:

```python
from config import db_connect
from scripts.yt_channel_monitor import get_recent_video_ids, get_video_meta, get_transcript

con = db_connect()
url, name = 'https://www.youtube.com/@Handle', 'Kanalname'
for vid_id in get_recent_video_ids(url, 30):
    if con.execute('SELECT video_id FROM videos WHERE video_id=?', (vid_id,)).fetchone():
        continue
    date_str, title = get_video_meta(vid_id)
    if not date_str or not title:
        continue
    con.execute(
        'INSERT OR IGNORE INTO videos (video_id, channel, title, upload_date, transcript, status)'
        ' VALUES (?, ?, ?, ?, ?, ?)',
        (vid_id, name, title, date_str, get_transcript(vid_id), 'new'))
con.commit()
```

2. Signal-Extraktion für die neuen Videos:

```python
from config import db_connect
from scripts.signal_extractor import analyze
from datetime import datetime

con = db_connect()
for row in con.execute(
    "SELECT * FROM videos WHERE channel=? AND status='new' ORDER BY upload_date DESC", (name,)
).fetchall():
    if not row['transcript']:
        continue
    result = analyze(row['transcript'], row['channel'], row['title'], row['upload_date'])
    con.execute("UPDATE videos SET status='done', analyzed_at=? WHERE video_id=?",
                (datetime.now().isoformat(), row['video_id']))
    con.commit()
```

3. Dashboard-Statistik aktualisiert sich erst, wenn `watchlist_manager` /
   `signal_manager` die Signale in die Watchlist überführt haben.

Pitfalls: Die `videos`-Tabelle hat **keine** `id`-Spalte — `video_id` (TEXT) ist der
Primärschlüssel, also immer `WHERE video_id=?`. Jede Video-Analyse kostet 1–2
OpenRouter-Calls; bei vielen Videos lieber die nächste Pipeline abwarten.

## Einen einzelnen Ticker forcieren

Zwei unabhängige Aspekte trennen und getrennt verifizieren:

1. **Tech-Scores:** `get_technical_score(ticker)` aus `utils`, dann
   `UPDATE watchlist SET tech_score=?, tech_direction=?, weekly_trend=?` — oder
   `refresh_tech_scores.py [--min-conviction]` für die ganze Watchlist.
2. **last_seen + News:** `stale_refresh_queue.py [--top N] [--stale-days 14] [--apply]`
   (Google-News-RSS, setzt `last_seen` auf heute). Der DB-Refresh gelingt auch, wenn das
   News-Parsing scheitert — deshalb beide Aspekte separat prüfen
   (`SELECT ticker,last_seen,tech_score,tech_direction FROM watchlist WHERE ticker='X';`
   plus `stale_refresh_log`).

Wenn `search_news` nur ein Item mit `Fehler: Couldn't find a tree builder` liefert, fehlt
`lxml` im Trading-venv (`./venv/bin/pip install lxml`).

## Manuell eingefügte Watchlist-Ticker

`conviction_score` entsteht NUR aus Mentions. Manuell eingefügte Ticker ohne Mentions
haben `conviction=NULL` und werden **nie** automatisch als Entry gewählt, auch mit
`status='watching'` und vorhandenem `tech_score` — Entries brauchen conviction ≥ Schwelle.

- `watchlist_cleanup.py` (Mo–Fr 22:30) droppt `watching` mit `last_seen` > 60 Tage als
  `stale>60d`. Manuelle Einträge ohne Mentions altern daher zwangsläufig heraus: Note
  `manual-longterm` setzen oder `last_seen` regelmäßig erneuern.
- Manuelle Einträge stehen außerhalb der Pipeline-Validierung; `sector_probation`,
  `last30days_gate` und der Leverage-Check gelten für den Entry trotzdem.
- Nordische/DK-Ticker brauchen das Yahoo-Suffix: `DEMANT.CO`, `NSIS-B.CO`. Ohne Suffix
  liefert `get_technical_score` `None` (404 "delisted") → trotz Conviction nicht kaufbar.
