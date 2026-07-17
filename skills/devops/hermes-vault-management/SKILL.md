---
name: hermes-vault-management
description: "Lifecycle of the Hermes Obsidian vault: identity layer setup (SOUL.md, MEMORY.md, USER.md), 00-CAPTURE folder, weekly review and health crons, and the daily vault-insights pipeline."
category: devops
---

# Hermes Vault Management

Umbrella for the full lifecycle of an Obsidian vault powering Hermes agent identity and knowledge compounding. Covers setup (identity files, capture folder, cron infrastructure) and daily operations (wiki maintenance, insight extraction, health checks).

---

## 1. Identity Layer Setup

Setup of SOUL.md, MEMORY.md, USER.md, 00-CAPTURE folder, and vault cron jobs. Based on @tonysimons_ "170-Line SOUL.md" and @shmidtqq "99% of Hermes Agent Users..."

### Prerequisites
- Hermes is running
- Obsidian vault under `/root/obsidian-vault/`
- `rclone` remote `gdrive:` configured

### Step 1: SOUL.md

**Path:** `/root/.hermes/SOUL.md`

Minimum sections:
1. **Identity** — Autonomous operator, thought partner. Not "assistant."
2. **Tone & Voice** — Separate: private (direct/unfiltered) vs public (precise/substantial)
3. **Pushback Rules** — When to disagree + how (with evidence). "Disagree and provide receipts."
4. **Autonomy Boundaries** — What can be done without asking, what requires OK
5. **Mission Map** — Live inventory of projects (active/stale/explicitly not)
6. **Accountability Loop** — Prevent output graveyard, push the user to act
7. **Self-Improvement** — Patch skills, analyze mistakes, remember corrections
8. **Cross-Session Behavior** — Automatically use MEMORY.md + USER.md

**Example Pushback section:**
```
## Pushback-Regeln
Du MUSST widersprechen, wenn:
- Eine Idee vage, unausgegoren oder bereits gescheitert ist
- Der Aufwand den Nutzen nicht rechtfertigt
So widersprichst du richtig:
- Immer mit Belegen: Daten, Code, konkretes Beispiel
- Biete eine Alternative, nicht nur Kritik
```

### Step 2: MEMORY.md

**Path:** `/root/.hermes/MEMORY.md`

Contains project-level facts that persist across sessions:
- Obsidian vault path + rclone config
- Hermes profiles & bot tokens
- Trading system details
- Gateway watchdog
- Skills overview
- Other infrastructure (GitHub, Playwright, TTS/STT)

**Do not** store temporary task info (PR numbers, issue IDs, "Phase X done").

### Step 3: USER.md

**Path:** `/root/.hermes/USER.md`

Personal profile (example for Martin):
- Role: SAP SAC Developer
- Language: German, informal "Du"
- Working style: Terminal-oriented, quick decisions
- Values: Precision, autonomy, maintainability, out-of-the-box thinking
- Dislikes: Sycophancy, hype language, overengineering

### Step 4: 00-CAPTURE folder

```bash
mkdir -p /root/obsidian-vault/00-CAPTURE/
touch /root/obsidian-vault/00-CAPTURE/.gitkeep
```

Capture-first folder: new notes land here, sorted later by vault-insights-daily.

### Step 5: Weekly Review Cron

```bash
hermes cron create \
  --name weekly-review \
  --schedule "0 19 * * 0" \
  --prompt "Weekly review: (1) Vault changes last 7 days (2) Trading check (3) Sync health (4) Project status (5) Max 3 recommendations (6) Flag issues"
```

### Step 6: Vault Self-Write Health Cron

```bash
hermes cron create \
  --name vault-self-write-health \
  --schedule "0 3 * * 6" \
  --deliver local \
  --prompt "Vault Self-Write: (1) Health check - broken links, orphans (2) Backward integration - new wikilinks (3) Gap detection - missing wiki pages (4) Synthesis - cross-topic analysis/MOC"
```

### Verification

