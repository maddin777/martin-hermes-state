#!/usr/bin/env python3
"""
test_lock_fix.py — Schneller Smoke-Test für den Negativ-Cache-/Lock-Fix.

Repliziert die watchlist_manager-Loop-Bedingung (eine offene äußere Schreib-
transaktion auf EINER Connection) und schickt nur N Namen durch
validate_and_register(con=con). Prüft:
  1. direkter Probe-Write von _cache_reject UNTER offener Transaktion (deterministisch)
  2. N echte unbekannte Namen end-to-end (kein 'database is locked')
  3. ob validation_rejects tatsächlich wächst

Aufruf:
    python3 test_lock_fix.py            # 15 Namen
    python3 test_lock_fix.py 10         # 10 Namen
Schreibt nichts Bleibendes außer echten Rejects (Probe-Zeile wird entfernt).
"""
import sys
import os
import time

_TR = "/root/.hermes/profiles/hermes_trading/skills/trading"
for _p in (_TR, os.path.join(_TR, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from config import db_connect
import company_validator as V

N = int(sys.argv[1]) if len(sys.argv) > 1 else 15
PROBE = "__locktest_probe__"

con = db_connect()

# Kandidaten: zuletzt erwähnte Namen, die NICHT schon als Alias bekannt sind
# -> die durchlaufen echte Validierung (und produzieren wahrscheinlich Rejects).
rows = con.execute("""
    SELECT DISTINCT m.name
    FROM watchlist_mentions m
    LEFT JOIN company_aliases a ON a.alias = lower(trim(m.name))
    WHERE a.alias IS NULL
    ORDER BY m.mention_date DESC
    LIMIT ?
""", (N,)).fetchall()
names = [r["name"] for r in rows]

before = con.execute("SELECT COUNT(*) FROM validation_rejects").fetchone()[0]
print(f"validation_rejects vorher: {before}")
print(f"Teste {len(names)} unbekannte Namen unter OFFENER Schreibtransaktion...\n")

# === Äußere Schreibtransaktion öffnen und offen halten (wie der echte Loop) ===
# Dieser INSERT startet via Python-Autobegin die Transaktion -> Write-Lock gehalten.
con.execute("""INSERT OR REPLACE INTO validation_rejects(name_key,reason,details)
               VALUES (?, 'probe', 'locktest')""", (PROBE,))

lock_error = False

# 1) Direkter Probe-Write über die GETEILTE Connection (deterministisch, ohne yfinance)
try:
    V._cache_reject("__locktest_shared__", "unknown", None, {"probe": 1}, con=con)
    probe_shared = con.execute(
        "SELECT 1 FROM validation_rejects WHERE name_key='__locktest_shared__'"
    ).fetchone() is not None
except Exception as e:
    probe_shared = False
    if "locked" in str(e).lower():
        lock_error = True
print(f"  [direkt] _cache_reject(con=shared) hat geschrieben: {probe_shared}")

# 2) Echte Namen end-to-end durch validate_and_register(con=con)
t0 = time.time()
for nm in names:
    try:
        res = V.validate_and_register(nm, con=con)
        print(f"  {nm[:38]:38} -> {res['status']:13} {res.get('reason') or ''}")
    except Exception as e:
        print(f"  {nm[:38]:38} -> EXCEPTION: {str(e)[:60]}")
        if "locked" in str(e).lower():
            lock_error = True
dt = time.time() - t0

# Probe-Zeilen wieder entfernen, dann committen (echte Rejects bleiben erhalten)
con.execute("DELETE FROM validation_rejects WHERE name_key IN (?, '__locktest_shared__')", (PROBE,))
con.commit()

after = con.execute("SELECT COUNT(*) FROM validation_rejects").fetchone()[0]
con.close()

print(f"\nDauer: {dt:.1f}s | validation_rejects: {before} -> {after} (+{after - before} echte Rejects)")
print(f"'database is locked' aufgetreten: {lock_error}")
if probe_shared and not lock_error:
    print("\n✅ FIX WIRKT: Schreiben unter offener Transaktion funktioniert, kein DB-Lock.")
    print("   -> watchlist_manager kann gefahrlos voll laufen.")
else:
    print("\n⚠️  Problem: Probe-Write fehlgeschlagen oder Lock aufgetreten — bitte Ausgabe schicken.")
