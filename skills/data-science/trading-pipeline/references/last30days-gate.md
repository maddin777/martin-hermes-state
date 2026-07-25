# Last30days Pre-Trade Gate

## Script
`scripts/last30days_gate.py` — Standalone Python-Script, läuft als Subprocess aus `signal_manager.py`.

## Funktionsweise
- **Quelle:** Google News RSS (kein API-Key nötig, kein Rate-Limit)
- **Suche:** `<TICKER> <Name> stock` als Query
- **Analyse:** Keyword-basiert (32 negative + 18 positive Keywords)
- **Score:** 0.0–1.0 (0.5 = neutral)

## Verdict-Stufen

| Exit-Code | Verdict | Bedeutung |
|-----------|---------|-----------|
| 0 | `ok` | Kein Eingriff, Entry läuft normal |
| 1 | `warning` | Negative News-Stimmung → Log-Eintrag |
| 2 | `block` | Stark negative News → **Entry abgebrochen** |

## Integration in signal_manager.py
- Position: Nach Grok Breaking-News-Check, vor Preis/ATR-Fetch
- Nur für HIGH-Conviction (≥0.80)
- Fail-Open: Jeder Fehler (Timeout, ConnectionError, ParseError) lässt den Entry passieren

## Beispiel-Output
```json
{
  "ticker": "AAPL",
  "verdict": "warning",
  "sentiment": "bearish",
  "score": 0.42,
  "findings": ["Apple Declines More Than Market", "Morgan Stanley revamps Apple target"],
  "sources": ["https://news.google.com/..."],
  "error": null
}
```

## Bekannte Grenzen
- Google News RSS liefert nur englische Quellen
- Keyword-basiert, kein LLM-Sentiment
- Nur News-Titel, keine Artikel-Tiefe
- Kein Reddit/X-Scraping (das macht der Hermes-Skill last30days)