# Content-Cluster → Digital-Product-Ideen (Vault als Produkt-Inventar)

Ergänzung zur Micro-SaaS-/Side-Hustle-Ideen-Pipeline: NicHt nur externer
Pain-Scan (Slots A/B/C), sondern auch der umgekehrte Weg — bestehenden
Vault-Inhalt (gesammelte Clippings/Rezepte/Guides/Konzepte) als
Monetarisierungs-Inventar lesen und in konkrete Digital-Products übersetzen.
Erprobt 14.09.2026 am Keto/Low-Carb-Cluster.

## Wann dieser Workflow statt des Pain-Scans

- Der User hat bereits eine inhaltliche Materialsammlung im Vault (z.B. 36
  Rezepte, Shopping-Guides, Speiseplan) — das ist das Produkt-Inventar.
- Die Frage ist "was kann ich daraus verkaufen?" statt "welchen Pain findet man".
- Produktform ist Digital (E-Book, Cheat-Sheet, Template, Mini-Kurs) — kein
  physischer Artikel, kein SaaS-Build nötig.

## Ablauf

1. **Asset-Lage erheben:** Was liegt schon vor (Rezepte, Guides, Speiseplan,
   Wiki-Konzepte)? Das ist das Inventar. `find` über Clippings/, Rezepte/,
   YouTube/Transkripte/, wiki/concepts/ — nicht nur einen Ordner.

2. **Digital-Product-Ideas-MOC** (unter `wiki/ideas/<Thema> MOC.md`):
   - Frontmatter `type: idea`.
   - **Asset-Lage** zuerst (Inventar-Liste).
   - **Tier-1/2/3** nach Aufwand/Monetarisierung:
     - Tier-1 = sofort druckbar: Cheat-Sheet (~€5), E-Book (~€9–15), Template
       (~€15). Testet Zielgruppe, baut E-Mail-Liste.
     - Tier-2 = Mini-Kurs / kleine App (~20–30h).
     - Tier-3 = Reichweiten-/Social-Pipeline (Faceless-Charts).
   - **Eskalations-Leiter:** billigster/schnellster Test zuerst → E-Mail-Liste →
     höherwertiges Produkt.

## Monetarisierungs-Pushback (wichtig, aus 14.09.)

- **Amazon KDP/Merch sind in Martins Mission Map PAUSIERT.** Nicht reflexartig
  KDP-Reaktivierung vorschlagen. Für kleines Digital-Product: **Gumroad/Payhip +
  E-Mail-Liste** (bessere Marge, kein Inventar, passt zur Faceless-Reichweiten-
  Strategie). Das ist ein begründeter Vorschlag, kein Ja-Sager.
- **Faceless-Standard** (konsistent mit dataviz-story-scout): statische Charts,
  1 Insight, 1 Caption, kein Creator-Gesicht, kein Voiceover.
- **Kontext-Präzision:** Nicht mit Pain-Scan/Vault-MOC vermischen — getrennte
  Dokumente.

## Verifikation

Broken-Link-Check der neuen Idea-MOC gegen den Vault (Auflösung für 2-Ebenen-
Tiefe `wiki/ideas/` und `wiki/concepts/`):

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
            p=os.path.join(vault,target)
            if not os.path.exists(p): missing.append(l)
        elif target.endswith('.md'):
            p=os.path.normpath(os.path.join(base,target))
            if not os.path.exists(p): missing.append(l)
        else:
            for sub in ['wiki/concepts','wiki/entities','wiki/ideas']:
                if os.path.exists(f'{vault}/{sub}/{target}.md'): break
            else: missing.append(l)
    print(name, 'Broken:', missing if missing else 'KEINE')
```

Kriterium: keine Broken Links (Selbst-Links = legitime Navigation). Erst dann
melden.

## Beispiel

`wiki/ideas/Ernährung Digital-Product MOC.md` (14.09.2026): 6 Ideen aus dem
Keto/Low-Carb-Cluster in 3 Tiers — Einkaufsliste-Cheat-Sheet → Meal-Prep-
Notion-Template → Kochbuch-E-Book → Mini-Kurs + Faceless-Social-Tier-3.
