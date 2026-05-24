# Telegram-Forward Inbox (X API Free Alternative)

Wenn die X API (~$100/mo Basic) zu teuer ist: Telegram-Forward-Inbox als **kostenlose Alternative** für Content-Ingestion aus X und anderen Quellen.

## Workflow

```
User forwardet Post/Link an Telegram-Chat
  └→ Hermes Cron (alle 30min)
       ├→ Letzte Nachrichten checken (via Telegram API getUpdates)
       ├→ Neue Nachrichten identifizieren (processed_ids Tracking)
       ├→ Pro Nachricht:
       │   ├→ Wenn URL: Inhalt fetchen (via web_extract / browser)
       │   ├→ LLM: 3-Bullet-Summary + Tags + Topic-Kategorie
       │   └→ Als .md in Obsidian Clippings/<Topic>/ ablegen
       └→ processed_ids speichern
```

## Vorteile vs X API

- **Kosten:** $0 (Telegram API ist kostenlos)
- **Quellen:** Funktioniert für X-Posts, YouTube-Links, Artikel, Substack, jede URL
- **Robustheit:** Kein API-Rate-Limit wie bei X
- **Setup:** Telegram-Chat existiert bereits (Ch_hermster oder ein dedizierter Channel)

## Benötigte Komponenten

1. **Telegram Bot Token** — existiert bereits in Hermes (.env)
2. **Cron-Job** — `hermes cron create` mit Schedule `*/30 * * * *`
3. **State-Tracking** — `processed_ids` in einer JSON-Datei
4. **Skill/Ablauf** — summarizer + tagger + Obsidian-Writer

## Beispiel-Cron-Prompt

```
Check the latest messages in the Telegram chat linked to this Hermes instance.
For each new message (not yet processed):
- If it contains a URL: fetch and summarize in 3 bullet points
- Auto-tag with relevant categories (Trading, Tech, AI, Polnisch, etc.)
- File into /root/obsidian-vault/Clippings/<topic>/<date-title>.md
- Mark as processed
```

## Einschränkungen

- Kein automatisches Monitoring — User muss aktiv forwarden
- Kein "geheime Bookmarks" von X — nur was geteilt wird
- Bei vielen täglichen Forwards manueller Aufwand