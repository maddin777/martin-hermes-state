---
name: hermes-profile-management
description: End-to-end management of isolated Hermes profiles — creation, .env setup, gateway systemd installation, cron scheduling, and gateway troubleshooting. Reusable for any profile (news, lang, trading, etc.).
category: devops
---

# Hermes Profile Management

Umbrella for creating, configuring, and troubleshooting isolated Hermes agent profiles with their own Telegram gateways, cron jobs, and environment.

---

## 1. Profile Creation & Setup

### Critical Execution Order

```bash
# 1. Create profile
hermes profile create <name>

# 2. Copy .env FIRST (empty by default, gateway needs it!)
cp /root/.hermes/.env /root/.hermes/profiles/<name>/.env
# Edit: TELEGRAM_BOT_TOKEN=<SEPARATE_BOT>  # MUST differ from main!
# Edit: TELEGRAM_HOME_CHANNEL=<id>  # Must include -100 prefix for channels
# Ensure OPENROUTER_API_KEY is set

# 3. Set model (interactive-only command needs workaround)
<name> model set <model> --provider openrouter

# 4. Write SOUL.md (no restart needed)

# 5. Kill conflicting gateways first
pkill -f gateway

# 6. Install + start gateway service
sudo <name> gateway install --system --run-as-user root
sudo systemctl restart hermes-gateway-<name>

# 7. Create cron (schedule positional first!)
<name> cron create "0 6 * * *" "<prompt>" --name <job> --deliver telegram

# 8. Test
<name> cron run <job_id>
```

### Telegram Channel / Bot Configuration

- **Bot token conflict:** Two gateways CANNOT share one bot token. Error: "Telegram bot token already in use (PID XXXX)". Fix: kill old gateway or use separate bot per profile.
- **TG Channel ID needs -100 prefix:** Channel IDs like `1003687061880` must be `-1003687061880`. Get via @userinfobot in channel. Private DM IDs are just numeric (e.g. 216051232).
- **Bot must be Admin in channel** with "Nachrichten posten" permission. Kicked bot = Forbidden errors on send.

### Profile Bot Naming Convention

Martin's profiles follow a strict naming pattern:

| Profile | Channel | Bot |
|---------|---------|-----|
| hermes_lang | Ch_hermster_lang | @hermster_lang (actual handle may end with _bot suffix) |
| hermes_trading | Ch_hermster_trade | @hermster_trader_bot |
| hermes_news | — | @hermster_news |

**Each profile has its own Telegram bot.** The main bot `@myhermster_bot` is ONLY for Martin's DM with Hermes — NOT for any channel/profiles.

**Implications:**
- The profile's `.env` must contain the profile-specific bot token, NOT the main bot token.
- When checking if a profile's messages arrive in its channel: test with the profile's bot, not the main bot.
- Do NOT assume `TELEGRAM_BOT_TOKEN` from the global `.env` is the right one — it's the DM bot, not the profile bot.

### Script-Level Telegram API Usage (Bypassing Gateway)

Some profile scripts (e.g., `strategy_optimizer.py`, `signal_manager.py`) send Telegram messages **directly** via `api.telegram.org` — they do NOT go through the Hermes Gateway at all.

**Delivery paths for profile scripts:**

1. **Hermes Cron + Gateway** → uses Hermes `deliver: telegram` → profile bot via Gateway
2. **System Crontab + Direct API** → script reads `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` from crontab env → sends via `requests.post()` directly
3. **Manual CLI run** → depends on which `.env` is sourced at runtime

**Troubleshooting direct-send scripts:**
- Check which bot token the script actually uses: `grep TELEGRAM_BOT_TOKEN $(which-profile-crontab)`
- Check `crontab -l` for the env variables — are they the profile bot's token or the main bot's?
- Direct-send scripts **silently fail** if the bot is not in the target channel — no Gateway error, no systemd alert
- The script logs the `send_telegram()` output but won't log a 400 Bad Request if the bot isn't a channel member
- To verify: call `api.telegram.org/bot<token>/getChat?chat_id=<channel_id>` — `400 Bad Request` = bot not a member

**Bot Channel Access Diagnosis (for any bot):**
```python
import urllib.request, json
url = f"https://api.telegram.org/bot{token}/getChat?chat_id={channel_id}"
try:
    resp = urllib.request.urlopen(url)
    data = json.loads(resp.read())
    if data.get("ok"): print("Bot IS in channel ✅")
except urllib.error.HTTPError as e:
    # 400 = bot not a member; 403 = kicked/blocked
    print(f"Bot NOT in channel ({e.code}) ❌")
```

**Fix:** Add the profile's bot as Admin in the target channel (Telegram → Channel → Administrators → Add Admin → select bot → enable "Send Messages").

### Cron Syntax Pitfalls

