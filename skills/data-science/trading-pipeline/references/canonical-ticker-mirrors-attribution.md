# Kanonik-Mirror-Fix + Attributions-Oszillation (10.09.2026)

Zwei verwandte Root Causes aus dem vault-insights-Report vom 10.09.2026.
Beide: **Spiegel-Listings / eingefrorene Felder verzerrten Statistiken, ohne
dass sich real etwas verschob.**

## A — `.SG`/`.MU`/`.F`-Spiegel-Ticker als Pseudo-Sentinents

**Symptom:** NetApp als `NTA.SG` (Sektor `Other`, kein `tech_score`), Short-C >
Long-C → zählte als Bärensignal. Gleich: SNOW (`US8334451098.SG`), Swatch
(`UHRN.SG`), Chevron (`CHV.SG`), XPeng (`8XPA.SG`), Seagate (ISIN.SG),
MicroStrategy (`MIGA.MU`), Evercore (`QGJ.MU`).

**Root Cause:** `technical_validator.resolve_ticker()` JS-... Schritt 3 (yf.Search)
bevorzugte EXPLIZIT DE-Börsen:
`if q.get("exchange") in ("GER","XETRA","FRA","STU","MUN"): return q.get("symbol")`.
`STU` = Stuttgart = `.SG`. Spiegel-Listings haben bei yfinance keinen Sektor
(→ `Other`) und zu wenig Liquidität/Bars für `tech_score`.

**Fix (DB-first, kein Hardcode):**
1. `resolve_ticker()` → Priorität wie `company_validator._exchange_priority`
   (US > `.DE` > Sonstige > `.SG/.MU/.F/.DU/.HM/.BE`) + DB-Kanonik-Mapping.
2. 18 Regeln in `canonical_tickers` (NTA.SG→NTAP, US8334451098.SG→SNOW,
   UHRN.SG→UHRN.SW, CHV.SG→CVX, 8XPA.SG→XPEV, IE00BKVD2N49.SG→STX,
   MIGA.MU→MSTR, QGJ.MU→EVR, NYT.SG→NYT, PFE.F→PFE, ISIN ohne Suffix …).
   Seed in `signal_manager.py` + `watchlist_manager.py` mitziehen.
3. Einmal-Migration `scripts/canonicalize_watchlist.py`: `--apply` schreibt,
   `--auto` löst Mirror ohne Score per yfinance-Namenssuche auf.
   **Guard:** `resolve_primary()` = Namensähnlichkeit ≥ 0.6 UND Priorität vor
   Ähnlichkeit. Ohne Guard: CATL ("...Amperex...") → TSM (TSMC, sim 0.45);
   Galaxy → 0P0.DE statt GLXY. Korrekt: CATL → 3750.HK.
4. `watchlist_cleanup.py` Stufe 1b: `.L` → auch `.F/.MU/.SG/.DU/.HM/.BE` ohne
   `tech_score` → `dropped`/`notes='no-liquidity-gate'` (Resurrection-Guard).
5. Zombie: Wirecard `WDI.HM` (insolvent, 0.015 €) manuell gedroppt.

Warnung bei Nebenbörsen: **NIE `ticker.endswith()` auf `.F` prüfen ohne auch
`.SG`/`.MU`/`.DU`/`.HM`/`.BE`** — Deutschland hat mehrere Nebenboersen-Suffixe.

## B — Attributions-Oszillation: `channels` von bought-Zeilen eingefroren

**Symptom:** Quellen-Attribution (Kanal-Zählung über exportierte Watchlist)
schwankt tgl. ±5–15, Summe wächst (221→302→383). Report loggte „Oszillation seit Tag 11".

**Root Cause (gemessen):** `watchlist_manager.py` UPDATE schreibt `channels`
nur für `status IN ('watching','dropped')`. **Bought-Zeilen (82/110 exportierte
Zeilen = 75 %) behalten den `channels`-Stand vom Kaufdatum.** Reconciliation
gegen `watchlist_mentions` (14-Tage-Fenster): 78/82 bought abweichend, 7/28
watching. AAPL: 16 gespeichert vs. 6 live; CRWD seit 04.06. eingefroren.

Der Export zählt über ALLE Zeilen → mischt 28 live-aktualisierte watching + 82
eingefrorene bought-Zeilen → Tageszählungen springen ohne realen Shift.

**Fix:** `channels` wird auch für `status='bought'` per aktuellen Fenster
nachgezogen; bought ohne Mentions → `channels='[]'`. BEWUSST nur das
Attributions-Feld — Status/Entry/Conviction/last_seen unangetastet.
Zusätzlich: `watchlist.channels`-Normalisierung nutzte `WHERE id=?`, aber 942
von 1781 Zeilen haben `id IS NULL` (Dedup via `rowid`) → JETZT `rowid`.

**Verifikation:** Attributionen 384→167, Mismatch 85→7 (Reste = watching,
Alias-Artefakt der Prüfprozedur).

**Sekundär:** Sprung 221→302→383 teils wegen 08.09.-Export-Änderung
(`list(set(x))[:3]` Top-3 → volle Liste). Zahlen vor/nach 08.09. nicht
vergleichbar.

## Allgemeine Regel

Wenn die Quellen-Attribution „oszilliert" und der Export mit `sorted(set(...))`
arbeitet: zuerst prüfen ob **status-abhängige Felder** bestehen (nur watching
aktualisiert, bought eingefroren). Eine „Oszillation" über 11 Tage ist meist
kein Rauschen, sondern eine eingefrorene Feldklasse.