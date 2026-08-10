# Fremdmodell-Zweitmeinung (Cross-Model Review) — kompletter Ablauf (09.08.2026)

Martin ließ den Trading-Skill zusätzlich mit `z-ai/glm-5.2` (unabhängiges Modell
über OpenRouter) prüfen, nachdem Hermes (deepseek) ihn bereits selbst reviewed
hatte. Das deckte echte Fehler auf, aber auch einen echten Rechenfehler des
Review-Modells — beide Teile sind hier festgehalten.

## Warum Zweitmeinung

Ein zweites, unabhängiges Modell hat keinen Kontext-Bias aus der eigenen
Entwicklung der Änderungen. Es liest denselben eingefrorenen Kontext frisch und
findet oft Konfig-Drift, den der Ersteller übersehen hat. Im konkreten Fall fand
glm-5.2 einen Widerspruch im frisch umgesetzten Phase-1-Fix (Regime-Override
trimmte profit_lock_atr nach oben und machte die Senkung wirkungslos), den die
eigene Analyse verpasst hatte.

## Technik (wie umgesetzt)

Baue eine Standalone-Analyse-Anfrage, die NUR den eingefrorenen Kontext an das
Zweitmodell schickt. Nicht die laufende Session-Geschichte. Dafür:

1. **Friere den relevanten Kontext ein** in einen Python-Script das:
   - Live-Kennzahlen aus der SQLite-DB zieht (Eval-Metriken, Exit-Verteilung,
     Watchlist-Verteilung, Top-Signale) → `sqlite3` + `dict(r) for r in rows`
   - Die aktuelle Config-Struktur (Regime-Tabelle, Exit-Logik, Drawdown,
     Sector-Blacklist) als Text-Summary einbettet
   - Den OPENROUTER_API_KEY aus der Profil-`.env` via `import env_loader` lädt
   - Einen POST an `https://openrouter.ai/api/v1/chat/completions` mit
     `{"model": "<andere-modell>", "messages": [{user: kontext}], "temperature": 0.3}`
2. **Vergleiche mit dem Standard-Modell auf demselben Kontext** — unterschiedliche
   Funde = Signal.
3. **Modell-Namen prüfen:** Verfügbarkeit vorher via `curl https://openrouter.ai/api/v1/models`
   checken (`z-ai/glm-5.2` existiert, ebenso glm-5/5.1/5-turbo, glm-4.7 etc.).

Funktionstest vor dem Review:
```python
from config import get_exit_config
for at in ['STANDARD','TECH','DEFENSIVE']:
    for r in ['bull','sideways','bear']:
        ec = get_exit_config(at, regime=r)
        print(at, r, ec)
```

## 🔴 KRITISCHE REGEL: Reviewer-Mathematik gegen Rohdaten verifizieren

Ein Review-Modell kann selbst rechnen und dabei irren. **Bevor du eine Zahl oder
Schlussfolgerung des Reviewers übernimmst, prüfe sie gegen die Roh-DB.**

Konkreter Fehler (09.08.): glm-5.2 behauptete "Winrate 10.4%, Break-Even 21.5%"
— es verwechselte die TARGET_HIT-Anzahl (8) mit der Winrate. Die echte Winrate
war `30/77 = 39%`. Auf dieser falschen Prämisse baute glm einen scheinbar
vernünftigen "Break-Even"-Schluss auf.

Die korrekte Analyse (Wert, den das Reviewer-Modell übersah):
```sql
SELECT CASE WHEN pnl_eur>0 THEN 'GEWINN' ELSE 'VERLUST' END typ,
       COUNT(*) cnt, ROUND(AVG(pnl_eur),2) avg_pnl, ROUND(SUM(pnl_eur),2) total
FROM positions WHERE exit_date IS NOT NULL GROUP BY typ;
-- 09.08: GEWINN 30 @ +62.88€ / VERLUST 47 @ -66.31€ → Payoff 0.95 < 1
```
**Der echte Killer war Payoff < 1 (Verluste größer als Gewinne), nicht die
Winrate.** Bei 39% WR braucht man Break-Even-WR von 51%. Der Review-Schluss
"Entry-Qualitätsproblem statt Exit-Problem" stimmte in der Richtung, aber die
Zahlenbasis war falsch.

## Checkliste: Reviewer-Aussagen verifizieren, NICHT blind übernehmen

- Jede abgeleitete Kennzahl (WR, Break-Even, Payoff, Sharpe) mit einem
  `sqlite3`-Query gegen die echte DB nachrechnen
- Den `exit_reason`-Count vs. die `pnl_eur > 0`-Anzahl unterscheiden (glm
  verwechselte TARGET_HIT-Exit-Count mit Winrate — das sind verschiedene Metriken)
- Konfig-Widersprüche, die der Reviewer nennt, im Code verifizieren (mit `grep`,
  `read_file`), nicht nur glauben
- Zwischen dem WERT der Reviewer-Aussage (Richtung stimmt) und der PRÄMISSE
  (Zahl fehlerhaft) unterscheiden — eine richtige Empfehlung kann auf falscher
  Rechnung stehen, und umgekehrt

## Starke Reviewer-Funde nutzen, wo sie stimmen

Die nützlichsten glm-5.2-Punkte (09.08.), die sich als korrekt erwiesen:

1. **Drei überlagerte Exit-Quellen = Config-Drift-Herd:** `ASSET_TYPE_MULTIPLIERS`
   + `regime_configs` in signal_manager + `strategy_config.json` um `profit_lock_atr`
   streiten → in EINE `get_exit_config()`-Matrix konsolidieren (siehe SKILL.md).
2. **Parallele Exit-Pfade prüfen:** `active_exit_check.py` zog den ATR-Chandelier
   auch dann, wenn Donchian-Primary den Trail führte → Donchian-Präzedenz in
   `active_exit_check` respektieren.
3. **`min_confidence`-Senkung war fehldiagnostiziert:** "Entry-Starvation"
   annehmend wurde 0.80→0.70 gesenkt, aber 76 bought existieren (keine Starvation)
   → zurück auf 0.80.
4. **`signal_source` war leer** bei allen 77 Trades → beim Entry setzen
   (`_derive_signal_source` aus Kanal-Präfixen rss/x_social/screener/youtube),
   damit Winrate-pro-Komponente messbar wird → Report-Block in nightly_eval.

## Verifikation nach Review-Fixes

```bash
cd /root/.hermes/profiles/hermes_trading/skills/trading
python3 -c "import ast; [ast.parse(open(f).read()) for f in \
  ['config.py','scripts/signal_manager.py','scripts/active_exit_check.py','scripts/nightly_eval.py']]"
PYTHONPATH=. python3 -c "
from config import get_exit_config
for at in ['STANDARD','TECH','DEFENSIVE']:
    for r in ['bull','sideways','bear']:
        print(at, r, get_exit_config(at, regime=r))
"
```