1. **Schedule positional FIRST**, prompt SECOND. No `--schedule` flag.
2. No `--repeat` flag (omit for forever).
3. **Cron needs gateway RUNNING.** Cron silently fails if gateway down.
4. **Profile .env is EMPTY by default.** Main .env does NOT auto-apply to profiles.
5. **Provider-specific API keys** must be in profile `.env` (e.g., `XIAOMI_API_KEY` for xiaomi provider).
6. **Delivery setting:** Must set `"delivery": "telegram"` or `--deliver telegram` on `cron create`.
7. **Gateway restart after changes:** Always `systemctl restart hermes-gateway-<profile>` after `.env`, `config.yaml`, or `jobs.json` changes.
8. **Response truncated: avoid delegate_task in cron prompts.** Models with low output-token limits (e.g. `openai/gpt-oss-120b:free`) can fail with `RuntimeError: Response truncated due to output length limit` when the cron prompt uses `delegate_task` — subagent output aggregates into the main response, exceeding the length check. Fix: remove `delegate_task`, compact prompt (max 10-12 items, bulletpoints), or use a model with higher output capacity.

10. **Model selection for cron jobs:** If truncation persists (even without `delegate_task`), switch to a model with higher output capacity. `openrouter/owl-alpha` (free, 1M context, agentic-workload-optimized) resolved the truncation issue for Martins `hermes-news` daily briefing. Set `model: "openrouter/owl-alpha"` and `provider: "openrouter"` in the cron job config. Owl Alpha is on the same OpenRouter routing tier -- no additional API key needed.

11. **xai-oauth 403 (spending limit) — switch provider entirely:** When xAI Grok tokens run out, the cron job returns HTTP 403 `personal-team-blocked:spending-limit`. The fix is NOT model-only — the entire provider must change:
    - Cron job: change both `model` (to e.g. `openrouter/owl-alpha`) AND `provider` (to `openrouter`)
    - x_search config in `config.yaml`: stays on `xai-oauth` (separate from cron model)
    - Cron prompt stays unchanged — the model swap is invisible to the LLM
    - When Grok credits are restored, switch back by reversing both fields
    - Do NOT set a `fallback_model` in config.yaml — the xai-oauth provider simply 403s and fallback doesn't help because the primary provider is wrong. Change the cron jobs provider directly.

12. **Profile cron `hermes cron run` may not execute immediately:** When you update `jobs.json` and restart the gateway, then trigger `hermes --profile <name> cron run <id>`, the job might NOT fire on the next scheduler tick if:
    - The NEW gateway (after restart) needs time to initialize its scheduler
    - The old gateways memory still has a cached copy of `jobs.json` from before the file was updated
    - The scheduler tick interval is longer than expected (varies by profile)
    
    **Consequence:** The `next_run_at` in `jobs.json` updates (showing the triggered run), but the run never actually executes. No output file appears, no log entry.
    
    **Fix:** Instead of relying on `cron run` immediately after a restart, either:
    - Wait for the next scheduled run (e.g. next 06:00 for news briefing)
    - Restart the gateway AGAIN after the `cron run` trigger, so it picks up the modified jobs.json fresh
    - Check `journalctl -u hermes-gateway-<profile> --since "5 min ago"` to see if the scheduler tick actually fired

13. **The cronjob tool only works for the main Hermes cron, NOT profile cron jobs.**

12. **xAI OAuth als Cron-Provider.** Der xAI-OAuth-Eintrag in der Credential-Pool (`hermes auth list` zeigt `xai-oauth (1 credentials)`) wird im Cron-Job so konfiguriert:
    ```json
    "model": "grok-4.20-0309-non-reasoning",
    "provider": "xai-oauth",
    ```
    Der Provider-Name ist `xai-oauth`, NICHT `xai`. Das Modell `grok-4.20-0309-non-reasoning` ist ein non-reasoning Modell für schnellere, direkte Antworten. Reasoning-Modelle haben kein `-non-reasoning` Suffix.

13. **JSON in jobs.json mit Sonderzeichen — patch-Tool vermeiden.** Wenn der Prompt deutsche Sonderzeichen enthält (Anführungszeichen „ “, Gedankenstriche —, ———), korrumpiert das `patch`-Tool die JSON-Struktur (fehlende Kommas, unescaped Chars).
    
    **Fix:** Immer Python mit `json.dump(ensure_ascii=False)` verwenden:
    ```python
    import json
    data = json.load(open(path))
    data["jobs"][0]["prompt"] = prompt_text
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    ```
    Das erhält Umlaute und Sonderzeichen lesbar und escaped automatisch notwendige Zeichen.

