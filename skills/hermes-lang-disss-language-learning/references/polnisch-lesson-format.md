---
name: polnisch-disss-context
title: Polnisch DiSSS Functional Context Lessons
description: "Polnisch-Lektionen fuer hermes_lang Profil mit DiSSS-Methode: Top-500 Selektion, n+1 Sentence Mining, Aspekt-Paare und Kasus, Lueckentext-Quiz."
trigger: "Polnisch Lektion, DiSSS Polnisch, polnisch-disss-daily"
---

# Polnisch DiSSS – Functional Context Lessons

## Aufgabenstruktur (taeglich)

Erstelle eine Polnisch-Lektion mit exakt folgendem Format:

### 1. Selektion (Top 500)
Waehle **10 hochfrequente polnische Woerter/Phrasen** aus den Top 500.
Ziehe aus dem gesamten Spektrum. Baue auf bereits behandelten Woertern auf.

### 2. Sentence Mining (n+1)
Gib fuer **jedes** Wort einen ultrakurzen n+1-Satz:
- Subjekt + Verb + Objekt (max 6 Woerter)
- Maximal 1 unbekanntes Wort pro Satz
- Format: **Wort** `Uebersetzung` + Satz. (Uebersetzung)

### 3. Der Grammatik-Haken
- **Bei Verben:** Aspekt-Paar (unvollendet/vollendet), z.B. `robic / zrobic`
- **Bei Nomen:** Endungsaenderung erklaeren (welcher Kasus)
- Max 2 Saetze

### 4. Interaktives Quiz
10 Lueckentexte: `______ ...` (Grundform – Loesung)

### 5. Aufloesung (Answer Key)
Nach dem Quiz: alle 10 Loesungen als nummerierte Liste.
- Format: `1. Loesung` – kurzer Hinweis (1 Satz), warum diese Form richtig ist

## Layout (Telegram)
- **fett** fuer Polnisch, `monospace` fuer Deutsch
- Trennlinie `---` zwischen Bloecken
- Max 2 Saetze pro Erklaerung

## Beispiel
```
**Polnisch – Lektion #N**
--- Selektion ---
**Pociag** `Zug`
**Jechac** `fahren`
**Szybko** `schnell`
**Bilet** `Fahrkarte`
**Dworzec** `Bahnhof`
... (insgesamt 10 Woerter)
--- Sentence Mining ---
**Pociag** `Zug`
Pociag jedzie szybko. (Der Zug faehrt schnell.)
Info: Nominativ (Subjekt)
--- Grammatik ---
**jechac** – jechac (unvoll.) / pojechac (voll.)
--- Quiz ---
[... 10 Lueckentexte]
--- Aufloesung ---
1. Pociag – Nominativ Singular
2. jedzie – 3. Person Singular von jechac
```

## Nach der Lektion
- Obsidian: `~/obsidian-vault/Lernen/Polnisch/04-Tagebuch.md`
- Lektion-Nummer erhoehen
- TTS mit 5 Saetzen (optional)

## Pitfalls

- **Obsidian-Diary wird bei Vault-Refresh ueberschrieben** — `04-Tagebuch.md` liegt auf GDrive. Bei `rclone sync` (Fresh-Bezug) gehen lokale Lesson-Eintraege verloren. Nach Vault-Refresh: Diary-Eintrag manuell neu anlegen.
- **Gateway muss laufen** — Cron-Job tickt nur bei aktivem `hermes_lang` Gateway. `hermes profile list` pruefen. Falls stopped: `systemctl reset-failed hermes-gateway-hermes_lang && systemctl start hermes-gateway-hermes_lang`.
- **Skill-Referenz im Cron-Job kann Job-Verlust verursachen** — Bei git pull + Scheduler-Neustart koennen Cron-Jobs mit `"skills": [...]` Feld aus jobs.json verschwinden. Loesung: Prompt muss alle Format-Anweisungen inline enthalten (wie hier) — das `skills`-Feld ist redundant. Nach jedem git pull: `cat {profile}/cron/jobs.json` auf Vollstaendigkeit pruefen.
- **Profilname ist `hermes_lang`** (Unterstrich), nicht `hermes-lang`.

## Regeln\n- Nie gleiche Woerter wie gestern\n- Max 1 neues Wort pro Satz\n- Immer Deutsch erklaeren