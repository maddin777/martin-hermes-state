---
name: hermes-identity-vault-setup
description: "Komplettes Setup: SOUL.md upgrade auf Community-Standard, MEMORY.md + USER.md anlegen, 00-CAPTURE-Ordner, Weekly Review Cron, Vault Self-Write Health Cron. Abgeleitet aus den Artikeln von @tonysimons_ und @shmidtqq."
category: devops
---

# Hermes Identity + Vault Setup

Setup der Identity Layer (SOUL.md, MEMORY.md, USER.md) + Vault Cron-Jobs.
Basierend auf @tonysimons_ "170-Line SOUL.md" und @shmidtqq "99% of Hermes Agent Users..."

## Voraussetzungen
- Hermes läuft
- Obsidian Vault unter `/root/obsidian-vault/`
- rclone remote `gdrive:` konfiguriert

## Schritt 1: SOUL.md upgraden

**Pfad:** `/root/.hermes/SOUL.md`

Minimale Sektionen:
1. **Identity** — Autonomous operator, thought partner. Nicht "assistant".
2. **Ton & Stimme** — Getrennt: privat (direkt/ungefiltert) vs öffentlich (präzise/substanziell)
3. **Pushback-Regeln** — Wann widersprechen + wie (mit Belegen). "Disagree and provide receipts."
4. **Autonomie-Grenzen** — Was ohne Fragen, was nur mit OK
5. **Mission Map** — Live-Inventory der Projekte (aktiv/stale/explizit nicht)
6. **Accountability Loop** — Output Graveyard verhindern, Martin zum Handeln bringen
7. **Self-Improvement** — Skills patchen, Fehler analysieren, Korrekturen merken
8. **Cross-Session-Verhalten** — MEMORY.md + USER.md automatisch nutzen

**Beispiel Pushback-Sektion:**
```
## Pushback-Regeln
Du MUSST widersprechen, wenn:
- Eine Idee vage, unausgegoren oder bereits gescheitert ist
- Der Aufwand den Nutzen nicht rechtfertigt
So widersprichst du richtig:
- Immer mit Belegen: Daten, Code, konkretes Beispiel
- Biete eine Alternative, nicht nur Kritik
```

## Schritt 2: MEMORY.md anlegen

**Pfad:** `/root/.hermes/MEMORY.md`

Enthält projektbezogene Fakten die über Sessions persistieren:
- Obsidian Vault Pfad + rclone Config
- Hermes-Profile & Bot-Tokens
- Trading-System Details
- Gateway-Watchdog
- Skills-Übersicht
- Sonstige Infrastruktur (GitHub, Playwright, TTS/STT)

Keine temporären Task-Infos speichern (PR-Nummern, Issue-IDs, "Phase X done").

## Schritt 3: USER.md anlegen

**Pfad:** `/root/.hermes/USER.md`

Enthält Martins persönliches Profil:
- Beruf/Rolle (SAP SAC Developer)
- Kommunikations-Präferenzen (Deutsch, Du, direkt)
- Arbeitsweise (Terminal-Style, schnelle Entscheidungen)
- Wichtig (Präzision, Autonomie, Wartbarkeit, Out-of-the-Box-Denken)
- Abneigungen (Sycophancy, Hype-Sprache, Overengineering)
- Bot-Namenskonvention

## Schritt 4: 00-CAPTURE-Ordner

```bash
mkdir -p /root/obsidian-vault/00-CAPTURE/
touch /root/obsidian-vault/00-CAPTURE/.gitkeep
```

Capture-First-Ordner: Neue Notizen landen hier, werden später von vault-insights-daily einsortiert.

## Schritt 5: Weekly Review Cron

```bash
hermes cron create \
  --name weekly-review \
  --schedule "0 19 * * 0" \
  --prompt "Führe Weekly Review durch: (1) Vault-Änderungen letzte 7 Tage (2) Trading-Check (3) Sync-Health (4) Projekt-Status (5) Max 3 Empfehlungen (6) Probleme flaggen"
```

Oder per cronjob tool mit action='create'.

## Schritt 6: Vault Self-Write Health Cron

```bash
hermes cron create \
  --name vault-self-write-health \
  --schedule "0 3 * * 6" \
  --deliver local \
  --prompt "Vault Self-Write: (1) Health Check - broken Links, Orphans (2) Backward Integration - neue Wikilinks ergänzen (3) Gap Detection - fehlende Wiki-Seiten (4) Synthesis - übergreifende Analyse/MOC"
```

## Verifikation

```bash
# SOUL.md prüfen
head -5 /root/.hermes/SOUL.md
# Soll Identity-Zeile enthalten: "Du bist Hermes, Martins autonomer Operator..."

# MEMORY.md prüfen
head -5 /root/.hermes/MEMORY.md
# Soll Obsidian-Vault-Pfad enthalten

# USER.md prüfen
head -5 /root/.hermes/USER.md
# Soll "USER.md — Martin" im Titel haben

# 00-CAPTURE prüfen
ls -la /root/obsidian-vault/00-CAPTURE/

# Crons prüfen
hermes cron list | grep -E "weekly-review|vault-self-write"
```

## Pitfalls
- SOUL.md zu lang oder zu abstrakt schreiben → lieber konkret mit Beispielen
- MEMORY.md mit transienten Daten füllen (Task-Status, Issue-Nummern) → verboten, nur durable Facts
- USER.md vergessen zu aktualisieren wenn Martins Prioritäten sich ändern
- Weekly Review zu detailliert → Kurz-Report reicht, [SILENT] wenn nix zu melden
- Vault Self-Write könntee zu viele Änderungen machen → auf max 5 Wikilinks + 2 neue Seiten + 1 Synthesis limitieren