14. **Cross-Profile Cron Delivery Bot Mismatch (CRITICAL).** Wenn du einen Cron-Job im **main Hermes Scheduler** anlegst (`cronjob`-Tool oder `hermes cron create`) mit `profile: <name>`, dann läuft der **Agent im Profil-Kontext**, aber die **Zustellung (Delivery) geht über den main Gateway/Bot** — NICHT über den Bot des Profils.

    **Symptom:** Der Job läuft erfolgreich (`last_status: ok`), aber die Zustellung scheitert mit `Chat not found` — weil der main-Bot nicht im Ziel-Channel ist. Der Profil-Bot wäre im Channel, wird aber nie für die Delivery verwendet.
    
    **Root Cause:** Der main Scheduler nutzt seinen eigenen Bot-Token für Delivery. Der `profile:` Parameter steuert nur die Runtime-Umgebung (`.env`, `config.yaml`), nicht den Delivery-Bot.
    
    **Fix — Job direkt ins Profil `cron/jobs.json` schreiben:**
    ```python
    import json
    path = '/root/.hermes/profiles/<profil>/cron/jobs.json'
    data = json.load(open(path))
    data['jobs'].append({
        'name': 'job-name',
        'prompt': '...',  # Vollständiger Prompt
        'skills': [],
        'model': {'model': 'openrouter/owl-alpha', 'provider': 'openrouter'},
        'schedule': {'kind': 'cron', 'expr': '0 6 * * *', 'display': '0 6 * * *'},
        'state': 'scheduled',
        'deliver': 'origin',  # KEY: 'origin' im Profil-Kontext = TELEGRAM_HOME_CHANNEL über Profil-Bot
        'no_agent': False
    })
    json.dump(data, open(path, 'w'), indent=2, ensure_ascii=False)
    ```
    Danach `systemctl restart hermes-gateway-<profil>`.
    
    **Warum `deliver: origin` im Profil funktioniert:**
    - Im main Scheduler bedeutet `origin` "zurück zum Chat, der den Job erstellt hat"
    - Im **Profil-Scheduler** resolved `origin` zum Profil-eigenen `TELEGRAM_HOME_CHANNEL` über den Profil-eigenen Bot
    - Das ist der kanonische Weg, um durch das Profil-Gateway zuzustellen
    
    **Nicht versuchen:** curl-Befehle in den Cron-Prompt zu packen — der Hermes Prompt-Validator blockiert shell-basierte Delivery-Payloads als Exfiltrations-Risiko (`threat pattern 'exfil_curl_url'`).
    
    **Verifikation:**
    ```bash
    source /root/.hermes/profiles/<profil>/.env
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
      -d "chat_id=${TELEGRAM_HOME_CHANNEL}" \
      -d "text=Test" \
      | python3 -c "import json,sys; print('✅' if json.load(sys.stdin).get('ok') else '❌')"
    ```

