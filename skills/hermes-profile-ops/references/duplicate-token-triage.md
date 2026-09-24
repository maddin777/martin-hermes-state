# Duplicate Telegram Credential Triage (Doctor-Warnungen)

Der Doctor-Durchlauf (`hermes doctor fix`) meldet regelmässig identische
Warnungen für mehrere Profile:
```
⚠ Duplicate platform credential across profiles (Profiles 'default' und 'X' both hold the same telegram credential (TELEGRAM_BOT_TOKEN))
```

**Kernregel: Diese Warnungen sind NICHT automatisch echte Konflikte.**
Ein TELEGRAM_BOT_TOKEN in einem Profil-.env ist nur dann ein Problem, wenn
dieses Profil tatsächlich als **aktiver Gateway** läuft und damit um den
Bot-Poll streitet. Ein brachliegender Token in einem Roster-/Delegation-Profil
(coder, designer, researcher, reviewer, writer — laufen als Subagenten über
den default-Gateway, nie als eigenes Gateway) ist harmlos. Der Doctor meldet
ihn trotzdem weiter, bis die Datei angefasst wird.

---

## Triage — erst feststellen, wer real konkurriert

### 1. Token-Hash vergleichen (Secret nie ausgeben)
```bash
for p in coder designer researcher reviewer writer; do
  h=$(grep '^TELEGRAM_BOT_TOKEN=' ~/.hermes/profiles/$p/.env 2>/dev/null | cut -d= -f2- | sha256sum | cut -c1-12)
  echo "$p: $h"
done
# gleicher Hash wie default = Duplikat; anderer Hash = eigenes Bot (z.B. hermes_trading, harmlos)
```

### 2. Nur aktive Gateways zählen
```bash
systemctl list-units --type=service | grep hermes-gateway
# NICHT alle aufgeführten zählen — nur `running`; `dead`/nicht vorhanden = Gateway startet nicht = Token harmlos
```

**Echter Konflikt existiert nur wenn: 2+ Profile als running-Gateway laufen UND
denselben Token halten.** Sonst nichts anfassen.

---

## Fix bei echtem Konflikt

### 1. Token aus dem Überschuss-Profil entfernen
Das Profil, das den Bot NICHT braucht (z.B. API-Server/Open-WebUI-only wie
hermes_learn), verliert seinen Telegram-Token. NUR die zwei Telegram-Zeilen,
Rest der .env unangetastet (OpenRouter, API_SERVER, etc. bleiben):
```bash
sed -i -E '/^TELEGRAM_BOT_TOKEN=/d; /^TELEGRAM_CHAT_ID=/d' \
  ~/.hermes/profiles/<profil>/.env
# Verify: grep -cE '^TELEGRAM_BOT_TOKEN=|^TELEGRAM_CHAT_ID=' -> 0
```

### 2. BEIDE Gateways neu starten (kritisch!)
Der geparkte Gateway (der den Konflikt verloren hat) versucht NICHT von selbst
neu zu verbinden — er bleibt im degraded-Zustand geparkt, bis er restarted wird.
```bash
systemctl restart hermes-gateway-<profil>.service   # der behobene
systemctl restart hermes-gateway.service            # der geparkte Haupt-Gateway
```

### 3. Verifizieren, dass der Haupt-Bot wieder exklusiv bedient wird
```bash
grep -iE 'telegram' ~/.hermes/logs/gateway.log | tail -6
# erwartet: '✓ telegram connected' + 'set_my_commands OK' + Home-Channel-Notification
# der frühere Fehler 'bot token already in use by the <profil> gateway' muss verschwunden sein
```

---

## Symptom-Erkennung im Log

Der Konflikt hinterlässt im Gateway-Log präzise Zeugen:
```
ERROR gateway.run: ✗ telegram failed to connect
ERROR gateway.run: 1 configured platform(s) failed to start and are parked ...
  telegram: Telegram bot token already in use by the '<profil>' profile gateway (PID XXXX)
  The gateway is DEGRADED
```
Diese Signaturen ignorieren — oder sofort die Triage oben anwenden.

---

## Merksätze

- Nie Token im Klartext ausgeben; immer nur sha256-Hash zum Vergleich.
- `systemctl running`-Status zählen, nicht die Warnung selbst, entscheidet ob real.
- Nach dem Entfernen BEIDE Gateways restarten — der geparkte reconnected nie von selbst.
- Roster-Profile ohne laufenden Gateway mit Token liegenlassen; nur anfassen wenn sie
  je als eigenes Gateway gestartet werden (dann vorher Token entfernen).