```bash
head -5 /root/.hermes/SOUL.md        # should have identity line
head -5 /root/.hermes/MEMORY.md      # should have vault path
head -5 /root/.hermes/USER.md        # should have "USER.md — Martin"
ls -la /root/obsidian-vault/00-CAPTURE/
hermes cron list | grep -E "weekly-review|vault-self-write"
```

## 3. Running the Weekly Review (Sunday 19:00 Cron)

The weekly review runs as a Hermes cron job (`weekly-review`, beb26022a5d9, schedule `0 19 * * 0`). It checks vault health, trading pipeline, project progress, and infrastructure. No user present — fully autonomous.

### Step 1: Vault Scan — Files Modified in Last 7 Days

```bash
find /root/obsidian-vault/ -type f -name '*.md' -newer /root/obsidian-vault/ -mtime -7 \
  | grep -v '.obsidian/' \
  | grep -v 'Projekte/Buecher/' \
  | sort
```

Categorize results into:
- **wiki/concepts/** — new conceptual pages (most valuable signal)
- **wiki/entities/** — new entity pages
- **Trading/** — watchlist, documentation changes
- **Clippings/** — new web clippings ingested
- **hermes/** — agent-related notes
- **Lernen/Polnisch/** — language learning progress
- **Other** — Stuff/, raw/, etc.

### Step 2: Trading Check

Read the Watchlist head to verify freshness:
```bash
head -5 /root/obsidian-vault/Trading/Watchlist.md
```
Key metrics to extract: Gesamt count, ≥76% Conviction count, export date.
Also check `Trading/Erklaerung.md` version line for documentation updates.

### Step 3: Cron Health

List all Hermes cron jobs and verify last-run status:
```bash
hermes cron list
```
Check specifically:
- `f5eb3bfaf65e` (obsidian-vault-bisync-nightly) — **`last_status` + `last_run_at`** prüfen. Der Job ist `no_agent` → silent bei Erfolg. Wenn `last_status = "ok"` und `last_run_at` < 2 Tage alt, ist alles gut. `cronjob action=run` liefert hier **keinen Output** bei Erfolg!
- `53f222b00811` (vault-insights-daily) — ran today?
- All other jobs should show status and recent `ok` run

### Step 4: Project Status

Map changes against known project inventory from the Mission Map:
- **🟢 Active** — pipeline running, wiki growing, learning progressing
- **🟡 Stalled** — content ingested but no execution
- **🔴 Paused** — intentionally paused (don't flag as problem)

### Step 5: Generate Report

Format: Kurz, strukturiert, Terminal-Style. Keine Prosa. Emoji sections.

Layout:
```
── WEEKLY REVIEW — KW <number> (<date>) ──────────
📂 VAULT (<count> Files geändert letzte 7 Tage)
  • wiki/concepts/ — bullet list of new concepts
  • Clippings — count + key themes
  • Other notable changes
📈 TRADING
  • Watchlist: stats, export date
  • Pipeline crons: ✅/❌
  • Notable signals
🏥 VAULT-HEALTH (N Cron Jobs)
  • f5eb3bfaf65e: last run status
  • All N jobs: ✅/❌ summary
📊 PROJEKT-STATUS
  • 🟢/🟡/🔴 per project with 1-liner
⚠️ PROBLEME
  • Any broken syncs, failed crons, errors
🎯 EMPFEHLUNGEN für KW <next>
  1. Suggestion with effort estimate
  2. ...
  3. ...
```

### Critical Pitfall — Cron Mode

**`execute_code()` is BLOCKED in cron mode** (security restriction). Use direct `terminal()` calls for Python-like logic and `read_file()`/`search_files()` for data extraction. Do NOT attempt `execute_code()`.

### Pitfalls — Weekly Review

- Watchlist.md may be long (150+ lines) — use `head` and pattern matching, not full read
- `find -mtime -7` counts from the start of the day, not from exact 7*24h ago — close enough for weekly review
- Some files may be modified by the vault-insights pipeline at 02:45 — this is expected, not a concern
- Gateway-watchdog runs every 5 min and its `ok` status is expected — brief Telegram timeout errors in trading/errors.log are NOT critical (polling noise)
- [SILENT]: If nothing changed (no new files, no trading updates, no cron failures), respond with exactly `[SILENT]` to suppress delivery
- **No-Agent Cron Status prüfen:** Wenn der weekly-review den `obsidian-vault-bisync-nightly` (f5eb3bfaf65e) prüft: `cronjob action=list` verwenden und `last_status` + `last_run_at` auswerten. `cronjob action=run` liefert bei no_agent-Scripts **keinen Output** bei Erfolg (exit 0, silent) → der weekly-review interpretiert das fälschlich als "Sync läuft nicht".

---

### Pitfalls (General)

- SOUL.md too long/abstract → keep concrete with examples
- MEMORY.md filled with transient data → prohibited, only durable facts
- USER.md forgotten when priorities change → update proactively
- Weekly review too detailed → short report; [SILENT] when nothing to report
- Vault Self-Write too many changes → limit: max 5 wikilinks + 2 new pages + 1 synthesis
- **User sagt "Änderungen nicht auf Server":** Nicht direkt Sync-Problem akzeptieren → `references/bisync-diagnostic.md` konsultieren. Erst dry-run prüfen ob GDrive die Dateien hat; oft ist der Upload vom User-Gerät defekt, nicht der Bisync.

---

## Clippings Ingest — Automatische Wiki-Befüllung aus Rohquellen

Seit 16.07.2026: Alle Rohquellen wurden von der Vault-Root-Ebene in
`Clippings/` verschoben (15 Unterordner + diverse Root-Dateien). Der
`clippings-ingest` Cron-Job verarbeitet sie täglich zu Wiki-Einträgen.

### Design-Prinzip

**ALLES was als Quelle dient, landet in Clippings/.** Die Unterscheidung
ist Raw vs Knowledge, nicht Ordner-basiert. Eine Trading-Notiz, ein Rezept,
ein Web-Clipping, ein YouTube-Transkript — alles wird in `wiki/` extrahiert.
Dateien in `Projekte/` (Arbeitsdokumente) und `Trading/` (Pipeline-Output)
bleiben separat, weil sie aktiv geschrieben werden, nicht konsumiert.

### Vault-Architektur (seit 16.07.2026)

```
obsidian-vault/
├── index.md, log.md               ← Wiki-Navigation
├── wiki/                          ← LLM-generiertes Wissen
│   ├── entities/ (27 Dateien)
│   ├── concepts/ (74 Dateien)
│   └── sources/ (172 Dateien)
├── Clippings/                     ← ALLE Rohquellen (15 Subordner + Dateien)
│   ├── Exil/                      ← Research
│   ├── YouTube/                   ← YouTube-Transkripte
│   ├── Lernen/                    ← Lernmaterial
│   ├── Reisen/, Rezepte/...       ← Persönliche Notizen
│   ├── boerse/, Geldverdienen/... ← Business/Börse
│   └── (Einzel-Clippings)         ← Web-Clippings & Transkripte
├── Projekte/                      ← Arbeitsdokumente (unverändert)
├── Trading/                       ← Pipeline-Output (unverändert)
├── System/                        ← Obsidian-Config
├── raw/                           ← Bereits vorhandene Rohdaten
└── SPEC.md, llm-wiki.md, README.md ← Standards
```

### Cron-Job: clippings-ingest

| Eigenschaft | Wert |
|-------------|------|
| Job-ID | `5b2f87f87a1e` |
| Schedule | `0 16 * * *` (täglich 16:00) |
| Deliver | origin |
| Skills | obsidian |

**Ablauf:**
1. `python3 ~/.hermes/scripts/clippings-scanner.py` — Findet neue/modifizierte
   Dateien in Clippings/ (rekursiv, .md + .txt). Output: JSON mit path, title,
   type, content_preview. Max 50 Dateien pro Lauf. Bei nichts Neuem: Silent (exit 0).
2. **LLM-Analyse** — Für jede Datei: DeepSeek extrahiert Entities (max 5),
   Concepts (max 3), Summary (1-2 Sätze)
3. **Wiki-Schreibzugriffe:**
   - `wiki/sources/<title>.md` — Source-Eintrag mit YAML Frontmatter + Summary
   - `wiki/entities/<Name>.md` — Neue Entity, NUR anlegen, nie überschreiben
   - `wiki/concepts/<Name>.md` — Neues Concept, NUR anlegen, nie überschreiben
4. **log.md** — Chronologischer Eintrag mit Entities + Concepts
5. **wiki/index.md** — Regeneriert aus allen Entities + Concepts
6. **processed-DB** — `.hermes/clippings_processed.json` speichert SHA256-Hash

### Wiederholungs-Skip

Der Scanner speichert pro Datei einen SHA256-Hash. Nur Dateien deren Hash
sich geändert hat werden neu verarbeitet. Erkannte Dateien geben keinen Output
(Silent-on-Success). Neue Dateien werden priorisiert (neueste mtime zuerst).

### Scripts

| Script | Pfad | Typ | Zweck |
|--------|------|-----|-------|
| Scanner | `~/.hermes/scripts/clippings-scanner.py` | no_agent | Findet neue Dateien, gibt JSON |
| Ingest | Cron-Prompt (Agent) | Agent | LLM-Analyse + Wiki-Schreibzugriffe |

### Manueller Test

```bash
# Zeigt was verarbeitet würde
python3 ~/.hermes/scripts/clippings-scanner.py

# Cron-Job manuell triggern
cronjob action=run job_id=5b2f87f87a1e

# Status prüfen
cat /root/obsidian-vault/.hermes/clippings_processed.json | python3 -m json.tool | head -20
```

### Bekannte Grenzen

- **Max 50 Dateien/Lauf** — Kostenkontrolle (OpenRouter DeepSeek). Neue Dateien
  werden priorisiert. Bei ~400+ unverarbeiteten: ~8 Tage bis vollständig.
- **Nur .md + .txt** — PDFs, Bilder, Audio werden ignoriert
- **Kein Cross-Doc-Dedup** — Zwei Clippings zum selben Thema erzeugen zwei
  Source-Einträge. Der vault-insights-daily kann später mergen.
- **File-Typ-Herleitung** — Typ wird aus dem Ordnernamen abgeleitet
  (Exil→article, YouTube→transcript, boerse→market_note, etc.)

---

## 2. Daily Vault Pipeline

After setup, a daily pipeline runs at 02:45 UTC (after GDrive bisync at 02:00) to maintain the vault: sort new content, extract insights, make proactive suggestions.

The pipeline has three parallel tasks. See `references/vault-insights-prompt.md` for the full cron prompt.

### A — Wiki Maintenance (Einsortieren)

Scan newly synced files in these directories (use `-maxdepth 5` so Unterordner wie `Projekte/MarineIT/` nicht übersehen werden):
- `boerse/`, `Trading/`, `Geldverdienen/` (trading subset), `hermes/` (trading subset)
- `Projekte/` (non-trading projects like Zeeslogger, MarineIT, etc.)
- Incorporate new insights into existing wiki pages (`concepts/`, `entities/`, `sources/`)
- Create new wiki pages for new concepts — for non-trading project files (e.g. Zeeslogger), create in `wiki/concepts/` with appropriate tags and source links
- Maintain wikilinks

#### Trading Data Quality

When the Watchlist shows a spike in unresolved "?" tickers in its data-quality section, use `references/ticker-resolution-protocol.md` to bulk-resolve them: extract from `trading.db`, categorize (typo / private / hallucination / real), resolve via hard-coded map + yfinance Search, update the database, and register new aliases in `watchlist_manager.py NORMALIZE_ALIASES` to prevent recurrence.

#### Derived Page Auto-Refresh

When creating a wiki page derived from a source file (e.g., `wiki/concepts/Exit Management.md` from `Trading/Erklaerung.md`):

**Achtung:** Die Exit-Management-Quelldatei ist `Trading/Erklaerung.md`, **nicht** `Projekte/Hermes_Trading_Skill_Erklaerung.md` (existiert nicht). Der vault-insights-daily Cron-Prompt wurde am 10.06.2026 auf den korrekten Pfad gefixt.

1. **Always update the nightly cron prompt** to include a timestamp comparison check on subsequent runs:
   - Compare `mtime` of source file vs wiki page
   - If source is newer, reload and update the wiki page
2. **Update `trading-index.md`** to add a wikilink to the new page
3. **Track the check in the nightly report** output

### B — Out-of-the-Box Thinking (Weiterdenken)

Scan ALL new files across: `Geldverdienen/`, `boerse/`, `hermes/`, `Trading/`, `Clippings/`, `raw/`
- Core idea of each article (1 sentence)
- Author's intention ("author wants you to: do X, because Y")
- **Mandatory opportunity scan** across:
  - Side hustles (SaaS, Affiliate, Digital Products, AI services)
  - Tax optimization (offshore structures, allowances, holding companies)
  - Location independence (low COL countries, visa programs, real estate)
  - Skill development (what pays next? Celonis, BW, AI agent consulting)
  - Business building (passive income structures, automation at scale)
- Map to Martin's existing infrastructure: does he have a profile/skill/cron already?
- Estimate effort in minutes/hours
- End with "Soll ich das jetzt umsetzen?"

### C — Proactive Suggestions (max 3)

Each suggestion must include:
- Concrete next step
- Effort estimate
- "Soll ich das jetzt umsetzen?"

### Pipeline Timing

| Cron | Schedule | Purpose |
|------|----------|---------|
| `obsidian-vault-bisync-nightly` (f5eb3bfaf65e) | 02:00 daily | GDrive bisync (local ↔ cloud) |
| `vault-insights-daily` (53f222b00811) | 02:45 daily | Wiki maintenance + out-of-box thinking |
| `vault-self-write-health` (326343c87149) | Sat 03:00 | Health check, backward integration, gap detection, synthesis |
| `weekly-review` (beb26022a5d9) | Sun 19:00 | Weekly review: trading, sync, projects, recommendations |

### User Preference (important)

When an article brings new insights AND needs new wiki entries — do BOTH. Not one or the other.

### Wiki Structure (seit Vault-Restrukturierung 16.07.2026)

```
/root/obsidian-vault/
├── wiki/
│   ├── concepts/         # Abstract concepts (aktuell 74)
│   ├── entities/         # Concrete entities (aktuell 27)
│   ├── sources/          # Processed sources (aktuell 172)
│   └── trading-index.md  # MOC
├── Clippings/            # ALLE Rohquellen (15 Subordner + Einzeldateien)
│   ├── Exil/             # Research
│   ├── YouTube/          # Transkripte
│   ├── boerse/           # Börse
│   ├── Geldverdienen/    # Business-Ideen
│   ├── Lernen/           # Lernmaterial
│   ├── Reisen/, Rezepte/, Sport/, ...  # Persönlich
│   └── *.md              # Einzel-Clippings
├── Projekte/             # Arbeitsdokumente
├── Trading/              # Pipeline-Output
├── System/               # Obsidian-Config
├── 00-CAPTURE/           # Quick notes
├── raw/                  # Legacy-Rohdaten
├── index.md, log.md      # Wiki-Navigation
└── SPEC.md, llm-wiki.md  # Standards
```

### D — Trading Pipeline Diagnostics

The vault-insights pipeline overlaps with the trading cron pipeline (02:00–05:00). When the nightly report shows `0` for Signal-Pipeline or other anomalies, consult `references/trading-pipeline-diagnostics.md`:
- Date semantics (publication date vs processing date — most common reason for "0")
- Reading cron.log for script failures (DB lock, crashes)
- Pipeline recovery steps

---

## Cross-Session Context Recovery

When the user references proposals or suggestions from prior sessions (e.g., "mach Vorschlag 2 und 3"), the nightly cron resets mean you have zero direct context. Use this protocol:

1. **Search session history first** — `session_search(query="Vorschlag [keyword]")` to find the original session
2. **Read session summaries** — The summaries contain the proposals and their status (implemented/pending)
3. **If ambiguous, probe deeper** — `session_search` on specific phrases from the summary ("Exit Management", "Auto-Refresh")
4. **Verify current state** — Check if the proposal was already implemented by inspecting files/db/cron
5. **Execute** — Implement pending proposals against current state, not the state at proposal time

### Common Cross-Session Patterns

| Pattern | How to handle |
|---------|--------------|
| "Vorschlag X kam durch" (was implemented) | Verify implementation is still intact, move on |
| "Vorschlag Y und Z bitte umsetzen" | Locate original proposals in prior session summaries, implement now |
| "Das hatte ich doch schonmal vorgeschlagen" | Search by topic, check if any implementation exists, report findings |

### Pitfalls

- Don't trust session numbers alone (Vorschlag 1/2/3) — read the summaries to confirm what each was
- Cron-session proposals often end with "Soll ich das jetzt umsetzen?" — if unanswered, treat as pending
- State may have changed since proposal time — re-evaluate before implementing

---

## Daily Cron Health Monitoring

Since 2026-05-26, a daily health check runs at **08:00** via Hermes Cron (`cron-health-daily`, b0b06693e8f9, Telegram delivery).

### Script

`/root/.hermes/scripts/cron_health.py` — parses the trading system's `cron.log` for today's jobs:

1. **Phase 1 — Tages-Crons:** Scannt das cron.log nach `=== <Datum> === <job> START ===`-Markern von heute. Liest den Block bis zum nächsten START, prüft auf ✅/❌/Traceback.
2. **Phase 2 — Pipeline-interne Jobs:** Innerhalb des `trading_pipeline`-Blocks werden Sub-Jobs (YouTube Scan, KI Analyse, etc.) via ihre `=== HH:MM:SS job START/DONE/ERROR ===`-Marker erfasst.
3. **Output:** Telegram-Report mit "Heute: X Jobs | ✅ Y | ❌ Z"

### How it parses

The script matches these log patterns:

```
=== Tue May 26 02:00:01 CEST 2026 === fundamental_data START ===  (outer cron)
=== 04:00:02 YouTube Scan START ===                                (pipeline internal)
=== 04:19:57 Technical Analysis ERROR (exit 1) ===                  (pipeline crash)
```

It does NOT count Hermes cron jobs (they have their own status tracking).

### Adding to this

If trading system scripts are added/removed from the crontab, `cron_health.py` should autodetect them because it scans for all START markers — no hardcoded list needed.

---

## Operation-Specific Pitfalls

- **Sync check before pipeline**: The bisync runs via cron (global scheduler), not via `sync.sh`. Don't falsely report sync broken because `sync.sh` has a different path.
- **X Bookmarks (paused)**: SuperGrok is integrated as a news-agent provider, but X Bookmarks access is still unresolved. Skip until further notice.
- **Obsidian Diary gets overwritten on vault refresh** — `04-Tagebuch.md` is on GDrive. After vault refresh, recreate diary entries manually.
- **`-maxdepth 3` ist zu flach für den Vault-Scan** — Dateien in `Projekte/MarineIT/` liegen auf Tiefe 4. Der vault-insights-daily Cron verwendet `-maxdepth 5` (gefixt 10.06.2026) um Project-Unterordner zu erfassen. Bei neuen Ordnerstrukturen immer zuerst `find /root/obsidian-vault/ -maxdepth 6 -type d` laufen lassen um die Tiefe zu prüfen.