## Updating Cron Prompts
    data["jobs"][0]["prompt"] = prompt_text
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    ```
    Das erhält Umlaute und Sonderzeichen lesbar und escaped automatisch notwendige Zeichen.

## Updating Cron Prompts in Response to User Feedback

When a user says "I don't like the output" of a cron job, the fix is almost always in the prompt — not in the model or the schedule. The following workflow covers diagnosing the mismatch, rewriting the prompt, and applying it cleanly.

### Workflow

1. **Read the failing output** — find the latest cron output file in the profile's cron output directory:
   ```bash
   ls -lt ~/.hermes/profiles/<profile>/cron/output/<job_id>/ | head -3
   ```
   Identify what the user dislikes (over-filtering, wrong tone, missing sections, etc.)

2. **Read the current prompt** — always from `jobs.json`, not from memory:
   ```bash
   python3 -c "import json; d=json.load(open('~/.hermes/profiles/<profile>/cron/jobs.json')); [print(j.get('prompt','')[:2000]) for j in d['jobs'] if j['id']=='<job_id>']"
   ```

3. **Diagnose the root cause** in the prompt text. Common patterns:
   - **Over-filtering**: language like "nur relevante", "streng priorisieren", "ignoriere" causes LLMs to drop content the user actually wants
   - **False "nothing to report"** : the prompt tells the LLM it can say "nothing happened" — LLMs take the easy out
   - **Missing explicit inclusion**: "X ist explizit erwünscht" beats "X darf erwähnt werden"
   - **Line count / length caps**: max 3 items can be too few; bump to 5

4. **Rewrite with user's preferences baked in** — do NOT just change one line. Rewrite the full prompt with:
   - Explicit positive directives ("X ist explizit erwünscht — nicht herausfiltern")
   - Concrete no-gos verbatim from user feedback
   - Quantified scope (max 5, not "wenige")
   - Removal of "escape hatches" like "entfällt" / "Ruhiger Morgen" — replace with "bei ruhigen Tagen: kurze Zusammenfassung"

5. **Apply via Python JSON** — never use shell quoting for long prompts with special chars:
   ```python
   import json
   path = "/root/.hermes/profiles/<profile>/cron/jobs.json"
   data = json.load(open(path))
   for job in data["jobs"]:
       if job["id"] == "<job_id>":
           job["prompt"] = """<new_prompt>"""
   with open(path, "w", encoding="utf-8") as f:
       json.dump(data, f, indent=2, ensure_ascii=False)
   ```
   See pitfall #13 below for why `patch`-tool fails on Sonderzeichen.

6. **Update reference files** — if a skill has a `references/` file documenting this crones format (e.g. `references/news-briefing-prompt-template.md` for the daily briefing), update it in sync with the new prompt version. The reference file stores the stable source list and the last-approved prompt text, so future edits start from the right baseline.

7. **Verify** — confirm the JSON is valid and the cron job is recognized:
   ```bash
   hermes --profile <profile> cron list | grep <job_id>
   python3 -c "import json; json.load(open('~/.hermes/profiles/<profile>/cron/jobs.json'))" && echo "Valid JSON"
   ```

8. **Inform the user** — tell them what changed and when the next run happens, so they know what to expect.

### User Preferences That Belong in Prompt, Not Just Memory

When Martin expresses a style/format/content preference about cron output, embed it in the prompt itself:
- "Lokale Ereignisse sind explizit erwünscht — nicht herausfiltern"
- "Kein 'entfällt' oder 'Ruhiger Morgen' — bei ruhigen Tagen: kurze Zusammenfassung"
- Saisonale Anhänge: Wassertemperaturen Ostsee/Schweriner See von Mai–September
- Max 5 Nachrichten statt 3

These go in the `jobs.json` prompt, not in memory. Memory captures who Martin is; the prompt captures how this specific cron should behave.

### Truncation Diagnosis for Profile Cron Jobs

12. **System crontab vs. Hermes cron for profile scripts — different env sources.** Profile scripts can run via system crontab (`crontab -l`) instead of Hermes cron. When they do, they read `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` from the **crontab's environment variables** (set at the top of the crontab), NOT from the profile's `.env`. If the crontab env vars point to the wrong bot (e.g. the main DM bot instead of the profile's bot), messages silently fail to reach the target channel. Check both: `grep TELEGRAM_BOT_TOKEN $(crontab -l)` AND `cat ~/.hermes/profiles/<name>/.env`.

13. **Triggered runs via `hermes cron run` execute asynchronously.** They schedule the job for the next scheduler tick -- not instantly. The cron list updates only after the run completes. Check the profile's cron/output/<job_id>/ directory for new output files.

14. **Duplicate TELEGRAM_BOT_TOKEN in system crontab — last declaration wins, silently.** When a system crontab (`crontab -l`) has multiple `TELEGRAM_BOT_TOKEN=...` lines, cron applies them sequentially — the LAST one overwrites all previous ones. This is invisible from any single line; you must read the full crontab to spot the duplicates. Common cause: running `setup.sh` multiple times appends new env blocks without removing old ones.

    **Diagnosis:**
    ```bash
    # Count declarations — should be exactly 1
    crontab -l | grep -c "^TELEGRAM_BOT_TOKEN="
    
    # Show all values — should all match the profile's bot
    crontab -l | grep "^TELEGRAM_BOT_TOKEN="
    ```

    **Fix:**
    ```bash
    crontab -l | sed '/^TELEGRAM_BOT_TOKEN=/d' > /tmp/clean_cron.txt
    # Then add the correct single declaration at the top
    echo "TELEGRAM_BOT_TOKEN=<correct-token>" > /tmp/new_cron.txt
    cat /tmp/clean_cron.txt >> /tmp/new_cron.txt
    crontab /tmp/new_cron.txt
    ```

    **Resolution checklist:**
    - Before: trading scripts silently fail (wrong bot, not in channel)
    - After one correct declaration: messages arrive in the profile's channel
    - Verify: `crontab -l | grep "^TELEGRAM_BOT_TOKEN="` shows exactly one line with the correct token

### Converting LLM-Driven Crons to no_agent

Mechanical cron jobs (bisync, health checks, routine scraping) don't need an LLM every cycle. Converting them to `no_agent` scripts saves tokens, runs faster, and is more reliable.

#### When to convert

- The job runs a deterministic command (rclone, curl, script)
- The output is always "yes it worked" — the LLM just summarizes what the command already printed
- The job runs frequently (daily or more)
- The job delivers to `local` (no user needs to read "success" messages)

#### The pattern: silent on success, alert on failure

```
┌──────────────────────────────────────────┐
│  Script exit 0, empty stdout             │  → SILENT (no delivery)
│  Script exit non-zero, stdout has error  │  → DELIVERED to user
└──────────────────────────────────────────┘
```

**Implementation steps:**

1. **Write the script** in `~/.hermes/scripts/<name>.sh`:
   ```bash
   #!/bin/bash
   set -u
   
   # Run the command
   OUTPUT=$(some-command 2>&1)
   EXIT_CODE=$?
   
   if [ $EXIT_CODE -eq 0 ]; then
     exit 0  # Silent on success
   fi
   
   # Failure — output error to be delivered
   echo "=== JOB FEHLER ==="
   echo "Zeit:    $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
   echo "Exit:    $EXIT_CODE"
   echo "$OUTPUT"
   exit 1
   ```

2. **Update the cron job:**
   ```bash
   hermes cron edit <job_id> --script <name>.sh --no-agent
   ```

3. **Set prompt** to a short description (just for reference, not executed):
   ```bash
   hermes cron edit <job_id> --prompt "Short description — runs via no_agent script"
   ```

#### Auto-recovery pattern

For commands that fail transiently (e.g., rclone bisync cache corruption), add an auto-recovery attempt before failing:

```bash
# First attempt
OUTPUT=$(some-command 2>&1)
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
  exit 0
fi

# Auto-recovery on known recoverable error
if echo "$OUTPUT" | grep -q "Must run --resync to recover"; then
  OUTPUT=$(some-command --resync 2>&1)
  EXIT_CODE=$?
  if [ $EXIT_CODE -eq 0 ]; then
    exit 0  # Recovery worked — still silent
  fi
fi

