# Ingredient Macro Database (seed)

Per-100 g (or per unit, noted) German-language macro values used for the
cookbook. Tuple = `(kcal, protein g, fett g, net-carbs g)`. These are
BLS/USDA standard estimates — label the product's macros as estimates, not
lab-verified. Net-carbs = total carbs minus fiber.

## Reference patterns

- German units: `g`, `ml`, `Stück/Stk/St.` (per item), `EL`(=tbsp, ~15g),
  `TL`(=tsp, ~5g), `Tasse/cup` (~150g generic), `Dose` (tuna ~150g),
  `Handvoll/Bund` (~30–60g), `Packung` (~200g), `Becher` (~150g).
- English fallback: tbsp=15g, tsp=5g, cup=150g, crack open early.
- Per-item weights: egg ~55g, avocado ~140g, onion ~110g, paprika ~120g,
  tomato ~90g (not cherry/passierte/gehackt), carrot ~70g, garlic clove
  ~5g, lemon ~70g, broccolini ~150g.

## Meat / Fish / Protein

| key | kcal | P | F | NC |
|---|---|---|---|---|
| rinderhack | 250 | 26.6 | 15.4 | 0 |
| rinderhack 5% fett | 160 | 21 | 5 | 0 |
| light hackfleisch | 148 | 21 | 7 | 0 |
| mageres rinderhack | 160 | 21.4 | 7.6 | 0 |
| rindergulasch | 137 | 20.9 | 5.5 | 0 |
| haehnchenbrust / filet / fleisch | 116–120 | 22.6–23.1 | 1.2–1.9 | 0 |
| haehnchenoberschenkel-filets | 172 | 20 | 10 | 0 |
| putenschinken | 105 | 18 | 3 | 1 |
| thunfisch | 184 | 28 | 7.3 | 0 |
| lachs | 208 | 20 | 13 | 0 |
| sardinen in olivenoel | 190 | 22 | 10 | 0 |

## Eggs / Dairy

| key | kcal | P | F | NC |
|---|---|---|---|---|
| ei (per piece) | 65 | 5.8 | 4.3 | 0.4 |
| eier (per 100g) | 155 | 13 | 11 | 1.1 |
| magerquark / magertopfen | 72 | 13.5 | 0.3 | 4 |
| skyr | 66 | 11 | 0.2 | 4 |
| griechischer joghurt | 110 | 8 | 7 | 4 |
| naturjoghurt | 61 | 3.5 | 3 | 4.5 |
| joghurt / joghurt 1,5% | 61 | 4.6 | 1.5 | 5 |
| protein-vanillejoghurt | 90 | 10 | 2 | 6 |
| cottage cheese / huettenkaese | 98 | 11 | 4.3 | 3.4 |
| milch / milch 1,5% | 47 | 3.3–3.4 | 1.5 | 4.8 |
| mandelmilch | 28 | 0.6 | 2 | 2 |
| kokosmilch light | 60 | 0.8 | 4.5 | 4 |
| sahne | 292 | 2 | 30 | 3 |
| sauerrahm / creme fraiche | 170 | 2.8 | 16 | 3 |
| schafsjoghurt | 90 | 4 | 6 | 4 |
| alpro light sahne | 60 | 2 | 4 | 4 |

## Cheese

| key | kcal | P | F | NC |
|---|---|---|---|---|
| harzer kase/kaese | 120 | 28 | 0.5 | 1 |
| kaese (generic) | 380 | 24 | 30 | 2 |
| light streukaese | 300 | 22 | 22 | 2 |
| geriebener mozzarella | 250 | 18 | 19 | 3 |
| feta | 265 | 14.2 | 21 | 4 |
| parmesan | 420 | 35 | 29 | 3.4 |

## Vegetables (net-carbs)

| key | kcal | P | F | NC |
|---|---|---|---|---|
| spitzkohl | 28 | 2.8 | 0.2 | 4.1 |
| wirsingkohl | 35 | 3.3 | 0.6 | 3.6 |
| weisskohl | 25 | 1.3 | 0.1 | 4 |
| rotkohl | 31 | 1.4 | 0.2 | 4.5 |
| broccoli / broccolini | 34–35 | 2.8–2.9 | 0.4 | 4 |
| spargel | 20 | 2.2 | 0.1 | 1.8 |
| sauerkraut | 15 | 1 | 0.2 | 2 |
| kartoffel(n) | 77 | 2 | 0.1 | 15.9 |
| suesskartoffel | 104 | 1.6 | 0.1 | 17 |
| tomate | 18 | 0.9 | 0.2 | 2.2 |
| cherrytomaten | 18 | 0.9 | 0.2 | 2.2 |
| passierte/gehackte tomaten | 24 | 1.2 | 0.2 | 3.5 |
| tomatenmark | 82 | 4.4 | 0.5 | 14 |
| gurke / persian cucumbers | 15 | 0.7 | 0.1 | 2.5 |
| paprika | 26 | 1 | 0.3 | 4 |
| zwiebel(n) / red onion / onion | 40 | 1.1 | 0.1 | 6–7 |
| knoblauch / garlic | 149 | 6.4 | 0.5 | 28 (5g/clove) |
| spinat | 23 | 2.9 | 0.4 | 1 |
| avocado | 160 | 2 | 15 | 2 |
| fruhlings-/lauchzwiebeln, jungzwiebel | 32 | 1.8 | 0.2 | 5 |
| karotte(n) | 41 | 0.9 | 0.2 | 7 |
| mais | 86 | 3.2 | 1.2 | 16.5 |
| kidneybohnen | 127 | 9 | 0.5 | 27 |
| champignons | 22 | 3.1 | 0.3 | 1.5 |
| rucola | 25 | 2.6 | 0.7 | 1.4 |
| salat | 15 | 1.4 | 0.2 | 1.1 |

