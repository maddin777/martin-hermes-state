# Debugging: Verschwundene Cron-Jobs

Wenn ein Cron-Job aus `jobs.json` verschwindet, ohne dass ihn jemand geloescht hat.

## Typisches Muster
- Job laeuft tagelang normal
- Nach einem `git pull` (oder anderem Scheduler-Neustart) ist der Job weg
- Andere Jobs (ohne Skill-Referenzen) ueberleben

## Ursache
Cron-Jobs mit **profile-spezifischen Skill-Referenzen** (`skills: [profil-skill-name]`) koennen beim Scheduler-Neustart nach `git pull` verloren gehen. Der Scheduler laeuft im Default-Profil und findet den referenzierten Skill dort nicht. Je nach Code-Path wird der Job dann als invalid behandelt und nicht wieder in `jobs.json` geschrieben.

Betroffen sind Jobs, bei denen `skills:` im `cronjob(action='create', ...)` Tool gesetzt wurde:
```
cronjob(action='create', skills=['hermes-lang-disss-language-learning'], ...)
```

Nicht betroffen sind Jobs ohne `skills:` (wie vault-insights-daily, bisync, watchdog).

## Debugging-Sequenz

```
# 1. Cron-Job-Liste checken
hermes cron list

# 2. Output-Verzeichnis nach alten Job-IDs durchsuchen
ls -la ~/.hermes/cron/output/

# 3. In den Output-Files nach altem Job suchen
cat ~/.hermes/cron/output/<job_id>/<latest>.md  2>/dev/null

# 4. Git Reflog nach Scheduler-Neustarts durchsuchen
git -C ~/.hermes/hermes-agent reflog --since="2026-04-20" -- cron/

# 5. Timeline erstellen:
#    - Wann wurde der Job zuletzt ausgefuehrt? (ls -lt output/<job_id>/)
#    - Wann war der letzte git pull? (reflog)
#    - Was wurde im git pull gecherrypickt? (git log alter_ref..neuer_ref -- cron/)

# 6. Andere Jobs im output/ cross-checken:
#    - Haben sie ueberlebt? Wann liefen sie zuletzt?
#    - Haben sie `skills:` Feld im jobs.json Eintrag?
```

## Fix

1. Job neu anlegen, aber **ohne `skills=`**.
2. Skill-Anweisungen stattdessen direkt in den Prompt embedden.
3. Nach dem Anlegen: `hermes cron list` notieren.
4. Nach jedem `git pull`: `hermes cron list` gegenchecken.

## Beispiel aus der Praxis

Der Polnisch-DiSSS-Job (`ca29d47dc885`) hatte `skills: ['hermes-lang-disss-language-learning']`. Er lief zuletzt am 23.04. um 23:28 (API-Connection-Error). Am 24.04. um 20:31 wurde `git pull --ff-only` ausgefuehrt (6 Cron-bezogene Commits im Pull). Danach war der Job aus `jobs.json` verschwunden. Die anderen Jobs (bisync, watchdog, vault-insights) ohne Skill-Referenzen ueberlebten.