# Real failure
echo "=== JOB FEHLER ==="
...
exit 1
```

#### Concrete example 1: Obsidian vault bisync

The nightly bisync (`obsidian-vault-bisync-nightly`, job `f5eb3bfaf65e`) was converted from LLM-driven to no_agent:

- **Script**: `~/.hermes/scripts/obsidian-bisync.sh`
- **Path consistency**: Use `gdrive:hermes-obsidian-vault/` NOT `gdrive:` with `--drive-root-folder-id`. The cache filenames differ between the two, causing "cannot find prior listings" on alternating runs.
- **Auto-resync**: Cache is deleted or corrupted after manual resyncs. Script auto-detects "Must run --resync to recover" and retries with `--resync`.
- **Excludes**: `*.conflict*`, `*conflict*`, `.DS_Store`
- **No `--resync-permission`**: This flag does NOT exist in rclone v1.73.5 — don't use it.
- **Silent on success**: Only notifies Martin if the bisync actually fails (network down, auth expired, etc.)

#### Pitfalls

- **no_agent scripts use empty-stdout = SILENT**. If the script prints anything on success (e.g., "✅ Done!"), it gets delivered to the user every time. Keep success stdout empty.
- **Exit code matters**. Even with empty stdout, exit non-zero triggers an error alert. Use `exit 0` explicitly after success.
- **Cache naming is path-dependent**. rclone bisync caches listing files named after the path strings. `gdrive:` and `gdrive:hermes-obsidian-vault/` produce different cache filenames. Stick with one path pattern.
- **Python over shell quoting**. For long prompts with German Sonderzeichen, use Python json.dump (see pitfall #13 below). For no_agent scripts, raw bash is fine since there's no prompt to corrupt.

#### Concrete example 2: Hermes state GitHub backup

The state backup (`hermes-state-github-sync`, job `736b150caef2`) was rebuilt from scratch after the old rsync+git approach died:

- **Script**: `~/.hermes/scripts/hermes-state-sync.sh`
- **Approach**: Git directly (no rsync middleman). Copies skills, filtered profiles, config files, and identity files into a local git clone → commits → pushes to GitHub.
- **no_agent**: Runs nightly at 03:00 via Hermes cron, no LLM involved.
- **Silent on success**: Only notifies if git push fails (network, auth, secrets blocked).
- **Secret scanning**: GitHub push protection blocks commits with `ghp_` tokens. Script auto-redacts, but source skill files need to be cleaned first. See `hermes-state-github-sync` skill for full documentation.

**Key lesson**: The old approach (LLM-driven + rsync + system crontab) had three failure points (LLM cost, rsync cache, system crontab env). The new approach has one (git push). When migrating any cron to no_agent, ask: "what's the simplest thing that can work and has the fewest moving parts?"

### Truncation Diagnosis for Profile Cron Jobs

When a profile cron job reports `RuntimeError: Response remained truncated after 3 continuation attempts`:

1. Check jobs.json for the model override: `cat ~/.hermes/profiles/<name>/cron/jobs.json | grep model`
2. Check profile config.yaml default model -- the cron job's model may have reverted to this default.
3. Check journalctl for the profile gateway: `journalctl -u hermes-gateway-<name> --no-pager -n 50` (truncation also shows in gateway shutdown logs when old gateway was still processing).
4. Verify the output file: `ls -lt ~/.hermes/profiles/<name>/cron/output/<job_id>/` -- if < 1KB and only error, job never completed.
5. Fix model in jobs.json, restart gateway, trigger test run.
6. If fix was already applied but reverted: see pitfall #10 -- model silently reverted to config.yaml default.
7. Full diagnostic recipe: `references/profile-cron-truncation-debug.md`

### Cron Jobs Lost After Git Pull (Skill-Ref Pitfall)

Cron jobs created with `skills: [profile-spezifischer-skill]` can disappear from `jobs.json` silently after a `git pull` restarts the scheduler. The scheduler runs in the default profile, can't find the referenced skill, and drops the job.

**Fix**: Never use `skills=` in cronjob create. Embed skill instructions directly in the prompt. After every `git pull`, run `hermes cron list` to verify all jobs survived.

**Full debugging guide**: `references/lost-cron-jobs-debugging.md` in this skill directory.

### Debugging Sequence

1. Bot works? Test with `getChat` API to verify bot is in target channel.
2. Crontab token clean? `crontab -l | grep "^TELEGRAM_BOT_TOKEN="` — exactly 1 line?
3. Gateway running? Check `ps aux | grep hermes` and `systemctl status`.
4. Cron last run error? Check cron list output.
5. Cron output files? Check profile cron output dir.
6. Gateway logs? Check `journalctl -u hermes-gateway-<profile> --no-pager -n 20`.
7. Profile .env has OPENROUTER_API_KEY and correct TELEGRAM_BOT_TOKEN?

### 429 Rate-Limit Cascade (Missing Toolset)

When a cron job fails with `HTTP 429: Provider returned error`, the root cause is often NOT the rate limit itself — it is a cascade from a missing `web` toolset:

```
Profile has toolsets: [hermes-cli, x_search] (no web)
  → Agent calls web_search → "Tool does not exist"
  → Falls back to browser_navigate
  → Bot detection walls on news/paywall sites (DataDome, Cloudflare)
  → Wasted tokens + retries → OpenRouter free-tier 429
