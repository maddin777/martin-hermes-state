---
name: subagent-driven-development
description: "Execute plans via delegate_task subagents (2-stage review)."
version: 1.1.0
author: Hermes Agent (adapted from obra/superpowers)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [delegation, subagent, implementation, workflow, parallel]
    related_skills: [writing-plans, requesting-code-review, test-driven-development]
---

# Subagent-Driven Development

## Overview

Execute implementation plans by dispatching fresh subagents per task with systematic two-stage review.

**Core principle:** Fresh subagent per task + two-stage review (spec then quality) = high quality, fast iteration.

## When to Use

Use this skill when:
- You have an implementation plan (from writing-plans skill or user requirements)
- Tasks are mostly independent
- Quality and spec compliance are important
- You want automated review between tasks

**vs. manual execution:**
- Fresh context per task (no confusion from accumulated state)
- Automated review process catches issues early
- Consistent quality checks across all tasks
- Subagents can ask questions before starting work

## The Process

### 1. Read and Parse Plan

Read the plan file. Extract ALL tasks with their full text and context upfront. Create a todo list:

```python
# Read the plan
read_file("docs/plans/feature-plan.md")

# Create todo list with all tasks
todo([
    {"id": "task-1", "content": "Create User model with email field", "status": "pending"},
    {"id": "task-2", "content": "Add password hashing utility", "status": "pending"},
    {"id": "task-3", "content": "Create login endpoint", "status": "pending"},
])
```

**Key:** Read the plan ONCE. Extract everything. Don't make subagents read the plan file — provide the full task text directly in context.

### 2. Per-Task Workflow

For EACH task in the plan:

#### Step 1: Dispatch Implementer Subagent

Use `delegate_task` with complete context:

```python
delegate_task(
    goal="Implement Task 1: Create User model with email and password_hash fields",
    context="""
    TASK FROM PLAN:
    - Create: src/models/user.py
    - Add User class with email (str) and password_hash (str) fields
    - Use bcrypt for password hashing
    - Include __repr__ for debugging

    FOLLOW TDD:
    1. Write failing test in tests/models/test_user.py
    2. Run: pytest tests/models/test_user.py -v (verify FAIL)
    3. Write minimal implementation
    4. Run: pytest tests/models/test_user.py -v (verify PASS)
    5. Run: pytest tests/ -q (verify no regressions)
    6. Commit: git add -A && git commit -m "feat: add User model with password hashing"

    PROJECT CONTEXT:
    - Python 3.11, Flask app in src/app.py
    - Existing models in src/models/
    - Tests use pytest, run from project root
    - bcrypt already in requirements.txt
    """,
    toolsets=['terminal', 'file']
)
```

#### Step 2: Dispatch Spec Compliance Reviewer

After the implementer completes, verify against the original spec:

```python
delegate_task(
    goal="Review if implementation matches the spec from the plan",
    context="""
    ORIGINAL TASK SPEC:
    - Create src/models/user.py with User class
    - Fields: email (str), password_hash (str)
    - Use bcrypt for password hashing
    - Include __repr__

    CHECK:
    - [ ] All requirements from spec implemented?
    - [ ] File paths match spec?
    - [ ] Function signatures match spec?
    - [ ] Behavior matches expected?
    - [ ] Nothing extra added (no scope creep)?

    OUTPUT: PASS or list of specific spec gaps to fix.
    """,
    toolsets=['file']
)
```

**If spec issues found:** Fix gaps, then re-run spec review. Continue only when spec-compliant.

#### Step 3: Dispatch Code Quality Reviewer

After spec compliance passes:

```python
delegate_task(
    goal="Review code quality for Task 1 implementation",
    context="""
    FILES TO REVIEW:
    - src/models/user.py
    - tests/models/test_user.py

    CHECK:
    - [ ] Follows project conventions and style?
    - [ ] Proper error handling?
    - [ ] Clear variable/function names?
    - [ ] Adequate test coverage?
    - [ ] No obvious bugs or missed edge cases?
    - [ ] No security issues?

    OUTPUT FORMAT:
    - Critical Issues: [must fix before proceeding]
    - Important Issues: [should fix]
    - Minor Issues: [optional]
    - Verdict: APPROVED or REQUEST_CHANGES
    """,
    toolsets=['file']
)
```

**If quality issues found:** Fix issues, re-review. Continue only when approved.

#### Step 4: Mark Complete

```python
todo([{"id": "task-1", "content": "Create User model with email field", "status": "completed"}], merge=True)
```

### 3. Final Review

After ALL tasks are complete, dispatch a final integration reviewer:

```python
delegate_task(
    goal="Review the entire implementation for consistency and integration issues",
    context="""
    All tasks from the plan are complete. Review the full implementation:
    - Do all components work together?
    - Any inconsistencies between tasks?
    - All tests passing?
    - Ready for merge?
    """,
    toolsets=['terminal', 'file']
)
```

### 4. Verify and Commit

```bash
# Run full test suite
pytest tests/ -q

# Review all changes
git diff --stat

# Final commit if needed
git add -A && git commit -m "feat: complete [feature name] implementation"
```

## Task Granularity

