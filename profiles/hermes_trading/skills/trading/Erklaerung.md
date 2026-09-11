# Änderungshistorie — Trading Skill

**Stand:** Paketen A–D + Sprints 1–7 + Bugfix-Sprint + Screener-Source + Watchlist-Performance-Fix + Rollen-Sprint R1–R4 + **Turtle-Konfluenz-Sprint** + **Phase 1+2 Fix (09.08.2026)** + **Watchlist-Cleanup-Archivierung (09.08.2026)** + **UK-Microcap-Gate (14.08.2026)** + **DQ-Isolation + Alarm-Crons (16.08.2026)** + **Drawdown-15-25-Zone auf 6 Pos (17.08.2026)** + **DQ-.L-Aufräumung im Cleanup + täglicher Cleanup (19.08.2026)** + **DQ-Deaktivierungs-Verifikation + Cleanup 1c (24.08.2026)** + **DQ-Root-Clause-Fix: keine Reaktivierung gedroppter .L + Dry-Run read-only (26.08.2026)** + **Selection Momentum-/Liquiditäts-Gate (27.08.2026)** + **Drawdown-Heilungs-Beschleunigung 15-25%: Size 65% + Conf 75% (01.09.2026)** + **Grok entfernt, twitterapi.io Standard (01.09.2026)** + **Alternative Momentum-Swing-Strategie dokumentiert (06.09.2026)** + **Volume-Backtest: NICHT übernommen (06.09.2026)** + **Sektor-abhängige Regime (07.09.2026)** + **Overlay-Bug Fix (07.09.2026)** + **Analyse-Sprint: 7 Defekte behoben (08.09.2026)** + **Messbarkeit: Gates, Quellen-Taxonomie, Beneficiary-Lifecycle, Video-Retry (08.09.2026)** + **Sizing entkoppelt, Momentum-Faktor repariert, Schattenbuecher (08.09.2026)** + **Kanonik-Mirror-Fix (.SG/.MU/ISIN) + Attributions-Oszillation Root-Cause (10.09.2026)**

## 10.09.2026 — Kanonik-Mirror-Fix + Attributions-Oszillation (Vault-Insights-Vorschläge 1–3)

Umgesetzt aus dem vault-insights-daily-Report vom 10.09.2026 (Abschnitt C).
Beide Vorschläge hatten dieselbe Ursache-Klasse: **Spiegel-Listings und
eingefrorene Felder verzerrten Statistiken, ohne dass sich real etwas verschob.**

### Vorschlag 1+3 — `.SG`/`.MU`/ISIN-Spiegel-Ticker als Pseudo-Shorts

**Symptom:** NetApp stand als `NTA.SG` in der Watchlist (Sektor `Other`,
kein `tech_score`), Short-C 82 % > Long-C 77 % → zählte als Bärensignal.
Analog Snowflake (`US8334451098.SG`), Swatch (`UHRN.SG`), Chevron (`CHV.SG`),
XPeng (`8XPA.SG`), Seagate (`IE00BKVD2N49.SG`), MicroStrategy (`MIGA.MU`),
Evercore (`QGJ.MU`).

**Root Cause:** `technical_validator.resolve_ticker()` Schritt 3 (yfinance-Suche)
bevorzugte **explizit** eine DE-Börse:
`if q.get("exchange") in ("GER","XETRA","FRA","STU","MUN"): return q.get("symbol")`.
`STU` = Stuttgart = `.SG`. Damit wurde systematisch das Nebenboersen-Spiegel-
Symbol genommen statt des Primärlistings. Folgen: yfinance liefert für diese
Symbole KEINEN Sektor (→ `Other`) und zu wenig Liquidität/Bars für einen
`tech_score` → die Zeile fiel ohne Filterung als Sentiment-Short in die Statistik.

**Fix:**
1. `technical_validator.resolve_ticker()` — DE-Bevorzugung entfernt; es gilt
   jetzt dieselbe Priorität wie in `company_validator._exchange_priority`
   (US-Primär > `.DE` > Sonstige > `.SG/.MU/.F/.DU/.HM/.BE`). Zusätzlich wird
   das DB-Kanonik-Mapping auf jedes Ergebnis angewendet.
2. **DB-First (kein Hardcode):** 18 neue Regeln in `canonical_tickers`
   (NTA.SG→NTAP, US8334451098.SG→SNOW, UHRN.SG→UHRN.SW, CHV.SG→CVX,
   8XPA.SG→XPEV, IE00BKVD2N49.SG→STX, MIGA.MU→MSTR, QGJ.MU→EVR, NYT.SG→NYT,
   PFE.F→PFE, ISIN-Varianten ohne Suffix …). Seed-Listen in `signal_manager.py`
   und `watchlist_manager.py` mitgezogen (greifen nur bei leerer Tabelle).
3. **Einmal-Migration `scripts/canonicalize_watchlist.py`** (Dry-Run default,
   `--apply` schreibt, `--auto` löst zusätzlich Nebenboersen-Mirror ohne Score
   per yfinance-Namenssuche auf). 9 Zeilen umbenannt, 2 gemerged
   (MIGA.MU→MSTR, YDX.MU→NBIS). Danach `refresh_tech_scores.py`.
   **Guard:** `resolve_primary()` verlangt Namensähnlichkeit ≥ 0.6 und
   Priorität vor Ähnlichkeit — sonst wurde "Contemporary Amperex Technology"
   (CATL) auf `TSM` (TSMC, sim 0.45) bzw. Galaxy Digital auf `0P0.DE` statt
   `GLXY` gemappt. Ergebnis: CATL → `3750.HK` (sim 1.00).
4. Sektoren der neuen Primär-Zeilen aus yfinance nachgezogen (EVR, GLXY, NYT,
   SNOW, STX, UHRN.SW, XPEV waren leer geerbt).
5. `watchlist_cleanup.py` Stufe 1b erweitert: `.L` → auch `.F/.MU/.SG/.DU/.HM/.BE`
   ohne `tech_score` werden auf `dropped` / `notes='no-liquidity-gate'` gesetzt
   (Sicherheitsgurt; verhindert Wiederauferstehung via Resurrection-Guard).
6. Zombie entfernt: `WDI.HM` (Wirecard AG, insolvent seit 2020, 0,015 €,
   aber `tech_score` 0.825) → `dropped`.

**Verifikation:** 0 aktive Nicht-Primär-Ticker im Export; NTAP hat jetzt
`tech_score` 0.85 / Technology, SNOW 0.825, CVX 0.80, DELL 0.85, GTLB 0.875.

### Vorschlag 2 — Attributions-Oszillation (Tag 11): Root Cause gefunden

**Symptom:** Die Quellen-Attribution (Kanal-Zählung über die exportierte
Watchlist) schwankte täglich um ±5–15 pro Quelle, Summe 221 → 302 → 383.

**Root Cause (gemessen, nicht vermutet):** Der Aggregations-UPDATE in
`watchlist_manager.py` schreibt `channels` nur für
`status IN ('watching','dropped')`. **Bought-Zeilen (82 von 110 exportierten
Zeilen = 75 %) behielten damit ihren Kanal-Stand vom KAUFDATUM.**

Reconciliation gegen `watchlist_mentions` (14-Tage-Fenster, `WATCHLIST_DAYS=14`):

| Status | Zeilen | Abweichung gespeichert vs. Live-Fenster |
|---|---|---|
| bought | 82 | **78** |
| watching | 28 | 7 (Alias-Artefakt der Prüfung) |

Beispiele: AAPL hatte 16 Kanäle gespeichert, aber nur 6 im Fenster; CRWD war
seit 04.06. eingefroren (7 statt 3).

**Wirkung:** Die Metrik mischte zwei Zeitbasen — 28 täglich aktualisierte
`watching`-Zeilen + 82 eingefrorene `bought`-Zeilen. Dadurch sprangen die
Tageszählungen, obwohl sich real nichts verschoben hatte. Der Report
protokollierte das seit 11 Tagen als „Oszillation".

**Fix:**
1. `watchlist_manager.py` zieht `channels` auch für `status='bought'` nach —
   **bewusst nur das Attributions-Feld**; Status, Entry-Daten, Conviction und
   `last_seen` bleiben unangetastet (keine Exit-/Reaktivierungslogik kippt).
2. `bought`-Zeilen **ohne** aktuelle Mentions bekommen `channels='[]'`
   (sonst steht der Kaufdatum-Stand für immer in der Statistik; 32 Zeilen).
3. `watchlist.channels`-Normalisierung nutzte `WHERE id=?` — 942 von 1781 Zeilen
   haben `id IS NULL` (Dedup arbeitet mit `rowid`) → griff ins Leere. Jetzt `rowid`.
4. Einmal-Backfill der 78 abweichenden bought-Zeilen.

**Verifikation:** Attributionen 384 → **167**, Mismatch-Zeilen 85 → 7
(verbleibende 7 sind `watching` und ausschließlich ein Alias-Artefakt der
Prüfprozedur, kein Datenfehler). Die Quelle ist jetzt eine **einzige Zeitbasis**.

**Sekundärbefund:** Der Sprung 221 → 302 → 383 ist teilweise auf die
08.09.-Änderung zurückzuführen (Export zeigte vorher nur die Top-3-Kanäle pro
Zeile via `list(set(x))[:3]`, danach die volle Liste). Zahlen vor und nach dem
08.09. sind daher **nicht direkt vergleichbar**.

## 08.09.2026 — Sizing entkoppelt, Momentum-Faktor repariert, Schattenbücher

Dritter Teil des Analyse-Sprints. Adressiert den Verstärker (Sizing) und macht die
Selektionsfrage messbar (Schattenbücher), statt sie zu erraten.

### Sizing — die Conviction bestimmt nicht mehr die Größe

Gegenrechnung auf denselben 84 Trades (`P&L = pnl_pct × Größe`, keine Annahme über
andere Entries):

| Regel | P&L | Median | Max |
|---|---|---|---|
| **IST** (conviction-skaliert) | **−1.196 €** | 997 € | 3.006 € |
| Gleiche Größe 875 € (budgetkonform) | **−148 €** | 875 € | 875 € |
| Gleiches Risiko, Cap 1.200 € | −86 € | 1.200 € | 1.200 € |
| IST, hart auf 1.200 € gedeckelt | −494 € | 997 € | 1.200 € |

**Rund 1.050 der 1.196 € gingen auf die Conviction-Skalierung zurück, nicht auf die
Signalauswahl.** Ursache: die Conviction ist am oberen Ende gegenläufig (Band 1.00 =
29 Trades, WR 34 %, −1.168 €), und `max_position_pct_high` = 20 % setzte dort das
meiste Geld ein. Positionen ≥ 1.800 € (Ø-Conviction 0.95): 25 Trades, WR 24 %,
−1.659 €. Positionen 800–1.200 € (Ø-Conviction 0.87): 25 Trades, WR 52 %, +566 €.

Drei zusammenhängende Änderungen:

1. **Basisgröße für alle.** `max_position_pct` = 0.125 (1/8 des 70 %-Rahmens) als
   einziger Deckel. `max_position_pct_high/_low` bleiben als deprecated stehen und
   werden nicht mehr gelesen. Conviction entscheidet weiterhin, OB ein Trade genommen
   wird und in welcher Reihenfolge (`priority_score`) — nur nicht mehr, wie groß.
2. **`risk_pct_per_trade` 1.5 % → 0.8 %.** Der alte Wert war unerreichbar und damit
   wirkungslos: 1.5 % × 8 Positionen = 12 % Portfoliorisiko, der Allokationsrahmen
   erlaubt aber nur ~875 € pro Position ≈ 0.6 % Risiko. Gemessen: Median-Ist-Risiko
   **71 €** gegen 150 € Ziel. `min(vol_size, pct × portfolio, …)` wählte deshalb fast
   immer den pct-Deckel — die Risk-Parity war dekorativ. Bei 0.8 % bindet sie
   innerhalb des Rahmens, der pct-Deckel wird zur Sicherheitsgrenze.
3. **Bremskaskade additiv statt multiplikativ** (`combine_size_brakes()`, Floor 0.40).
   Vorher: Drawdown × Sektor-Regime × VIX × Probation = 0.65 × 0.5 × 0.5 = **16 %** der
   Basisgröße — ein valider Kandidat fiel unter die 200-€-Mindestgröße und wurde stumm
   verworfen (das neue Gate `size-below-minimum` zeigt genau das). Jetzt werden die
   Reduktionen addiert und am Floor abgeschnitten: mehrere Bremsen verstärken sich,
   können den Trade aber nicht rechnerisch auslöschen. Wer in einer Lage gar nicht
   handeln will, soll das über ein Gate entscheiden, nicht über eine Multiplikation
   gegen null.

### Momentum-Faktor — war für jeden Ticker identisch

`factor_scores.momentum_score` stand in **allen 4.844 Zeilen auf 1.0**. Ursache in
`_compute_momentum_score()`: der Default `idx = -1` ließ die Bedingung `if idx >= 0`
immer fehlschlagen, beide Returns wurden auf `0` gesetzt, die Funktion gab `0 − 0 = 0`
zurück — für jeden Ticker. `_percentile()` einer Liste aus lauter Nullen liefert für
jedes Element 1.0. Der mit 30 % höchstgewichtete Faktor trug damit exakt null
Querschnitts-Information; das Composite-Ranking lief allein auf
Quality/Value/Revision/LowVol.

- Negativer Index wird korrekt in eine Position übersetzt; zu kurze Historie liefert
  `None` und fällt aus dem Ranking, statt es mit einem erfundenen Neutralwert zu
  verwässern.