```

**Diagnosis:** Check `request_dump` in profile's sessions dir → check `config.yaml` for `toolsets` → check model (free tier?). **Also compare `jobs.json` model override vs `config.yaml` default — they can drift apart.** A DM test run may work but the cron fail because the profile has a different model/toolset than your session.

**Fix:** Add `web` to toolsets, switch from free model to paid, and sync config.yaml default with cron override to prevent future confusion.

Full recipe: `references/cron-429-toolset-diagnosis.md`

---

## 2. Gateway Troubleshooting

Diagnose and fix `hermes-gateway.service` or profile gateway failures.

### Symptoms & Fixes

**"PID file race lost to another gateway instance"**
Stale `gateway.pid` from previous unclean shutdown.
Stop service → delete `gateway.pid` in `~/.hermes/` → `reset-failed` → start service.

**"Telegram bot token already in use (PID XXXX)"**
Another gateway instance (or zombie) holds the bot token.
Kill process with `ps aux | grep hermes`, then `reset-failed` and start service.

**systemd "Start request repeated too quickly"**
systemd rate-limiter after repeated crashes (counter at 6).
Run `systemctl reset-failed` on the service before retrying.

**Telegram connect timed out (fallback IP timeout)**
If `gateway.log` shows `telegram connect timed out after 30s` and `api.telegram.org` is reachable, the `TelegramFallbackTransport` is failing on the seed IP.
Fix: Add `HERMES_TELEGRAM_DISABLE_FALLBACK_IPS=true` to the profile's `.env`.
This must be set in EVERY profile `.env` that runs a Telegram gateway — it does NOT cascade from the main profile.
Then `systemctl reset-failed && systemctl restart hermes-gateway-<profile>`.
See `devops/gateway-watchdog` skill for automatic recovery.

**Profile gateway conflicts**
Profile gateways sharing the same Telegram bot token — only ONE can run at a time.

## 3. Gateway Loop Healthcheck — Proactive Monitoring

Three-layer protection: aggressive systemd auto-restart + a tight cron watchdog + weekly proactive restart.

### Architecture

**Layer 1 — systemd auto-restart (always-on recovery)**
- `Restart=always` (not `on-failure` — catches planned stops too)
- `RestartSec=10` — restart within 10s instead of 60s
- `TimeoutStopSec=20` — SIGKILL after 20s (was 90s, preventing lengthy hangs)
- `StartLimitBurst=3` / `StartLimitIntervalSec=600` — max 3 restarts in 10min
- This means: the gateway is back within ~10s of any exit, planned or unplanned

**Layer 2 — Cron Watchdog (intelligent recovery, every 5min)**
- Every 5min via `no_agent=True` cron (was 30min)
- Script: `~/.hermes/scripts/gateway-watchdog.py`
- Checks: Is the service active? Does the Telegram API respond (`getMe`)?
- Both OK → silent exit (no log, no message)
- Failure → service restart + log entry
- Same error >2x in 60min → CRITICAL (no restart, manual intervention required)

**Layer 3 — Weekly Proactive Restart (prevents stale bytecode cache)**
- Every Sunday 04:00 via `no_agent=True` cron
- Script: `~/.hermes/scripts/weekly-gateway-restart.sh`
- Calls `systemctl restart`, then waits up to 24s for active state
- Must match `TimeoutStopSec` — the restart script's wait loop should be slightly longer than the stop timeout

### Setting Up the Healthcheck

```bash
# 1. systemd Drop-In for restart limits + fast recovery
mkdir -p /etc/systemd/system/hermes-gateway.service.d
cat > /etc/systemd/system/hermes-gateway.service.d/99-restart-limit.conf << 'CONF'
[Service]
Restart=always
RestartSec=10
StartLimitBurst=3
StartLimitIntervalSec=600
TimeoutStopSec=20
CONF
systemctl daemon-reload
# No restart needed — changes apply on next service stop/start
```

2. Write the watchdog script at `~/.hermes/scripts/gateway-watchdog.py`
3. Create the cron job (`no_agent=True`, `every 5m`, deliver: local)
4. Create the weekly restart script at `~/.hermes/scripts/weekly-gateway-restart.sh`
5. Log file: `/root/.hermes/logs/gateway-watchdog.log`

### Gateway Shutdown Diagnosis

When Martin sees a "gateway shutting down" message, determine if it's planned or a problem:

**Planned shutdowns (no action needed):**
- Weekly restart (Sunday 04:00) — `journalctl` shows `signal=SIGTERM` + `parent_cmdline=/sbin/init`
- Gateway stop via systemctl — same SIGTERM signature
- Check: `journalctl -u hermes-gateway.service --since "1 hour ago" | grep -i "shutdown\|SIGTERM"`

**Unplanned shutdowns (investigate):**
- Crashes with traceback — `journalctl` shows Python exceptions before SIGTERM
- OOM kill — `journalctl` shows `code=killed, status=9/KILL` without prior SIGTERM
- Telegram API errors — `get_updates` failures during graceful shutdown (harmless but noisy)
- Check: `journalctl -u hermes-gateway.service -n 50 | grep -E "ERROR|CRITICAL|Traceback|killed"`

**Graceful shutdown Telegram error (harmless):**
```
Error while calling `get_updates` one more time to mark all fetched updates.
Suppressing error to ensure graceful shutdown.
```
This is a Telegram Python library quirk — occurs when getting one last poll during shutdown. Not critical.

**Verify config change was applied:**
```bash
systemctl show hermes-gateway.service | grep -E "Restart=|RestartUSec|TimeoutStopUSec"
```
- `Restart=always` ✅
- `RestartUSec=10s` ✅
- `TimeoutStopUSec=20s` ✅

### Why TimeoutStopSec Matters

Old 90s value caused:
- Weekly restart hung for 90s before SIGKILL
- During that time, the gateway was "deactivating" — cron jobs backed up
- Users saw the "shutting down" message and couldn't tell if it was planned

New 20s value:
- Quick enough that the restart feels instant
- Still plenty of time for graceful Telegram shutdown
- Paired with `RestartSec=10s` → gateway is back within 30s total

### Escalation Procedure

When the watchdog log shows **CRITICAL** (same error >2x in 60min):

```bash
systemctl status hermes-gateway.service
cat ~/.hermes/logs/gateway-watchdog.log | tail -10
journalctl -u hermes-gateway.service -n 50
```

After fixing the root cause, reset tracking:
```bash
rm -f /tmp/hermes-gateway-watchdog-track
systemctl reset-failed hermes-gateway.service
systemctl restart hermes-gateway.service
```

### Telegram Fallback IP Timeout

If `gateway.log` shows `telegram connect timed out after 30s` but `api.telegram.org` is reachable, the `TelegramFallbackTransport` is failing on the seed IP.

Fix:
```bash
echo "HERMES_TELEGRAM_DISABLE_FALLBACK_IPS=true" >> ~/.hermes/profiles/<profile>/.env
```
This must be set in **every** profile `.env` that runs a Telegram gateway — it does NOT cascade from the main profile.
Then `systemctl reset-failed && systemctl restart hermes-gateway-<profile>`.

### Systemd Drain Timeout Mismatch

When `systemctl restart` of the gateway causes the service to hang in **"deactivating"**:

**Symptom:**
```
WARNING gateway.run: Stale systemd unit detected: ...
has TimeoutStopSec=60s but drain_timeout=60s
(expected >=90s). systemd may SIGKILL the gateway mid-drain.
Run `hermes gateway service install --replace` to regenerate the unit.
```

**Fix:**
```bash
systemctl kill hermes-gateway-{profil}.service
systemctl reset-failed hermes-gateway-{profil}.service
hermes --profile {profil} gateway service install --replace
systemctl start hermes-gateway-{profil}.service
```

The regenerated unit has correct `TimeoutStopSec`.

**After regeneration, re-apply the custom Drop-In** with aggressive settings:
```bash
cat > /etc/systemd/system/hermes-gateway-{profil}.service.d/99-restart-limit.conf << 'CONF'
[Service]
Restart=always
RestartSec=10
StartLimitBurst=3
StartLimitIntervalSec=600
TimeoutStopSec=20
CONF
systemctl daemon-reload
systemctl restart hermes-gateway-{profil}.service
```

`hermes gateway service install --replace` regenerates the **main unit file**, resetting `TimeoutStopSec` to upstream default. Always re-apply the Drop-In afterward.

After LXC/VM restart, verify all gateway services started:

```bash
# 1. List all gateway services
systemctl list-units --type=service --all | grep hermes-gateway

