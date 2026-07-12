#!/usr/bin/env python3
"""
Vault Self-Write: Broken Link Detection Script (embedded in terminal)
=======================================================
Usage: python3 broken-link-detection-script.py
Run from vault root (/root/obsidian-vault/).

Scans wiki/ concepts, entities, sources, trading-index, and index
for [[wikilinks]], resolves them, and reports broken ones with
noise-filtering for navigational self-references.

v2026-07-04 — Added: trailing-backslash detection, .md.md detection,
              ./ prefix handling, improved self-link matching with
              wiki/concepts/ prefix.
v2026-07-11 — Confirmed: vault-root-relative links handled correctly by CASE C.
"""

import re, os, glob, datetime

VAULT = "/root/obsidian-vault"

# ── Step 1: Build set of all existing wiki page names (lowercase) ──
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

# ── Step 3: Collect all wiki files to scan ──
wiki_files = (glob.glob(f"{VAULT}/wiki/concepts/*.md")
              + glob.glob(f"{VAULT}/wiki/entities/*.md")
              + glob.glob(f"{VAULT}/wiki/sources/*.md")
              + [f"{VAULT}/wiki/trading-index.md",
                 f"{VAULT}/wiki/index.md"])

NOISE = {'wiki', 'wiki/', 'wiki/concepts', 'wiki/entities',
         'wiki/sources', 'wiki/index', 'wiki/ideas'}

def strip_path_prefix(target):
    """Remove wiki/concepts/, wiki/entities/, wiki/sources/, wiki/, ./ from a target."""
    t = target
    for pfx in ['wiki/concepts/', 'wiki/entities/', 'wiki/sources/', 'wiki/']:
        if t.startswith(pfx):
            return t[len(pfx):]
    if t.startswith('./'):
        return t[2:]
    return t

def is_broken_trailing_backslash(target):
    """Detect [[Exil-Polen\\|Polen]] — escaped backslash before pipe."""
    return '\\\\' in target

def is_double_md_md(target):
    """Detect [[wiki/concepts/SOUL.md.md]] — double .md extension."""
    return target.rstrip(']').endswith('.md.md')

broken = []
nav_count = 0
for wf in sorted(wiki_files):
    wf_rel = os.path.relpath(wf, VAULT)
    wf_name = os.path.splitext(os.path.basename(wf))[0].lower()
    wf_dir = os.path.dirname(wf)
    content = open(wf).read()
    for m in re.finditer(r'\[\[([^\]]+)\]\]', content):
        raw = m.group(1)
        target = raw.split('|')[0].strip()
        if not target:
            continue

        # ── DETECT: trailing backslash (e.g. [[Exil-Polen\\|Polen]]) ──
        if is_broken_trailing_backslash(target):
            broken.append((wf_rel, m.group(0), target, 'trailing_backslash'))
            continue

        # ── DETECT: double .md.md extension ──
        if is_double_md_md(target):
            broken.append((wf_rel, m.group(0), target, 'double_md_extension'))
            continue

        # ── NOISE FILTER: self-links and navigation ──
        stripped_target = strip_path_prefix(target)
        tl = target.lower().rstrip('/')
        stripped_lower = stripped_target.lower()

        if stripped_lower in NOISE or tl in NOISE:
            nav_count += 1
            continue

        # Self-link: link target matches current file name (after path strip)
        # e.g. [[wiki/concepts/Automation]] in Automation.md
        clean_name = stripped_lower
        if clean_name.endswith('.md'):
            clean_name = clean_name[:-3]
        if clean_name == wf_name:
            nav_count += 1
            continue

        # ── CASE A: ../../ relative path ──
        if target.startswith('../'):
            abs_t = os.path.normpath(os.path.join(wf_dir, target))
            if os.path.exists(abs_t + '.md') or os.path.exists(abs_t):
                continue
            broken.append((wf_rel, m.group(0), target, 'broken_relative_path'))
            continue

        # ── CASE B: Direct wiki page name ──
        clean = clean_name
        if clean in existing_wiki:
            continue

        # Check with subdirectory prefixes stripped
        found = False
        for pfx in ['concepts/', 'entities/', 'sources/', '']:
            c = clean
            if c.startswith(pfx):
                c = c[len(pfx):]
            if c in existing_wiki:
                found = True
                break
        if found:
            continue

        # ── CASE C: Cross-vault link (e.g. [[Trading/Watchlist]]) ──
        vault_prefixes = ['', 'Trading/', 'hermes/', 'Geldverdienen/',
                          'boerse/', 'Clippings/', 'Projekte/', 'Lernen/',
                          'Exil/', 'Garten/', 'Reisen/', 'Sport/', 'Rezepte/',
                          'Stuff/', 'Mindset/', 'Personen/', 'Uhren/',
                          'YouTube/', 'Inbox/', 'raw/', '00-CAPTURE/']
        for pfx in vault_prefixes:
            check = f"{pfx}{clean}"
            if check.lower() in all_files:
                found = True
                break
            # also try with .md
            if (check + '.md').lower() in all_files:
                found = True
                break
        if found:
            continue

        broken.append((wf_rel, m.group(0), target, 'missing_wiki_page'))

# ── REPORT ──
print(f"BROKEN_LINKS_COUNT: {len(broken)}  (nav_noise={nav_count})")
for wf, link, t, reason in sorted(broken):
    print(f"  {reason}: {wf} | {link}")


# ══════════════════════════════════════════════════════════════════════
# ORPHAN DETECTION
# ══════════════════════════════════════════════════════════════════════
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
for opath, age in sorted(orphans)[:20]:
    print(f"  ORPHAN: {opath} (age={age}d)")