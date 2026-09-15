---
name: recipe-cookbook-ebook
description: "Turn Obsidian recipe clippings into a Keto cookbook PDF."
category: productivity
---

# Recipe Cookbook & Macro E-Book

Build a sellable recipe cookbook / nutrition E-Book as a **direct-headless
PDF** from Obsidian recipe clippings. Stands on its own: no LibreOffice, no
python-docx needed (reportlab only), Mac transportable. This is a distinct
class of task from plain document creation (`pdf`/`docx` bundled skills
can't compute macros or parse recipe YAML for you).

## When to Use

- "Mach mir ein Keto-/Low-Carb-Kochbuch E-Book"
- Any "recipe collection → digital product (E-Book/PDF)" request
- Adding a macro/nutrition table to a recipe collection
- Extending an existing cookbook (new recipes, low-carb variants, layout)

## Source Layout (Obsidian)

Recipes live as `.md` clippings, typically `Clippings/Rezepte/*.md`. Each has:
- YAML frontmatter: `titel`, `kochzeit`, `portionen`, `quelle`, `tags`
- `## Zutaten` bullet list (ingredients + amounts, German units)
- `## Zubereitung` (often empty — don't fabricate steps)

Extract all recipes into one structured JSON (`/tmp/rezepte_raw.json`):
read title/kochzeit/portionen from frontmatter; split body into `zutaten` (
strip bullets, `**bold**`, `[[wikilinks]]`) and `zubereitung` (skip `|`table
rows and `[`-prefixed noise).

## Macro Computation (core technique)

Build a **per-100g (or per-unit) nutrition DB** mapping normalized ingredient
keys → `(kcal, protein g, fett g, net-carbs g)`. See
`references/ingredient-macro-db.md` for the seed dataset.

Parsing an ingredient line → `(grams_estimate, match_key)`:
1. **Amount extraction** in priority order:
   - `(\d+)\s*g` → grams directly
   - `(\d+)\s*ml` → grams (*1.0 for liquids)
   - `(\d+)\s*Stück/Stk/St.` → per-item count; weight depends on the food
     (egg ~55g, avocado ~140g, onion ~110g, paprika ~120g, tomato ~90g,
     carrot ~70g, garlic clove ~5g, lemon ~70g, broccolini ~150g)
   - `(\d+)\s*Dosen` → tuna can ~150g
   - Handvoll/Bund ~30–60g; EL(tbsp)=15g; TL(tsp)=5g; Tasse/cup ~150g generic
   - Packung ~200g; Becher ~150g
2. **Ingredient matching**: normalize the string (lowercase, `-`→space,
   umlauts ä→ae ö→oe ü→ue ß→ss, AND strip accents é→e etc. via
   `unicodedata.normalize('NFD')` + drop combining chars — otherwise
   "Crème fraîche" never matches "creme fraiche"). Then check a prioritized
   substring order list (most specific first, e.g. `rinderhack 5% fett`
   before `rinderhack`).
3. **Ignore negligible lines**: any ingredient containing
   `nach Geschmack`, `nach Belieben`, `nach Wahl`, `Prise/Priese`, `etwas`,
   `optional`, `individuell`, `zum Braten`, `zum Servieren` → macros ≈ 0,
   skip (they're seasoning/grains-of-salt level).

Compute per recipe: sum `kcal/protein/fett/netcars` across matched
ingredients. Round. This gives total-per-recipe; note portion-dependence.

## Honest Keto Categorization (important)

Do NOT label every "High-Protein" recipe as keto. Categorize by net-carbs:
- `KETO/LOW-CARB`: net-carbs ≤ 12 g
- `MODERAT`: 12–20 g
- `HIGH-CARB`: > 20 g (Pasta, potatoes, sweet potato, buckwheat, oats)

Martin's real cluster is ~15/35 keto — many sister recipes are High-Protein
but carb-heavy. **Surface this honestly in the E-Book** (category column) and
offer (don't force) low-carb substitutions for the HIGH-CARB carbs. This is
what makes the product credible vs. generic AI-recycled cookbooks.

## Drop the placeholder

Skip any recipe whose title is `Keine Rezept-Informationen gefunden` or that
has zero `zutaten`.

## PDF Generation (headless, reportlab only)

No LibreOffice/`soffice`, no `python-docx` in this environment — but directly
rendering with reportlab platypus works and is fully headless:

```python
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
    TableStyle, PageBreak, ListFlowable, ListItem, KeepTogether)
```

Structure: cover → intro (honest "macro values are estimates" disclaimer) →
16:8 plan → macro summary table → per-recipe pages (grouped by category,
each `KeepTogether` so a recipe doesn't split) → notes page. Use
`Paragraph` for rich text (escape `&` → `&amp;`), `Table` for the macro
summary + meal plan, color-coded category tags.

Verify with pypdf: render, then `PdfReader(...)` → check page count, title
metadata, and that expected recipe names / category counts appear in the
extracted text.

## Pitfalls

- **Accents/umlauts kill matching** — "Crème fraîche", "Rinderbrühe" need
  full NFD normalization in the matcher, not just umlaut→ae.
- **Key ordering** — most-specific substring keys first; "all-purpose flour"
  becomes "all purpose flour" after `-`→space, so match both variants.
- **Empty / table-backed recipes** — many clippings have no `Zubereitung`;
  never invent steps. Recipes with no quantities (plain "Gurke", "Salat")
  yield 0 kcal — fix by adding sane default grams or mark them as
  "Portionsangabe fehlt", don't fabricate exact numbers.
- **KeepTogether** prevents a recipe's list spilling across a page break.
- Include an explicit disclaimer that macros are BLS/USDA estimates, not
  lab-verified — required for a sellable product.

## Deliverable

Write the PDF to the vault for linkage: `Clippings/Rezepte/<Titel>.pdf` and
a copy at the workspace root for direct delivery. Update the cluster/MOC and
Digital-Product MOC with a "E-Book V1 ✅" progress note + link. Confirm the
file compiles and link resolves before reporting done.