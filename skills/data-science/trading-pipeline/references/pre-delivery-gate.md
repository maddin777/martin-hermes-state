# Pre-Delivery-Verification-Gate (14.09.2026)

Anthropic "Methode 4" / vault-insights-daily Vorschlag 2: Signal-Outputs vor der
Delivery gegen FESTE Kriterien laufen lassen (proof-of-work statt
Selbstbestätigung). Der erste Blick des Operators soll nicht der 4./5. sein.

## Was es ist

Ein eigenständiges Script `scripts/pre_delivery_gate.py`, das die Top-N
Watchlist-Kandidaten (Shortlist wie `nightly_eval.calc_top_signals`) AUS DER
LIVE-DB validiert — vor dem Telegram-Versand. Es liefert einen **Befund**
(💬 Text-String) und blockiert NIE die Zustellung (graceful Degradation).

## Feste Kriterien (Entry-Gate)

Pro Kandidat (`verify_candidate(row, threshold)`) mit Threshold aus
`config.DEFAULT_CONFIG["min_confidence"]` (Default 0.60):

1. `conviction_score_aged >= min_confidence`  → sonst **block**
2. `tech_score` vorhanden (NOT NULL)          → sonst **block** ("kein tech_score")
3. `tech_direction == 'LONG'`                 → sonst **warn** (NEUTRAL/SHORT sind
   trotz hoher Conviction NICHT long-entry-fähig)
4. `.L`-Microcap OHNE tech_score (= DQ-Fall)  → sonst **block**
5. `mention_count <= 1`                        → **warn** ("nur 1 Mention", Einzel-Hit fragil)

Status ist `pass` (✅) / `warn` (⚠️) / `block` (🚫). `build_gate_line(con, limit=5)`
baut daraus eine HTML-Zeile für den Report-Header.

## Integration (nightly_eval.py)

```python
signals_line = build_top_signals_line(con, limit=5)
src_win_line = build_signal_source_line(con)
try:
    from scripts.pre_delivery_gate import build_gate_line
    gate_line = build_gate_line(con, limit=5)
except Exception as e:
    gate_line = f"🛡 Pre-Delivery-Gate: ❌ nicht verfügbar ({e})"
...
# in BEIDEN Message-Blöcken (Tages- UND Wochen-Report) nach signals_line:
f"{signals_line}{src_win_line}"
f"\n{gate_line}"
```

## Design-Prinzipien

- **Proof-of-work, nicht Selbstbestätigung:** Das Gate rechnet gegen die
  Live-DB neu statt dem Pipeline-Report zu vertrauen. Ein Top-Signal kann
  hohe Conviction zeigen, aber am Entry-Gate scheitern (z.B. tech_direction
  NEUTRAL/SHORT) — genau das deckt der erste Operator-Blick jetzt auf.
- **Fail-open nach außen:** Kein Impact auf die Delivery. Fehler im Gate →
  Zeile zeigt "❌ nicht verfügbar", Report geht trotzdem raus.
- **DB-first:** Schwelle aus config, keine Hardcodes im Script (außer fallback).
- Query ist bewusst IDENTISCH zu `calc_top_signals` → die Shortlist im Report
  und die geprüfte Shortlist können nie auseinanderlaufen.

## Beispiel-Output (live, 14.09.2026)

```
🛡 Pre-Delivery-Gate: ⚠️ 3 gewarnt (Schwelle 60%)
⚠️ Diageo plc (DEO) nur 1 Mention
⚠️ The Cheesecake Factory Incorporated (CAKE) nur 1 Mention
✅ Allianz SE (ALV.DE) entry-fähig
✅ Chevron Corporation (CVX) entry-fähig
⚠️ Bristol-Myers Squibb Company (BMY) nur 1 Mention
```

## Verifikation

```bash
cd /root/.hermes/profiles/hermes_trading/skills/trading
PYTHONPATH=. python3 scripts/pre_delivery_gate.py          # live gegen DB
python3 -c "import ast; ast.parse(open('scripts/nightly_eval.py').read())"
# Trockenlauf ohne Telegram-Versand:
PYTHONPATH=... python3 -c "import nightly_eval as n; n.send_telegram=lambda m: print(m); n.main()"
```

## Pitfall

Der Report hat ZWEI fast identische Message-Blöcke (Tages- und Wochen-Report).
Beim Patchen in `nightly_eval.py` immer eindeutige Kontext-Zeile mitnehmen
(z.B. die `"🔧 Strategy Optimizer"`-Zeile unterscheidet den Wochen-Block) —
sonst trifft `patch` den falschen Block (siehe Haupt-Pitfall "patch-Tool kann
den FALSCHEN Code-Block treffen").
