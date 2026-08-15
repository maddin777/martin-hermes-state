# UK-Microcap-Gate (.L Datenqualität) — 14.08.2026

## Problem-Symptom
RSS-Quelle `share talk` spülte UK-AIM/Nano-Caps (AET.L, BSFA.L, HREE.L, KZG.L, SHOE.L, MAC.L, AMRQ.L, SNDA.L …) in die `watchlist`. In der Watchlist-Pflege (vault-insights/export) tauchten sie als **DQ-Fälle** auf: `conviction_score ≈ 0.76` aber `tech_score`/`tech_direction` leer (`–`). Ihre Konviction konnte theoretisch in die Entry-Pipeline rutschen und verpestete die Conviction-Verteilung.

## Warum ein reiner Bar-Count-Gate scheitert
`get_technical_score()` verlangt bereits `len(df) >= 50` und berechnet `ema200` (≈ 200 Bars) — ein Ticker OHNE 200 Bars liefert ohnehin `None`. Ein UK-Nano-Cap MIT 200+ Bars bekam also trotzdem einen Score, obwohl es als AIM-Microcap praktisch unhandelbar ist. **Der eigentliche Differenzierer ist Tagesumsatz (Turnover), nicht Bar-Anzahl.**

## Implementierter Fix (utils.py, einzige Quelle get_technical_score)
```python
UK_MIN_BARS         = 200      # ~1 Jahr Handelstage
UK_MIN_TURNOVER_EUR = 500_000  # konsistent mit signal_manager min_liquidity_eur
```
```python
_, _, df = get_price_data_cached(ticker)
if df is None or df.empty or len(df) < 50:
    return None
if str(ticker).endswith(".L"):
    if len(df) < UK_MIN_BARS:
        return None
    _c = df["Close"].iloc[:,0] if df["Close"].ndim > 1 else df["Close"]
    _v = df["Volume"].iloc[:,0] if df["Volume"].ndim > 1 else df["Volume"]
    _turnover = turnover_to_eur(float(_c.tail(20).mean()), float(_v.tail(20).mean()), ticker)
    if _turnover < UK_MIN_TURNOVER_EUR:
        return None
```
Kein Extra-Netzwerk-Call: der Turnover wird aus dem bereits geladenen `df` berechnet (TTL-Cache von `get_price_data_cached`). `turnover_to_eur` berücksichtigt GBp (÷100) + FX über `price_to_eur`.

Kein Score → kein `tech_score`/`tech_direction` in der Watchlist → `signal_manager`-Entry-Queries (`tech_score >= threshold` + `tech_direction='LONG/SHORT'`) finden den Kandidaten nicht.

## Verifikations-Rezept (Live-Daten, 14.08.)
```python
import sys; sys.path.insert(0, ".")
import env_loader
from utils import get_technical_score
for t in ["AET.L","BSFA.L","HREE.L","KZG.L","SHOE.L","MAC.L","GLEN.L","AV.L","TSCO.L","ULVR.L","VOD.L","BARC.L","BP.L","ANTO.L"]:
    r = get_technical_score(t)
    print(f"{t:8} -> " + ("None (geblockt)" if r is None else f"conf={r['confidence']} dir={r['direction']}"))
```
- Geblockt (AIM-Microcaps): AET, BSFA, HREE, KZG, SHOE, MAC, SNDA, 0UKI, ECR, FCM, POLB, FMET, BOOM, KEN, ORCP, TYM, HDD, ORR, HVO, SOU, TEK
- Durchgelassen (liquide Large-Caps korrekt): GLEN, AV, TSCO, ULVR, VOD, BARC, BP, ANTO, ATYM, KGF, HSX, WISE, TATE, LGEN, RSW, FRAS
- AMRQ.L (Amaroq) bleibt drauf — echtes, liquides Minen-Listing, kein Fehlverhalten.

## Gotcha: refresh_tech_scores.py leert keine veralteten Scores
`refresh_tech_scores.py` macht `if tech: UPDATE watchlist SET tech_score=?, tech_direction=?`. Wenn `get_technical_score` jetzt `None` liefert, bleibt der ALTE (vor-Gate-)Score stehen → der Microcap sähe weiter entry-fähig aus. **Manuell clearen:**
```python
from utils import get_technical_score
from config import db_connect
con = db_connect()
for r in con.execute("SELECT ticker FROM watchlist WHERE ticker LIKE '%.L' AND tech_score IS NOT NULL").fetchall():
    t = r["ticker"]
    if get_technical_score(t) is None:
        con.execute("UPDATE watchlist SET tech_score=NULL, tech_direction=NULL, weekly_trend=NULL WHERE ticker=?", (t,))
        con.commit()
```

## Bedien-/Ops-Hinweis
- Gate wirkt automatisch beim nächsten `technical_validator.py` / `watchlist_manager.py` / `refresh_tech_scores.py`-Lauf. Kein Cron-Neustart.
- Nicht-`.L`-Ticker sind unberührt (keine Kollateral-Effekte auf US/EU-Namen).
- `signal_manager` hatte historisch **0** Paper-Entries gegen jegliche `.L`-Ticker — die Entry-Gates (tech + `passes_liquidity_filter` ≥500k€) schützten bereits; das Gate schließt das DQ / Conviction-Pollution-Loch davor.
- Schwelle justierbar über `UK_MIN_TURNOVER_EUR` in `utils.py`; 500k€ = konsistent mit `signal_manager` `min_liquidity_eur`.
