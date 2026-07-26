#!/usr/bin/env python3
"""
Broken Link Detection Script for Vault Self-Write Health Cron.

Verwendet im vault-self-write-health Cron (Sa 03:00).
Erkennt echte Broken Links unter Berücksichtigung aller Noise-Patterns.

Installation:
    cp broken-link-detection.py ~/.hermes/scripts/

Usage:
    python3 ~/.hermes/scripts/broken-link-detection.py /pfad/zum/vault

Siehe `obsidian` Skill ("Health Check" section) für die vollständige
Methodik der Noise-Filterung.
"""

import os, re, sys
from datetime import datetime, timedelta

VAULT = sys.argv[1] if len(sys.argv) > 1 else "/root/obsidian-vault"

# --- Index aller .md Dateien ---
all_md_names = {}
for root, dirs, files in os.walk(VAULT):
    if '.obsidian' in root or 'Projekte/Buecher' in root:
        continue
    for f in files:
        if not f.endswith('.md'):
            continue
        fpath = os.path.join(root, f)
        name_noext = f[:-3]
        all_md_names[name_noext.lower()] = fpath
        rel = os.path.relpath(fpath, VAULT)
        parts = rel.split('/')
        for i in range(1, len(parts)):
            partial = '/'.join(parts[i:])
            all_md_names[partial.lower()] = fpath

# --- Wiki-Dateien sammeln ---
wiki_files = []
for root, dirs, files in os.walk(os.path.join(VAULT, 'wiki')):
    for f in files:
        if f.endswith('.md') and not f.startswith('.'):
            wiki_files.append(os.path.join(root, f))
for fname in ['index.md', 'log.md']:
    fpath = os.path.join(VAULT, fname)
    if os.path.exists(fpath):
        wiki_files.append(fpath)

# --- Noise-Patterns ---
NOISE_PREFIXES = {
    'wiki', 'wiki/concepts', 'wiki/entities', 'wiki/sources', 'wiki/index',
    'wiki/trading-index', 'wiki/concepts/index', 'wiki/entities/index',
    'wiki/sources/index', 'concepts', 'entities', 'sources',
    'wiki/tasks', 'wiki/reports', 'wiki/ideas'
}

KNOWN_FOLDERS = {
    '00-CAPTURE', 'Clippings', 'Exil', 'Garten', 'Geldverdienen', 'Inbox',
    'Lernen', 'Mindset', 'Personen', 'Projekte', 'Reisen', 'Rezepte', 'Sport',
    'Stuff', 'System', 'Tools', 'Trading', 'Uhren', 'YouTube', 'boerse', 'hermes',
    'raw', 'wiki', 'Haus', 'Gemeinnütziger Verein'
}

MANUSCRIPT_PREFIXES = (
    'Kapitel_', 'KAPITEL_', 'Verleger', 'LEKTORATS', 'Keltenstein__',
    'KELTENSTEIN__', 'Bible_Version', 'Bernstein-Kern', 'Bevor_wir_zum_Cover',
    'Buchprojekte_', 'Bruder_Columban', 'Jarl_', 'Eirik_', 'Der_Stein',
    'Der_Nebel', 'Der_Grenzstein', 'Das_Zittern', 'Das_Summen', 'Whispwood',
    'Versailles', 'Toledo_', 'Salem_', 'Prag_1598', 'London_1888', 'title_',
    'MICRO-INSTRIKTIONEN', '1Kapitel', 'DER_RISS', 'Inhalt_von_prompt',
    'Hier_ist_eine_Zusammenfassung', 'created_', 'Cowboy_Butter_Chicken',
    'Hähnchen-Pasta', 'Protein_Ofen', 'Mein_Garten', 'Vollständiges_Transkript',
    'Änderungsprotokoll', 'Revisionsstatus', 'Klappentext', 'Inhaltsabriss',
    'Schreibregeln', 'Analyse_und_Empfehlungen'
)

WIKI_SUBDIRS = {'entities/', 'concepts/', 'sources/', 'tasks/', 'reports/', 'ideas/'}

link_pattern = re.compile(r'\[\[([^\[\]]+?)(?:\|([^\[\]]*?))?\]\]')

broken_links = []
for fpath in wiki_files:
    rel = os.path.relpath(fpath, VAULT)
    fname_noext = os.path.splitext(os.path.basename(fpath))[0]
    fdir = os.path.dirname(fpath)
    try:
        content = open(fpath, 'r', errors='ignore').read()
    except:
        continue
    for match in link_pattern.finditer(content):
        target = match.group(1).strip()
        target_clean = target.replace('.md', '').strip()
        # 1. Noise-Prefix
        if target_clean.lower() in {p.lower() for p in NOISE_PREFIXES}:
            continue
        # 2. Self-Link
        if target_clean == fname_noext:
            continue
        # 3. Trailing Backslash
        if '\\\\' in target:
            broken_links.append((rel, target, "Trailing backslash"))
            continue
        # 4. Double .md.md
        if '.md.md' in target:
            broken_links.append((rel, target, "Double .md extension"))
            continue
        # 5. Relative Pfade (../../ oder ./)
        if target.startswith('../') or target.startswith('./'):
            resolved = os.path.normpath(os.path.join(fdir, target))
            if not resolved.endswith('.md'):
                resolved += '.md'
            if not os.path.exists(resolved):
                broken_links.append((rel, target, "Relative path not found"))
            continue
        # 6. wiki/-Subdir-Prefix (entities/, concepts/, etc.)
        found = False
        for prefix in WIKI_SUBDIRS:
            if target_clean.startswith(prefix):
                candidate = os.path.join(VAULT, 'wiki', target_clean + '.md')
                if not os.path.exists(candidate) and not os.path.exists(os.path.join(VAULT, 'wiki', target_clean)):
                    broken_links.append((rel, target, f"Path not found in wiki/"))
                found = True
                break
        if found:
            continue
        # 7. Wiki-Concept/Entity/Source per Name-Match
        for prefix in ['wiki/concepts/', 'wiki/entities/', 'wiki/sources/']:
            if os.path.exists(os.path.join(VAULT, prefix + target_clean + '.md')):
                found = True
                break
        if found:
            continue
        # 8. Vault-root-relative
        if os.path.exists(os.path.join(VAULT, target_clean + '.md')):
            continue
        # 9. Name-Match
        if target_clean.lower() in all_md_names:
            continue
        # 10. Known Folder, Twitter Handle, Manuscript
        if target_clean in KNOWN_FOLDERS:
            continue
        if target_clean.startswith('@'):
            continue
        if target_clean.startswith(MANUSCRIPT_PREFIXES):
            continue
        # 11. Vault-root-relative mit bekanntem Ordner-Prefix
        first_part = target_clean.split('/')[0]
        if first_part in KNOWN_FOLDERS:
            candidate = os.path.join(VAULT, target_clean + '.md')
            if not os.path.exists(candidate):
                stripped = target_clean.split('/')[-1] if '/' in target_clean else target_clean
                if stripped.lower() in all_md_names:
                    continue
                broken_links.append((rel, target, "Vault-root path not found"))
            continue
        # 12. Echter Broken Link
        broken_links.append((rel, target, "No matching wiki page or vault file"))

# Deduplicate
seen = set()
unique_broken = []
for rel, tgt, reason in broken_links:
    key = f"{rel}|{tgt}"
    if key not in seen:
        seen.add(key)
        unique_broken.append((rel, tgt, reason))

print(f"Scanned {len(wiki_files)} wiki files")
print(f"Broken links: {len(unique_broken)}")
for rel, tgt, reason in unique_broken:
    print(f"  {rel} -> [[{tgt}]] — {reason}")