#!/usr/bin/env python3
"""
cleanup_env.py – Bereinigt doppelte Zeilen in /root/.hermes/.env

AUSFÜHREN:
    python3 cleanup_env.py [--dry-run]
"""
import argparse, os, re

ENV_PATH = "/root/.hermes/.env"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    with open(ENV_PATH) as f:
        lines = f.readlines()

    seen_keys = {}
    output = []
    removed = []

    for line in lines:
        stripped = line.strip()
        # Leerzeilen und Kommentare immer behalten
        if not stripped or stripped.startswith('#'):
            output.append(line)
            continue
        m = re.match(r'^([A-Z_][A-Z0-9_]*)\s*=', stripped)
        if m:
            key = m.group(1)
            if key in seen_keys:
                removed.append((key, stripped[:60]))
                continue  # Duplikat überspringen
            seen_keys[key] = True
        output.append(line)

    print(f"=== .env Cleanup ===")
    print(f"Zeilen gesamt: {len(lines)} → bereinigt: {len(output)}")
    if removed:
        print(f"\nEntfernte Duplikate ({len(removed)}):")
        for key, val in removed:
            print(f"  {key}: {val}")
    else:
        print("Keine Duplikate gefunden.")

    if not args.dry_run and removed:
        with open(ENV_PATH, 'w') as f:
            f.writelines(output)
        print("\n✅ .env bereinigt")
    elif args.dry_run:
        print("\n(Dry-Run)")

if __name__ == "__main__":
    main()
