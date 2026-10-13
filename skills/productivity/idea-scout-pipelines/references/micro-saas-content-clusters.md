# Content-Cluster → Digital-Product-Ideen (Vault als Produkt-Inventar)

Der umgekehrte Weg zum Pain-Scan: bestehenden Vault-Inhalt (Clippings/Rezepte/Guides/
Konzepte) als Monetarisierungs-Inventar lesen und in Digital-Products übersetzen.
Erprobt am Keto/Low-Carb-Cluster (36 Rezepte, Shopping-Guides, Speiseplan).

## Wann dieser Workflow statt des Pain-Scans

- Der User hat schon eine Materialsammlung im Vault — das ist das Produkt-Inventar.
- Frage ist "was kann ich daraus verkaufen?" statt "welchen Pain findet man".
- Produktform ist Digital (E-Book, Cheat-Sheet, Template, Mini-Kurs) — kein SaaS-Build.

## Ablauf

1. **Asset-Lage erheben:** `find` über Clippings/, Rezepte/, YouTube/Transkripte/,
   wiki/concepts/ — nicht nur einen Ordner.
2. **Digital-Product-Ideas-MOC** unter `wiki/ideas/<Thema> MOC.md`, Frontmatter `type: idea`:
   - **Asset-Lage** zuerst (Inventar-Liste).
   - **Tier-1** sofort druckbar: Cheat-Sheet ~€5, E-Book ~€9–15, Template ~€15 (testet
     Zielgruppe, baut E-Mail-Liste). **Tier-2** Mini-Kurs/kleine App (~20–30h). **Tier-3**
     Reichweiten-/Social-Pipeline (Faceless-Charts).
   - **Eskalations-Leiter:** billigster/schnellster Test zuerst → E-Mail-Liste → höherwertiges
     Produkt.

## Monetarisierungs-Pushback (wichtig)

- **Amazon KDP/Merch sind in Martins Mission Map PAUSIERT** — nicht reflexartig KDP
  reaktivieren. Für kleines Digital-Product: **Gumroad/Payhip + E-Mail-Liste** (bessere
  Marge, kein Inventar, passt zur Faceless-Reichweiten-Strategie).
- **Faceless-Standard** (konsistent mit dem DataViz-Scout): statische Charts, 1 Insight,
  1 Caption, kein Gesicht, kein Voiceover.
- Nicht mit Pain-Scan/Vault-MOC vermischen — getrennte Dokumente.

## Verifikation — Broken-Link-Check der Idea-MOC

```python
import re, os
vault='/root/obsidian-vault'
for name in ['wiki/ideas/<Thema>.md']:
    txt=open(f'{vault}/{name}').read()
    links=re.findall(r'\[\[([^\]]+)\]\]', txt)
    base=os.path.dirname(f'{vault}/{name}')
    missing=[]
    for l in links:
        target=l.split('|')[0].strip()
        if target.startswith('wiki/'):
            if not os.path.exists(os.path.join(vault,target)): missing.append(l)
        elif target.endswith('.md'):
            if not os.path.exists(os.path.normpath(os.path.join(base,target))): missing.append(l)
        else:
            for sub in ['wiki/concepts','wiki/entities','wiki/ideas']:
                if os.path.exists(f'{vault}/{sub}/{target}.md'): break
            else: missing.append(l)
    print(name, 'Broken:', missing if missing else 'KEINE')
```

Kriterium: keine Broken Links (Selbst-Links = legitime Navigation), erst dann melden.

**Beispiel:** `wiki/ideas/Ernährung Digital-Product MOC.md` — 6 Ideen aus dem Keto-Cluster
in 3 Tiers: Einkaufslisten-Cheat-Sheet → Meal-Prep-Notion-Template → Kochbuch-E-Book →
Mini-Kurs + Faceless-Social-Tier-3.
