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

### Pitfalls

- SOUL.md too long/abstract → keep concrete with examples
- MEMORY.md filled with transient data → prohibited, only durable facts
- USER.md forgotten when priorities change → update proactively
- Weekly review too detailed → short report; [SILENT] when nothing to report
- Vault Self-Write too many changes → limit: max 5 wikilinks + 2 new pages + 1 synthesis

---

## 2. Daily Vault Pipeline

After setup, a daily pipeline runs at 02:45 UTC (after GDrive bisync at 02:00) to maintain the vault: sort new content, extract insights, make proactive suggestions.

The pipeline has three parallel tasks. See `references/vault-insights-prompt.md` for the full cron prompt.

### A — Wiki Maintenance (Einsortieren)

Scan newly synced files in trading-relevant directories: `boerse/`, `Trading/`, `Geldverdienen/` (trading subset), `hermes/` (trading subset).
- Incorporate new insights into existing wiki pages (`concepts/`, `entities/`, `sources/`)
- Create new wiki pages for new concepts
- Maintain wikilinks

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

### Wiki Structure

```
/root/obsidian-vault/
├── wiki/
│   ├── concepts/         # Abstract concepts (Market Regime, Kelly, Out-of-the-Box Opportunity Scan)
│   ├── entities/         # Concrete entities (Polymarket, SuperGrok, Quant Roadmap)
│   ├── sources/          # Sources with references to originals
│   └── trading-index.md  # MOC
├── 00-CAPTURE/           # Quick notes, no folder thinking (Anti-Breakdown)
├── boerse/               # Raw data
├── Trading/              # Watchlist
├── Geldverdienen/        # Trading portion: Polymarket, Quant, BTC, OpenClaw
├── hermes/               # Trading portion: Polymarket, KIMI Prompts, Analyst
├── Clippings/            # Web clippings
└── raw/                  # Raw data
```

### Pitfalls

- **Sync check before pipeline**: The bisync runs via cron (global scheduler), not via `sync.sh`. Don't falsely report sync broken because `sync.sh` has a different path.
- **X Bookmarks (paused)**: SuperGrok is integrated as a news-agent provider, but X Bookmarks access is still unresolved. Skip until further notice.
- **Obsidian Diary gets overwritten on vault refresh** — `04-Tagebuch.md` is on GDrive. After vault refresh, recreate diary entries manually.