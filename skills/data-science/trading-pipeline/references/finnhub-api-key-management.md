# Finnhub API Key Management

## Wo der Key liegt

Einzige aktive Quelle: `/root/.hermes/profiles/hermes_trading/.env`
```
FINNHUB_API_KEY=***hier***
```

Geladen via `thematic/lib/finnhub_client.py` Zeile 13:
```python
FINNHUB_KEY = os.environ.get("FINNHUB_API_KEY")
```
Nach `import env_loader` (Zeile 8), das die `.env` lädt.

## Symptom: 403 Forbidden auf allen Endpunkten

Thematic Pipeline Log zeigt:
```
[Finnhub] Fehler /stock/metric: 403 Client Error: Forbidden for url: ...
[Finnhub] Fehler /stock/recommendation: 403 Client Error: Forbidden ...
```

Das bedeutet: API-Key ist abgelaufen, Monatslimit erschöpft, oder revoked.

## Diagnose

```bash
# Key prüfen
grep FINNHUB_API_KEY /root/.hermes/profiles/hermes_trading/.env

# Test-Request (403 = tot, 200 = lebt)
curl -s "https://finnhub.io/api/v1/stock/profile2?symbol=AAPL&token=$(grep FINNHUB_API_KEY /root/.hermes/profiles/hermes_trading/.env | cut -d= -f2)"
```

## Fix

1. Neuen Free-Tier Key auf https://finnhub.io/ holen
2. In `/root/.hermes/profiles/hermes_trading/.env` ersetzen
3. Kein Restart nötig — nächster Pipeline-Lauf liest neuen Key

## Welche Pipeline-Schritte betroffen sind

| Schritt | Finnhub-Abhängigkeit | Verhalten bei 403 |
|---------|---------------------|-------------------|
| Fundamental Screen | **Zwingend** (PE, ROE, Short Interest, Earnings) | Liefert leere Daten, Pipeline zeigt ❌ |
| Factor Ranking | **Optional** (Fallback auf yfinance) | Läuft trotzdem durch ✅ |

## Key auch in Doku-Dateien

Der Key steht evtl. auch in `/root/obsidian-vault/Stuff/n8nONporxmox.txt` — dort beim Wechsel ebenfalls updaten.