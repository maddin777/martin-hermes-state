## Supplements (Session 01.07.2026)

### Echte Lücke: 44 Minuten nach Schedule noch nicht gefeuert

Ein One-Shot-Job (`daily-news-briefing-extra-0930`, id `100418893b49`) wurde um
09:11 erstellt mit Schedule `2026-06-30T09:30:00` (= 19 Minuten in der Zukunft).
Um 10:14 zeigte der Job immer noch:
- `next_run_at: null`
- `last_run_at: null`
- `state: scheduled`

Obwohl 44 Minuten vergangen waren, hat der Scheduler den Job nie aufgegriffen.
Fix: `cronjob action=run job_id=100418893b49` — der Job lief dann sofort (10:21)
und produzierte 25KB Output.

### Doppeltes Update (deliver-Änderung) als mögliche Ursache

Der Job wurde innerhalb von 30 Sekunden dreimal geupdated:
1. `cronjob create` → deliver=local
2. `cronjob update` → deliver=origin
3. `cronjob update` → deliver=telegram:-1003687061880

Es ist möglich, dass die schnelle Update-Kette den internen Zustand des
Schedulers korrumpiert hat — der Job hatte beim Erstellen einen gültigen
Schedule, aber die Updates haben `next_run_at` auf null gesetzt ohne ihn
neu zu schedulen.

**Prävention:** One-Shot-Jobs nach Erstellung mit allen Parametern auf einmal
anlegen, nicht Schrittweise updaten. Oder recurring Cron mit `repeat: 1` nutzen.