- `_percentile()` gibt bei Eingaben ohne Streuung jetzt 0.5 plus Warnung zurück statt
  1.0 — genau diese Rückgabe hatte den Bug unsichtbar gemacht („toter Faktor" sah aus
  wie „alle maximal stark").
- Universum: `us_universe.csv` (600 liquide US-Titel) wird dazugemischt, Limit von 200
  auf 400 angehoben (`factor_max_tickers`). 136 Ticker sind für ein Top-Dezil zu dünn.

Verifiziert an synthetischen Kursverläufen: Aufwärtstrend +0.566, Seitwärts −0.002,
Abwärts −0.254, Trend-mit-Spike +0.157 (der jüngste Monat wird korrekt abgezogen).

### PEAD — Fenster und Schwelle kalibriert

Befund: nur **9 von 1.038** Cache-Einträgen hatten überhaupt einen Boost ≠ 0 (0,9 %).
Das ist nicht kaputt, sondern strukturell — aber zwei Parameter passten nicht zum
Effekt, den sie abbilden sollen:

- **Fenster 4 → 10 Tage.** Post-Earnings-Announcement-Drift läuft über Wochen *nach*
  der Meldung; ein 4-Tage-Fenster misst die Ankündigungs-Reaktion, also gerade das,
  was der Effekt nicht ist.
- **Mindest-Überraschung 2 % (relativ).** Vorher zählte `diff > 0` jede Abweichung als
  BEAT, auch +0,0001 EPS. Ein Vorzeichentest auf verrauschten Schätzungen ist nahe an
  einem Münzwurf. `surprise_pct` wird jetzt mitgeschrieben, damit die Schwelle später
  aus Daten kalibriert statt geraten wird.

Beides per Environment übersteuerbar (`PEAD_WINDOW_DAYS`, `PEAD_MIN_SURPRISE_PCT`).

### Schattenbücher — `scripts/shadow_selection.py` (neu)

Vier Selektions-Regeln laufen täglich parallel, jede mit eigenem Buch und eigenem P&L.
Das Skript trifft **keine** Entscheidung: es ändert weder Config noch `positions`.

| Buch | Regel |
|---|---|
| `live_baseline` | Was der Live-Entry heute wählen würde — dieselbe Klausel wie `signal_manager`, inklusive der quellenabhängigen Mindest-Mentions. Ohne diese Referenz sind die anderen Zahlen bedeutungslos. |
| `h1_momentum` | Cross-sectional: Top-N nach `factor_scores.composite_score` mit Momentum-Perzentil ≥ 0.60. Kein absoluter Schwellenwert → hungert nie, flutet nie. Überspringt sich selbst mit Begründung, wenn `factor_scores` älter als 7 Tage ist. |
| `h2_pead` | PEAD als Primärquelle statt als +2 %-Aufschlag. |
| `h3_crowding` | Sentiment invertiert: unter den preisbestätigten Kandidaten die mit der *niedrigsten* Conviction — im **Band 0.30–0.65**. Die Untergrenze ist wesentlich: rankt man einfach aufsteigend, gewinnen Einträge mit conv≈0.12, und das ist kein leises Signal, sondern gar keines. |

Alle Bücher bekommen Levels aus derselben Quelle wie der Live-Entry
(`get_exit_config` über den Sektor-Regime-Schlüssel) und werden mit derselben
Simulation bewertet (`crabel_shadow_eval.simulate_forward`, per Import statt Nachbau) —
sonst wäre der Vergleich durch unterschiedliche Exit-Parameter verzerrt. Alle Bücher
nennen gleich viele Kandidaten (TOP_N = 5), sonst misst man Selektivität statt
Signalgüte.

Eingehängt als Schritt 7 der `trading_pipeline` (nach dem Signal Manager, damit das
Baseline-Buch denselben Watchlist-Zustand sieht wie der Live-Entry) und als kompakte
Zeile im täglichen Telegram-Report (`nightly_eval.build_shadow_line()`).

### Geänderte Dateien
| Datei | Änderung |
|---|---|
| `scripts/signal_manager.py` | Sizing von der Conviction entkoppelt; `combine_size_brakes()` |
| `data/strategy_config.json` | `max_position_pct` 0.15→0.125, `risk_pct_per_trade` 0.015→0.008, `size_brake_floor` neu |
| `thematic/factor_ranker.py` | Momentum-Index-Bug, `_percentile`-Guard, Universums-Merge, Limit 200→400 |
| `scripts/pead_signal.py` | Fenster 4→10 Tage, relative Mindest-Überraschung, `surprise_pct` im Info-Dict |
| `scripts/shadow_selection.py` (neu) | Vier Selektions-Bücher, Vorwärtsbepreisung, Bericht |
| `scripts/trading_pipeline.py` | Schritt 7 „Shadow Selection" |
| `scripts/nightly_eval.py` | `build_shadow_line()` in beiden Report-Formaten |

### Verifikation
Test-Suite 29 grün, AST über 21 Dateien. Bremskaskade gegen Referenzwerte geprüft
(Drawdown+Sektor+VIX: alt 16 % → neu 40 %). Momentum-Score an vier synthetischen
Kursverläufen. Schattenbücher gegen DB-Kopie: Auswahl idempotent (zweiter Lauf am
selben Tag erzeugt keine Duplikate), `positions` unberührt. Bewertungspfad mit echten
`exit_rules` und synthetischen Verläufen: steigend → TIME_STOP nach 7 d bei +4,80 %,
fallend → SL_HIT nach 4 d bei exakt −3,75 % (= 1,5 × ATR), seitwärts → TIME_STOP 0 %.

### Offen
`h1_momentum` liefert erst Kandidaten, wenn `factor_ranker` wieder läuft — die
Thematic-Pipeline steht seit 13.07. Das Buch meldet das selbst und übergeht sich,
statt stillzuschweigen. Und die Bücher entscheiden nichts: erst ab N≈30 je Hypothese
ist der Vergleich mit `live_baseline` belastbar.

## 08.09.2026 — Messbarkeit: Gate-Protokollierung, Quellen-Taxonomie, Beneficiary-Lifecycle, Video-Retry

Nachtrag zum Analyse-Sprint. Die vier als „offen" markierten Punkte sind umgesetzt.
Auslöser war eine Auswertung der 84 Trades nach Dimensionen, die einen Befund lieferte,
der die Priorisierung verändert hat.

### Vorbefund — die Conviction ist am oberen Ende gegenläufig

| Conviction beim Entry | n | WR | P&L | Ø Size |
|---|---|---|---|---|
| **= 1.00** | 29 | 34 % | **−1.168 €** | 1.402 € |
| 0.90–0.99 | 19 | 37 % | −193 € | 1.496 € |
| **unter 0.90** | 36 | 44 % | **+100 €** | 1.058 € |

93 % des Gesamtverlusts steckt im Top-Band des eigenen Scores; alles unterhalb 0.90 ist
zusammen leicht profitabel. Ursache in der Formel: `sentiment_score` ist der Bull-Anteil
der Mentions und wird bei **einer** bullishen Mention 1.0 — maximale Einigkeit ohne jede
Bestätigung. Verifiziert: 69 % aller Einträge mit Conviction 1.00 haben genau eine Mention.

Das Sizing verstärkt genau das: Positionen ≥ 1.800 € (Ø-Conviction 0.95) machen 25 Trades,
WR 24 %, **−1.659 €**; Positionen 800–1.200 € (Ø-Conviction 0.87) machen 25 Trades,
WR 52 %, **+566 €**. Ergänzend: 43 % der Trades sterben unter 4 Tagen und kosten −1.884 €,
die übrigen 48 Trades machen +623 €.

### Punkt 1 — Gate-Protokollierung an jedem Abbruch (`signal_manager.py`)
Von ~20 `continue`-Pfaden im Entry-Loop protokollierten drei. In der Live-DB stand deshalb
ausschließlich `gate='crabel'`, und es war nicht feststellbar, **wo** der Kandidatenstrom
versiegt. Jetzt schreibt ein Closure `_skip(gate)` an jedem Abbruch eine Zeile; 22 von 23
Pfaden sind angeschlossen (`already-open` bewusst nicht — das ist ein Duplikat, kein
geblockter Entry, und würde die Tabelle täglich fluten). Neue Gate-Namen u.a.
`cooldown-24h`, `no-price-data`, `sector-regime-bull`, `correlation`, `earnings-blackout`,
`macro-event-day`, `segment-history`, `size-below-minimum`, `sector-exposure`.

`size-below-minimum` ist dabei der diagnostisch wichtigste: die multiplikative Bremskaskade
(Drawdown × Sektor-Regime × VIX × Probation) kann einen validen Kandidaten unter 200 €
drücken — im Log sah das bisher aus wie „kein Kandidat".

`log_blocked_entry()` verträgt jetzt fehlende Preis-/ATR-Daten (Gates vor der Preisabfrage
schreiben NULL-Levels), und `crabel_shadow_eval.py` filtert Zeilen ohne `would_entry` aus
der Vorwärtsbepreisung — sie zählen für die Häufigkeitsstatistik, nicht für den
Counterfactual.

### Punkt 2 — Quellen-Taxonomie statt globaler Schwellen (`config.py`)
`min_mentions >= 2` war das bindende Entry-Kriterium (23 Kandidaten mit Conviction ≥ 0.65 →
2 → 0). Die Schwelle galt für alle Quellen gleich, obwohl der Screener genau eine Zeile pro
Ticker und Tag schreibt und sie strukturell nie erreichen konnte.

Neu in `config.py`: `DETERMINISTIC_CHANNELS`, `is_deterministic_source()`,
`confirmation_factor()`. Zwei Regeln bauen darauf auf:

1. **Mindest-Mentions quellenabhängig** — deterministische Quelle: 1 Mention genügt,
   Meinungsquellen: unverändert ≥ 2. Gemessen: **0 → 6 Kandidaten**. Bewusst nicht
   `min_mentions=1` global — das ergäbe 13 und ließe genau das Verlustband wieder herein.
2. **Bestätigungs-Faktor auf dem Sentiment-Term** — der Bull-Anteil wird mit der Zahl
   *unabhängiger Kanäle* skaliert (1 Kanal → ×0.5, ab 2 → ×1.0). Deterministische Quellen
   sind ausgenommen: eine reproduzierbare Messung gewinnt durch Wiederholung keine
   Information. Wirkung: Screener-Kandidat behält 0.763, Einzelmeinung fällt 0.763 → 0.443
   (unter `min_conviction`), „2 Mentions aus einem Kanal" 0.835 → 0.515. Das HIGH-Sizing-Band
   (≥ 0.80, 20 % Position) schrumpft von 2 auf 1 Kandidaten.

### Punkt 3 — Beneficiary-Lifecycle (`beneficiary_mapper.py`, beide `thesis_monitor.py`)
Zwei Befunde: `theme_beneficiaries.status` wurde von **keiner** Codestelle je geändert
(alle 220 auf `candidate`, die Filter `status != 'archived'` überall wirkungslos), und
208 davon sind älter als 60 Tage — jüngstes `last_updated` ist der 13.07. Trotzdem bekamen
33 Ticker daraus dauerhaft Conviction-Boost.

- **Schreibseite**: beide `thesis_monitor`-Writer setzen jetzt `beneficiary_id` (aufgelöst
  über `theme_id` + `ticker`). Die Spalte war in allen 81 Zeilen NULL — der Lookup lief
  immer leer, deshalb griff auch der Case-Fix vom selben Tag ins Nichts.
- **Lifecycle**: `sync_beneficiary_status()` leitet den Status bei jedem Mapper-Lauf neu ab —
  `archived` bei nicht-aktivem Theme, gebrochener These oder Mapping > 60 Tage; `active` bei
  aktivem Theme + INTACT; sonst `candidate`. Rein ableitend, damit kein fehlgeschlagener
  Lauf einen Zustand dauerhaft verfälscht. Verifiziert gegen DB-Kopie: 208 archiviert,
  Boost-Kreis **33 → 12 Ticker**, zweiter Lauf 0 Änderungen.
- **Zweites Netz**: `get_thesis_conviction_boost()` prüft zusätzlich das Alter, damit ein
  ausgefallener Mapper-Lauf keinen Boost aus monatealten Mappings durchlässt.

### Punkt 4 — Video-Retry und Quarantäne (`signal_extractor.py`)
Die Retry-Logik („nach 3 Fehlversuchen dauerhaft skippen") war **toter Code**: die Abfrage
holte ausschließlich `status='pending'`, ein auf `error` gesetztes Video kam nie wieder in
die Schleife. Beweis: alle 36 Fehler-Videos standen auf `error_count=1` — kein einziges hat
je einen zweiten Versuch bekommen. Jeder transiente Fehler war endgültiger Signalverlust.

- Auswahl umfasst jetzt `status='error' AND error_count < MAX_ERROR_ATTEMPTS` (Default 3,
  per Env übersteuerbar).
- Neuer Endzustand `failed` statt weiter `error` — nur so ist unterscheidbar, was noch
  wiederholt wird und was aufgegeben wurde.
- Neuer Endzustand `transcript_expired`: `cleanup_db()` leert Transkripte älter als 7 Tage;
  ein in diesem Fenster gescheitertes Video ist nicht nachholbar und kreist sonst endlos
  im Retry-Pool. Von den 36: **11 echt wiederholbar, 25 ohne Transkript**.
- Lauf-Bilanz und DB-Bestand werden am Ende ausgegeben, ab 10 endgültig gescheiterten
  Videos zusätzlich eine Log-Warnung. Bisher lief der Ausfall vollständig stumm.

### Geänderte Dateien
| Datei | Änderung |
|---|---|
| `scripts/signal_manager.py` | `_skip()`-Closure an 22 Gate-Pfaden; `log_blocked_entry` verträgt NULL-Levels; quellenabhängige `MENTIONS_CLAUSE` in beiden Kandidaten-Abfragen |
| `config.py` | `DETERMINISTIC_CHANNELS`, `is_deterministic_source()`, `confirmation_factor()`, `MIN_MENTIONS_DETERMINISTIC`, `MIN_CONFIRM_CHANNELS` |
| `scripts/watchlist_manager.py` | Bestätigungs-Faktor in beiden Conviction-Funktionen; Altersgrenze beim Thesis-Boost |
| `scripts/crabel_shadow_eval.py` | filtert Zeilen ohne `would_entry` aus der Vorwärtsbepreisung |
| `thematic/beneficiary_mapper.py` | `sync_beneficiary_status()` + Aufruf am Ende von `main()` |
| `scripts/thesis_monitor.py`, `thematic/thesis_monitor.py` | `beneficiary_id` wird geschrieben |
| `scripts/signal_extractor.py` | Retry-Auswahl, `MAX_ERROR_ATTEMPTS`, Zustände `failed`/`transcript_expired`, Lauf-Bilanz + Backlog-Warnung |

### Verifikation
Test-Suite 29 grün, AST-Check über 16 geänderte Dateien. Gegen DB-Kopien verifiziert:
`log_blocked_entry` mit und ohne Preisdaten inkl. Dedup über
`UNIQUE(ticker, direction, block_date, gate)`; die neue Kandidaten-Klausel liefert 6 statt 0;
`sync_beneficiary_status` ist idempotent; `watchlist_manager --dry-run` lässt die
Watchlist-Tabelle bit-identisch.

### Weiterhin offen — und bewusst nicht entschieden
Die Selektionsfrage selbst. Die obigen Fixes machen sie **messbar**, sie beantworten sie
nicht. Aus der Datenlage folgen drei Kandidaten, die als eigene Schattenbücher gegen den
Status quo laufen müssten, bevor eines davon live geht:
Cross-sectional Momentum (12-1 + SMA200-Filter, `screener_source.setup_metrics()` liefert
die Inputs bereits), PEAD als Primärquelle statt +2 %-Nudge (`pead_signal.py` vollständig
vorhanden), und Sentiment als Crowding-Malus statt als Selektor — die einzige Lesart, die
die 84 Trades stützen. Ebenfalls offen: SHORT (9 Trades, 22 % WR, −251 €, kein
Borrow-/Kostenmodell) und das Sizing, das noch immer mit der Conviction skaliert.

## 08.09.2026 — Analyse-Sprint: 7 Defekte aus Code-Review + DB-Auswertung

Vollständige Analyse von Codebasis, fachlichen Prozessen und **Live-DB** (84 geschlossene
Trades, 62 Pipeline-Läufe 28.07.–08.09.). Kernbefund: das System handelt nicht mehr
(79 % Cash, 2/8 Positionen, Log meldet täglich "Keine Watchlist-Kandidaten"). Sieben
Defekte behoben — bewusst OHNE neue Gates, ohne Exit-Umbau, ohne Änderung an
`get_exit_config()` / `check_drawdown()` / den Entry-Schwellen.

### Fix 1 — Mention-Aggregation je Ticker statt je Rohname (`watchlist_manager.py`)
`GROUP BY name` über die Rohnamen, aber `UPDATE ... WHERE ticker=?` — bei mehreren
Namensvarianten pro Ticker lief das UPDATE mehrfach und der **zuletzt verarbeitete
Variant gewann**. `mention_count` war dadurch systematisch zu klein, ausgerechnet bei
den meistgenannten Titeln. Jetzt zwei Phasen: (A) Rohname → Ticker via
`validate_and_register`, (B) EINE kombinierte Aggregation über alle Namen eines Tickers,
EIN INSERT/UPDATE. Neu: `--dry-run` stellt alt/neu gegenüber, ohne zu schreiben.
Verifiziert (Live-DB, 14d-Fenster): 13 Ticker mit mehreren Varianten, z.B. GOOGL
1 → 22 Mentions, Conviction 0.12 → 0.78; HOOD 6 → 9; CRM 2 → 9; DBK.DE 2 → 8.

> ⚠️ **Wichtig — das behebt die Entry-Starvation NICHT allein.** Gemessen an der
> Live-DB bleibt `mention_count >= 2` das bindende Kriterium: von 23 Kandidaten mit
> Conviction ≥ 0.65 passieren nur **2**. Der hochbewertete Pool besteht überwiegend aus
> **Screener-Signalen mit genau einer Mention** (eine Zeile pro Ticker und Tag, ein
> Name, keine Varianten) — für die ändert die Aggregation nichts. Ob `min_mentions`
> für deterministische Quellen gelockert wird, ist eine Strategieentscheidung und
> wurde hier bewusst NICHT getroffen.

### Fix 2 — Thesis-Boost griff nie bei gebrochenen Thesen (`watchlist_manager.py`)
Zwei überlagerte Fehler: (a) `thesis_status_log.status` wird in GROSSSCHREIBUNG
geschrieben, der Vergleich lief case-sensitiv gegen Kleinschreibung; (b) **`beneficiary_id`
ist in allen 81 Zeilen NULL** — weder `scripts/thesis_monitor.py` noch
`thematic/thesis_monitor.py` schreiben die Spalte, der Lookup lief also immer leer.
Jede Position mit Beneficiary-Eintrag bekam dadurch +0.02, auch bei BROKEN. Jetzt
normalisierter Vergleich + Lookup zusätzlich über den Ticker; WEAKENING → 0.0.

### Fix 3 — `source_registry`-Zähler (`source_lifecycle.py` + `fix_source_counters.py` NEU)
`evaluate_active_sources()` schrieb `total_bought = total_bought + SUM(rollierende
30d-Snapshots über 90d)`. Jeder Trade steckte in ~30 Snapshots, und die Summe wurde
**wöchentlich erneut addiert** → exponentielle Inflation (`der aktionaer` = 6358 bei
84 Trades im ganzen System); `total_mentions` wurde nie geschrieben. Aus diesen Feldern
speisen sich `adjust_weights()` und `get_channel_calibration()` — das Sentiment-Signal
wurde also doppelt gedämpft (0.3 × 0.3) auf Basis einer Statistik, die etwas anderes
misst, als ihr Name sagt. Jetzt werden alle Kennzahlen absolut aus `positions` /
`watchlist_mentions` berechnet und per SET geschrieben (idempotent verifiziert).
`scripts/fix_source_counters.py` korrigiert die Bestandswerte einmalig
(Dry-Run-Default, read-only per DB-Hash verifiziert; `--apply`, `--reset-weights`).
Nach der Korrektur: max. 32 Trades je Quelle, `techaktien` avg_pnl −19.1 € → **+3.1 €**.

### Fix 4 — Portfolio-Report zeigte falsche Zahlen (`signal_manager.py`, `dashboard.py`)
Report meldete "54 Trades / 35 % WR", die DB sagt **84 / 39 %**. `cfg["total_trades"]`
und `winning_trades` werden nur im SL/TP-Pfad hochgezählt — nicht bei `TECH_BROKEN`,
`TIME_STOP`, `DRAWDOWN_EMERGENCY` oder Exits aus `active_exit_check.py`. Beide Reports
lesen jetzt aus `positions`; `adapt_strategy()` ebenso für die Win-Rate.

### Fix 5 — `tech_score`-Wertebereich (`utils.py`, `watchlist_manager.py`, `refresh_tech_scores.py`)
Neuer Helfer `clamp_tech_score()` auf [0,1] an beiden Schreibstellen. Eine Bestandszeile
stand auf **5.0** (IQV) und passierte damit jeden `tech_score >= X`-Entry-Filter
automatisch. Zusätzlich schreibt `refresh_tech_scores.py` jetzt `weekly_trend` mit —
vorher wurde er dort nur gecleart, nie aktualisiert, sodass ein Refresh einen frischen
`tech_score` neben einen veralteten `weekly_trend` setzte. Beide bilden zusammen das
Momentum-Gate in `entry_gate_reason()` und müssen aus demselben Aufruf stammen.

### Fix 6 — Committee-Fehlerquote 45 % (`roles/committee.py`)
5 von 11 Checks endeten in `ERROR_FAIL_OPEN`; Logmarker `Committee/committee_bull:
Parse-Fehler`. Die eigene Regel vom 20.07. ("JSON-Repair ab >5 % Ausreißerquote")
war deutlich überschritten. Jetzt: `max_tokens` pro Rolle (Bull 800 → 1600, Bear/Risk
1000) und eine Repair-Stufe vor dem Fail-Open, die den gehärteten `_try_parse()` aus
`signal_extractor.py` wiederverwendet. Getestet gegen die realen Fehlermuster: trailing
commas, Steuerzeichen und Mehrfach-Objekte werden gerettet, hart abgeschnittenes JSON
bleibt Fail-Open (dagegen hilft nur der höhere Token-Deckel). Zusätzlich wird die
Rohantwort bei Parse-Fehler in `committee_log` persistiert — bisher ging genau die
Payload verloren, die man zur Diagnose braucht.

### Fix 7 — toter Parameter `min_confidence` entfernt
Der Key wurde vom Entry-Pfad **nie gelesen**: die wirksame Tech-Score-Schwelle liefert
die Drawdown-Matrix (0.70/0.75). `adapt_strategy()` verstellte ihn trotzdem laufend und
verschickte Telegram-Zeilen wie "Min. Konfidenz erhöht auf 80 %", der
`strategy_optimizer` durchsuchte 6 Stufen im Grid und schrieb das Ergebnis zurück.
Entfernt statt scharfgeschaltet — eine zweite, konkurrierende Quelle für dieselbe
Schwelle wäre genau das Muster, das die Exit-Matrix am 09.08. beseitigt hat.
Grid dadurch 6× kleiner. Die Drawdown-Matrix liegt jetzt als reine Funktion
`drawdown_params()` in `config.py` (SSOT neben `get_exit_config()`); Report und
Dashboard zeigen die tatsächlich wirksame Schwelle.

### Geänderte Dateien
| Datei | Änderung |
|---|---|
| `scripts/watchlist_manager.py` | Zwei-Phasen-Aggregation je Ticker + `--dry-run`; Thesis-Boost case-insensitiv + Ticker-Lookup; `clamp_tech_score` |
| `scripts/source_lifecycle.py` | `evaluate_active_sources` rechnet absolut aus `positions`/`watchlist_mentions`; `channel_variants()`/`_channel_match_sql()` neu |
| `scripts/fix_source_counters.py` (neu) | Einmalige Bestandskorrektur, Dry-Run-Default |
| `scripts/signal_manager.py` | Trade-Zähler + Win-Rate aus DB; `min_confidence`-Mutationen raus; `drawdown_params` aus config |
| `config.py` | `drawdown_params()` (Drawdown-Matrix als SSOT) |
| `utils.py` | `clamp_tech_score()` |
| `scripts/refresh_tech_scores.py` | Clamping + `weekly_trend` mitschreiben |
| `scripts/strategy_optimizer.py`, `scripts/backtester.py` | `min_confidence` aus Grid/Write-Back/Reports entfernt |
| `scripts/dashboard.py` | Trades/WR aus DB; "Min. Konfidenz" → wirksamer "Min. Tech-Score" |
| `roles/committee.py` | Token-Budget je Rolle, JSON-Repair vor Fail-Open, Rohantwort im Audit-Log |

### Verifikation
Test-Suite **29 passed** (`PYTHONUTF8=1 python -m pytest tests/ -q`; ohne das Flag
scheitert `test_exit_asymmetry` unter Windows an cp1252 — die Tests öffnen Dateien ohne
`encoding=`, auf dem Server ist UTF-8 Default). AST-Check aller 11 geänderten Dateien
grün. `watchlist_manager --dry-run` gegen eine DB-Kopie durchlaufen: Watchlist-Tabelle
bit-identisch (Hash vor/nach gleich). `fix_source_counters.py` Dry-Run read-only
(DB-Hash unverändert), `--apply` idempotent (2. Lauf = 0 Änderungen).

### Offen (bewusst nicht angefasst)
- `min_mentions >= 2` blockt weiterhin fast alle Kandidaten (siehe Kasten bei Fix 1).
- `theme_beneficiaries`: 220 Einträge, **alle** im Status `candidate` — keiner wurde je
  promoted. Die Thematic-Pipeline läuft täglich mit LLM-Kosten und wirkt über genau
  einen Pfad in den Handel (Conviction-Boost), der bis heute defekt war (Fix 2).
- `blocked_entries` enthält nur `gate='crabel'` — die Gates vom 27.08. (`momentum-gate`,
  `liquidity-gate`) und 06.09. (Sektor-Regime) haben in 62 Läufen keine Zeile erzeugt.
- 36 Videos hängen dauerhaft auf `status='error'`.
- `watchlist` hat nach dem Table-Swap keinen PRIMARY KEY und `id INT` nullable — die
  Ursache des `rowid`-vs-`id`-Pitfalls vom 09.08.

## 27.08.2026 — Selection-Rebuild: Momentum ist Gate, Sentiment ist Stärke

Long-Entries benötigen jetzt zwingend `weekly_trend='bullish'` UND `tech_direction='LONG'`; Shorts analog `bearish` UND `SHORT`. News-Sentiment (`conviction_score` bzw. `conviction_score_bear`) bleibt erhalten und sortiert bzw. gewichtet ausschließlich Kandidaten, die dieses Preis-Momentum-Gate passiert haben. Es kann keinen Entry allein auslösen.

`get_technical_score()` verlangt für alle Listings mindestens 200 Bars und mindestens 500.000 EUR durchschnittlichen 20-Tage-Turnover. Nicht kanonisch gemappte Nebenbörsen-Ticker mit `.F`, `.MU` oder `.SG` werden zusätzlich hart abgewiesen; bestehende `canonical_tickers`-Mappings bilden die Whitelist. Momentum- und Liquiditätsblockaden werden als `momentum-gate` bzw. `liquidity-gate` in `blocked_entries` protokolliert. Die Top-Watchlist enthält nur technisch bestätigte LONG-Kandidaten und sortiert diese danach per News-Conviction.

## 26.08.2026 — DQ-Root-Clause-Fix: keine Reaktivierung + Cleanup-Dry-Run read-only

### Problem (Root-Cause der wiederkehrenden DQ-Akkumulation)
Seit dem 19.08.-Cleanup (Stufe 1b/1c) wurde jeder `.L`-Microcap (ohne tech_score) bzw. jeder `.L` aus deaktivierten Quellen nachts vom Cleanup (22:30) auf `dropped` gesetzt — aber **am nächsten Morgen waren dieselben `.L` wieder `watching`** (last_seen blieb alt, 08.12.–08.18, also keine frischen Zuflüsse). `dq_alarm` (22:40) feuerte dann täglich (DQ 14 + deakt 28 = 42 ≥ 10). Live-Befund 26.08.: alle 14 DQ-Einträge waren zu 100% aus `rss:share talk` (enabled=0) und hingen seit der Deaktivierung fest.

**Root-Cause:** `watchlist_manager.py` (Pipeline 03:30) reaktivierte in der Mention-Verarbeitung **jede `dropped`-Zeile** zurück auf `watching`:
```sql
UPDATE watchlist SET ... status='watching'
WHERE ticker=? AND status IN ('watching', 'dropped')
```
Die historischen Share-Talk-Mentions liegen weiter in den Mention-Tabellen. Jede Nacht holte der Manager die gedroppten `.L` daraus zurück → Cleanup droppt 22:30, Pipeline reaktiviert 03:30 → DQ akkumulierte trotz Cleanup.

### Fix
1. **`scripts/watchlist_manager.py`** — DQ-Reaktivierung blockiert: die Aufweck-`WHERE`-Clause schließt `no-liquidity-gate` und `source-deactivated` aus. Solche Drops sind per Definition untradable (Liquidity-Gate / tote Quelle) und dürfen nie wieder zum Signal werden. Benigne Drops (stale>60d, merge, dedup, notes NULL) bleiben reaktivierbar.
   ```sql
   WHERE ticker=? AND status IN ('watching', 'dropped')
     AND (notes IS NULL OR notes NOT IN ('no-liquidity-gate','source-deactivated'))
   ```
2. **`~/.hermes/scripts/watchlist_cleanup.py`** — Dry-Run-Fußangel gefixt: Vorher führte das Script die UPDATE-Stufen (Stufe 1/1b/1c + Stale) und den `commit()` **immer** aus, nur die Archivierung war an `--apply` gebunden → ein "Dry-Run" hat die Live-DB verändert (hat bei der Diagnose ungewollt die 14 `.L` live gedroppt). Jetzt: Zählung per `SELECT COUNT(*)`, Schreiben NUR mit `--apply`. Dry-Run ist echt read-only (verifiziert: DB-Hash vor/nach identisch).

### Verifikation (26.08., Live-DB)
- `dq_alarm.py`: DQ 14→**0**, Deaktivierungs-Check 28→**0** → **silent** (keine Regression)
- `watchlist_cleanup.py` dry-run bei 0 `.L` ohne Score + read-only (DB-Hash `040381c0…` unverändert)
- watchlist_manager.py parst sauber; ASI+AST-Check ok; in State-Backup synchronisiert

### Geänderte Dateien
| Datei | Änderung |
|---|---|
| `scripts/watchlist_manager.py` | Reaktivierungs-WHERE: `notes NOT IN ('no-liquidity-gate','source-deactivated')` |
| `~/.hermes/scripts/watchlist_cleanup.py` | Alle Stufen-1-UPDATEs + commit gated auf `--apply`; Zählung per SELECT; Dry-Run read-only |

**Nachfolge-Purge (26.08.):** Nach dem Root-Clause-Fix wurden die historischen Share-Talk-Mentions an der Quelle entfernt, damit der Manager sie nie wieder verarbeitet — nicht nur downstream blockiert:
- `watchlist_mentions` `channel='rss:share talk'`: **225 Zeilen** gelöscht
- `external_mentions` `source_name='Share Talk'`: **528 Zeilen** gelöscht
- Verifiziert: DQ 0/0 silent; 0 `.L` ohne tech_score; 0 `.L`-channels enthalten `share talk`.
- **Backup:** `data/share_talk_backup_20260826.db` (Tabelle `watchlist_mentions_backup` + `external_mentions_backup`).
- **Warum beide:** social_scanner `inject_into_watchlist` liest `external_mentions` nur `published_at >= jetzt-2d` (Share-Talk endet 18.08. → würde nicht re-injizieren), aber `watchlist_manager`-Aggregation liest ALLE `watchlist_mentions` (kein Channel-Filter) → die 225 `watchlist_mentions`-Zeilen waren die eigentliche Wiedergeburtsquelle. Quelle ist `enabled=0/removed` → kein neuer Zufluss.

## 24.08.2026 — DQ-Deaktivierungs-Verifikation + Cleanup Stufe 1c

### Problem
Der vault-insights-daily mahnte wiederholt an, die **share-talk-Deaktivierung** (19.08.) zu verifizieren. Der Check ergab: Der bestehende `dq_alarm.py` zählte nur `.L` **ohne** tech_score — aber **8 `.L`-Einträge MIT tech_score** (AET, AMRQ, ANTO, ATYM, FRAS, GEX, MPAL, 80M) blieben aus `rss:share talk` (enabled=0) im Watchlist-Hauptteil, weil Cleanup Stufe 1b nur `tech_score IS NULL` droppte. Dazu zählte `dq_alarm` als "exklusiv deaktiviert" auch Large-Caps (STLA/patrick boyle, AEM/urban jäkle, KKR/meet kevin) — False-Positives, weil der Check nicht auf `.L` begrenzt war.

### Fix
1. **`dq_alarm.py`** (Cron `37d505cbc47b`, Mo–Fr 22:40): neue Kennzahl `count_deactivated_only()` — zählt `.L`-Ticker in watching/bought, deren EINZIGE Quelle deaktiviert ist (enabled=0, aus `source_registry`). Bewusst nur `.L` (die DQ-Flut-Quelle), damit Large-Caps mit einzelnem toten Kanal nicht falsch alarmen. Kombiniert mit dem DQ-Count; Regression ab Schwelle 10 → Telegram-Alarm.
2. **`~/.hermes/scripts/watchlist_cleanup.py`** (Cron `7e364ce47b69`, Mo–Fr 22:30): neue **Stufe 1c** — `.L`-Einträge MIT tech_score, die zu 100% aus deaktivierten Quellen stammen, werden auf `dropped/notes='source-deactivated'` gesetzt. Bought-Positionen unangetastet. Lädt deaktivierte Quellen dynamisch aus `source_registry`, parst `channels` (JSON).

### Verifikation (24.08., Live-DB)
- `dq_alarm.py`: DQ 16→0, Deaktivierungs-Check 0 → silent (kein Alarm)
- Cleanup: 27 `.L` ohne tech_score (Stufe 1b) + 8 mit Score aus share talk (Stufe 1c) → dropped
- Nach dem Lauf: **0** `.L` aus share talk in watching/bought; übrig bleiben nur legitime `.L` (the motley fool uk, pensioncraft)
- dq_alarm.py in State-Backup `martin-hermes-state` synchronisiert

## 19.08.2026 — DQ-.L-Aufräumung in watchlist_cleanup + Cleanup täglich

### Problem
Der UK-Liquidity-Gate (14.08.) blockierte korrekt neue tech_scores für `.L`-AIM/Nano-Caps, aber die Bestands-Einträge blieben als `watching` mit hoher Conviction dauerhaft in der DB (last_seen bleibt durch tägliche RSS-Zuflüsse frisch → 60d-Stale-Regel greift nie). DQ akkumulierte 1→8→14→17. Allein die Quelle **`rss:share talk`** lieferte **100% der DQ-Fälle** (67 von 81 Share-Talk-Einträgen sind `.L`), obwohl `signal_manager` **nie** eine `.L`-Position eröffnet hat (0 Trades) — die Quelle ist für das System faktisch wertlos.

### Fix
1. **`~/.hermes/scripts/watchlist_cleanup.py`** — neue Stufe 1b: `.L`-Ticker ohne tech_score (status `watching`) werden sofort auf `status='dropped', notes='no-liquidity-gate'` gesetzt. Bought-Positionen werden NICHT angefasst. Gedroppte wandern konservativ erst nach 180d ins Archiv (kein Datenverlust).
2. **Cron `7e364ce47b69`** (Name jetzt `watchlist-cleanup-daily`) — von wöchentlich (So 07:30) auf **Mo–Fr 22:30** umgestellt: nach dem Export (22:15), vor dem DQ-Alarm (22:40). Verhindert Akkumulation statt sie wöchentlich einmal zu räumen.

### Verifikation (19.08., Live-DB)
- DQ-Count vorher **17** (über Schwelle 10) → nachher **0**
- 34 `.L`-Einträge auf `dropped/no-liquidity-gate` gesetzt, davon 33 als Restbestand, keiner als bought
- `--apply`-Pfad sauber: 7 Artefakte archiviert, keine Fehler

### Hinweis
Die Quelle `rss:share talk` (weight 0.5, probation) bleibt aktiv und speist weiter neue `.L`-Caps ein — der Cleanup räumt sie jetzt täglich weg. Falls die Quelle langfristig nur Rauschen liefert, sollte sie auf `enabled=0`/`removed` geprüft werden (Source-Lifecycle 07.07.-Prinzip: lieber penalisieren als komplett rausschmeissen — aktuell nicht angefasst).

## 19.08.2026 — Quelle `rss:share talk` DEAKTIVIERT (0% Erfolgsquote)

### Hintergrund
Ergänzung zum DQ-Cleanup-Fix. Verifiziert am 19.08.: Die Quelle Share Talk (source_registry id=55, `https://www.share-talk.com/feed/`) hat über ihren gesamten Lebenszyklus (seit 07.06.) **keinen einzigen Trade generiert** — `total_mentions=0`, `total_bought=0`, `win_rate=0.0`, `avg_pnl_per_trade=0.0`. Sie lieferte 83% non-tradable `.L`-Microcaps und war damit die Wurzel der DQ-Akkumulation (1→8→14→17).

### Fix
`UPDATE source_registry SET enabled=0, status='removed', rejection_reason='0% Erfolgsquote ...' WHERE id=55;` — reversibel in der DB.

### Wirkung
- Stoppt den neuen `.L`-Zufluss an der Wurzel (Scan nur für enabled=1)
- Der watchlist-cleanup-Fix (19.08.) bleibt als Sicherheitsnetz für andere Quellen, die `.L`-Caps liefern (motley fool uk, seeking alpha)
- Cron `53f222b00811` (vault-insights-daily) Prompt nachgeschärft: SHORT sentiment-basiert zählen (bear>long), tech_direction=SHORT bei bought-LONG-Positionen NICHT als neue Bärenwelle darstellen; DQ-Zufluss aus anderen Quellen überwachen



## 01.09.2026 — Drawdown 15-25%-Zone: Größe 65% + Conf 75% (Heilungs-Beschleunigung)

### Problem
Portfolio bei **-18.1% Drawdown** vom ATH (11.208 → 9.211, Cash 82.5%). Es gab zwar **23-34 entry-fähige Kandidaten** (conv≥0.60-0.80 + tech_score + direction), aber die 15-25%-Bremszone (Size 50% + Conf 80%) machte die Heilung mathematisch endlos: Mit ±40-60€ PnL pro Trade brauchte es **10-20 profitable Winner** für die +651€, um die Zone zu verlassen (unter 12% DD). Zusätzlich filterte die 80%-Confidence die meisten der 23 Kandidaten raus (nur conv≥0.80 kamen durch). Resultat: 82% Cash, 2 Positionen, festgefahren.

### Fix
In `check_drawdown()` (signal_manager.py), 15-25%-Zone:
- `size_factor`: **0.50 → 0.65** (Positionen ~30% größer, jeder Winner bringt mehr)
- `min_confidence`: **0.80 → 0.75** (nun 34 statt 23 Kandidaten entry-fähig)
- `max_positions`: 6 (unverändert)

### Drawdown-Matrix (aktuell)
| Drawdown | Size | Conf | Max Pos | Wirkung |
|----------|------|------|---------|---------|
| < 12% | 100% | 70% | 8 | Normalbetrieb |
| 12-15% | 75% | 75% | 6 | Warnzone |
| 15-25% | **65%** | **75%** | **6** | Bremszone, gemildert (01.09.) |
| ≥ 25% | close_all | 100% | 0 | Notbremse + 7d Cooldown |

### Schutz bleibt intakt
`size_factor < 1` (noch nicht volle Größe) + `min_confidence > default 0.60` (noch strenger als Normalbetrieb). Es war eine Milderung der Bremse, kein Aushebeln. Erwartete Wirkung: ~5-8 Trades statt 10-20 zur Heilung.

### Verifiziert
`check_drawdown()` live bei 18.1% → size_factor 0.65, min_confidence 0.75, max_positions 6. Syntax + Funktion OK.

## 17.08.2026 — Drawdown 15-25%-Zone: max_positions 4 → 6

### Problem
Hohe Cashquote (74.7%) trotz Bull-Regime + kein Cooldown. Grund: Portfolio lag bei **-18.5% Drawdown** vom ATH → die 15-25%-Bremszone setzte `max_positions: 4` (aus `check_drawdown()`). Da bereits 4 Positionen offen waren, wurden ALLE neuen Entries mit "Max. Positionen (4) erreicht" geblockt — obwohl 53 Watchlist-Kandidaten investierbar waren und `max_positions` global bei 8 liegt.

### Fix
In `check_drawdown()` (signal_manager.py): 15-25%-Zone `max_positions` von **4 → 6**. Size-Faktor 0.50 + min_confidence 0.80 bleiben unverändert (graduierte Bremse intakt) — es werden nur mehr Slots freigegeben, damit bei -18.5% wieder 2 zusätzliche Trades möglich sind.

### Drawdown-Matrix (aktuell)
| Drawdown | Size | Conf | Max Pos | Wirkung |
|----------|------|------|---------|---------|
| < 12% | 100% | 70% | 8 | Normalbetrieb |
| 12-15% | 75% | 75% | 6 | Warnzone |
| 15-25% | 50% | 80% | **6** (war 4) | Bremszone, aber handlungsfähig |
| ≥ 25% | close_all | 100% | 0 | Notbremse + 7d Cooldown |

### Verifiziert
`check_drawdown()` live bei -18.5% → Size 50%, Conf 80%, MaxPos 6. Syntax OK.

## 16.08.2026 — DQ-Isolation (Export) + DQ-Regressions-Alarm + Weekly-Exit-Review

### Problem
Der vault-insights-daily meldete drei Nächte in Folge DQ-Wachstum (1 → 8 → 14). `.L`-Microcaps (AIM/Nano-Caps) landeten über `rss:share talk` in der Conviction-Watchlist (≥76%) OHNE Tech-Score (der UK-Liquidity-Gate vom 14.08. blockt ihren Score). Sie wurden im Export-Filter-View als normale Signale gezählt und verzerrten Sektor-Verteilung, SHORT-Anteil und das `max 3 pro Sektor`-Constraint.

### Lösung
1. **`export_watchlist.py` — DQ-Isolation:** `.L`-Ticker mit fehlendem Tech-Score werden vor der Statistik-Berechnung in einen separaten **DQ-Block** ausgelagert. Sie zählen NICHT mehr in Gesamt/≥76%/Sektor/SHORT-Statistik und sind keine Entry-Kandidaten. Verifiziert: 11 DQ-Microcaps aussortiert, liquide `.L`-Large-Caps (ANTO, GLEN, AV, TSCO) bleiben korrekt als Signale.
2. **`refresh_tech_scores.py` — veraltete Scores clearen:** Wenn `get_technical_score` jetzt `None` liefert (Gate blockt), wird der ALTE Score `NULL` gesetzt (vorher blieb er stehen → Eintrag sah entry-fähig aus). Doku-Gotcha vom 14.08. behoben.
3. **`dq_alarm.py` (neu) + Cron `dq-alarm-daily` (37d505cbc47b, Mo–Fr 22:40, no_agent):** Watchdog zählt `.L`-Microcaps ohne Tech-Score (≥76%). Alarm NUR bei Regression (Schwelle überschritten ODER Anstieg über Schwelle), silent bei stabil. State-File `data/dq_alarm_state.txt`. Schwelle 10.
4. **`weekly_exit_review.py` (neu) + Cron `weekly-exit-review` (310dfa0df1a6, So 07:00, no_agent):** Offene Positionen vs Exit-Matrix (`get_exit_config`). Prämisse des Insights korrigiert: **0 offene Shorts** (alle 4 offenen = LONG). Zusätzlich Config-Drift-Check zwischen `get_exit_config` und `get_asset_multipliers`.

### ✅ Fix: Config-Drift `trailing_step` STANDARD (behoben 16.08.)
`active_exit_check.py` las den Trailing-Step aus **`get_asset_multipliers` (Legacy)**, wo `STANDARD.trailing_step = 0.5` steht — die Exit-Matrix `get_exit_config` hat `step = 0.75`. Das war exakt das 09.08.-Parallele-Pfad-Muster (signal_manager nutzte bereits get_exit_config, active_exit_check nicht). **Behoben:** `active_exit_check.py` auf `get_exit_config(asset_type, regime)` umgestellt — Regime wird einmal geladen (`get_current_regime` inline), `pos_mult` = Exit-Matrix. Key-Mapping `trailing_step`→`step`, `atr_sl`→`sl`. Verifiziert: STANDARD step jetzt 0.75 (vorher 0.5).

### ✅ Fix: signal_manager + crabel_shadow_eval auf get_exit_config (16.08.)
Der Weekly-Review deckte zusätzlich auf, dass der Skill seit 09.08. behauptete, signal_manager nutze get_exit_config — real nutzte es `get_asset_multipliers` an 4 Stellen. **Komplett migriert:**
- **`signal_manager.py`:** `compute_sl_tp` (Entry-SL/TP) bekommt `regime`-Parameter und nutzt die Matrix (`ec["sl"]`, `ec["tp"]`). Beide Aufrufer (log_blocked_entry, open_new_positions) reichen Regime durch. Zeile 741 Partial-TP `pos_mult` → Matrix (`partial_atr`). Zeile 1921 Sizing `sl_multiplier` → Matrix `["sl"]`. Toter `mult` (1960) entfernt. Import `get_asset_multipliers` entfernt.
- **`crabel_shadow_eval.py`:** `simulate_forward` nutzt Matrix (`step`, `sl`, `profit_lock_atr`) statt Legacy + cfg-Fallback (Default 2.0 → Matrix 1.0). `_get_regime` inline, Regime in main einmal geholt.
- **Wichtig:** Entry-SL/TP («compute_sl_tp») sind jetzt **regime-abhängig** (z.B. STANDARD bull tp=3.5× vs sideways 2.5×) — konsistent zu active_exit_check und adapt_strategy. Regime-Quelle überall: `get_current_regime(con)` (DB), nicht die JSON-Makrodatei.
- **Weekly-Review-Drift-Check** prüft jetzt alle drei Pfade (signal_manager, active_exit_check, crabel_shadow_eval) auf echte Legacy-Aufrufe `get_asset_multipliers(`.

### Verifikation (16.08.2026, Live-Daten)
- Export: `✅ Watchlist exportiert: 116 Einträge … 11 DQ .L-Microcaps aussortiert`
- DQ-Alarm: Count 11 (Schwelle 10) → Alarm bei Regression, silent bei stabil (State getestet)
- Exit-Review: 4 offene Positionen ✅, Drift `trailing_step STANDARD 0.75 vs 0.5` erkannt

### Geänderte Dateien
| Datei | Änderung |
|---|---|
| `scripts/export_watchlist.py` | DQ-Isolation: `_is_dq()` + DQ-Block im Output, Statistik ohne DQ |
| `scripts/refresh_tech_scores.py` | veraltete Scores werden gecleart (rowcount-gesteuert) |
| `scripts/dq_alarm.py` (neu) | DQ-Regressions-Watchdog (Schwelle 10, State) |
| `scripts/weekly_exit_review.py` (neu) | Positionen vs Exit-Matrix + Config-Drift-Check |
| `scripts/active_exit_check.py` | umgestellt auf `get_exit_config()` (trailing_step 0.5→0.75 Fix, Regime inline) |
| `scripts/signal_manager.py` | `compute_sl_tp`/Partial-TP/Sizing auf `get_exit_config` (Entry-SL/TP regime-abhängig), toter mult entfernt |
| `scripts/crabel_shadow_eval.py` | `simulate_forward` auf Matrix (step/sl/profit_lock statt Legacy+cfg-Fallback) |
| `~/.hermes/scripts/dq_alarm.sh`, `weekly_exit_review.sh` (neu) | Wrapper für Hermes no_agent-Crons |

## 14.08.2026 — UK-Microcap-Gate (Datenqualität `.L`-Ticker)

### Problem
RSS-Quelle `share talk` spült UK-AIM/Nano-Caps (AET.L, BSFA.L, HREE.L, KZG.L, SHOE.L, MAC.L …) in die Watchlist. Diese hatten trotz fehlender/geringer Kurshistorie und minimalem Tagesumsatz potenziell einen Tech-Score → sie tauchten als LONG/SHORT-Entry-Kandidaten auf und verpesteten die Conviction-Verteilung (DQ-Fälle in der Watchlist-Pflege).

### Lösung
Eindeutiges **Historie- + Liquiditäts-Gate** direkt in der einzigen Quelle `get_technical_score()` in `utils.py`:
```python
UK_MIN_BARS         = 200      # ~1 Jahr Handelstage
UK_MIN_TURNOVER_EUR = 500_000  # konsistent mit signal_manager min_liquidity_eur
```
Für `.L`-Ticker gilt: **kein Tech-Score**, wenn `len(df) < 200` **oder** 20-Tage-Ø-Tagesumsatz (aus dem bereits geladenen df, kein Extra-Call) `< 500k€`. Kein Score → kein `tech_score`/`tech_direction` → kein LONG/SHORT-Entry-Kandidat.

### Warum das Gate nicht überflüssig ist
`get_technical_score` verlangte zwar schon `len(df)≥50` und EMA200 (≈200 Bars), aber ein UK-Nano-Cap mit 200+ Bars bekam trotzdem einen Score, obwohl es als AIM-Microcap praktisch unhandelbar ist. Das Turnover-Kriterium ist der eigentliche Differenzierer.

### Verifikation (14.08.2026, Live-Daten)
- **Geblockt (20 `.L` bestätigt):** AET.L, BSFA.L, HREE.L, KZG.L, SHOE.L, MAC.L, 0UKI.L, ECR.L, FCM.L, POLB.L, FMET.L, BOOM.L, KEN.L, ORCP.L, TYM.L, HDD.L, ORR.L, HVO.L, SOU.L, TEK.L → veraltete `tech_score`/`tech_direction` aus der Watchlist gelöscht (refresh_tech_scores leert nicht, wenn `tech` None).
- **Durchgelassen (liquid, korrekt):** GLEN.L, ULVR.L, WISE.L, TATE.L, LGEN.L, RSW.L, AV.L, TSCO.L, ANTO.L, ATYM.L, KGF.L, HSX.L, VOD.L, BARC.L, BP.L u.a.
- **Position-Check:** `signal_manager` hat **0** Paper-Entries gegen sämtliche `.L`-Ticker je eröffnet — Entry-Gates (tech + Liquidität) hatten das bereits verhindert.

### Cron-/Ops-Hinweis
Das Gate wirkt automatisch beim nächsten `technical_validator.py`/`watchlist_manager.py`/`refresh_tech_scores.py`-Lauf. Kein Cron-Neustart nötig.

## 09.08.2026 — Watchlist Cleanup: Dropped-Archivierung

### Problem
`watchlist_cleanup.py` setzte `watching`>60d auf `dropped`, aber `dropped`-Einträge wurden **nie physisch entfernt/archiviert** → die `watchlist`-Tabelle wuchs unbegrenzt (1193 `dropped` bei nur 464 `watching`). Keine FK-Constraints/Trigger verweisen auf `watchlist`, daher war eine Bereinigung sicher.

### Lösung
`watchlist_cleanup.py` (`~/.hermes/scripts/`) erweitert um eine **Archivierungs-Stufe** (Stufe 4) — konservativ, kein Datenverlust:
- Neue Tabelle **`watchlist_archive`** (Migration per `CREATE TABLE IF NOT EXISTS`, alle `watchlist`-Spalten + `archived_at` + `archived_reason`).
- **Artefakte sofort archivieren**: `notes LIKE 'merged into%'` (Dedup-Merges), `'nicht börsennotiert%'` (privat), `'strukturiertes Produkt%'` (Zertifikate).
- **Altersbasiert**: alle übrigen `dropped` mit `last_seen` > 180 Tage (`ARCHIVE_AFTER_DAYS=180`).
- Archivieren = INSERT in `watchlist_archive` + DELETE aus `watchlist` (Rows bleiben als Historie abfragbar).
- Sauberkeit: `watching`/`bought` werden nie angefasst.

### 🔴 Pitfall: DELETE über `rowid`, nicht `id`
Die Dedup (`watchlist_dedup.py`) verwaltet Zeilen via `rowid` (`WHERE rowid=?`), wodurch die `id`-Spalte bei vielen Zeilen **NULL** ist (802 von 1637!). Ein `DELETE ... WHERE id=?` traf bei diesen Zeilen nichts → die Zeile wurde zwar ins Archiv kopiert, aber nicht aus der Watchlist entfernt (Duplikat-Bug, Archiv wuchs fälschlich). **Fix:** `SELECT rowid, *` + `DELETE ... WHERE rowid=?` — konsistent mit dem restlichen System.

### Modi
- `python3 watchlist_cleanup.py` → **Dry-Run** (zeigt nur, was archiviert würde)
- `python3 watchlist_cleanup.py --apply` → tatsächliche Verschiebung. **Cron ruft den Wrapper `watchlist_cleanup_apply.sh` mit `--apply`** (siehe unten), damit die Archivierung automatisch greift.

### Erstlauf (09.08.2026, nach rowid-Fix)
Alle 119 Artefakt-Drops (94 mit gültiger `id` beim ersten Lauf + 25 `id=NULL`-Zeilen via `rowid`) archiviert. Verbleibend: 0 Artefakt-Drops in der Watchlist. Watchlist 1662→**1637** (464 watching, 76 bought, 1097 dropped — die 1097 sind <180d alt, werden in späteren Sonntags-Läufen automatisch archiviert). Offene Positionen (4) unberührt, keine Überlappung zwischen Archiv und offenen Positionen. Lauf ist **idempotent** (2. Lauf = 0 neue).

### Cron
Job `watchlist-cleanup-weekly` (07:30 So) zeigt jetzt auf den Wrapper **`~/.hermes/scripts/watchlist_cleanup_apply.sh`**, der `watchlist_cleanup.py --apply` aufruft → automatische Archivierung.

## 09.08.2026 — Phase 1+2 Fix (Exit-Strategie + Signal-Rauschen)

### Auslöser
Review des Trading-Skills ergab: 77 geschlossene Trades netto -1.230€, 82% SL_HIT, 0% Win Rate über 30 Tage, 100% SL-Exits (0% TP), -8.6% YTD vs SPY +13.1%. 464 Watchlist-Einträge mit Ø 0.27 Conviction = Rauschen. Top-Band (Top 3/5/10) 0 gekauft. 30 Tage lang kein einziger Take-Profit.

### Root Cause #1 — Exit-Strategie mathematisch kaputt
- `signal_manager.py check_open_positions()` zog den Chandelier-Trailing **ohne profit_lock-Gate** nach (Zeile `if atr and not _donchian_primary:`). Der stündliche Check hob den SL bei jedem minimalen Hoch an → Trades wurden vor dem TP gestoppt. Der 15.07.-Fix (`profit_lock_atr`) existierte NUR in `active_exit_check.py`, nicht im stündlichen `signal_manager.py`.
- **Config-Drift:** Die Regime-Adaption (`adapt_strategy()`) schrieb in `trailing_step_atr`, aber der Exit-Check liest `profit_lock_atr` → der Trailing-Delay war komplett wirkungslos.
- `profit_lock_atr = 2.0` > SL (1.5x ATR) → im Sideways war der Wert unerreichbar → 0% TP-Hits.

### Fixes Phase 1
1. **`signal_manager.py`**: profit_lock-Gate in `check_open_positions()` eingebaut (Chandelier-Trailing nur noch ab `pnl_atr >= profit_lock_atr`).
2. **`active_exit_check.py`**: Default `profit_lock_atr` 2.0 → 0.5.
3. **`config.py`**: `ASSET_TYPE_MULTIPLIERS[].profit_lock_atr` alle 2.0/2.5/1.5 → 0.5.
4. **`signal_manager.py` `adapt_strategy()`**: schreibt jetzt in `profit_lock_atr` statt `trailing_step_atr` (Config-Drift behoben).
5. **Donchian-Primary-Exit aktiviert**: `donchian_exit_enabled: true`, `donchian_exit_mode: "primary"` (Turtle-Exit gibt Trends Raum; Initial-SL bleibt harter Floor).
6. `strategy_config.json`: `profit_lock_atr 2.0→0.5`, `trailing_step_atr 2.0→0.75`, `min_confidence 0.8→0.70` (Entry-Starvation behoben), `min_conviction 0.6→0.65`.

### Fixes Phase 2 — Signal-Rauschen
7. **`config.py`**: `MIN_CONVICTION` 0.55 → 0.60.
8. **`watchlist_manager.py`**: Tech-Score-Kandidaten-Schwelle `MIN_CONVICTION*0.5` (0.30) → `MIN_CONVICTION` (0.60) — nur solide Kandidaten bekommen Tech-Scores.
9. **`source_lifecycle.py`**: `min_trades_for_eval` 5→3, `promote_min_trades` 5→3, `remove_no_mention_days` 90→60 (aggressiveres Quellen-Management).
10. **`backtest_gate.py`** (neu): Backtest vor Config-Änderungen — GO/GEDULD/NO-GO basierend auf Sharpe, WR, Trade-Anzahl.

### Erwartung
Exit-Quote von 0% TP auf 20-30% heben. Weniger Rauschen in der Watchlist. Wenn nach 4 Wochen keine Verbesserung → Phase 3 (radikaler Umbau, siehe Cron `phase-3-review-trading` am 06.09.).

## 27.08.2026 — Exit-Asymmetrie: 1R/3R, Zeit-Stopp, Peak-Chandelier

Die Exit-Matrix erzwingt nun in allen neun Asset-/Regime-Kombinationen mindestens 3:1 Ziel/Risiko. `compute_sl_tp()` validiert dies zusätzlich fail-closed. Ein gemeinsames, reines Modul `exit_rules.py` stellt den 7-Handelstage-Zeit-Stopp, den initialen Risikofloor und das monotone Peak-/Trough-Chandelier bereit. `signal_manager.py`, `active_exit_check.py` und `crabel_shadow_eval.py` verwenden diese Regeln zusammen mit `get_exit_config()`; der Trail startet erst ab +1 ATR (`profit_lock_atr=1.0`). Der harte TP-Deckel wurde aus den laufenden Exit-Pfaden entfernt: TP bleibt Ergebnisziel/Backup, der Gewinn-Exit läuft primär über Chandelier beziehungsweise Donchian-Primary. Der Weekly-Drift-Check prüft jetzt zusätzlich `profit_lock_atr=1.0` in JSON, DEFAULT_CONFIG, DEFAULT_EXIT_CONFIG und der vollständigen Matrix.

## 09.08.2026 — glm-5.2-Review: Exit-Matrix + Konsolidierung + Winrate-Messung

### Auslöser
Zweites Review mit dem unabhängigen Modell `z-ai/glm-5.2`. Deckte einen Widerspruch im Phase-1-Fix auf: Der Regime-Override in `adapt_strategy()` trimmte `profit_lock_atr` auf 1.5–2.5 nach oben und machte die 0.5-Senkung (Phase 1A) im Sideways wirkungslos. Außerdem drei überlagerte Trail-/Exit-Quellen mit unklarer Präzedenz.

### Root Cause #2 — Drei überlagerte Exit-Quellen
1. `ASSET_TYPE_MULTIPLIERS` (config.py) — asset-type-spezifisch
2. `regime_configs` (in signal_manager.py) — Regime-Override, überschrieb profit_lock_atr nach oben
3. `strategy_config.json` `profit_lock_atr` — manueller Wert, wurde vom Regime-Override gekillt
Zusätzlich: `active_exit_check.py` kannte Donchian-Primary nicht → zog den ATR-Chandelier parallel zum Donchian-Trail → zwei konkurrierende Stops.

### Fixes
1. **`get_exit_config(asset_type, regime)`** in config.py — deterministische Exit-Matrix (9 Kombinationen STANDARD/TECH/DEFENSIVE × bull/sideways/bear), einzige Quelle für SL/TP/partial/profit_lock.
2. **`adapt_strategy()`** konsolidiert: nutzt die Matrix, entfernt den profit_lock-Tripping-Block (profit_lock_atr bleibt jetzt konstant aus der Matrix = 1.0).
3. **`profit_lock_atr` = 1.0** überall (Matrix + ASSET_TYPE_MULTIPLIERS) — Kompromiss: niedriger als 2.0 (unerreichbar im Sideways), höher als 0.5 (Intraday-Noise).
4. **`active_exit_check.py` AKTION 3**: respektiert Donchian-Primary-Präzedenz (überspringt den Chandelier wenn Donchian fährt), profit_lock aus pos_mult.
5. **`signal_manager.py` `check_open_positions()`**: profit_lock aus pos_mult statt globaler cfg.
6. **`min_confidence` 0.70 → 0.80** — glm hat recht: keine Entry-Starvation (76 bought), die Senkung war fehldiagnostiziert.
7. **`signal_source` beim Entry setzen** (`_derive_signal_source`, aus Kanal-Präfixen rss/x_social/screener/youtube) + **Winrate-nach-Quelle** im nightly_eval-Report (`build_signal_source_line`).

### Wichtige Korrektur zu glm
glm behauptete "10.4% Winrate, Break-Even 21.5%". **FALSCH** — glm verwechselte TARGET_HIT-Zahl (8) mit der Winrate. Reale Winrate: **30/77 = 39%**. Das wahre Problem ist Payoff: Gewinner Ø +62.88€, Verlierer Ø -66.31€ → Payoff 0.95 < 1. Bei 39% WR braucht man Break-Even-WR von 51%. **Die Verluste sind größer als die Gewinne** — fehlende R:R-Asymmetrie in der Durchschnitts-Realisierung (TP 2.5x konfiguriert, aber real nur ~+63€; SL-Verluste bis -364€ durch Gaps/Execution). Das verlagert den Fokus von reiner Winrate auf die Verlustseite verkleinern.

### Erwartung
Exit-Matrix eliminiert die Config-Drift. profit_lock 1.0 erreichbar im Sideways. Winrate-nach-Quelle zeigt ab 09.08. welche Komponente (RSS/X/YouTube/Screener) trägt. min_confidence 0.80 filtert schwache Signale raus (weniger, bessere Trades).

## 09.08.2026 — (a) Gewinner-Exit + (b) Earnings/Makro-Schutz (glm-5.2-Gegencheck)

### Auslöser
Datenanalyse der Verlustseite + Gegencheck durch glm-5.2. Ergebnis: Das Hauptproblem ist NICHT die Winrate (sie ist 39%), sondern dass Gewinner zu früh abgeschnitten werden (Payoff 0.95 statt benötigtem 1.56). Zusätzlich Tag-0-Verluste durch Overnight-Earnings-/Makro-Gaps (05.06.2026: 4 gleichzeitige Tag-0-Stopps = NFP-Tag). WICHTIG: historische Daten liefen mit dem ALTEN Chandelier-System, Turtle-Donchian-Primary ist erst seit heute aktiv.

### Fix (a) — Gewinner-Exit entkoppelt
- **Breakeven-Zug nach Partial-TP entfernt im Donchian-Primary-Modus.** Vorher: nach 50% Partial-TP bei 1.5x ATR wurde der SL auf Breakeven gezogen → der 50%-Rest wurde am BE ausgestoppt bevor der Donchian-Trail/TP greifen konnte. Jetzt: im Donchian-Primary-Modus bleibt der initiale SL stehen, der Donchian-Turtle übernimmt das Stopp-Handling. (Chandelier-Modus behält altes BE-Verhalten.)
- Freigabe zum Laufenlassen: die 8 echten TARGET_HIT-Winner erreichten alle ~100-130% ihres TP — das Ziel ist erreichbar, es wurde nur durch zu enges Trailing/BE abgewürgt.

### Fix (b) — Earnings/Makro-Schutz
1. **`is_macro_event_day()`**: blockt Entries am ersten Freitag (NFP/US-Arbeitsmarkt) — der verlässlichste wiederkehrende Makro-Termin. FOMC/CPI bewusst NICHT per Tageregel (variieren zu stark → falsch-positive Blöcke).
2. **`has_overnight_gap(cur, atr, prev)`**: blockt Entry wenn letzter Close > 60% einer Tages-ATR vom Vortag entfernt ist (Overnight-Earnings-/News-Gap). Fail-open ohne Referenz.
3. **`get_prev_close_ratio(ticker)`**: liefert (current, prev_close) aus dem gecachten df — kein Extra-API-Call.
4. Beide Filter im Entry-Loop integriert (nach Earnings-Blackout, vor Crabel-Gate).

### Wichtige Nuance (Turtle ist erst 1 Tag aktiv)
Historische SL_HIT-„Gewinner" (AMD, NDA, LITE, NVDA) stammen vom defekten Chandelier-System — sie sagen NICHTS über das neue Donchian-Primary-Verhalten aus. Wir dürfen aus alten Daten keine Schlüsse aufs neue System ziehen. Die neuen Exit-Fixes gelten ab heute, die Wirkung zeigt sich erst in den nächsten Wochen.

### Erwartung
- Gewinner laufen weiter (kein BE-Abwürgen im Donchian-Modus) → Payoff steigt Richtung 1.5+
- Keine Tag-0-Entries an NFP + keine Overnight-Gap-Entries → weniger -100€+ Verlusttrades
- Nächster Check nach 4 Wochen (Cron phase-3-review-trading) mit den neuen Daten.

## 09.08.2026 — Top-5-Signale im Tages-Report (Telegram)

### Was
Der `nightly_eval.py` Tages-Report (Mo–Fr 05:00) und Wochen-Report (So 06:00) enthalten jetzt einen **🎯 Top-Signale-Block** mit den 5 besten Watchlist-Kandidaten.

### Implementierung
- `calc_top_signals(con, limit=5)` — Query: `status='watching'` + `ticker IS NOT NULL`, sortiert nach `conviction_score_aged DESC, tech_score DESC, conviction_score DESC`
- `build_top_signals_line(con, limit=5)` — HTML-Formatierung für Telegram: Name, Ticker, Conviction (aged), Tech-Score, tech_direction (📈/📉/➖), Mention-Count
- Integration in beide msg-Formate (täglich + Sonntag) via `signals_line`

### Warum conviction_score_aged
Die rohen `conviction_score`-Werte sind oft 1.0 bei 1 Mention (frisch, aber unbestätigt). `conviction_score_aged` ist alterungsbereinigt (14d-Halbwertszeit) und zeigt etablierte Kandidaten wie Allianz (13x Mentions, 81%) statt 1-Mention-Zufallstreffer.

### Delivery
Kein neuer Cron nötig — nightly_eval sendet bereits täglich. Ziel: `TELEGRAM_HOME_CHANNEL` = `-1003918757178` (Ch_hermster_trade).

## 20.07.2026 — Turtle-Konfluenz-Sprint (Donchian + Asymmetrie)

### Prinzip
Ausgewählte Bausteine des Turtle-Systems (Dennis/Eckhardt 1983) übernommen — bewusst NICHT als Standalone-System. Das Original handelte einen diversifizierten Futures-Korb; Hermes handelt einen korrelierten Aktien-Basket (DAX/MDAX/S&P100), wo der reine Breakout-Edge dünn und diversifikationsschwach ist (Studien: ~5–7% p.a. auf Aktien vs. Futures; Sharpe-Verfall post-2005). Übernommen wurden daher nur die assetklassen-robusten Teile: Donchian-Breakout als Konfluenz-Signal, Donchian-Trailing-Exit (opt-in) und die Asymmetrie-Denkweise im Optimizer. Deterministischer Backbone und bestehende Exit-Pfade bleiben per Default unverändert.

### Punkt 1 — ATR-Risk-Parity-Sizing: bereits vorhanden, NICHT dupliziert
`signal_manager.open_new_positions()` (Vol-Adj-Block) rechnet bereits:
```
risk_amount     = portfolio_value × risk_pct_per_trade   (1.5%)
sl_distance_eur = sl_multiplier(asset_type) × ATR_eur
position_size   = (risk_amount / sl_distance_eur) × price_eur
```
Ein SL-Hit verliert damit exakt `risk_pct_per_trade` des Portfolios — über die ECHTE SL-Distanz (asset-type × ATR), nicht nur „1 ATR". Das ist die korrektere Form der Turtle-N-Idee, FX-aware. Kein Code-Change nötig.

### Punkt 2 — Donchian-Breakout als Konfluenz (`utils.py`)
Neuer Helfer `get_donchian_breakout(ticker, entry_period=20, exit_period=10, slow_period=55)`:
- Nutzt `get_price_data_cached()` → KEINE zusätzlichen API-Calls (df ist nach `get_technical_score` bereits im 5-min-TTL-Cache; gleiche Mechanik wie `get_crabel_patterns`).
- Schließt den laufenden (unfertigen) Tagesbar aus der Kanal-Referenz aus → ein Ausbruch kann sich nicht selbst maskieren.
- Rückgabe: `upper_20/lower_20`, `upper_55/lower_55`, `exit_low/exit_high` (Trailing-Referenz), Breakout-Flags (`breakout_long`, `breakout_short`, `breakout_long_slow`, `breakout_short_slow`).

Integriert als **Score-Komponente 9** in `get_technical_score()`:

| Bedingung | Score |
|---|---|
| 55-Tage-Hoch (S2-Ausbruch) | +1.0 |
| 20-Tage-Hoch (S1-Ausbruch) | +0.5 |
| 20-Tage-Tief (S1-Ausbruch) | −0.5 |
| 55-Tage-Tief (S2-Ausbruch) | −1.0 |

`max_score` bleibt bewusst **10** (wie beim Crabel-Bonus) — sonst würden alle Confidences Richtung 0.5 gestaucht und die kalibrierten `tech_score`-Schwellen im `signal_manager` brechen. Das `donchian`-Dict landet im Return und fließt automatisch in `technical_validator.py`.

### Punkt 3 — Donchian-Trailing-Exit (`signal_manager.py`, `check_open_positions()`)
Config-gated, **Default `off`** (Verhalten unverändert bis manuell aktiviert). Neue Keys in `DEFAULT_CONFIG`:
```python
"donchian_exit_enabled": False,
"donchian_exit_mode":    "off",    # off | ratchet | primary
"donchian_exit_period":  10,       # Turtle S1-Exit: 10-Tage-Gegen-Extrem
```
- **`ratchet`**: Donchian-Extrem als ZUSÄTZLICHER Verengungs-Floor über dem ATR-Chandelier (konservativ; bindet selten, nie riskanter).
- **`primary`**: Donchian-Extrem ERSETZT den Chandelier als Trail (echter Turtle-Exit, gibt Trends Raum). Der Chandelier-Block wird dann übersprungen; der Initial-SL aus `compute_sl_tp` bleibt harter Floor.

Beide Modi **monoton**: heben den Stop für LONG nur an / senken ihn für SHORT nur ab — lockern nie. Damit bleiben Ist-Risiko und Drawdown-Circuit-Breaker (mark-to-market) konsistent. Fixe TP + Partial-TP bleiben unangetastet (Donchian = Zusatz, kein Ersatz). Log-Marker: `🐢 Donchian-Trail`.

### Punkt 4 — Asymmetrie-Denkweise im Optimizer (`strategy_optimizer.py` + `backtester.py`)
**Composite-Score neu** — kein eigenständiger Win-Rate-Term mehr:
```
Expectancy 35% | Payoff-Ratio 20% | Profit Factor 20% | Sharpe 15% | −MaxDD 10%
```
mit `expectancy = WR × avg_win − (1−WR) × avg_loss` und `payoff_ratio = avg_win / avg_loss`. Begründung: ein Trendfolge-Profil (WR ~35–40%, große Winner) darf nicht dafür bestraft werden, oft falsch zu liegen, solange der Erwartungswert stimmt. **BEIDE** `calculate_metrics`-Kopien angepasst — sonst optimiert der Walk-Forward-Pfad (nutzt `backtester`) weiter auf Win-Rate.

**`adjust_from_eval_metrics` entschärft** (zwei anti-asymmetrische Auto-Regeln):

| Alt | Neu |
|---|---|
| WR < 40% → `min_confidence` +5% | nur wenn ZUSÄTZLICH PF < 1.1 (echter Edge-Verlust) |
| TP-Hits < 20% → `atr_tp_multiplier` −0.25 | nur wenn ZUSÄTZLICH PF < 1.2 (weite Ziele zahlen sich nicht aus) |

Bei gesundem Profit Factor ist eine niedrige TP-Hit-Quote ERWARTET — die Gewinne kommen aus dem Trailing, nicht aus dem Fix-TP. `payoff_ratio` + `expectancy` zusätzlich im Metrics-Return und im Optimizer-Log.

**Verifikation** (`verify_turtle.py`, standalone): Turtle-Profil (35% WR, Payoff 3.75, Exp +2.65%/Trade) vs. Mean-Reverter (70% WR, Payoff 0.5, Exp +0.20%/Trade) → NEU-Composite **0.786 vs. 0.221** (alt: 0.503 vs. 0.461, kaum getrennt — der Win-Rate-Term stützte den Mean-Reverter künstlich).

### Deploy-Hinweis
Die erweiterte `get_technical_score`-Rückgabe (`donchian`-Key) + der neue Score-Anteil verschieben die Confidence-Verteilung minimal. Da `max_score` bei 10 bleibt, sollten die Schwellen halten. Nach Deploy einmal `refresh_tech_scores.py` laufen lassen und Watchlist-Confidences gegenprüfen.

### Geänderte Dateien
| Datei | Änderung |
|---|---|
| `utils.py` | `get_donchian_breakout()` neu; Score-Komponente 9 + `donchian`-Key in `get_technical_score()` |
| `signal_manager.py` | Donchian-Trailing in `check_open_positions()`; 3 Config-Keys; Import `get_donchian_breakout` |
| `strategy_optimizer.py` | Composite auf Expectancy/Payoff; `adjust_from_eval_metrics` asymmetrie-bewusst; Expectancy/Payoff im Log |
| `backtester.py` | Composite in `calculate_metrics` konsistent umgestellt |

---

## 17.07.2026 — Hedgefonds-Rollen-Sprint (R1–R4)

### Prinzip
Der deterministische Pipeline-Backbone bleibt unangetastet. LLM-Rollen werden ausschließlich an Urteils-Stellen eingefügt — als kontrollierte, geloggte, budgetierte Bausteine mit Fail-Open-Fallback auf das heutige Verhalten. Exit-Pfade (`check_open_positions`, SL/TP, `_emergency_close_all`) wurden NICHT angefasst.

### Neues Paket `roles/` (Trading-Root)

| Datei | Zweck |
|---|---|
| `roles/__init__.py` | `ensure_roles_schema(con)` — idempotente Migration (`llm_budget_log`, `committee_log`), prozessweit gecacht |
| `roles/budget.py` | Harte Tages-Token-Budgets pro Rolle. `check_and_reserve()` / `record_spend()` / `remaining()` |
| `roles/committee.py` | Investment Committee: Bull → Bear → Risk |
| `roles/devils_advocate.py` | Devil's Advocate (Thesis-Monitor Stufe 2) |

Nutzt den bestehenden `thematic/lib/llm_client.py` und `thematic/lib/prompt_loader.py` (DRY — kein zweiter HTTP-Wrapper). Neue Prompts liegen in `thematic/prompts/`.

**Budgets** (Konstanten in `budget.py`, bewusst NICHT in der Strategy-Config — der `strategy_optimizer` soll daran nicht drehen):
```python
DAILY_TOKEN_BUDGET = {
    "committee":       150_000,
    "devils_advocate":  60_000,
    "extractor_analyst": 400_000,
}
```
Überschreitung → `check_and_reserve()` liefert `False` → Aufrufer geht in den Fail-Open-Pfad + `⚠ Budget`-Zeile.

### Modell-Konfiguration (`thematic/config/thematic_config.json`)
```json
"committee_bull":    "deepseek/deepseek-v4-pro",
"committee_bear":    "openai/gpt-5.4-nano",
"committee_risk":    "google/gemini-2.5-flash-lite",
"devils_advocate":   "deepseek/deepseek-v4-flash-0731",
"extractor_analyst": "deepseek/deepseek-v4-flash-0731"
```
Bull, Bear und Risk sind DREI verschiedene Provider (DeepSeek / OpenAI / Google) — Bull und Bear MÜSSEN verschieden sein, sonst widerlegt sich dasselbe Modell nur mit denselben Biases. `grok-lite` bewusst NICHT fürs Committee (wird vom Breaking-News-Check genutzt, Rate-Limits schonen).

**Modellwahl-Historie (20.07.2026, live per Sonde `probe_model.py` verifiziert):**
- **Bear: Qwen3.5-flash → gpt-5.4-nano.** Qwen ist ein Reasoning-Modell und verbrannte ~5400 nicht-abschaltbare Reasoning-Tokens pro Call — bei `max_tokens=800` lief der Denkprozess voll und lieferte `content=""` (`finish_reason=error`), was jeden Bear-Call in Fail-Open trieb. `reasoning:{exclude:true}` unterdrückt nur die Ausgabe, nicht die Abrechnung. gpt-5.4-nano ist denkfrei (`reasoning_tokens=0`) und liefert die inhaltlich schärfste Gegenanalyse der getesteten Kandidaten (benennt konkrete fehlende Trigger statt höflicher Relativierung).
- **Bull: DeepSeek-flash → DeepSeek-pro.** Bessere Argumentationsqualität, ebenfalls denkfrei.
- Ergebnis: **~3500 Tokens pro 3-Rollen-Check** statt ~9000 mit Qwen. 150k-Committee-Budget trägt damit ~40 Checks/Tag.
- **Verworfen:** tencent/hy3 (nur höfliche Relativierung, kein scharfer Angriff), grok-4-fast (bei OpenRouter deprecated → Grok 4.3), gemini-3.1-flash-lite & deepseek-v4-pro-als-Bear (Provider-Kollision mit Risk bzw. Bull).
- **Bekannter Rest-Ausreißer:** DeepSeek-pro (Bull) läuft in ~1 von 7 Calls in einen Longtail und stößt an den 800er-Deckel → Truncation → Fail-Open. Im Shadow-Mode kosmetisch (Trade läuft durch wie ohne Committee). JSON-Repair-Fallback erst bauen, wenn echte Läufe eine Ausreißerquote >5 % zeigen.

---

### R1 — Investment Committee (Pre-Entry Gate, Shadow-Mode)

**Datei:** `scripts/signal_manager.py`, `open_new_positions()`

**Einbaupunkt:** im Kandidaten-Loop NACH dem Crabel-Gate, VOR dem VIX-Halving-Block. Begründung: das Committee ist das teuerste Gate und darf nur Kandidaten sehen, die alle billigen deterministischen Gates (Weekly Trend, Allokation, Sektor, Korrelation, Liquidität, Earnings, Segment, Breaking News, Crabel) passiert haben. So zahlen wir LLM-Kosten nur für Kandidaten, die sonst tatsächlich gekauft würden.

**Neue Config-Keys** (in `DEFAULT_CONFIG`):
```python
"committee_enabled":            True,
"committee_mode":               "shadow",   # shadow | active
"committee_max_checks_per_run": 6,
```
Der Loop läuft nach `priority_score` absteigend → das Committee prüft automatisch die besten Kandidaten zuerst. Nach Erreichen des Limits laufen weitere Kandidaten OHNE Committee (Fail-Open + Log-Zeile).

**Drei sequenzielle Calls** (Bear braucht Bulls These, Risk braucht beide — kein Threading, kein Async):
1. **Bull Analyst** → `{"thesis", "conviction", "key_assumptions"}`
2. **Bear Analyst** → erhält die Bull-These und MUSS sie angreifen → `{"counter_thesis", "severity", "dealbreaker", "dealbreaker_reason"}`
3. **Risk Officer** → erhält beide Thesen + Portfolio-Kontext, bewertet die POSITION (Klumpenrisiko, Regime-Fit), nicht die Aktie → `{"verdict", "size_factor", "rationale"}`

**Entscheidungsregel — deterministisch im Code, nicht im LLM:**
```python
if risk_verdict == "VETO" and bear_dealbreaker:
    final = "VETO"
elif risk_verdict in ("VETO", "REDUCE"):
    final = "REDUCE"; size_factor = clamp(risk_size_factor, 0.5, 1.0)
else:
    final = "APPROVE"; size_factor = 1.0
```
Ein VETO braucht ZWEI unabhängige Stimmen (Risk + Bear-Dealbreaker) — ein einzelnes Modell darf nie allein einen Trade killen. Ein Risk-VETO ohne Bear-Dealbreaker wird zu REDUCE mit `size_factor=0.5` abgeschwächt. Ein unbekanntes/unparsbares Verdict → APPROVE.

**Shadow-Mode (Default):** ändert NICHTS am Verhalten, schreibt nur `committee_log` (`would_block=1` bei VETO). Aktivierung erst nach 2–4 Wochen Auswertung (R4).

**Kontext-Beschaffung:** Die offenen Positionen werden mit EINER Query VOR dem Loop geladen (`committee_positions_text`), nicht pro Kandidat — zusätzliche Queries unter der äußeren Connection sind in diesem Projekt eine bekannte Lock-Quelle. `regime`, `macro`, `sector_exposure`, `portfolio_value`, `drawdown_pct`, `current_price`, `atr`, `crabel` sind bereits im Scope. News via `tavily_client.fetch_ticker_news(ticker, days=1)`, max. 5 Snippets à 200 Zeichen; Tavily-Fehler → `"Keine News verfügbar."`, kein Abbruch.

**Fail-Open:** Jeder Exception-Pfad in `run_committee()` → `{"final_verdict": "ERROR_FAIL_OPEN", "size_factor": 1.0}` + Log-Eintrag. Es wird NIE eine Exception in den Entry-Loop propagiert. Zusätzlich umschließt der Aufrufer den ganzen Block mit `try/except`.

**Audit-Trail:** `committee_log.entry_happened` wird nach erfolgreichem `INSERT INTO positions` per `mark_entry_happened()` auf 1 gesetzt → Join-Basis für R4.

---

### R2 — Devil's Advocate im Thesis Monitor

**Datei:** `scripts/thesis_monitor.py`

**Problem:** Stufe 1 stellt mit einem einzigen Gemini-Prompt die Frage „ist die These intakt?" — das erzeugt Bestätigungsbias. Verlustpositionen bleiben zu lange INTACT.

**Trigger für Stufe 2** (sonst 0 Zusatzkosten):
- Stufe-1-Verdict ist `INTACT` oder `UNCERTAIN` **UND**
- die Position steht ≥3 % im Minus (`DEVIL_PNL_TRIGGER = -0.03`)

PnL richtungssicher in `_unrealized_pnl_pct()`:
```
LONG:  (price − entry) / entry
SHORT: (entry − price) / entry
```
Preis über `get_price_data_cached()` aus `utils`. Preis nicht ermittelbar → Stufe 2 entfällt. Preis und `entry_price` sind beide in Heimwährung → keine FX-Umrechnung nötig, das Verhältnis ist währungsneutral.

**Merge-Regel — deterministisch, konservativ:**
```python
if kill_probability >= 0.70 and verdict in ("INTACT", "UNCERTAIN"):
    verdict = "WEAKENING"
    rationale = f"[Devil's Advocate p={p:.2f}] " + "; ".join(kill_reasons) + " | " + rationale
```
Bewusst NUR Downgrade auf WEAKENING, nie direkt BROKEN: der bestehende, getestete 3-Tage-WEAKENING-Streak (`_check_weakening_streak`) übernimmt die Eskalation. **Es wird kein neuer Exit-Pfad gebaut** — das minimiert das Risiko neuer Short-/Exit-Bugs auf null.

Ab `kill_probability >= 0.85` zusätzlich sofortige Telegram-Info mit den 3 Gründen (reine Information, keine Aktion).

**Schema:** idempotente Migration `_migrate_devil_columns()` (Muster `PRAGMA table_info`):
```sql
ALTER TABLE thesis_status_log ADD COLUMN devil_kill_prob REAL;
ALTER TABLE thesis_status_log ADD COLUMN devil_reasons TEXT;  -- JSON-Array
```
Beide Felder im bestehenden INSERT mitgeschrieben (NULL wenn Stufe 2 nicht lief). News werden aus Stufe 1 wiederverwendet — kein zweiter Tavily-Call. Budget erschöpft → Stufe 2 entfällt, Stufe-1-Verdict gilt.

Zusätzlich: `busy_timeout=30000` in `main()` gesetzt (`_db_connect()` nutzt raw `sqlite3.connect`).

---

### R3 — 2-Pass-Extractor

**Datei:** `scripts/signal_extractor.py`

**Problem:** EIN Mega-Prompt pro 15k-Chunk erledigte gleichzeitig Firmenerkennung, Namens-Normalisierung, Sentiment, Stärke, Preisziele und Action-Hint. Die Erkennungsleistung ist gut, aber Sentiment/Stärke sind Nebenprodukte eines überladenen Prompts.

**Pass A — „Scout"** (pro Chunk, `deepseek-v4-flash` wie heute): NUR Erkennung. Erkennungsregeln wortgleich zum Legacy-Prompt übernommen — die Erkennungsleistung soll sich durch den Umbau NICHT ändern. Zusätzlich pro Firma `context_snippet` (wörtliches Zitat, max 300 Zeichen) und `rough_sentiment`.

**Pass B — „Analyst"** (EIN Call pro Video, Modell `extractor_analyst`): erhält NICHT das Transkript, sondern nur die deduplizierte Firmenliste mit Snippets (max. 3 pro Firma, `MAX_SNIPPETS_PER_COMPANY`). Liefert das fundierte Urteil.

**Kompatibilität:** Das Ergebnis-Objekt pro Video bleibt feldkompatibel (`name/sentiment/strength/reason/mentioned_price/price_target/action_hint` + `market_outlook`, `key_themes`, `source`). `catalyst` ist rein additiv. **`watchlist_manager.py` wurde NICHT angefasst** — Katalysator-Nutzung in der Conviction ist Out-of-Scope (späterer Sprint, erst wenn Daten vorliegen).

Der Name kommt IMMER aus dem Scout — der Analyst darf ihn nicht umschreiben, sonst bricht das Matching im `company_normalizer`. Ungültige Enum-Werte (sentiment/strength/action_hint/catalyst) werden auf sichere Defaults normalisiert.

**Fallback-Kaskade:**
1. Analyst schlägt fehl (Retries/Parse/Budget/Netzwerk) → Firmen aus Pass A mit `sentiment = rough_sentiment`, `strength = "moderate"`, `reason = context_snippet[:150]`, `action_hint = "watch_for_reversal"`, `catalyst = "none"`. Die Pipeline liefert damit NIE weniger als heute.
2. Auch pro Firma: lässt der Analyst eine Firma aus, kommt sie über den Scout-Fallback rein → die Firmenmenge des 2-Pass-Pfads ist garantiert die des Scouts.
3. Umschalter `EXTRACTOR_MODE` via Environment (Default `two_pass`, `legacy` = heutiger Code-Pfad vollständig erhalten). Rollback ist ein Einzeiler in der Crontab/Env, kein Deploy.

**Refactoring:** `call_api` → generisches `_call(model, system_prompt, user_content)` + `_call_cascade()`, die Legacy-, Scout- und Analyst-Pfad teilen.

> ⚠️ **Wichtiges Detail im Fehlerverhalten von `_call_cascade()`:** Nur ein `json.JSONDecodeError` eskaliert auf die nächste Kaskaden-Stufe. Alle anderen Exceptions (Netzwerk, `KeyError`) propagieren nach oben — genau wie im bisherigen `call_api()`. `main()` setzt das Video dann auf `status='error'` + `error_count+1` → Retry beim nächsten Lauf. Würde die Kaskade sie schlucken, wäre das Video `status='done'` mit 0 Firmen und käme nie wieder → stiller Datenverlust. Einzige Ausnahme: der Analyst-Call fängt selbst ab und fällt auf die Scout-Daten zurück, weil Pass A da bereits gelaufen und bezahlt ist.

---

### R4 — Auswertung & Aktivierung

**Datei:** `scripts/nightly_eval.py` → neue Funktion `calc_committee_shadow(con, days)`

Join `committee_log` × `positions` über (Ticker, Richtung, Entry-Datum). Nur Zeilen mit `entry_happened=1` sind auswertbar. Ausgabe im Tages-Report (14d) bzw. Wochen-Report (30d):
- Checks gesamt, aufgeschlüsselt nach APPROVE / REDUCE / VETO / Fehler
- **`veto_hit_rate`**: Anteil der VETO-Trades, die im Minus endeten. >50 % = das Committee hat überwiegend Verlierer erwischt
- P&L der VETO- und APPROVE-Kohorte, noch offene VETO-Trades

Fehlt `committee_log` (Sprint nicht deployed) → `None`, kein Fehler.

**Aktivierung** nur, wenn die Shadow-Daten zeigen, dass VETOs überwiegend Verlusttrades getroffen hätten: `committee_mode` in der persistierten Strategy-Config auf `active` — über `save_config()`, damit die Config auf Disk landet (bekannte Persistenz-Bug-Klasse).

---

### Explizit Out-of-Scope (unverändert)
- Keine autonome Agenten-Orchestrierung, kein LLM entscheidet über Pipeline-Ablauf
- Keine Änderungen an Exit-Logik, SL/TP, Drawdown-Mechanik, `watchlist_manager`, Dashboard
- Keine neuen Cronjobs, keine neuen Daemons
- Katalysator-Feld fließt NICHT in Conviction/Scoring (nur Datensammlung)
- Kein Multi-Turn-Debattieren zwischen den Rollen (genau eine Runde Bull → Bear → Risk)

---

## 15.07.2026 — Post-Mortem Umbau

### Auslöser
Systematische Analyse der 69 geschlossenen Trades ergab:
- Total P&L: -839,95€, Win Rate: 43,5%
- **75% aller Trades enden im SL** (SL_HIT), **0% erreichen TP** (TARGET_HIT)
- **0-3 Tage Haltedauer: -1.867€** (51% aller Trades, 22,9% WR)
- **8-14 Tage Haltedauer: +363€** (76,9% WR)
- Mai: +1.179€ (70,8% WR) vs Juni: -1.480€ (31,3% WR) — Regime-Wechsel Bull→Sideways

### Änderung 1: Trailing erst ab +2x ATR aktivieren

**Datei:** `scripts/active_exit_check.py` — AKTION 3 (Trailing Stop)

**Vorher:** Trailing wurde ab Entry aktiv — bei jedem normalen Pullback (0.75x ATR) triggert der Trailing Stop, noch bevor der Trade +2x ATR erreicht. Folge: 75% SL_HIT, 0% TP_HIT.

**Nachher:** Trailing wird erst aktiv wenn der Trade mindestens +2x ATR (`profit_lock_atr`) im Plus ist. Bis dahin läuft der Trade ungestört mit dem initialen Stop-Loss.

**Änderung:**
```python
# ALT: Trailing läuft sofort ab Entry
trailing_step = pos_mult["trailing_step"]
if direction == "LONG":
    ...

# NEU: Trailing erst aktiv ab +2x ATR im Plus
trailing_step = pos_mult["trailing_step"]
profit_lock_threshold = cfg.get("profit_lock_atr", 2.0)
if pnl_atr >= profit_lock_threshold:
    if direction == "LONG":
        ...
```

**Erwartung:** SL_HIT von 75% → ~50%, TP_HIT von 0% → ~20%

---

### Änderung 2: Quellen-Weighting nach P&L statt Win Rate

**Datei:** `scripts/source_lifecycle.py` — `adjust_weights()`

**Vorher:** Gewicht wurde basierend auf `win_rate_90d` angepasst. Folge: Quellen mit hoher WR aber negativem P&L (z.B. beating beta: 67% WR, -18€/Trade) wurden hoch gewichtet.

**Nachher:** Gewicht wird basierend auf `avg_pnl_per_trade` angepasst. Quellen mit positivem P&L werden hochgesetzt (≥ +10€ → +15% Weight), Quellen mit negativem P&L runtergesetzt (≤ -10€ → -20% Weight).

**Neue Thresholds:**
| Threshold | Alt (WR) | Neu (P&L) |
|-----------|----------|-----------|
| Boost | `win_rate_90d >= 60%` | `avg_pnl_per_trade >= +10€` |
| Penalize | `win_rate_90d < 35%` | `avg_pnl_per_trade <= -10€` |

**Effekt:** `ticker symbol: you` (+108€/Trade) → hoch, `financial education` (-113€/Trade) → runter.

---

### Änderung 3: Regime-Adaptive Parameter

**Datei:** `scripts/signal_manager.py` — `adapt_strategy()`

**Vorher:** Die Funktion passte nur SL/TP und Confidence an, ohne klare Regime-Basis. Trailing-Step war global 0.75x ATR.

**Nachher:** Die Funktion setzt zuerst eine **Regime-Basis** (überschreibt die Default-Werte aus strategy_config.json), DANN kommen die Trade-basierten Anpassungen.

| Regime | SL Multi | TP Multi | Trailing ab | Min. Confidence |
|--------|----------|----------|-------------|-----------------|
| **Bull** | 1.5x | 3.5x | +1.5x ATR | 0.65 |
| **Sideways** | 1.5x | 2.5x | +2.0x ATR | 0.70 |
| **Bear** | 2.0x | 3.0x | +2.5x ATR | 0.75 |

**Regime-Erkennung:** Läuft bereits in `fundamental_data.py` (US-Regime 60% + EU-Regime 40% Gewichtung) und wird in `regime_history`-Tabelle gespeichert. `get_current_regime()` in `signal_manager.py` liest den letzten Eintrag.

**Regime-Basis-Logik:**
```python
regime_configs = {
    "bull":     {"sl": 1.5, "tp": 3.5, "trailing_atr": 1.5, "confidence": 0.65},
    "sideways": {"sl": 1.5, "tp": 2.5, "trailing_atr": 2.0, "confidence": 0.70},
    "bear":     {"sl": 2.0, "tp": 3.0, "trailing_atr": 2.5, "confidence": 0.75},
}
```

---

### Offene Punkte / Nächste Schritte
- Regime-Erkennung verbessern: aktuell 60/40 US/EU, könnte um VIX-Term-Structure ergänzt werden

---

## 23.07.2026 — PnL-Update für offene Positionen

### Problem
Offene Positionen hatten `pnl_eur = NULL` in der DB, weil das PnL zwar im `check_open_positions`-Loop berechnet (`pnl_pct * position_size - commission`), aber nie zurück in die DB geschrieben wurde. Geschlossene Positionen bekamen ihren PnL beim Exit-Code (Routine 5), offene blieben NULL.

### Fix
`signal_manager.py` Zeile 639–646: Direkt nach der PnL-Berechnung wird jetzt ein UPDATE in die DB geschrieben:

```python
con.execute(
    "UPDATE positions SET pnl_eur=?, pnl_pct=? WHERE id=?",
    (round(pnl_eur, 2), round(pnl_pct * 100, 2), pos["id"])
)
con.commit()
```

Das Update läuft **vor** den Exit-Checks (SL/TP/Trailing/Partial-TP). Wenn ein Exit triggert, überschreibt der Exit den PnL mit dem finalen Wert. Das ist Absicht — der Zwischenstand wird pro Tick erfasst, der finale Wert beim Close.

### Aktuelle Positionen (23.07., nach Fix)
| Ticker | Entry | Jetzt | P&L |
|--------|-------|-------|-----|
| AAPL | 314.47 | 325.89 | +8.60€ (+3.6%) |
| PANW | 326.35 | 335.28 | +19.44€ (+2.7%) |
| ANET | 186.26 | 174.87 | -43.44€ (-6.1%) |
| DIS | 95.85 | 95.87 | -0.20€ (-0.0%) |

### Nächster Pipeline-Lauf
Ab morgen 03:30 aktualisiert der signal_manager das PnL automatisch bei jedem Tick.

---

## 23.07.2026 — Finn-loop (Hermes-Adaption)

### Was ist der Finn-loop?
3-Skill-System von Alex Finn (finna) für deterministische Agent-Workflows:
**Spec → Build → Review, Humans merge.**

Adaptiert von Claude Code + Linear auf Hermes + Obsidian Vault.

### Skills (3 neue)
| Skill | Datei | Zweck |
|-------|-------|-------|
| `finn-spec` | `~/.hermes/skills/meta/finn-spec/SKILL.md` | Interviewt Martin, schreibt Task-Spec mit ACs + NGs |
| `finn-build` | `~/.hermes/skills/meta/finn-build/SKILL.md` | Claimt agent-ready Task, implementiert, reviewed |
| `finn-review` | `~/.hermes/skills/meta/finn-review/SKILL.md` | Reviewt gegen Spec, 3-stufiges Verdict |

### Queue
- Tasks: `/root/obsidian-vault/wiki/tasks/<name>.md`
- Queue: `/root/obsidian-vault/wiki/tasks/README.md`
- Martin setzt `agent-ready: true` im Frontmatter — das ist das Approval-Gate

### Workflow
```
Idee → finn-spec → Spec-Datei → Martin: agent-ready
  → finn-build → Implementierung → needs-review
  → finn-review → Verdict
    → approved → Martin merged
    → changes-requested → Build fix → Re-Review
    → needs-human-review → Martin entscheidet
```
- Wiki-Seite: `wiki/concepts/Finn-loop (Hermes Adaption).md`

---

## 24.07.2026 — Last30days Integration ins Trading

### Was
Zwei Integrationen des Last30days-Skills in den Trading-Agenten:

**Option A: Weekly Cron** `last30days-trading-weekly` (fc93e6e82376)
- Sonntag 08:00, Telegram
- Analysiert Top-5 Watchlist-Kandidaten über Reddit, HN, X, GitHub, Web
- Report mit Sentiment, Risikofaktoren, Kauf-Empfehlung pro Kandidat

**Option B: Pre-Trade Gate** (signal_manager.py, nach Zeile 1582)
- `last30days_gate.py` — Standalone Python-Script, Google News RSS (kein API-Key)
- Keyword-basierte Sentiment-Analyse: 32 negative + 18 positive Keywords
- Drei Stufen: `ok` (exit 0), `warning` (exit 1), `block` (exit 2)
- Nur für HIGH-Conviction Kandidaten (≥0.80)
- Shadow-Validator: block → kein Entry, warning → Log, ok → kein Eingriff
- Fail-Open: Fehler im Gate stoppen den Entry nicht

### Relevante Dateien
- `scripts/last30days_gate.py` — Pre-Trade Gate Script
- `scripts/signal_manager.py` — Integration als letzter Filter vor Entry
- `~/.hermes/skills/meta/last30days/SKILL.md` — Hermes Skill
- Backtest der neuen Parameter auf historischen Daten (Mai vs Juni)
- Short-Trade-Regel: aktuell 28,6% WR — prüfen ob Shorts im Sideways pausiert werden sollen
|
|---
|
|## 30.07.2026 — Sector-Blacklist (Probation-Mechanismus)
|
|### Problem
|Der Industrials-Sektor war 19 Tage geblockt, aber der Probation-Trade wurde nie ausgeführt. Der Blacklist-Mechanismus war nur ein statischer Hinweis in `strategy_config.json` — keine echte Blockade-Logik.
|
|### Lösung
|**Neue DB-Tabelle `sector_blacklist`** (idempotent in `watchlist_manager.py`):
|```sql
|sector TEXT PK, blocked_at, cooldown_days (14), probation_status (NULL/active/success/failed),
|probation_entry_ticker, probation_opened_at, probation_pnl
|```
|
|**Helper `get_sector_blockade_info(con)`** in `watchlist_manager.py`:
|- Berechnet Cooldown-Resttage und Probation-Status
|- Cooldown abgelaufen + kein Probation-Status → Fenster OFFEN
|- Ausgabe im Watchlist Manager Output
|
|**`export_watchlist.py`**: Liest jetzt aus DB statt `strategy_config.json`. Zeigt echten Status: Cooldown-Resttage, Probation-Fenster, aktive Trades.
|
|**Dashboard**: Sektor-Status aus DB statt JSON. Farbcodiert: 🚫 Cooldown, 🟡 Fenster offen, 🟢 aktiv, ✅ bestanden, ❌ fehlgeschlagen.
|
|**Migration**: Alte `sector_blacklist` aus `strategy_config.json` wird einmalig in DB überführt.
|
|**Industrials-Reset**: `blocked_at = 2026-07-11` (vor 19 Tagen) → Cooldown (14d) endete 25.07. → Probation-Fenster ist offen, ein Trade möglich.
|
|### Geänderte Dateien
|| Datei | Änderung |
||---|---|
|| `watchlist_manager.py` | `get_sector_blockade_info()` neu; Migration + Output; Import STRATEGY_CONFIG_PATH |
|| `export_watchlist.py` | DB-Ladung statt JSON; echter Status in Markdown |
|| `dashboard.py` | DB-Ladung statt JSON; farbcodierte Anzeige mit Resttagen |
|
|---
|
|## 30.07.2026 — Signal-Kalibrierung + Top-Band-Validierung
|
|### Auslöser
|Post über Pattern-Detection-Pipeline: zwei Probleme identifiziert — (1) keine Kalibrierung zwischen lauten und leisen Signalquellen, (2) keine separate Validierung der Top-Band-Einträge.
|
|### Punkt 1: Signal-Kalibrierung nach avg_pnl_per_trade
|
|**Neue Funktion `get_channel_calibration(con)`** in `watchlist_manager.py`:
|Liest `avg_pnl_per_trade` aus `source_registry` und wandelt in Faktor [0.3, 2.0]:
|| avg_pnl | Faktor | Bedeutung |
||---------|--------|-----------|
|| ≥ +50€  | 1.5x   | Starke Quelle |
|| ≥ +20€  | 1.2x   | Gute Quelle |
|| ≥ -5€   | 1.0x   | Neutral |
|| ≥ -20€  | 0.7x   | Schwache Quelle |
|| < -20€  | 0.3x   | Schlechte Quelle |
|| Keine Daten | 1.0x | Unbekannt |
|
|**Integration**: `calculate_conviction()`, `calculate_conviction_bear()`, `calculate_conviction_aged()` — alle drei akzeptieren jetzt optionalen `calibration`-Parameter. Der Faktor multipliziert das Channel-Weight pro Mention. Eine Quelle mit +50€/Trade bekommt 1.5x Gewicht, eine mit -30€/Trade nur 0.3x.
|
|**Effekt**: Eine leise, präzise Quelle (z.B. 5 Mentions, +50€/Trade) überstimmt eine laute, mittelmäßige Quelle (100 Mentions, -10€/Trade) nicht mehr.
|
|### Punkt 2: Top-Band-Validierung
|
|**Neue Funktion `calc_top_band_metrics(con)`** in `nightly_eval.py`:
|Validiert separat die Top-3/5/10 der Watchlist (nach conviction_score):
|- Wieviele wurden gekauft (bought_count)
|- Win Rate der gekauften
|- Sum P&L
|- Zeitfenster: 30 Tage
|
|**Migration**: `eval_metrics` Tabelle um Spalten `top3_win_rate`, `top5_win_rate`, `top10_win_rate`, `top3_bought`, `top5_bought`, `top10_bought`, `top3_pnl`, `top5_pnl`, `top10_pnl` erweitert.
|
|**Output**: Tägliche Ausgabe im Nightly Eval — separate Metriken für das Top-Band, nicht nur den Durchschnitt.
|
|### Geänderte Dateien
|| Datei | Änderung |
||---|---|
|| `watchlist_manager.py` | `get_channel_calibration()` neu; Kalibrierung in allen 3 Conviction-Funktionen |
|| `nightly_eval.py` | `calc_top_band_metrics()` neu; Migration + INSERT; Tägliche Ausgabe |
| `social_scanner.py` | `fetch_twitter_grok()`, `fetch_x_search_grok()`, `_call_x_search()`, `_resolve_xai_token()`, `_parse_grok_json()` neu; Grok primär, twitterapi.io Fallback; `get_active_x_search_queries()` für generische X-Searches |

## 31.07.2026 — Grok Twitter Integration

### Problem
Twitter/X-Daten flossen ausschließlich über `twitterapi.io` (Drittanbieter, limitierte Credits). Grok (xAI) hat nativen X-Zugriff via `x_search`-Tool in der Responses API.

### Lösung
- Neue `fetch_twitter_grok()` in `social_scanner.py` — Single-Call: Grok sucht + extrahiert Unternehmen in einem xAI API-Call
- Fallback auf twitterapi.io bei Fehler (Fail-Open) mit Telegram-Benachrichtigung im Trading-Channel
- `_resolve_xai_token()` liest OAuth-Token aus `auth.json` (credential_pool.xai-oauth, sortiert nach `last_refresh` statt nur erstem Eintrag — 3 parallel existierende Tokens möglich)
- `_call_x_search()` nutzt xAI Responses API (`/v1/responses`) mit `x_search`-Tool
  - Antwort-Parsing aus `output[].content[].text` (nicht `output_text` — das ist bei Responses API `None`)
  - Citations aus inline `url_citation`-Annotations
- Model: `grok-4.5` (grok-2-latest existiert nicht mehr auf xAI, nur Responses API Models wie grok-4.5/grok-3 funktionieren)
- `fetch_x_search_grok()` für generische X-Searches (Keyword/Thema, `source_type='x_search'`)
- `_send_telegram_alert()` für Fallback-Benachrichtigungen via `TELEGRAM_CHAT_ID`
- `beneficiary_a` in `thematic_config.json` von `grok-lite` auf `deepseek/deepseek-v4-flash-0731` umgestellt

### Geänderte Dateien
| Datei | Änderung |
|---|---|
| `scripts/social_scanner.py` | +170 Zeilen: 5 neue Funktionen, `main()` priorisiert Grok, Telegram-Alert bei Fallback |
| `thematic/config/thematic_config.json` | `beneficiary_a: grok-lite` → `deepseek/deepseek-v4-flash-0731` |

---

## 2026-08-27 — 6-Monats-Review: profit_lock-Drift, Guardrail, Backtest-Befund

### Problem (Kontext: Bot 6 Monate ohne Profit)
Gesamt-P&L −1.165 € auf 81 geschlossene Trades (Start 10k). Win-Rate 40,7 %,
Payoff 0,91 (<1 = Killer), EV −14,4 €/Trade. 66× SL_HIT vs 9× TARGET_HIT.
Regime-Label durchgehend "bull" obwohl Juni/Juli real Chop waren. Benachteiligung durch
Drawdown-Brake seit 08.07. (≈79 % Cash, August nur 3 Trades). Alpha vs SPY YTD: −20 pp.

### Fix 1 — profit_lock-Drift (Config/Anzeige, kein Execution-Pfad mehr)
Die **Exit-Execution** war bereits konsolidiert (alle 3 Pfade lesen `get_exit_config`,
Matrix = 1.0 — verifiziert per grep: KEINE echten `get_asset_multipliers(`-Aufrufe mehr).
Aber `profit_lock_atr` lebte **verwaist** als `0.5` in `strategy_config.json` UND in
`DEFAULT_CONFIG` (signal_manager Zeile 56) → `backtest_gate.py` und Dashboard zeigten "0.5x".
**Fix:** beide auf `1.0` angeglichen (SSOT = Matrix).

### Fix 2 — operating_mode Guardrail (Punkt 1 des Reviews)
Bot hat **keinen Echtgeld-Pfad** (kein Broker-Modul, schreibt nur in `positions` = Paper).
Guardrail explizit gemacht: `strategy_config.json` → `"operating_mode": "paper_experiment"`.
Regelbasierte Trend-Edge-Systeme (Amumbo-SMA200, FX-Paper-Bot) laufen bereits parallel.

### Backtest-Befund (Variante B & C, `scripts/backtest_variants.py`)
Neues Script: simuliert alternative Exit-/Signal-Logik auf den **realen 81 gehandelten
Positionen** (kein Lookahead — ATR/R am Entry-Tag, OHLC danach).
- **Variante C** (1R/3R + 7d-Zeitstopp + Chandelier 2×ATR vom Peak ab +1R):
  Auf den 46 sauberen Trades (Preisdaten vorhanden) **Verbesserung −2.802 € → −2.088 €**
  (+700 €), Payoff 3.07 (avg_win 3.0R vs avg_loss −1.0R). ABER WR kollabiert auf 7 %:
  **nur 3/46 erreichen +3R, 43× SL** → der Exit ist NICHT das Kernproblem.
- **Variante B** (Crowd-Veto via `mention_count ≥ 5`): hilft nicht — crowded −482 € vs
  quiet −699 €, beide negativ. Crowd-Mention ist nicht der Differenzierer.
- **Caveat:** 36/82 Trades `NO_DATA` (delisted/Exoten-Suffixe), die fehlenden waren
  überproportional Gewinner (+1.620 € real) → C-Ergebnis ist **konservativ**.
  `mention_count` ist AKTUELL, nicht Point-in-Time.
- **Kernaussage:** Weder Exit-Fix noch Crowd-Filter retten dieses Signal. Die Selection
  (LLM-extrahierter Influencer-Sentiment) ist negativ-EV unabhängig vom Exit.
  → Selection-Neuaufbau + ggf. C-Exit-Übernahme laufen als Finn-loop-Task.

### Geänderte Dateien
| Datei | Änderung |
|---|---|
| `data/strategy_config.json` | `profit_lock_atr` 0.5→1.0; `+operating_mode: paper_experiment` |
| `scripts/signal_manager.py` | `DEFAULT_CONFIG.profit_lock_atr` 0.5→1.0 |
| `scripts/backtest_variants.py` | NEU — Varianten-Backtest auf realen Trades |

---

## 2026-08-27 — Wöchentlicher Strategie-Review-Cron

**Neu:** `scripts/weekly_strategy_review.py` — wöchentlicher Report der
Post-Umbau-Kennzahlen (SL_HIT-Quote, Payoff, Win-Rate, EV/Trade,
Momentum-Gate-Blockaden), Vergleich "vor/nach dem 27.08.-Umbau". Sendet
Telegram-Report in `Ch_hermster_trade` (HTTP 200 verifiziert).

- **Hermes-Cron:** `weekly-strategy-review` (b907fdfdba5c), So 09:00, no_agent
- **Wrapper:** `~/.hermes/scripts/weekly_strategy_review.sh` (chdir + PYTHONPATH + .env)
- **Zielmarken:** SL_Quote < 60 % | Payoff > 1.5 | EV > 0
- **Datenquelle:** `positions`-Tabelle live (eval_metrics.avg_r_multiple ist 0.0/unbrauchbar → nicht nutzen)

**Pitfall erneut:** Telegram `parse_mode=HTML` scheitert an nackten `<`/`>`
(z.B. "SL_Quote < 60%") — "Unsupported start tag". Fix: HTML-escape der rohen
Daten + Formulierung "unter/über" statt `<`/`>`. Dasselbe Muster wie die
HTML-Telegram-Nachrichten in nightly_eval.

---

## 2026-08-27 — Nasdaq-Momentum-Screener (Task 3, Finn-loop)

**Neu:** `screener_source.py` scannt jetzt zusätzlich zum Alt-Universum (DAX/MDAX/SP100)
ein breites **US-/Nasdaq-Universum** (Martins Scope: Nasdaq-100 + ~500 liquide
US-Growth/Mid-Caps). `data/us_universe.csv` (600 Zeilen).

**Architektur (2-stufig, review-approved):**
- `_build_universe()` liefert `(ticker, channel)`-Tupel; Alt → `channel='screener'`,
  Nasdaq → `channel='screener_nasdaq'` (eigene Quelle für getrenntes P&L).
- `stage1_prefilter()` — billiger Preis/Volumen-Prefilter OHNE `yf.info`:
  Preis ≥ 2 $, 20-Tage-Ø-Turnover ≥ 500k EUR, Budget `MAX_STAGE2_CANDIDATES=400`
  (passt exakt zu `_PRICE_CACHE_MAX=400`).
- `select_candidates()` teilt das Regime-Limit über beide Quellen.
- Konstanten: `MIN_STAGE1_PRICE_USD=2.0`, `MIN_STAGE1_TURNOVER_EUR=500_000`,
  `LEGACY_STAGE2_MAX=250`.

**Verifikation (Orchestrator):** dry-run Universum 601 (Alt=250, Nasdaq=351),
Stage 1→2: 351→150, 146 long/1 short → 11 emittiert. Echter Lauf → `screener_nasdaq`
in `source_registry` (active) + 4 Nasdaq-Mentions. FX-Check: `price_to_eur()` wandelt
US-Ticker korrekt USD→EUR (kein Bug). Keine Regression der Alt-Quelle.

**Cron:** läuft automatisch in der Nacht-Pipeline (`trading_pipeline.py` Schritt
"screener_source"). Weekly-Review-Cron gewichtet `screener_nasdaq` separat.

**Finn-loop:** Task `screener-nasdaq.md`, review-approved.

---

## 2026-08-27 — KI-Analyse Härtung (Task 4, Finn-loop)

**Problem:** Pipeline 3,5-4,5h (Kollision mit nightly_eval 05:00 / crabel 06:30). Root-Cause:
`signal_extractor.py` → 20 JSON-Fehler-Kaskaden (3-stufige Fallback-Kaskade je Call) + hartes
`timeout=60` + serielle Chunk-Verarbeitung. ~16 min/Video.

**Fix (review-approved):**
- `_try_parse()` gehärtet — Fenced-Code-Block-Erkennung (```json), trailing-comma-Reparatur,
  Steuerzeichen-Säuberung, JSON-Decoder-Locator (raw_decode über `{`/`[`-Starts). Keine
  Apostrophen-Reparatur (Macy's/L'Oréal intakt). 5/5 Problem-Muster geparst.
- `REQUEST_TIMEOUT` 60→120s (env `REQUEST_TIMEOUT`, Default 120, Range 30-300).
- `_run_scout_chunks()`: Scout-Chunks parallel via `ThreadPoolExecutor(max_workers=min(3,total))`,
  `pool.map` = deterministische Reihenfolge; Analyst bleibt seriell nach Merge.
- `_call()` retryt 429/5xx mit Retry-After-Respekt + exp. Backoff, max 3 (REQUEST_MAX_ATTEMPTS≤5).
- WAL-Checkpoint in trading_pipeline.py (DB-Konsistenz bei parallelen Writes).

**Verifikation:** 9/9 Tests, 2.56s. Benchmark: 97k-Zeichen/7-Chunk-Video = 504s; typischer Tag
(~28 Chunks) von 3,5h auf <1h. Output-Struktur unverändert (companies/market_outlook/key_themes).

**Caveat:** AC-7 (DONE vor 05:00) wird beim nächsten echten Pipeline-Lauf (Mo-Fr 03:30) verifiziert —
code-seitig erfüllt, wartet auf Live-Beweis. Erklaerung.md jetzt ergänzt (Reviewer-Should-Fix #1).

**Finn-loop:** Task `pipeline-ki-analyse-haertung.md`, review-approved.

---

## 2026-08-29 — Vault-Insights Vorschläge 1+2 umgesetzt

### Vorschlag 1 — `screener_nasdaq` korrekt im Source-Quality-Tracking

**Problem:** `calc_source_quality()` (nightly_eval.py) speicherte `source_type` nie —
alle Kanäle fielen auf den DB-Default `'youtube'`. Dadurch wurde `screener_nasdaq`
(neuer US-Growth-Kanal, seit 27.08.) im Quality-Tracking/Dashboard als YouTube
klassifiziert statt als eigene Quelle, ebenso alle RSS- und Screener-Quellen.

**Fix (`scripts/nightly_eval.py`):** Pro Channel wird `source_type` aus
`source_registry` aufgelöst (`source_key=? OR source_type=? OR lower(display_name)=lower(?)`),
`rss:`-Prefix wird dabei gestrippt, Fallback bleibt `'youtube'`. Der `source_quality`-INSERT
enthält jetzt die `source_type`-Spalte.

**Verifiziert (Live-Lauf 29.08.):** `screener_nasdaq`→`screener_nasdaq`,
`screener`→`screener`, alle `rss:*`→`rss`, YouTube-Kanäle→`youtube`.
Counter: youtube 15 / rss 10 / screener 1 / screener_nasdaq 1.

**Erwartung:** screener_nasdaq taucht im Dashboard-Sources-Qualitäts-Tab als eigene
Screener-Quelle auf (Q≈0.77, 8 Mentions). Die Gewichtung selbst (weight=1.0, aktiv)
läuft weiter über `source_lifecycle.adjust_weights()` — solange die Quelle <5 Trades
hat, bleibt sie unverändert (korrekt).

### Vorschlag 2 — `conviction_score_bear` im Watchlist-Export

**Problem:** Der vault-insights-daily musste die Zahl der "echten Shorts"
(`conviction_score_bear > conviction_score`) über netto Bear→Bull-Mentions
approximieren, weil `export_watchlist.py` den Bear-Score nicht exportierte.

**Fix (`scripts/export_watchlist.py`):** Neue Spalte **Short-C** (Conviction short/bear)
nach Long-C im Watchlist-Markdown-Export. Wird im Canonical-Merge mitgeführt
(übernommen beim Merge + beim Kampf um den höheren Conviction-Score).

**Verifiziert (Live-Lauf 29.08.):** 105 Einträge exportiert, Spalte `Short-C` mit
Werten (z.B. SK hynix Long-C 100% / Short-C 51%; CAT 100% / 28%; AAPL 100% / 88%).

**Erwartung:** vault-insights-daily kann echte Shorts jetzt direkt aus `Watchlist.md`
zählen (`Short-C > Long-C`), keine Approximation über Bear/Bull-Mentions mehr.