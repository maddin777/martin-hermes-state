## Supplements (Session 01.07.2026)

### Encoding-Probleme bei manueller Telegram-Delivery via curl

Beim manuellen Zustellen von Cron-Output über den Profil-Bot (nachdem ein Job
im default Scheduler gelaufen ist aber nicht delivered hat) können zwei Fallstricke
auftreten:

1. **curl heredoc frisst Sonderzeichen** — `curl -d "text=$(cat <<'EOF'...)"` 
   zerstört Unicode-Zeichen wie `•`, `°`, `—`, `☀️`. Die Nachricht kommt
   verstümmelt an (nur "Politik" oder "IT" als Fragment).

2. **JSON-Payload gibt 404** — `urllib.request` mit JSON-Body
   (`json.dumps({"chat_id": ..., "text": ...})`) auf die Telegram API gibt
   HTTP 404, obwohl der Bot gültig ist und form-data via curl funktioniert.

**Fix:** Python mit `urllib.parse.urlencode` (form-data, nicht JSON):

```python
import urllib.request, urllib.parse

url = f"https://api.telegram.org/bot{token}/sendMessage"
data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
req = urllib.request.Request(url, data=data)
resp = urllib.request.urlopen(req)
```

Oder curl mit `--data-urlencode`:
```bash
curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
  --data-urlencode "chat_id=${CHAT_ID}" \
  --data-urlencode "text@-" <<< "$CHUNK"
```

### `.env` einlesen in Python nicht per `source`

`source /root/.hermes/profiles/<profil>/.env && python3 -c "..."` funktioniert NICHT —
die gesourcten Env-Vars sind nur in der Shell aktiv, nicht im Python-Subprozess.

**Fix:** Die `.env`-Datei in Python selbst parsen:

```python
import os
with open('/root/.hermes/profiles/hermes-news/.env') as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ[k.strip()] = v.strip().strip('"').strip("'")
```

### Deepseek-Test: Job im default Scheduler mit profile + deliver: telegram

Am 01.07.2026 wurde ein Test-Job (id `76cd23166bce`) mit `model: deepseek/deepseek-v4-flash`,
`profile: hermes-news` und `deliver: telegram` im default Scheduler angelegt und per
`cronjob run` getriggert.

**Ergebnis:** Der Job lief erfolgreich (Inhalt gut, 25KB Output), aber die Delivery
kam im DM (Home-Channel des default Bots @myhermster_bot) an — nicht im News-Channel
Ch_hermster_news. Grund: `cronjob run` ignoriert das `profile`-Feld (siehe neues Pitfall),
der Job lief im default Kontext.

**Konsequenz:** Für Delivery in den News-Channel muss der Job zwingend im
hermes-news Profil-Scheduler leben.