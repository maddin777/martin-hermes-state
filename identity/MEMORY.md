# MEMORY.md — Hermes' Projekt-Notizbuch

> Persistent über Sessions hinweg. Wird bei jedem Session-Start automatisch geladen.
> Aktualisiert: 2026-05-23

## Obsidian Vault
- Pfad: `/root/obsidian-vault` (root)
- rclone remote: `gdrive:` → Folder `hermes-obsidian-vault`
- Cron: `obsidian-vault-bisync-nightly` (ID: f5eb3bfaf65e), 02:00 täglich, deliver=local
- Nutzt direkten `rclone bisync` mit `--drive-root-folder-id`, NICHT `sync.sh`
- `sync.sh` hat REMOTE_PATH="hermes-obsidian-vault" (auf Hyphen gefixt 23.05.)
- Cron `vault-insights-daily` (ID: 53f222b00811), 02:45 täglich, deliver=telegram
- Wiki: wiki/concepts/, wiki/entities/, wiki/sources/, trading-index.md
- Todos: `/root/obsidian-vault/todos.md` (YAML-Format)

## Hermes-Profile & Bots
Alle isoliert mit Wrapper `/root/.local/bin/`. System-crontab setzt pro Profil korrekten Token.

| Profil | Bot | Kanal |
|--------|-----|-------|
| hermes_trading | @hermster_trader_bot (8220070984) | Ch_hermster_trade (-1003918757178) |
| hermes_lang | @hermster_lang_bot | Ch_hermster_lang |
| hermes-news | — | — |
| Main DM | @myhermster_bot (8643170747) | — |

## Trading-System (v4.0)
- RSS-Cron/News-Cron (social_scanner.py, Mo-Fr 10:45)
- Dashboard Port 8081
- Quellen: RSS/Twitter/YouTube (verwalten ohne SSH)
- Pipeline: yt_channel_monitor → signal_extractor (KI) → technical_validator (yfinance) → signal_manager

## Gateway-Watchdog
- Stufe 1: systemd Restart=on-failure, StartLimitBurst=3/600s
- Stufe 2: Cron alle 30min (no_agent, gateway-watchdog.py)
- Fix: HERMES_TELEGRAM_DISABLE_FALLBACK_IPS=true

## Skills
- Trading-Skill: `/root/.hermes/profiles/hermes_trading/skills/trading/`
- Polnisch-DiSSS: hermes_lang Profil, 21:00 täglich
- Vault-Insights-Daily: siehe vault-insights-daily Skill
- Gateway-Watchdog: siehe gateway-watchdog Skill

## Sonstiges
- GitHub: maddin777 (gh CLI + PAT)
- Playwright Chromium 147 at ~/.cache/ms-playwright/chromium-1217/
- Browser engine: auto
- xai-oauth (SuperGrok) eingerichtet, x_search Toolset enabled
- TTS: Edge de-DE-FlorianMultilingualNeural
- STT: faster-whisper 1.2.1 (model base)