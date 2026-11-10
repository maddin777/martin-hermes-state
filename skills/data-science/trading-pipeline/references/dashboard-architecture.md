# Dashboard-Architektur

Single-file Python HTTP server with inline HTML/CSS/JS — no framework, no templates.

## Betrieb

- Port **8081**, unter **systemd** (`trading-dashboard.service`), nicht als
  Background-Prozess. Restart: `systemctl restart trading-dashboard.service`.
- `override.conf` des Service setzt `DASHBOARD_BIND=0.0.0.0` und `DASHBOARD_TOKEN`.
- Der `__main__`-Block lädt die `.env` des Trading-Profils, damit `DASHBOARD_BIND`
  immer gesetzt ist.
- Watchdog: Cron `d1c92b5337c5`, no_agent alle 15 min,
  `~/.hermes/scripts/dashboard-watchdog.sh`. Der Watchdog exportiert die `.env` vor dem
  Restart — ohne das bindet der Neustart auf `127.0.0.1` und das Dashboard ist nur noch
  lokal erreichbar. `start_dashboard.sh` macht dasselbe für manuelle Starts.
- **Zwei Kopien** (`~/.hermes/...` live, `/root/martin-hermes-state/...` git-backup) —
  immer beide editieren. Details: `live-vs-state-backup.md`.

## Neue Section hinzufügen

1. Tab-Button in `tab-nav`:
   `<button class="tab-btn" onclick="showTab('exits')" style="color:#ff9800">🚪 Exits</button>`
2. Tab-Content-Container nach dem letzten Tab:
   `<div id="tab-exits" class="tab-content">{build_exits_section(data)}</div>`
3. `build_*_section(data)`-Funktion vor `build_thematic_section()`: bekommt das
   `data`-Dict (open_pos, closed, watchlist, cfg, stats …) und gibt einen HTML-String
   zurück (inline SVG, Tabellen; kein externes JS/SVG-Lib).

Bestehende Tabs: portfolio, watchlist, sources, quality, cron, thematic, exits.

## Quellen-Tab

Pro YouTube-Kanal: Status-Badge (🟢 Aktiv, 🧪 Probation, 🆕 Kandidat, ⏸ Deaktiviert),
30-Tage-Mentions, Win Rate (grün ≥50 %, gelb ≥30 %, rot <30 %), Ø PnL, Weight
(grün ≥1.0, gelb ≥0.5, orange <0.5), Penalty-Grund. Daten aus `source_registry` +
`watchlist_mentions`-Aggregat. Channel-Namen case-insensitiv matchen (`stats_ci`), sonst
zeigt der Tab `–` trotz vorhandener Mentions.

## Exit-Stairway (🚪 Exits-Tab)

Standard-Level: 25 % @ 1× ATR → 25 % @ 2× ATR → 50 % @ 3× ATR.

Pro Position: SVG-Stairway (200×160 px) mit Gitterlinien bei 1×/2×/3× ATR,
🟢 aktueller Preis (grün/rot je P&L), 🔻 Stop-Loss, 🔺 Trailing, ◆ Take-Profit,
— Entry, ✅ erreichter Step, ⏳ offener Step; dazu Key-Values-Tabelle (Entry, SL, TP,
Aktuell, Trailing, ATR, Größe, Trail-Status, Step-out-Fortschritt) und Step-Out-Badges
(`TP1: 25 % @ 135.20 ✅`).

Daten: `data["open_pos"]` (entry, sl, tp, trailing_sl, atr_at_entry) plus
`yfinance.Ticker().fast_info['last_price']` live pro Request; ATR-Fallback
`abs(tp - entry) / 3.0`. Funktion `build_exits_section(data)`.

## Sortierbare Tabellen

Muster (Klick auf Header, stabile Sortierung, numerisch vs. Text):
`dashboard-sortable-table-pattern.md`.
