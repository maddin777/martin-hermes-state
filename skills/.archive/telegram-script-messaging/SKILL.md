---
name: telegram-script-messaging
description: Send TG from agent/cron scripts; HTML parse_mode pitfall.
---

# Telegram Script Messaging

Konvention für Scripts (v.a. no_agent-Cron-Wrapper) die eigene Telegram-Nachrichten
an einen Kanal/Chat senden — unabhängig vom Hermes-Framework-Messaging.

## Credentials & .env-Sourcing

Vom Script (nicht vom Hermes-Wrapper) ausgehend:

```python
import os
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN", "")
TG_CHAT  = os.environ.get("TELEGRAM_HOME_CHANNEL") or os.environ.get("TELEGRAM_CHAT_ID", "")
```

- `TELEGRAM_BOT_TOKEN` (oder `TELEGRAM_TOKEN`) = Bot-Token.
- **Quellen-Kanal-Konvention im Trading-Profil:** der eigene Trading-Bot-Kanal
  (`Ch_hermster_trade` = `-1003918757178`) liegt in `TELEGRAM_CHAT_ID` —
  **nicht** `TELEGRAM_HOME_CHANNEL` (das ist der Hermes-Home-Kanal). Erst HOME_CHANNEL,
  dann CHAT_ID als Fallback ist die generische Reihenfolge, aber für Trading-Jobs
  explizit `TELEGRAM_CHAT_ID` setzen/verifizieren.
- Die system-crontab / Trading-Crons dürfen NUR den Trading-Bot-Token verwenden,
  nicht z.B. @myhermster_bot.

no_agent-Wrapper laden `.env` (Konvention, s. trading-skill/Erklaerung.md):
```bash
export $(grep -v '^#' /root/.hermes/profiles/hermes_trading/.env | xargs)
```

## ⚠️ parse_mode="HTML" scheitert an rohen `<` / `>` — die #1-Falle

Wenn du `parse_mode="HTML"` setzt und die Message irgendwo ein nacktes `<`/`>`
enthält (oft aus generierten Daten), kommt:
```
HTTP 400: Bad Request: can't parse entities: Unsupported start tag "" at byte offset N
```
Das `<` wird als Tag-Anfang interpretiert. Beispiele die crashen:
- `"SL_Quote < 60%"` (Text), `"Payoff > 1.5"`
- Dict-Strings mit `<`/`>` in reasons/Fehlermeldungen

**Fix — zweigleisig:**
1. **HTML-escapen** der rohen Daten im Text: `import html; html.escape(str(x))`
   (macht aus `<` → `&lt;`, `>` → `&gt;`, `'` → `&#x27;`).
2. **Vermeide `<`/`>` in Prosa** — formuliere "unter 60%" / "über 1.5" statt
   `< 60%` / `> 1.5`. Auch `Δ`/`→` sind ok, aber bei den Tags vorsichtig sein.

**Diagnose:** `.sendMessage` HTTP 400 ohne weitere Meldung → isolieren: erst plain
senden (200?), dann exakte Message. Kontrolle unbedingt eigenständig ausführen, nicht
nur auf Script-nur-print verlassen.

## Fehlermeldung von Telegram auslesen

Rufe `r.json()["description"]` / `r.text` beim Fehler aus, um die Byte-Offset-Info
("Unsupported start tag at byte offset 65") zu sehen — das zeigt exakt welches Zeichen.

## Script-geprüftes Beispiel (weekly_strategy_review)

Eigenes, verifiziertes Muster das 200 liefert: HTML-escape der rohen Dict-Reasons via
`html.escape(...)`, "unter/über"-Formulierung statt `<`/`>`, strukturierte `<b>`-Tags
für echte Hervorhebungen.