**Each task = 2-5 minutes of focused work.**

**Too big:**
- "Implement user authentication system"

**Right size:**
- "Create User model with email and password fields"
- "Add password hashing function"
- "Create login endpoint"
- "Add JWT token generation"
- "Create registration endpoint"

## Red Flags — Never Do These

- Start implementation without a plan
- Skip reviews (spec compliance OR code quality)
- Proceed with unfixed critical/important issues
- Dispatch multiple implementation subagents for tasks that touch the same files
- Make subagent read the plan file (provide full text in context instead)
- Skip scene-setting context (subagent needs to understand where the task fits)
- Ignore subagent questions (answer before letting them proceed)
- Accept "close enough" on spec compliance
- Skip review loops (reviewer found issues → implementer fixes → review again)
- Let implementer self-review replace actual review (both are needed)
- **Start code quality review before spec compliance is PASS** (wrong order)
- Move to next task while either review has open issues

## Handling Issues

### If Subagent Asks Questions

- Answer clearly and completely
- Provide additional context if needed
- Don't rush them into implementation

### If Reviewer Finds Issues

- Implementer subagent (or a new one) fixes them
- Reviewer reviews again
- Repeat until approved
- Don't skip the re-review

### If Subagent Fails a Task

- Dispatch a new fix subagent with specific instructions about what went wrong
- Don't try to fix manually in the controller session (context pollution)

## Efficiency Notes

**Why fresh subagent per task:**
- Prevents context pollution from accumulated state
- Each subagent gets clean, focused context
- No confusion from prior tasks' code or reasoning

**Why two-stage review:**
- Spec review catches under/over-building early
- Quality review ensures the implementation is well-built
- Catches issues before they compound across tasks

**Cost trade-off:**
- More subagent invocations (implementer + 2 reviewers per task)
- But catches issues early (cheaper than debugging compounded problems later)

## Integration with Other Skills

### With writing-plans

This skill EXECUTES plans created by the writing-plans skill:
1. User requirements → writing-plans → implementation plan
2. Implementation plan → subagent-driven-development → working code

### With test-driven-development

Implementer subagents should follow TDD:
1. Write failing test first
2. Implement minimal code
3. Verify test passes
4. Commit

Include TDD instructions in every implementer context.

### With requesting-code-review

The two-stage review process IS the code review. For final integration review, use the requesting-code-review skill's review dimensions.

### With systematic-debugging

If a subagent encounters bugs during implementation:
1. Follow systematic-debugging process
2. Find root cause before fixing
3. Write regression test
4. Resume implementation

## Example Workflow

```
[Read plan: docs/plans/auth-feature.md]
[Create todo list with 5 tasks]

--- Task 1: Create User model ---
[Dispatch implementer subagent]
  Implementer: "Should email be unique?"
  You: "Yes, email must be unique"
  Implementer: Implemented, 3/3 tests passing, committed.

[Dispatch spec reviewer]
  Spec reviewer: ✅ PASS — all requirements met

[Dispatch quality reviewer]
  Quality reviewer: ✅ APPROVED — clean code, good tests

[Mark Task 1 complete]

--- Task 2: Password hashing ---
[Dispatch implementer subagent]
  Implementer: No questions, implemented, 5/5 tests passing.

[Dispatch spec reviewer]
  Spec reviewer: ❌ Missing: password strength validation (spec says "min 8 chars")

[Implementer fixes]
  Implementer: Added validation, 7/7 tests passing.

[Dispatch spec reviewer again]
  Spec reviewer: ✅ PASS

[Dispatch quality reviewer]
  Quality reviewer: Important: Magic number 8, extract to constant
  Implementer: Extracted MIN_PASSWORD_LENGTH constant
  Quality reviewer: ✅ APPROVED

[Mark Task 2 complete]

... (continue for all tasks)

[After all tasks: dispatch final integration reviewer]
[Run full test suite: all passing]
[Done!]
```

## Remember

```
Fresh subagent per task
Two-stage review every time
Spec compliance FIRST
Code quality SECOND
Never skip reviews
Catch issues early
```

**Quality is not an accident. It's the result of systematic process.**

## General Delegation Pitfalls (Beyond Code)

These pitfalls apply to ANY delegated task, not just software development.

### Content Quality: Subagent Delivered Empty Sections

**Symptom:** A subagent was asked to generate a daily news briefing. It delivered only section headers with no content — the text was empty between headings.

**Root cause:** The subagent was told to research AND write. Its `web_search` tool had no credits (Firecrawl exhausted). It couldn't fetch any data, so it produced a skeleton with no substance. Because the subagent's output was a self-report (not verified against the actual channel), the controller didn't detect the empty output until the user complained.

**Prevention: Pre-collect data, then delegate formatting.**
- Before delegating a content generation task, gather the raw data yourself via fallback methods (curl for RSS feeds, browser for websites, Open-Meteo for weather)
- Package the structured data into the subagent's `context` parameter
- The subagent's only job: format the data into the required output and deliver it
- This eliminates tool-failure risk from the subagent

