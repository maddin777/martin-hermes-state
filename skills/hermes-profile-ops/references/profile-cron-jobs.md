# Profile-cron jobs: create, migrate, edit, verify

A profile (`~/.hermes/profiles/<profil>/`) has its OWN scheduler and its OWN
`cron/jobs.json`. The `cronjob` tool and `hermes cron` act on the DEFAULT scheduler
(`/root/.hermes/cron/jobs.json`) unless you pass the profile (`hermes -p <profil> cron ...`,
`hermes-<profil> cron ...`). Confusing the two is the root cause of most "job runs but nothing arrives" reports.

## Job shape (profil `jobs.json`)

```json
{
  "id": "<11-hex>",
  "name": "<job-name>",
  "prompt": "...",
  "skills": ["<skill>"],
  "model": "<provider/model>",
  "provider": "<provider>",
  "schedule": {"kind": "cron", "expr": "0 6 * * *", "display": "0 6 * * *"},
  "deliver": "telegram",
  "state": "scheduled",
  "enabled": true,
  "repeat": {"times": null, "completed": 0},
  "no_agent": false,
  "enabled_toolsets": ["web"]
}
```

`deliver: telegram` sends through the PROFILE's bot into its `TELEGRAM_HOME_CHANNEL`.
`deliver: local` writes only the session log — use it for scan jobs whose results a later
digest job reports, so the user gets one message instead of five.

## Create / migrate

1. **Check both schedulers first** — the common failure is two jobs with the same name,
one in each scheduler, running with different models and different prompts:
   ```bash
   grep -l '"<job-name>"' /root/.hermes/cron/jobs.json \
     /root/.hermes/profiles/<profil>/cron/jobs.json
   ```
2. **Back up** the target `jobs.json` before editing.
3. **Write the job** with Python `json` (atomic: write a tmp file, then `os.replace`), never
   by hand-editing string fragments — prompts contain quotes, newlines and umlauts:
   ```python
   import json, hashlib, os
   from datetime import datetime
   path = "/root/.hermes/profiles/<profil>/cron/jobs.json"
   data = json.load(open(path, encoding="utf-8"))
   job = {...}                       # shape above
   job["id"] = hashlib.md5(f"{job['name']}-{datetime.now().isoformat()}".encode()).hexdigest()[:11]
   data["jobs"].append(job)
   tmp = path + ".tmp"
   with open(tmp, "w", encoding="utf-8") as f:
       json.dump(data, f, indent=2, ensure_ascii=False)
   os.replace(tmp, path)
   ```
4. **Remove the old job** from the default scheduler (`hermes cron remove <id>`) in the same
   session, not "later" — otherwise both keep delivering.
5. **Skill must exist inside the profile too.** A profil cron resolves skills from
   `~/.hermes/profiles/<profil>/skills/`; copy the skill directory there (and re-copy after
   every change to the canonical skill, otherwise the profil runs a stale copy).
6. **Gateway must be running** for the profil scheduler to tick:
   `systemctl start hermes-gateway-<profil>.service`; check
   `gateway_state.json` → `gateway_state == "running"` and `platforms.telegram.state`.
7. **Verify:** exactly one scheduler contains the name (step 1 grep), `next_run_at` is the
   intended time, and the model/provider match the intent.

## Edit the prompt of an existing job

- The job's `prompt` IS the job's skill definition. To change what a job does, edit the prompt.
- `hermes cron edit <job_id> --prompt "$(cat /tmp/newprompt.txt)"` — check the file exists and
  is non-empty first: a missing file passes an empty prompt and the job then runs unprompted.
- `--prompt` does not touch `enabled_toolsets`; re-check that field in `jobs.json` afterwards.
- Verify by reloading `jobs.json` and asserting the old text is gone and the new text is
  present — do not trust the CLI's "Updated job" line.

## Toolsets must match prompt prohibitions

If the prompt forbids a capability, the toolset must not include it (`file` off when the
prompt says "use only the script output", `terminal` off when it says "no shell"). A
contradiction makes the model reach for a blocked tool, hang, and then invent a reason
instead of delivering. `enabled_toolsets` has no CLI flag — it is only settable in
`jobs.json`. Confirm what the scheduler will actually use with
`_resolve_cron_enabled_toolsets(job, {})` from `cron/scheduler.py`.

## Manual trigger and proof of a run

- Trigger in the FOREGROUND with a >=600s tool timeout (digest jobs take 2–4 minutes);
  backgrounding with `nohup ... &` can report `Ran now: succeeded` without creating a session.
- `Ran now: succeeded` is NOT proof. Proof is: session `cron_<job_id>_<ts>` in
  `logs/agent.log` with `Turn ended` AND `delivered to telegram:`...`, plus `deliveries.db`
  showing `length(content)` well above zero.
- `last_status: ok` with an empty body is a real failure (see `daily-news-briefing`
  error-pattern section).
- A gateway restart does not trigger a job.

## One-off reminders and paused jobs

- One-off reminder at a fixed date: `hermes cron create "<min> <hour> <day> <month> *" --repeat 1 --deliver origin "<text>"`.
  Without `--repeat 1` the expression fires yearly on the same date. Verify `next_run_at`.
- `--paused` is a bare switch; `--paused false` is invalid — just omit it.
- `hermes cron resume <id>` keeps a past `next_run_at`; with `cron.catch_up_missed` (default
  true) the job runs once immediately. Before resuming, decide whether that catch-up run is
  harmless (report/alarm yes, orders or live config changes no).

## Health checks

Read `last_status` per critical job id straight from `jobs.json`; a health script that only
parses one log misses jobs that write elsewhere and reports "ok" during a permanent failure.

`cron_health.py`-style log scanners have three recurring false alarms:
- **Timing overlap:** a job starting in the same minute as the health check has START but no
  DONE yet → reported as crashed. Stagger the health check (e.g. 08:30 for 08:00 jobs).
- **Marker format:** it looks for `✅ ... DONE`; a job that prints `=== DONE ===` without the
  ✅ is flagged unknown. Emit the ✅ prefix in every cron echo line.
- **Block slicing:** a DONE line landing after the next job's START marker falls outside the
  parsed block. Widen the slice or shorten the upstream runtime.

## Gateway self-restart deadlock

A cron job that restarts its own gateway via `systemctl restart` waits for its own drain and
is then SIGKILLed with the whole cgroup — the restart succeeds but `last_run_at` stays None.
`journalctl -u hermes-gateway` shows "drain timed out ... 1 in-flight cron job" before the
kill. Decouple the restart: systemd timer or
`systemd-run --no-block --unit=<name> --collect systemctl restart hermes-gateway`. Back up
`jobs.json` and remove the old cron job before switching.

## Change-detection markers

Any job that reports "files changed since last run" depends on its marker file:
- persist the marker (`~/.hermes/cache/<marker>`), never `/tmp` — a lost marker silently
  re-baselines and an interval of changes disappears;
- **find with the existing marker FIRST, then touch it** — touching first baselines at "now"
  and finds nothing;
- bootstrap the first run with `-mtime -N` so the whole tree is not re-ingested.
