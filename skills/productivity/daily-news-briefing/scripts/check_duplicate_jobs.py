#!/usr/bin/env python3
"""Check for duplicate news-briefing jobs across default and profile schedulers.

Usage: python3 check_duplicate_jobs.py [jobname] [profile]

Default: checks 'daily-news-briefing' in hermes-news profile.
Returns exit code 0 if OK (1 or 0 jobs), 1 if duplicates found.

Output is human-readable for cron delivery.
"""

import json
import sys

JOBNAME = sys.argv[1] if len(sys.argv) > 1 else "daily-news-briefing"
PROFILE = sys.argv[2] if len(sys.argv) > 2 else "hermes-news"
DEFAULT_PATH = "/root/.hermes/cron/jobs.json"
PROFILE_PATH = f"/root/.hermes/profiles/{PROFILE}/cron/jobs.json"

def count_jobs(path: str) -> int:
    try:
        with open(path) as f:
            data = json.load(f)
        return sum(1 for j in data.get("jobs", []) if j.get("name") == JOBNAME)
    except (FileNotFoundError, json.JSONDecodeError):
        return 0

default_count = count_jobs(DEFAULT_PATH)
profile_count = count_jobs(PROFILE_PATH)
total = default_count + profile_count

print(f"🔍 Duplikat-Job-Check: '{JOBNAME}'")
print(f"   Default Scheduler: {default_count}")
print(f"   Profil '{PROFILE}':   {profile_count}")
print(f"   Gesamt: {total}")

if total > 1:
    print(f"\n❌ GEFAHR: {total} Jobs gefunden! Läuft parallel.")
    print(f"   Lösung: Job aus Default Scheduler löschen:")
    print(f"   → hermes cron remove <job-id>")
    print(f"   Oder: Profil-Job löschen wenn der Default-Job der richtige ist.")
    sys.exit(1)
elif total == 1:
    print(f"\n✅ Sauber: Genau 1 Job aktiv.")
    sys.exit(0)
else:
    print(f"\n⚠️  Kein Job gefunden mit Namen '{JOBNAME}'.")
    sys.exit(0)