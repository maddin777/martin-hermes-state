# Exit-Config-Konsolidierung (get_exit_config) — 16.08.2026

## Was passiert ist
Der vault-insights-daily + ein manueller Review deckten auf, dass `get_exit_config()`
(config.py Exit-Matrix, Single Source of Truth seit 09.08.) **nicht überall** als
einzige Quelle genutzt wurde — obwohl die Doku im Skill-Doc behauptete, signal_manager
sei bereits umgestellt. Es gab **drei parallele Pfade** mit Legacy `get_asset_multipliers`:

| Pfad | vor 16.08. | genutzte Legacy-Keys | Fix |
|------|-----------|----------------------|-----|
| `signal_manager.py` (Entry-Engine) | `get_asset_multipliers` an 4 Stellen | `atr_sl`, `atr_tp` (compute_sl_tp Entry-SL/TP), `partial_atr` (741), `atr_sl` (Sizing 1921), toter `mult` (1960) | auf `get_exit_config`, `regime`-Parameter durchgereicht |
| `active_exit_check.py` (Exit-Check) | `get_asset_multipliers` | `trailing_step` (STANDARD=0.5× vs Matrix step=0.75×), `atr_sl` | auf `get_exit_config`, Regime inline |
| `crabel_shadow_eval.py` (Shadow) | eigene Legacy-Formel **+ cfg-Fallback** `profit_lock_atr` Default 2.0 | `trailing_step`, `atr_sl`, `profit_lock` | auf `get_exit_config` (profit_lock 2.0→Matrix 1.0) |

## Wichtigste Lektion: Der verborgene dritte Pfad
Der Docstring von `compute_sl_tp` behauptete, `crabel_shadow_eval.py` nutze ihn —
**das war falsch**. crabel importierte compute_sl_tp NICHT, sondern hatte eine eigene
Kopie der Exit-Logik in `simulate_forward()`, inkl. eines cfg-Fallback `profit_lock_atr`
mit Default **2.0** (die Matrix hat seit dem 09.08-Fix 1.0). Ohne die Umstellung wären
Live- und Shadow-Kohorten mit unterschiedlichen profit_lock-Werten gerechnet worden —
die Shadow-Auswertung wäre still falsch gewesen.

**Regel:** Beim Konsolidieren einer Config-Quelle NIE nur "die zwei Exit-Checks"
greppen. `grep -rn "<funktion>" scripts/*.py` über ALLE Pfade inkl. Shadow/Eval-Scripts
(fehlende `from X import compute_sl_tp`-Imports prüfen — importiert es nicht, hat es oft
eine eigene Kopie).

## Regime-Abhängigkeit (Verhaltensänderung!)
`compute_sl_tp` (Entry-SL/TP) ist jetzt **regime-abhängig**, nicht mehr statisch:
- STANDARD bull: TP 3.5× vs sideways 2.5× (aktuelle Werte: Regime bull → 3.5×)
- Das ist konsistent zu active_exit_check + adapt_strategy

**Regime-Quelle überall:** `get_current_regime(con)` (DB `regime_history`), NICHT die
JSON-Makrodatei (`get_macro_signal()` in signal_manager liest MACRO_SIGNAL_PATH — andere
Quelle, nur für Entry-Entscheidungen/allow_short, nicht für Exit-Parameter).

## Statischer Drift-Check — Grep-Falle
Der `weekly_exit_review.py` check_config_drift() scannt die Pfade auf Legacy-Aufrufe:
- Nur echte Aufrufe `get_asset_multipliers(` (direkte Klammer) zählen
- Docstring-/Kommentar-Erwähnungen wie `...get_asset_multipliers (Legacy)` haben ein
  **Leerzeichen vor der Klammer** → werden ignoriert
- Sonst false-positives bei jeder erklärenden Notiz im Code

Ein `#`-Kommentar ist per `l.strip().startswith("#")` filterbar — Docstring-Text ist es
NICHT (beginnt nicht mit `#`), daher der Klammer-Test.

## Drift-Check-Deckung
`weekly_exit_review` prüft jetzt alle drei Pfade (signal_manager, active_exit_check,
crabel_shadow_eval) → Alarm nur wenn ein echter `get_asset_multipliers(`-Aufruf zurückkehrt.
Das verhindert die Wiederkehr des 09.08.-Parallele-Pfad-Musters.

## Manueller Verifikations-Rezept
```python
import sys; sys.path.insert(0,'.'); import env_loader
from config import db_connect, get_exit_config
import importlib
sm = importlib.import_module('scripts.signal_manager')
cr = importlib.import_module('scripts.crabel_shadow_eval')
aec = importlib.import_module('scripts.active_exit_check')
wr = importlib.import_module('scripts.weekly_exit_review')
c = db_connect()
regime,_ = sm.get_current_regime(c)
# compute_sl_tp alle Kombis (LONG+SHORT × 3 asset_types) ohne Exception
for at in ['STANDARD','TECH','DEFENSIVE']:
    for d in ['LONG','SHORT']:
        sm.compute_sl_tp(100.0, 2.0, at, d, regime=regime)
print('OK')
print(wr.check_config_drift() or 'kein Drift')
```
