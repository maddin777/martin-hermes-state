# Vault Self-Write Health — 2026-07-18

## Changes Made

### Fixes
- **SOUL.md.md double extension** → Fixed in `wiki/concepts/SOUL.md` (line 1)
- **entitys/ typo folder** → 7 files migrated to `entities/` (Claude Cowork, Claude, Hermes, Karpathy, NotebookLM, Vidrush, n8n). Unique files copied, duplicates merged (entities/ is canonical). `entitys/` deleted.

### Backward Integration (4 wikilinks)
| Page | New Link |
|------|----------|
| Agent Loop.md | [[Jamon Agentic Setup]] + [[sources/Jamon Agentic Setup]] |
| Trading Pipeline Architecture.md | [[sources/2 Hermes Workflows (0xJeff)]] |
| KDP.md | 2 sources (Mike Hager, Digital Product Strategy) |
| Faceless YouTube.md | 3 sources (Vidrush, Viral Format, Data Storytelling) |

### Gap Detection (1 new page)
- **entities/OpenClaw.md** — 18+ YouTube transcripts + 1 Geldverdienen source

### Synthesis
- None needed. All clusters already covered by existing concept pages.

## Persistent Broken Links (manual fix required)
1. `ECC Everything Claude Code.md` → `[[../skills/hermes-agent-skill-authoring]]` — skills/ not in vault
2. `Graphiti & Zep Memory.md` → `[[../Trading Data Sources]]` — path issue (relative from concepts/)
3. `Historische Romantasy-Projekte.md` → `[[../concepts/Sterne der Inquisition]]` — path issue
4. `Polymarket.md` → `[[../../hermes/Hermes as the Ultimate Analyst]]` — file missing
5. `trading-index.md` → 3 missing Knowledge-Gaps: [[Aktien (KI Zulieferer)]], [[Information Theory (Polymarket)]], [[boerse Clippings]] ([[OpenClaw]] now resolved)

## Orphans Stats
| Category | Count | Assessment |
|----------|-------|------------|
| Rezepte | 36 | Expected — not wiki-relevant |
| Geldverdienen | 28 | Legacy — pre-Wiki era |
| Clippings/ root | 36 | Legacy — pre-Wiki era |
| boerse/ | 11 | Legacy |
| hermes/ | 66 | Legacy — many files never linked |
| raw/ | 16 | Legacy |