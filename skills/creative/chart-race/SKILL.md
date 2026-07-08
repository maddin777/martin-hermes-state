---
name: chart-race
description: >
  Animierte 9:16-Datenvideos (TikTok/Reels) auf Kommando — Bar-Race,
  Stacked-Area oder Line-Race. DeepSeek baut die Config, Python rendert
  Frame für Frame via matplotlib + ffmpeg. BYO-Daten oder Self-Fetch aus
  Whitelist-Quellen. Triggere diesen Skill immer wenn der Nutzer ein
  animiertes Chart-Video / Reel / Chartrace erzeugen will.
---

# Chart-Race Skill

Erzeugt **animierte 9:16-Datenvideos** (TikTok/Instagram Reels) auf Kommando.
Rollenteilung: **DeepSeek denkt, Python rendert.**

```
Kommando → DeepSeek V4 flash → Render-Config (JSON) → render_engine.py → MP4
           (Config-Builder)      (validiert + Sanity)     (deterministisch)
```

## Chart-Typen

| Typ | Wann | Beispiel |
|-----|------|----------|
| `stacked_area` | Zusammensetzung über Zeit | "Benzinpreis DE Zusammensetzung als stacked_area, 30s" |
| `line_race` | mehrere Serien im Zeitverlauf | "Benzinpreis DE/FR/IT als line_race, langsam" |
| `bar_race` | Ranking, das sich ändert | "teuerstes Benzin Europa als bar_race" |

## Zwei Datenmodi

**Modus A — BYO-Daten:** CSV mit --data übergeben. DeepSeek erkennt
Wide/Long-Format, Spalten-Mapping und Trennzeichen aus dem CSV-Kopf.

**Modus B — Self-Fetch:** Keine Datei. DeepSeek wählt Quelle aus
Whitelist (data_sources.md), Fetcher baut die CSV währungsbereinigt.

## Nutzung

```bash
# Abhängigkeiten (bereits installiert im default-Profil)
# pip install httpx pandas numpy matplotlib
# ffmpeg muss im PATH sein (vorhanden)

# Immer ins Scripts-Verzeichnis wechseln vor dem Aufruf:
cd ~/.hermes/skills/creative/chart-race/scripts

# Modus A — eigene Daten
python hermes_dataviz.py \
  "Zusammensetzung Benzinpreis DE als stacked_area, 40s, dunkel" \
  --data /daten/benzin_zusammensetzung_de.csv --out /tmp/reel.mp4

# Modus B — Selbst holen
python hermes_dataviz.py \
  "teuerstes Benzin Europa als bar_race, langsam"

# Nur Config prüfen, nicht rendern
python hermes_dataviz.py "..." --data x.csv --config-only
```

## Exit-Codes

- 0: Erfolg, MP4 geschrieben
- 2: Config-Fehler (validate_config)
- 3: need_input (DeepSeek braucht Rückfragen)

## Prompt

Der System-Prompt für DeepSeek liegt in `references/deepseek_prompt.md`.
Die Config-Schema-Referenz in `references/config_schema.md`.
Verfügbare Self-Fetch-Quellen in `references/data_sources.md`.

## Fallstricke

- **Währungsfehler:** Nicht-Euro-Länder müssen im Fetcher umgerechnet werden
- **Gemischte Skalen:** Nicht Tankpreis (~2€) mit Rohöl (~80$/bbl) in einen line_race mischen
- **Zu viele Labels:** milestone_labels auf 3–6 begrenzen (9:16 wird sonst unleserlich)
- **Kein DEEPSEEK_API_KEY nötig:** Skill nutzt OpenRouter, nur OPENROUTER_API_KEY muss gesetzt sein. Der Key wird via `env_loader.py` aus dem hermes_trading-Profil geladen.
- **Self-Fetch erfindet Fetcher-Namen:** DeepSeek halluziniert manchmal Script-Namen (z.B. `fetch_fuel_prices.py` statt `fetch_oil_bulletin.py`). Workaround: Bei `FEHLER: Fetch-Skript X nicht vorhanden` → prüfen welcher Fetcher aus `references/data_sources.md` passt, Config manuell korrigieren, oder Modus A (BYO-Daten) nutzen.
- **Scripts-Verzeichnis:** Scripts liegen relativ zum Skill-Ordner. IMMER `cd` in `scripts/` vor dem Aufruf, sonst finden die relativen Pfade (`../references/`) nicht.
- **Render-Dauer:** ~1.200 Frames dauern Minuten. Das gehört nicht in einen N8N-Node (Timeouts, Speicher). N8N orchestriert nur den Trigger.