## Fruit / Nuts / Seeds / Fats

| key | kcal | P | F | NC |
|---|---|---|---|---|
| medjool-datteln | 280 | 2 | 0.1 | 62 |
| beeren / himbeeren | 52–57 | 0.7–1.2 | 0.3–0.7 | 5–9 |
| zitrone | 29 | 1.1 | 0.3 | 6 |
| limette | 30 | 0.7 | 0.2 | 5 |
| chiasamen | 486 | 17 | 31 | 6 |
| erdnuss | 567 | 26 | 49 | 11 |
| erdnussbutter | 588 | 25 | 50 | 15 |
| leinsamen | 536 | 18 | 42 | 1 |
| walnuesse | 654 | 15 | 65 | 7 |
| sesamsamen | 573 | 18 | 50 | 7 |
| olivenoel / oel / sesamoel / chiliol | 884 | 0 | 100 | 0 |
| butter / gesalzene butter | 717 | 0.9 | 81 | 0.1 |

## Carbs-Carriers & Misc

| key | kcal | P | F | NC |
|---|---|---|---|---|
| pasta | 370 | 13 | 1.5 | 68 |
| buchweizen / buchweizenmehl | 340–343 | 13–13.3 | 3.1–3.4 | 60–61 |
| haferflocken / hafermehl | 363–371 | 12.4–13.5 | 6.8–7 | 58–62 |
| dinkelmehl | 346 | 10.9 | 1.7 | 66 |
| mehl / all-purpose flour | 364 | 10.3 | 1 | 73 |
| proteinpulver | 380 | 70 | 6 | 8 |
| speisestaerke | 370 | 0.6 | 0.1 | 91 |
| panko mehl | 355 | 13 | 5 | 64 |
| wrap (generic) / wraps-tortilla | 290 | 9 | 8 | 42 |
| protein wraps | 180 | 30 | 7 | 15 |
| tortilla-chip | 500 | 6 | 24 | 62 |
| reis | 130 | 2.7 | 0.3 | 28 |
| honig | 304 | 0.3 | 0 | 82 |
| ahornsirup | 260 | 0 | 0 | 67 |
| zucker | 400 | 0 | 0 | 100 |
| kakaopulver | 228 | 20 | 14 | 10 |
| essiggurken | 15 | 0.4 | 0.1 | 2 |
| schokodrops | 530 | 5 | 30 | 60 |
| gochujang | 130 | 4 | 2 | 25 |

## Sauces / Seasonings (negligible-to-low; ~0 if `nach Geschmack`)

| key | kcal | P | F | NC |
|---|---|---|---|---|
| sojasauce / tamari | 53–56 | 8–10 | 0.1 | 5–7 |
| worcestershiresauce | 110 | 0 | 0 | 27 |
| huehner-/rinder-/gemuesebruehe | 2–4 | 0.3–0.5 | 0 | 0.2–0.3 |
| curry paste | 90 | 2 | 3 | 14 |
| ingwer | 80 | 1.8 | 0.8 | 15 |
| dijonsenf / senf | 60–66 | 3.5–4.4 | 3–3.3 | 5 |
| balsamico | 88 | 0.7 | 0 | 17 |
| peri-peri-sauce / -gewuerz | 90–250 | 1–10 | 5–8 | 8–35 |
| light curry ketchup | 70 | 1.5 | 0.5 | 15 |
| fischsauce | 35 | 5 | 0 | 4 |
| dill / petersilie / koriander / schnittlauch | 23–43 | 2.1–3.3 | 0.5–1.1 | 1–5 |
| zimt | 247 | 4 | 1.2 | 27 |
| salz / kosher salt | 0 | 0 | 0 | 0 |
| pfeffer / black pepper | 251 | 10 | 3 | 38 |
| chiliflocken / chilipulver / cayenne | 280–318 | 12–14 | 14–17 | 30 |
| paprikapulver | 282 | 14 | 13 | 35 |