**Prevention: Set toolsets to what the subagent actually needs.**
- If the subagent only needs to format and deliver: use `toolsets=['terminal', 'file']` only
- Don't include `'web'` if you already collected the data — this wastes tokens and introduces failure risk from unavailable external services
- When a subagent DOES need external data but Firecrawl is unavailable: include `'browser'` in toolsets as a fallback, and instruct it to use curl for RSS feeds if web_search fails

**Prevention: Verify subagent output externally.**
- A subagent's self-report ("✅ Nachricht gesendet") is NOT sufficient proof of quality
- After a content-delivery subagent completes: check the actual delivery target (Telegram channel, API response, file contents)
- For Telegram: verify message IDs were returned and content length is reasonable
- For files: `read_file` the output before declaring success

**Diagnosis chain for empty/partial subagent output:**
1. Did the subagent's `web_search` or `web_extract` calls succeed? → Check Firecrawl credit status
2. If Firecrawl is empty → Use curl for RSS feeds (Google News RSS works), Open-Meteo for weather
3. Re-delegate with pre-collected data in `context`, exclude `'web'` from toolsets
4. Verify the output landed as expected (check the target channel/message IDs, read the file)

**Reliable data sources when Firecrawl is empty:**

| Need | Fallback Method |
|------|----------------|
| German news headlines | `curl -s "https://news.google.com/rss?hl=de&gl=DE&ceid=DE:de"` — parse with Python xml.etree.ElementTree |
| Finance news | `curl -s "https://news.google.com/rss/search?q=DAX+%C3%96l+Gold+Bitcoin&hl=de"` |
| Regional/Local news | Same pattern with different search terms |
| Weather forecast | `curl -s "https://api.open-meteo.com/v1/forecast?latitude=XX&longitude=YY&daily=..."` — free, no key |
| Water temperatures | Browser on wassertemperatur.org (browser_navigate + browser_snapshot) |
| General web content | Browser fallback (browser_navigate) — but many portals block without residential proxy |

**Concrete example (Daily News Briefing, Firecrawl credits = 0):**

```python
# WRONG: Subagent researches + writes (fails when tools are down)
delegate_task(
    goal="Create daily news briefing",
    context="Recherchiere aktuelle Nachrichten und erstelle ein Briefing",
    toolsets=['web', 'terminal', 'file']  # web_search fails → empty content
)

# RIGHT: You collect data, subagent only formats
# Step 1: Collect data via curl/browser
curl -s "https://news.google.com/rss?hl=de&gl=DE"  # → structured output
curl -s "https://api.open-meteo.com/v1/forecast?..."  # → weather data

# Step 2: Subagent formats + delivers
delegate_task(
    goal="Format collected data into briefing and send to Telegram",
    context=f"""
    RAW DATA - Politik & Internationales:
    1. [Headline] - [Source] - [Description]
    2. ...
    
    RAW DATA - Wetter:
    Ratzeburg: 22°C / 8°C
    
    Send via Telegram API using source .env and curl.
    """,
    toolsets=['terminal', 'file']  # no web tools needed — data already collected
)
```

### Factual Accuracy: Don't Invent Model Details

**Symptom:** When asked about a car model's special editions, I claimed the Renault Twingo 1 had "Running" and "Extreme" models with higher ground clearance. These do not exist.

**Root cause:** I combined fragmented memory of different Sondermodelle (Twingo "Air", "Pack", "L'Espace") with the general concept of a "higher trim" and fabricated a name and specification. I didn't verify before stating as fact.

**Prevention:**
- For product/model/specification questions: ONLY state facts you are confident about
- If memory is fuzzy: say "Ich glaube aber lass mich kurz checken" and verify via web search or external source
- After a correction from the user: acknowledge the error explicitly, don't deflect
- Niche automotive knowledge (special editions, production years, specific engine codes) is HIGH-RISK for hallucination — always verify

### Tool Availability Assumptions

- **Never assume `web_search` or `web_extract` will work** — Firecrawl credits can be empty at any time (refresh cycle, billing issues)
- **Always include fallback instructions** when a subagent needs external data: "If web_search fails, use curl for RSS feeds or browser_navigate"
- **Prefer `terminal` + `curl` over `web_search`** for reliable data retrieval — RSS feeds, Open-Meteo APIs, and similar endpoints work without Firecrawl credits
- **Verify subagent output yourself** — a subagent that says "✅ Nachricht gesendet" may have sent empty content. Check the actual delivery target

## Further reading (load when relevant)

When the orchestration involves significant context usage, long review loops, or complex validation checkpoints, load these references for the specific discipline:

- **`references/context-budget-discipline.md`** — Four-tier context degradation model (PEAK / GOOD / DEGRADING / POOR), read-depth rules that scale with context window size, and early warning signs of silent degradation. Load when a run will clearly consume significant context (multi-phase plans, many subagents, large artifacts).
- **`references/gates-taxonomy.md`** — The four canonical gate types (Pre-flight, Revision, Escalation, Abort) with behavior, recovery, and examples. Load when designing or reviewing any workflow that has validation checkpoints — use the vocabulary explicitly so each gate has defined entry, failure behavior, and resumption rules.

Both references adapted from gsd-build/get-shit-done (MIT © 2025 Lex Christopherson).
