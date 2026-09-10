# last_seen-Staleness: Zuletzt-Spalte != echte Mention-Freshness

## Kern-Erkenntnis (09.09.2026)
Die Watchlist-"Zuletzt"-Spalte liest `watchlist.last_seen` in der Trading-DB
(`/root/.hermes/profiles/hermes_trading/skills/trading/data/trading.db`).
Dieses Feld wird **NICHT automatisch beim Mention-Ingest** hochgezogen —
nur `stale_refresh_queue.py` (und manuelle Touches) aktualisieren es.

**Folge:** Eine hohe Staleness-Metrik ("80 von 108 >14d stale") kann ein reines
`last_seen`-Artefakt sein, obwohl die DB aktuelle Mentions hat. Der
vault-insights-daily meldete NVDA/MSFT/GOOGL/AMD wochenlang als "stale",
obwohl NVDA am selben Tag 379 Mentions hatte.

## Belegte Werte (09.09.2026)
| Ticker | last_seen (Zuletzt) | letzte echte Mention |
|--------|---------------------|---------------------|
| NVDA | 28.05. | 09.09. (379 Mentions) |
| MSFT | 27.05. | 07.09. (239) |
| GOOGL | 24.05. | 07.09. (257) |
| AMD  | 28.05. | 31.08. (102) |
| AAPL | 09-08 | frisch |
| ASML/AVGO | 09-08 | frisch |

## Verifikation — echte Mention-Freshness (statt last_seen glauben)
```bash
cd /root/.hermes/profiles/hermes_trading/skills/trading/data
sqlite3 trading.db <<'EOF'
.headers on
.mode column
SELECT name, MAX(mention_date) as last_m, COUNT(*) as n
FROM watchlist_mentions
WHERE name LIKE '%NVIDIA%' OR name LIKE '%Microsoft%' OR name LIKE '%Apple Inc%'
   OR name LIKE '%ASML%' OR name LIKE '%Broadcom%' OR name LIKE '%Alphabet%'
   OR name LIKE '%Advanced Micro%' OR name LIKE '%SK hynix%'
GROUP BY name ORDER BY last_m;
EOF
```
Stichtag-Vergleich: `watchlist.last_seen` (Anzeige-Feld) vs `MAX(mention_date)`
aus `watchlist_mentions` (echtes Mention-Datum). Wenn letzteres deutlich
frischer ist → `last_seen`-Artefakt, Staleness-Metrik für diese Position
unbrauchbar.

## Schemata
- `watchlist.last_seen` — Anzeige-Feld; **nicht** beim Ingest aktualisiert.
- `watchlist_mentions.mention_date` — echte Mention-Quelle, vom Ingest befüllt.
- `external_mentions.fetched_at` — voller Fetch-Zeitstempel (`2026-09-09T02:05...`).
- `stale_refresh_queue.py` — einziger Aktualisierer von `last_seen`; wurde am
  08.09. erstellt (Antwort auf vault-insights-Punkt 3), Stand 09.09. **keinem
  Cron zugeordnet** → läuft nie automatisch.

## PITFALL / empfohlener Fix
Bei jeder Staleness-Aussage (z.B. in einem vault-insights Report) zuerst
zwischen `last_seen`-Artefakt und echter Mention-Staleness unterscheiden.
Dauer-Fix: `last_seen` beim Mention-Ingest mitführen (Kopplung an
`watchlist_mentions`), damit Anzeige-Stempel und echte Freshness nicht
auseinanderlaufen.

Wichtig auch: `watchlist_cleanup.py` (22:30, Mo–Fr) droppt `watching`-Einträge
mit `last_seen` > 60 Tage als `stale>60d`. Manuelle Long-Term-Einträge ohne
Mentions (z.B. die 8 Longevity-Kandidaten vom 30.08.) verlieren so nach ~60
Tagen den Status — sie brauchen `notes='manual-longterm'` oder periodische
`last_seen`-Refreshs.