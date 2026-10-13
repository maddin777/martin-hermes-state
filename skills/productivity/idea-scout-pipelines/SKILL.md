---
name: idea-scout-pipelines
description: "Weekly dataviz + Micro-SaaS idea-scout cron pipelines."
trigger:
  - "Data story / dataviz ideas"
  - "Micro-SaaS / side-hustle idea scan"
  - "Wöchentlicher Ideen-Scan / Digest"
  - "Source-rotation scan cron"
---

# Idea-Scout Cron Pipelines

Umbrella for Martin's recurring, German-language **source-scan → scored, deduped idea
list → weekly digest** cron pipelines. Two members share one method:

- **DataViz Story Scout** — weekly data-story ideas for faceless social content
- **Micro-SaaS Opportunity Scan** — weekday pain scans + Sunday implementability digest

A third sibling class (`daily-news-briefing`) delivers a *formatted news digest* rather
than an *idea list*; it stays a separate skill.

## When to Use

- "Gib mir Data-Story-Ideen" / wöchentlicher Dataviz-Digest / `dataviz-ideen-weekly`
- "Welche Micro-SaaS-Idee lohnt sich" / Pain-Scan / Side-Hustle-Ideen / `microsaas-scan`
- Debugging a frozen cluster-store, a digest that reports "keine Veränderung", or a dead
  data source behind an idea scan

## Shared Pipeline Method (always-on rules)

- **The goal file IS the live prompt, not this skill.** Cron jobs run
  `hermes goal --file ~/hermes/goals/<name>.txt`; change sources, scoring parameters or
  output rules in the goal file. The skill documents the *method* behind them.
- **One dedup store per pipeline**, under `~/hermes/reports/`. Similarity >~70% → merge
  into the existing entry (counter/votes +1, append quotes) **and refresh `last_seen` to
  today**; otherwise create a new entry. **Always update `last_seen` on a re-find** — else
  the digest falsely reports "kein MOVER / Cluster abklingend".
- **Store-freeze PITFALL:** if scans run but the store never changes (digest says "keine
  Veränderung"), the cause is almost always that the **goal files lost their STORE-UPDATE
  step** — fix the goal files, do not suspect the digest.
- **Web fallback when Firecrawl credits are exhausted** (reset ~monthly, mid-month has
  long dead windows): Exa Search `mcporter call 'exa.web_search_exa(...)'`; Jina Reader
  `curl -s "https://r.jina.ai/URL"`; Google News RSS via curl; Wikipedia API
  (`action=parse` → HTML, `action=query&prop=extracts&explaintext` → plain text); `web_search`
  runs on DDGS backend already (no Firecrawl needed for simple searches).
- **Never invent data.** Every idea needs a real, freely-accessible source. Better 7 solid
  ideas than 10 with dead sources.
- **Delivery:** scans write reports + store; the weekly digest is the single delivery point
  (`deliver=telegram`). Keep per-scout delivery settings in the goal files / cron config.

## DataViz Story Scout (weekly)

Job `dataviz-ideen-weekly` (`f9f061808aaf`), Sa 12:00, goal `~/hermes/goals/dataviz_ideen.txt`,
reports `~/hermes/reports/dataviz_ideen_YYYY-WW.md` (8-week dedup window).

- **Every idea must hit one of 4 hooks (hard gate):** Identität "Bin ich normal?" ·
  Vergleich "Wo stehe ich?" · Neugier "Echt jetzt?" · Überraschung "Wtf?".
- **HARD constraint: static charts only** — 1 insight, 1 caption, no video, no voiceover.
  Animation ideas (bar-chart-race, animierte Karte, Scrollytelling) only as a "Video (später)"
  note, never the main proposal.
- **Story formula:** "Seit [Zeitraum] ist [Alltagsgut] um [überraschende Zahl] gestiegen/gefallen."
- **Source priority:** Destatis GENESIS, Eurostat, Bundeshaushalt, DIW/SOEP, BNetzA/SMARD,
  Tankerkönig-API, FRED, Bundesagentur für Arbeit, Numbeo, News-RSS.
- Pre-verified topics + concrete dataset/table numbers: `references/dataviz-evergreen-topics.md`.

## Micro-SaaS Opportunity Scan (weekdays + Sunday digest)

Slots A/B/C wälzen unterschiedliche Quellen ab (A Reddit+HN, B G2/Capterra/Trustpilot,
C IndieHackers+App-Stores) und schreiben in EINEN 30-Tage-Cluster-Store; der Wochen-Digest
am Sonntag liefert ausschliesslich implementierbare Ideen.

- **Scoring 1-5: SCHMERZ × MACHBARKEIT.** Alles <3 auf einer Achse → verworfen.
- **Wettbewerbsgate (GATE, hart):** eingegrabener Incumbent (>2 J. ODER Nutzerbasis ODER
  Daten-Moat) besetzt den Kern-Use-Case → **MACHBARKEIT max. 2** (= verworfen), AUSSER ein
  klar benannter **Keil** existiert. Reife Gratis-/DIY-Lösung → **SCHMERZ -1**. Niedrige
  Eintrittsbarriere ohne Moat bei besetztem Markt zählt GEGEN die Idee, nicht dafür.
- **Pain-Validität:** wiederkehrend, kostet Zeit/Geld/Nerven, schlechte Workarounds,
  erreichbare Nische, Zahlungsbereitschafts-Signal.
- **Action-Schwelle (Digest):** Schmerz≥4 UND Machbarkeit≥4 UND ≥8 Stimmen über ≥14 Tage
  → "READY TO VALIDATE". Real: 0-2 echte Kandidaten pro Woche, nicht 20.
- **Fan-out:** alle Scan-Jobs `deliver=local` (nur Report + Store), der Digest ist der
  EINZIGE Lieferpunkt. Implementierbarkeits-Filter im Digest: Schmerz≥3 ∧ Machbarkeit≥4 ∧
  Gate bestanden (benannter Keil, kein fehlender WETTBEWERB-Block) ∧ solo <3 Monate ∧ freie
  Datenquelle ∧ plausible Zahlungsbereitschaft — sonst ehrlich "diese Woche nichts".
- Siehe auch `references/micro-saas-content-clusters.md` für den umgekehrten Weg
  (bestehenden Vault-Inhalt als Digital-Product-Inventar lesen statt Pain-Scan) — inkl.
  Monetarisierungs-Pushback (Gumroad/Payhip statt KDP).

## Verification

```bash
hermes cron list | grep -E "dataviz|microsaas|scan"
ls -lt ~/hermes/reports/ | head            # letzte Reports
cat ~/hermes/goals/dataviz_ideen.txt       # Goal-File = Prompt
```