# 2. Enable + start disabled ones
systemctl start hermes-gateway-{profil}.service
systemctl enable hermes-gateway-{profil}.service

# 3. Check cron health
hermes cron list
```

#### Dashboard Pipeline-Tab: Statische Einträge entfernen

Das Trading-Dashboard (`dashboard.py` im `hermes_trading` Profil) hat einen `⏰ Cron & Logs` Tab mit einer Pipeline-Tabelle. Die Einträge kommen teils aus der System-Crontab, teils aus einem statischen Beschreibungs-Dict (`SCRIPT_DESCRIPTIONS`).

Wenn ein Pipeline-Eintrag nie läuft (Status "–" / nie gelaufen), liegt es meist daran, dass:
- Das Script nicht existiert (`export_watchlist` wurde z.B. nie implementiert)
- Der Cron-Job gelöscht oder nie angelegt wurde
- Der Eintrag nur Deko im Beschreibungs-Dict ist

**Fix:** Beide Stellen im Code bereinigen:
1. `SCRIPT_DESCRIPTIONS` Dict — den Eintrag löschen
2. Filter-Liste in der `for line in output.splitlines()` Schleife — den Key entfernen
3. Dashboard neustarten (zwei Wege):
   - **Via 15-min Watchdog (sauberer):** `pkill -f dashboard.py` — der `dashboard-watchdog.sh` (Cron alle 15min) erkennt den Ausfall und startet neu
   - **Sofort:** `cd /root/.hermes/profiles/hermes_trading/skills/trading && source venv/bin/activate && nohup python dashboard.py > /dev/null 2>&1 &` (wenn watchdog zu langsam ist)
   - Verifikation: `curl -s -o /dev/null -w "%{http_code}" http://localhost:8081/` → `200`

## Cron-Integration — Two-Tier System

Hermes has two independent cron systems:
- **Global scheduler** (`~/.hermes/cron/jobs.json`) — default profile
- **Profile scheduler** (`{profile}/cron/jobs.json`) — per gateway profile

A profile cron job runs ONLY when the associated gateway is active. Gateway down → no ticks → jobs pile up.

