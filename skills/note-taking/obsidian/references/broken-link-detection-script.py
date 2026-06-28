#!/usr/bin/env python3
"""
Vault Self-Write: Broken Link Detection Script (embedded in terminal)
=======================================================
Usage: python3 broken-link-detection-script.py
Run from vault root (/root/obsidian-vault/).

Scans wiki/ concepts, entities, sources, trading-index, and index
for [[wikilinks]], resolves them, and reports broken ones with
noise-filtering for navigational self-references.
"""

import re, os, glob
from pathlib import Path

VAULT = "/root/obsidian-vault"

# ── Step 1: Build set of all existing wiki page names ──
existing_wiki = set()
for f in (glob.glob(f"{VAULT}/wiki/concepts/*.md")
          + glob.glob(f"{VAULT}/wiki/entities/*.md")
          + glob.glob(f"{VAULT}/wiki/sources/*.md")):
    name = os.path.splitext(os.path.basename(f))[0]
    existing_wiki.add(name.lower())

# ── Step 2: All vault files for ../../ resolution ──
all_files = {}
for root, dirs, files in os.walk(VAULT):
    if '.obsidian' in root:
        continue
    for f in files:
        if f.endswith('.md'):
            rel = os.path.relpath(os.path.join(root, f), VAULT)
            all_files[rel.lower()] = rel

# ── Step 3: Scan wiki files for [[links]] ──
wiki_files = (glob.glob(f"{VAULT}/wiki/concepts/*.md")
              + glob.glob(f"{VAULT}/wiki/entities/*.md")
              + glob.glob(f"{VAULT}/wiki/sources/*.md")
              + [f"{VAULT}/wiki/trading-index.md",
                 f"{VAULT}/wiki/index.md"])

# Noise-prefixes: navigational links like [[wiki]] [[wiki/concepts]] etc.
NOISE = {'wiki', 'wiki/', 'wiki/concepts', 'wiki/entities',
         'wiki/sources', 'wiki/index'}

broken = []
for wf in sorted(wiki_files):
    wf_rel = os.path.relpath(wf, VAULT)
    wf_dir = os.path.dirname(wf)
    content = open(wf).read()
    for m in re.finditer(r'\[\[([^\]]+)\]\]', content):
        raw = m.group(1)
        target = raw.split('|')[0].strip()
        if not target:
            continue

        # Noise filter — skip navigation self-references
        tl = target.lower().rstrip('/')
        stripped = tl
        for prefix in ['wiki/concepts/', 'wiki/entities/', 'wiki/sources/', 'wiki/']:
            if stripped.startswith(prefix):
                stripped = stripped[len(prefix):]
        if stripped in NOISE or tl in NOISE:
            continue

        # ── Case A: ../../ relative path ──
        if target.startswith('../'):
            # !!! PITFALL:
            # From wiki/, ../../ goes TWO levels up → vault parent (/root/),
            # NOT to vault root (/root/obsidian-vault/).
            # From wiki/concepts/, ../../ correctly goes to vault root.
            # The correct link from wiki/ to vault root is ../, not ../../
            abs_t = os.path.normpath(os.path.join(wf_dir, target))
            if os.path.exists(abs_t + '.md') or os.path.exists(abs_t):
                continue
            broken.append((wf_rel, m.group(0), target))
            continue

        # ── Case B: Direct wiki page name ──
        clean = target.strip().lower()
        if clean in existing_wiki:
            continue

        # Check with path prefixes stripped
        found = False
        for prefix in ['concepts/', 'entities/', 'sources/', '']:
            c = clean
            if c.startswith(prefix.lower()):
                c = c[len(prefix):]
            if c in existing_wiki:
                found = True
                break
        if found:
            continue

        # ── Case C: Cross-vault link (e.g. [[Trading/Watchlist]]) ──
        for prefix in ['', 'Trading/', 'hermes/', 'Geldverdienen/',
                       'boerse/', 'Clippings/', 'Projekte/', 'Lernen/',
                       'Exil/', 'Garten/', 'Reisen/', 'Sport/', 'Rezepte/',
                       'Stuff/', 'Mindset/', 'Personen/']:
            check = f"{prefix}{clean}"
            if check.lower() in all_files:
                found = True
                break
        if found:
            continue

        broken.append((wf_rel, m.group(0), target))

print(f"BROKEN_LINKS_COUNT: {len(broken)}")
for wf, link, t in broken:
    print(f"  BROKEN: {wf} | {link} | target={t}")

# ── Orphan Detection ──
import datetime
now = datetime.datetime.now()
thirty_days_ago = now - datetime.timedelta(days=30)

wiki_texts = ""
for wf in wiki_files:
    wiki_texts += open(wf).read() + "\n"

orphan_dirs = ['Geldverdienen', 'boerse', 'hermes', 'Trading',
               'Clippings', 'raw', 'Projekte/MarineIT']
orphans = []
for od in orphan_dirs:
    od_path = os.path.join(VAULT, od)
    if not os.path.isdir(od_path):
        continue
    for root, dirs, files in os.walk(od_path):
        if '.obsidian' in root or 'Buecher' in root or 'Bücher' in root:
            continue
        for f in files:
            if not f.endswith('.md'):
                continue
            fpath = os.path.join(root, f)
            mtime = os.path.getmtime(fpath)
            age = (now - datetime.datetime.fromtimestamp(mtime)).days
            if age <= 30:
                continue
            rel = os.path.relpath(fpath, VAULT)
            fname = os.path.splitext(f)[0]

            # Check if any wiki page links to this file
            linked = False
            for pat in [f'[[{fname}]]', f'[[{fname}|',
                        f'[[../../{rel}]]', f'[[../../{rel}|',
                        f'[[{rel}]]', f'[[{rel}|']:
                if pat in wiki_texts:
                    linked = True
                    break
            if not linked:
                orphans.append((rel, age))

print(f"\nORPHAN_COUNT: {len(orphans)}")
for opath, age in orphans[:20]:
    print(f"  ORPHAN: {opath} (age={age}d)")