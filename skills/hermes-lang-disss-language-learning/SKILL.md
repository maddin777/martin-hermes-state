---
name: hermes-lang-disss-language-learning
title: "DiSSS Language Learning (Hermes-Lang)"
description: "Automatisiert Tim Ferriss DiSSS-Methode (Dekonstruktion, Auswahl, Sequenzierung, Simplifizierung, Stakes) fuer Sprachenlernen im hermes_lang Profil. Eingabe: Sprache (z.B. Spanisch). Erzeugt Obsidian-Plan, Anki-CSV, taeglichen Cron fuer Telegram."
trigger: "Lerne [SPRACHE] mit DiSSS"
requirements:
  - web_search
  - execute_code
  - write_file
  - terminal
  - cronjob
output: "~/obsidian-vault/Lernen/[SPRACHE]/; ~/Anki/[SPRACHE].csv; Cron-Job-ID"
---

# DiSSS Sprachenlernen Skill fuer hermes_lang

## 0. Voraussetzungen (pruefen vor Start)

**Gateway muss laufen.** Cron-Jobs brauchen ein aktives Gateway. Pruefe:
```bash
hermes profile list | grep hermes_lang  # Status muss "running" sein
```
Falls stopped: `hermes_lang gateway start`.

**Profilname ist `hermes_lang`** (Unterstrich), NICHT `hermes-lang`. Alle Pfade im Skill verwenden `hermes_lang`.

**Model-Wahl:** Fuer Cron-Jobs mit laengeren Prompts (Quiz + Grammatik + Fortschritt) `openrouter/owl-alpha` nutzen -- vermeidet Output-Truncation, die bei `openai/gpt-oss-120b:free` auftreten kann.

**Ordner anlegen**:
```bash
mkdir -p ~/obsidian-vault/Lernen/[SPRACHE]
```

## 1. Dekonstruktion
```
web_search(query="top 1000 most frequent words [SPRACHE] frequency list")
web_search(query="essential grammar rules [SPRACHE] Pareto 80/20")
web_search(query="[SPRACHE] pronunciation guide IPA")
web_search(query="100 most common phrases [SPRACHE]")
```
write_file(path="~/obsidian-vault/Lernen/[SPRACHE]/01-Dekonstruktion.md", content="## Vokabel\n[RESULTS1]\n## Grammatik\n[RESULTS2]\n## Aussprache\n[RESULTS3]\n## Phrasen\n[RESULTS4]")

## 2. Auswahl (80/20)
```
execute_code(code="""
voc = '''[VOC RESULTS]'''
lines = [l for l in voc.splitlines() if l.strip() and not l.startswith('#')]
top_voc = lines[:200]
print('**Top 200 Vok:**', '\\n'.join(top_voc[:20]), '...')
""")
```
write_file(path="~/obsidian-vault/Lernen/[SPRACHE]/02-Auswahl.md", content="**Top Vokabel:**\n[TOP_VOC]\n**Top Grammatik (10):**\n[TOP_GRAM]\n**Top Phrasen (50):**\n[TOP_PHRASES]")

## 3. Sequenzierung
Plan:
1. Woche 1: Aussprache + 50 Vok (20min/Tag)
2. Woche 2: Grammatik + Phrasen
3. Woche 3: Konversation
4. Woche 4: Review/Immersion
write_file(path="~/obsidian-vault/Lernen/[SPRACHE]/03-Sequenz.md", content="## Sequenz\n| Woche | Fokus | Zeit |\n|---|---|---|\n|1|Aussprache+Vok|20min|\n|2|Grammatik|20min|\n|3|Konvo|30min|\n|4|Review|20min|")

## 4. Simplifizierung
```
csv = 'Front;Back\n'
for v in top_voc:
  csv += f'{v};[DE Uebersetzung]\n'
write_file(path=f"~/Anki/[SPRACHE].csv", content=csv)
```
**Ressourcen**: Duolingo, YouTube "[SPRACHE] Tim Ferriss".

## 5. Cron-Job anlegen (Stakes)

```bash
hermes -p hermes_lang cron create "0 8 * * *" \
  "DiSSS Lesson [SPRACHE]: Quiz 10 random Vok (PL->DE), 1 Grammatik-Tipp, Fortschritt in Obsidian." \
  --name [SPRACHE]-disss-daily \
  --deliver telegram \
  --model provider=openrouter,model=openrouter/owl-alpha
```

**Kein `deliver='local'`** -- liefert an Ch_hermster_lang. Ohne `--deliver telegram` landen Lektionen im lokalen Output-Ordner und nie auf Telegram.

**Kein `skills=` im cronjob create** -- Skill-Referenzen in Cron-Jobs koennen beim Scheduler-Neustart (z.B. nach git pull) zum Verlust des Jobs fuehren. Das Default-Profil hat den Skill nicht, daher kann der Scheduler den Job als invalid behandeln. Stattdessen die Skill-Anweisungen direkt in den Prompt schreiben.

## Pitfalls

- **Profilname: `hermes_lang`** (Unterstrich), nicht `hermes-lang`. Falscher Pfad -> Cron bricht ab.
- **Gateway muss laufen** -- `hermes profile list` pruefen, sonst schlaegt Cron silent fehl.
- **Cron-Job kann bei git pull fliegen** -- Cron-Jobs mit profile-spezifischen Skill-Referenzen (`skills: [hermes-lang-disss-language-learning]`) werden beim Scheduler-Neustart nach `git pull` ggf. nicht geladen. Loesung: Skills im Prompt embedden, nicht als `skills=` referenzieren. Nach jedem git pull: `hermes cron list` pruefen.
- **Model-Output-Limit:** `openai/gpt-oss-120b:free` truncated bei Quiz+Grammatik+Fortschritt. `openrouter/owl-alpha` nutzen.
- **Anki manuell importieren:** CSV wird geschrieben, aber nicht automatisch in Anki geladen.
- **20min/Tag max** -- Skill ist fuer Mikro-Lektionen ausgelegt.
- **Keine `hermes_tools`-Importe in Scripts** -- `from hermes_tools import read_file` existiert nicht. Daten per `read_file` Tool holen, nicht per Python-Script.

## Verify

```bash
hermes cron list --profile hermes_lang
grep -c "[SPRACHE]" ~/Anki/[SPRACHE].csv 2>/dev/null || echo "CSV leer/fehlt"
ls ~/obsidian-vault/Lernen/[SPRACHE]/
```

Dann einen Dry-Run:
```bash
hermes -p hermes_lang cron run [JOB_ID]
```

Pruefe ob Lektion auf Ch_hermster_lang ankommt.