**Diagnosis for "crons stopped since date X":**
1. `hermes profile list` → gateway running?
2. `systemctl status hermes-gateway-{profil}.service` → systemd alive?
3. `journalctl -u hermes-gateway-{profil}.service -n 50` → cause of death?
4. `cat {profile}/cron/jobs.json` → check `next_run_at` in the past?

Full diagnosis recipes in `references/gateway-watchdog-diagnosis.md`.

### Quick Health Check

```bash
systemctl status hermes-gateway.service --no-pager
tail -15 ~/.hermes/logs/agent.log
journalctl -u hermes-gateway.service --no-pager -n 20
```

### Health Check Response Protocol (User Preference)

**CRITICAL RULE — When any job status is not green (ok/OK):**

Do NOT just report the status to the user. IMMEDIATELY:

1. Identify which specific job/slot is non-green
2. Open the relevant logs (agent.log, errors.log, journalctl, pipeline log)
3. Find the root cause — error message, exit code, timestamp
4. Propose a concrete fix or diagnosis step
5. Report: "X ist gelb/rot wegen Y. Fix: Z"

**Never:**
- "Job X ist gelb" ohne Kontext
- "Soll ich mal schauen?" (mach es einfach)
- Nur den Status auflisten ohne Ursachenforschung

Diese Regel gilt für ALLE Status-Checks — Trading-Dashboard, Cron-Jobs, Pipeline-Logs, Gateway-Status. Wenn ein Indikator nicht grün ist, ist die erste Aktion immer Debugging, nicht Reporting.

### Systemd Unit Configuration Pitfalls

- Add `PIDFile=/run/hermes-gateway/hermes-gateway.pid` and **both** `EnvironmentFile=/root/.hermes/.env` **and** `EnvironmentFile=/root/.hermes/profiles/<profile>/.env` to the service unit.
- Use `ExecStartPre` to:
  - `mkdir -p /run/hermes-gateway`
  - `chmod 755 /run/hermes-gateway`
  - `rm -f /root/.hermes/gateway.pid /root/.hermes/profiles/<profile>/gateway.pid`
- Reload systemd: `systemctl daemon-reload` after editing the unit file.
- Don't remove `gateway_state.json` unless necessary — it tracks cron state.
- After 6 failed starts, systemd enters rate-limit — must `reset-failed` before retrying.
- Stale `gateway.pid` files (both `~/.hermes/gateway.pid` and profile-specific) are the #1 cause of PID file race errors.

---


## 4. State Backup to GitHub

Create a durable, token-efficient backup of Hermes state (skills, profiles, config, identity files) using the no_agent cron pattern described in §1.

### Architecture

```
LLM-driven (deprecated)     →    no_agent script (current)
rsync → local git → push    →    git directly (no rsync)
system crontab              →    Hermes cron
always "success" message    →    silent on success, alert on failure
```

### What Gets Synced

| Source | Destination | Exclusions |
|--------|------------|------------|
| `~/.hermes/skills/` | `skills/` | `.cache/`, `cron/output/` |
| `~/.hermes/profiles/hermes-*/` | `profiles/hermes-*/` | `.env`, `venv/`, `logs/`, `data/`, `cron/output/`, `sessions/` |
| `~/.hermes/config.yaml` | `config/config.yaml` | — |
| `~/.hermes/cron/jobs.json` | `config/jobs.json` | — |
| `~/obsidian-vault/SOUL.md` | `identity/SOUL.md` | — |
| `~/obsidian-vault/MEMORY.md` | `identity/MEMORY.md` | — |
| `~/obsidian-vault/USER.md` | `identity/USER.md` | — |

All in a flat repo with `.gitignore` excluding secrets, binaries, and caches.

### Initial Setup

```bash
gh repo create <user>/<repo> --public --description "Hermes Skills/Memory/State Backup"
cd /root && git clone https://github.com/<user>/<repo>.git
```

### Sync Script Pattern

Location: `~/.hermes/scripts/hermes-state-sync.sh`

The script (see `references/state-backup-script.md`):
1. Copies the selected source directories into the local git clone
2. Runs `git add -A && git commit -m "..."`
3. Pushes to GitHub
4. **Silent on success** (empty stdout + exit 0)
5. **Error output on failure**

### Cron Setup

```bash
hermes cron create \
  --name "hermes-state-github-sync" \
  --schedule "0 3 * * *" \
  --script hermes-state-sync.sh \
  --no-agent \
  --deliver local
```

### Pitfalls

**GitHub Push Protection (Secret Scanning):**
GitHub blocks pushes containing `ghp_` tokens. If the initial sync fails with "GH013: Push cannot contain secrets":
```bash
grep -rn 'ghp_' /path/to/local/clone/ --include='*.md'
```
Redact the PAT in both the synced copy AND the source skill file under `~/.hermes/skills/`.

**No changes → silent exit:**
If nothing changed since last sync, the script exits 0 without committing. No empty commits.

**Large files bloating the repo:**
Exclude binaries in `.gitignore`. If something slipped through:
```bash
echo "*.db" >> .gitignore
git rm --cached *.db
git commit -m "Remove DB files from repo"
git push origin main
```

**Repair after server rebuild:**
```bash
cd /root && git clone https://github.com/<user>/<repo>.git
cp -r <repo>/skills/* ~/.hermes/skills/
cp <repo>/config/* ~/.hermes/
```
