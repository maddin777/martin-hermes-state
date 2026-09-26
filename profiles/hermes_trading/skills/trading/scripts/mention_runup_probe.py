#!/usr/bin/env python3
"""Probe: Kommen die bullishen Kanal-Nennungen VOR oder NACH der Kursbewegung? — 25.09.2026.

Anlass: Artikel @leopardracer (21.09.2026) — "Kleinanleger, die nach dem Anstieg einsteigen, sind ein
negatives Signal", "Gewichte aus Daten statt von Hand". Unser Conviction-Score hat Handgewichte, und
hohe Conviction schnitt bisher schlechter ab (h3_crowding). Erklaerungskandidat: die Kanaele besprechen
Aktien, die schon gelaufen sind.

Drei Fragen, ein Datensatz (Zustand je Ereignistag nur aus Daten bis zu diesem Tag nachgebaut):
  P2 (Hauptfrage)  Sagt der Kursanstieg VOR der Nennung das Ergebnis danach voraus (negativ = Hinterherlaufen)?
  P1               Welche Vorzeichen haben die Bausteine des Conviction-Scores, wenn man sie an Daten schaetzt,
                   und schlaegt ein daraus geschaetzter Score den Handscore ausserhalb der Stichprobe?
  P3               Traegt die Put/Call-Ratio etwas bei? (Insider-Daten: unbrauchbar, siehe Bericht.)

EREIGNIS: bullishe Nennung aus einer Meinungsquelle (alle Kanaele ausser DETERMINISTIC_CHANNELS) am Tag t, fuer
die es in den 30 Kalendertagen davor keine bullishe Meinungs-Nennung desselben Tickers gab. Name -> Ticker ueber
watchlist.name und company_aliases, nur eindeutige Zuordnungen.

ZEITACHSE (keine Vorausschau):
  Anstieg    Schlusskurs t-1 gegen t-21 (20 Handelstage) bzw. t-6 (5 Tage), also VOR dem Nennungstag.
             z_runup = Anstieg / Streuung der 20-Tage-Renditen dieser Aktie in den 250 Tagen davor.
  Einstieg   Schlusskurs des ersten Handelstags NACH t (Pipeline laeuft nachts, Entry am Folgetag).
  Ergebnis   fwd5  = Rendite 5 Handelstage nach Einstieg (Live-Haltedauer: Time-Stop an Tag 7).
             fwd21 = Rendite 21 Handelstage nach Einstieg (nur berichtet).
             live  = simulate_forward() aus crabel_shadow_eval (SL/Chandelier/Time-Stop wie das Shadow-Buch),
                     Exit-Matrix nach Sektor und regime_history am Tag t, minus 2 x 0,1 % Slippage (nur berichtet).
  Marktbereinigung: jedes Ergebnis minus Mittel aller Ereignisse mit Einstieg in derselben Kalenderwoche
             (Suffix "_dm"). Das entfernt die gemeinsame Marktbewegung ohne Benchmark-Zuordnung (.F/.SG-Kurse
             von US-Aktien machen jeden Index-Vergleich schief).
  Kurse ohne Handel (>20 % unveraenderte Schlusskurse in den 60 Tagen vor t) werden ausgeschlossen, Zahl im Bericht.

VORAB FESTGELEGT (nicht nachtraeglich aendern)
  Stichprobe: mind. 300 Ereignisse mit fwd5, 150 verschiedene Ticker, 10 Kalenderwochen mit je >= 9 Ereignissen.
     Darunter: "NICHT AUSSAGEKRAEFTIG", keine Kennzahlen.
  P2  Kennzahl A = Mittel ueber Wochen (>= 9 Ereignisse) der Spearman-Korrelation z_runup20 ~ fwd5_dm.
      Kennzahl B = Mittel ueber diese Wochen von [Mittel fwd5_dm im unteren Anstiegs-Drittel minus oberem Drittel].
      Unsicherheit: Bootstrap ueber Wochen (Bloecke, 2000) und ueber Ticker (Cluster, 1000); es zaehlt jeweils die
      ungunstigere 95-%-Grenze (A: groessere obere Grenze, B: kleinere untere Grenze).
      HINTERHERLAUFEN BESTAETIGT, wenn obere Grenze A < 0 UND untere Grenze B > 0 UND A < 0 in beiden
         chronologischen Haelften (Wochen geteilt).
      MOMENTUM (Gegenteil), wenn untere Grenze A > 0 UND obere Grenze B < 0 UND A > 0 in beiden Haelften.
      Sonst KEIN BELEGBARER EFFEKT.
  P1  Logistische Regression (IRLS, Ridge 1.0) von [fwd5_dm > 0] auf standardisierte Merkmale:
      z_runup20, z_runup5, log(1+Nennungen30), Kanaele30, Bull-Anteil, Staerke-gewichteter Bull-Anteil,
      Screener-Treffer30 (0/1). Koeffizienten mit 95-%-KI (ungunstigere Grenze aus Wochen- und Ticker-Bootstrap).
      Ausserhalb der Stichprobe: Fit auf den ersten 60 % der Wochen, Test auf den letzten 40 %.
      Kennzahl = wochenweise Spearman-IC von Regressions-Score bzw. Handscore (calculate_conviction ohne
      Kanalgewichte, wie live ohne Kalibrierung) mit fwd5_dm, Differenz mit Wochen-Bootstrap.
      DATEN-SCORE BESSER, wenn untere 95-%-Grenze der Differenz > 0. Sonst NICHT BESSER.
  P3  Nur wenn >= 150 Ereignisse eine PCR-Messung in den 3 Tagen bis t haben: Spearman PCR ~ fwd5_dm mit
      Wochen-Bootstrap (gepoolt, weil zu wenige je Woche). Sonst "NICHT AUSSAGEKRAEFTIG".
  Nichts davon aendert den Handel. Ein positives Ergebnis rechtfertigt nur eine neue Shadow-Hypothese.

NUR LESEND: trading.db wird nicht veraendert. Ausgaben in data/mention_runup_probe/.
Aufruf:
    venv/bin/python scripts/mention_runup_probe.py --dry-run      # Ereignisse zaehlen, nichts laden
    venv/bin/python scripts/mention_runup_probe.py --build        # Kurse laden (Cache), Ereignistabelle bauen
    venv/bin/python scripts/mention_runup_probe.py --analyze      # Bericht aus der Ereignistabelle
"""
import argparse
import math
import os
import sys
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

_ROOT = "/root/.hermes/profiles/hermes_trading/skills/trading"
for _p in (_ROOT, os.path.join(_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

OUT_DIR = os.path.join(_ROOT, "data", "mention_runup_probe")
PRICES = os.path.join(OUT_DIR, "prices.pkl")
EVENTS = os.path.join(OUT_DIR, "events.csv")

GAP_DAYS = 30               # keine bullishe Meinungs-Nennung in so vielen Kalendertagen davor
LOOKBACK_DAYS = 30          # Fenster fuer die Nennungs-Merkmale
RUNUP_LONG, RUNUP_SHORT = 20, 5
VOL_WINDOW = 250
H_MAIN, H_LONG = 5, 21
STALE_WINDOW, STALE_MAX = 60, 0.20
PCR_MAX_AGE = 3
PRICE_START = "2025-03-01"
SLIPPAGE = 0.001

MIN_EVENTS, MIN_TICKERS, MIN_WEEKS, MIN_WEEK_N = 300, 150, 10, 9
MIN_PCR = 150
BOOT_WEEK, BOOT_TICKER = 2000, 1000
TRAIN_SHARE = 0.60
RIDGE = 1.0
STRENGTH_W = {"strong": 1.0, "moderate": 0.6, "weak": 0.3}
FEATURES = ["z_runup20", "z_runup5", "log_mentions30", "channels30", "bull_share", "bull_share_w", "screener30"]


# ─────────────────────────────────────────────────────────────── Ereignisse (nur DB)
def name_map(con):
    """lower(name/alias) -> ticker, nur eindeutige Zuordnungen."""
    rows = con.execute("""
        SELECT lower(name) n, ticker FROM watchlist WHERE ticker IS NOT NULL AND name IS NOT NULL
        UNION SELECT lower(alias), ticker FROM company_aliases
    """).fetchall()
    m = {}
    for r in rows:
        m.setdefault(r[0], set()).add(r[1])
    return {k: next(iter(v)) for k, v in m.items() if len(v) == 1 and k}


def load_mentions(con, deterministic):
    df = pd.DataFrame([dict(r) for r in con.execute(
        "SELECT name, channel, sentiment, strength, mention_date FROM watchlist_mentions "
        "WHERE mention_date IS NOT NULL").fetchall()])
    if df.empty:
        return df
    nm = name_map(con)
    df["ticker"] = df["name"].str.lower().map(nm)
    df = df.dropna(subset=["ticker"]).copy()
    df["date"] = pd.to_datetime(df["mention_date"].str[:10], errors="coerce")
    df = df.dropna(subset=["date"])
    df["det"] = df["channel"].isin(deterministic)
    return df.sort_values("date").reset_index(drop=True)


def find_events(ment):
    """Erste bullishe Meinungs-Nennung je Ticker nach >= GAP_DAYS ohne bullishe Meinungs-Nennung.

    Ereignisse in den ersten GAP_DAYS der Datenreihe entfallen: dort ist nicht belegbar, dass davor keine
    Nennung war (die Tabelle beginnt erst am ersten Datum)."""
    if ment.empty:
        return pd.DataFrame(columns=["ticker", "date"])
    start = ment["date"].min() + pd.Timedelta(days=GAP_DAYS)
    bull = ment[(ment.sentiment == "bullish") & (~ment.det)]
    out = []
    for t, g in bull.groupby("ticker"):
        last = None
        for d in sorted(g["date"].unique()):
            d = pd.Timestamp(d)
            if (last is None or (d - last).days > GAP_DAYS) and d >= start:
                out.append((t, d))
            last = d
    return pd.DataFrame(out, columns=["ticker", "date"])


def mention_features(ment, ticker, t):
    """Merkmale aus Nennungen bis EINSCHLIESSLICH t (Tag der Nennung), Fenster LOOKBACK_DAYS."""
    g = ment[(ment.ticker == ticker) & (ment.date <= t) & (ment.date > t - pd.Timedelta(days=LOOKBACK_DAYS))]
    op = g[~g.det]
    n = len(op)
    bull = int((op.sentiment == "bullish").sum())
    bear = int((op.sentiment == "bearish").sum())
    neut = n - bull - bear
    bw = float(sum(STRENGTH_W.get(s, 0.6) for s in op.loc[op.sentiment == "bullish", "strength"]))
    chans = sorted(set(op.channel))
    return {"mentions30": n, "bull30": bull, "bear30": bear, "neutral30": neut, "channels30": len(chans),
            "channel_list": "|".join(chans), "bull_weighted30": bw,
            "bull_share": bull / n if n else 0.0,
            "bull_share_w": bw / (0.6 * n) if n else 0.0,
            "screener30": int(bool(g.det.any())),
            "log_mentions30": math.log1p(n)}


def hand_conviction(f):
    """Handscore wie live, ohne Kanalgewichte/Kalibrierung (die sind heutiger Stand = Vorausschau)."""
    from watchlist_manager import calculate_conviction
    chans = [c for c in f["channel_list"].split("|") if c]
    return calculate_conviction(f["bull30"], f["bear30"], f["neutral30"], f["mentions30"], f["channels30"],
                                channels_list=chans, bullish_weighted=f["bull_weighted30"])


# ─────────────────────────────────────────────────────────────── Kurse
def download_prices(tickers, end):
    import yfinance as yf
    frames = {}
    tickers = sorted(set(tickers))
    for i in range(0, len(tickers), 100):
        chunk = tickers[i:i + 100]
        raw = yf.download(chunk, start=PRICE_START, end=end, auto_adjust=True, group_by="ticker",
                          progress=False, threads=True)
        for t in chunk:
            try:
                d = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
                d = d[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
                if len(d):
                    d.index = pd.to_datetime(d.index).tz_localize(None).normalize()
                    frames[t] = d
            except Exception:
                pass
        print(f"  Kurse {min(i + 100, len(tickers))}/{len(tickers)}", flush=True)
    return frames


def price_features(df, t):
    """Anstieg vor t, Einstieg am ersten Handelstag nach t, Ergebnisse. None bei zu kurzer/lueckenhafter Historie."""
    c = df["Close"]
    before = c[c.index < t]
    after = df[df.index > t]
    if len(before) < RUNUP_LONG + 1 + 60 or len(after) < 1:
        return None, "kurze Historie"
    last60 = before.iloc[-STALE_WINDOW:]
    if (last60.diff().iloc[1:] == 0).mean() > STALE_MAX:
        return None, "ohne Handel"
    p1 = before.iloc[-1]
    r20 = p1 / before.iloc[-1 - RUNUP_LONG] - 1
    r5 = p1 / before.iloc[-1 - RUNUP_SHORT] - 1
    hist = before.iloc[-(VOL_WINDOW + RUNUP_LONG + 1):]
    roll20 = (hist / hist.shift(RUNUP_LONG) - 1).dropna().iloc[:-1]
    roll5 = (hist / hist.shift(RUNUP_SHORT) - 1).dropna().iloc[:-1]
    sd20, sd5 = roll20.std(), roll5.std()
    if not (sd20 > 0 and sd5 > 0):
        return None, "kurze Historie"
    entry_date = after.index[0]
    entry = float(after["Close"].iloc[0])
    fut = after["Close"].iloc[1:]
    rec = {"entry_date": entry_date, "entry": entry, "runup20": r20, "runup5": r5,
           "z_runup20": (r20 - roll20.mean()) / sd20, "z_runup5": (r5 - roll5.mean()) / sd5,
           "fwd5": float(fut.iloc[H_MAIN - 1] / entry - 1) if len(fut) >= H_MAIN else np.nan,
           "fwd21": float(fut.iloc[H_LONG - 1] / entry - 1) if len(fut) >= H_LONG else np.nan}
    seg = df[df.index <= entry_date].iloc[-15:]
    tr = np.maximum(seg["High"] - seg["Low"],
                    np.maximum((seg["High"] - seg["Close"].shift()).abs(), (seg["Low"] - seg["Close"].shift()).abs()))
    rec["atr"] = float(tr.iloc[1:].mean()) if len(seg) >= 6 else np.nan
    return rec, None


def live_sim(df, rec, asset_type, regime):
    """Live-Exitlogik (SL/Chandelier/Time-Stop) ab dem Tag nach dem Einstieg. pnl netto nach Slippage."""
    from config import get_exit_config
    from crabel_shadow_eval import simulate_forward
    bars = df[df.index > rec["entry_date"]]
    if not (rec["atr"] > 0) or len(bars) < 7:
        return np.nan, None
    ec = get_exit_config(asset_type=asset_type, regime=regime)
    sl = rec["entry"] - ec["sl"] * rec["atr"]
    tp = rec["entry"] + ec["tp"] * rec["atr"]
    outcome, exit_px, _days = simulate_forward(bars, rec["entry"], sl, tp, rec["atr"], "LONG", asset_type,
                                               None, regime=regime)
    return float(exit_px) / rec["entry"] - 1 - 2 * SLIPPAGE, outcome


# ─────────────────────────────────────────────────────────────── Aufbau
def build(con, dry_run=False, prices=None):
    from config import DETERMINISTIC_CHANNELS, get_asset_type
    ment = load_mentions(con, DETERMINISTIC_CHANNELS)
    ev = find_events(ment)
    print(f"Nennungen mit eindeutigem Ticker: {len(ment)} | Ereignisse: {len(ev)} | Ticker: {ev.ticker.nunique()}"
          f" | {ev.date.min():%Y-%m-%d} bis {ev.date.max():%Y-%m-%d}" if len(ev) else "keine Ereignisse", flush=True)
    if dry_run or ev.empty:
        return None
    if prices is None:
        if os.path.exists(PRICES):
            prices = pd.read_pickle(PRICES)
            missing = sorted(set(ev.ticker) - set(prices))
            if missing:
                prices.update(download_prices(missing, date.today().isoformat()))
        else:
            prices = download_prices(ev.ticker.unique(), date.today().isoformat())
        os.makedirs(OUT_DIR, exist_ok=True)
        pd.to_pickle(prices, PRICES)
    sectors = {r[0]: r[1] for r in con.execute("SELECT ticker, sector FROM companies").fetchall()}
    reg = pd.DataFrame([dict(r) for r in con.execute("SELECT date, regime FROM regime_history").fetchall()])
    reg_s = (pd.Series(reg.regime.values, index=pd.to_datetime(reg.date)).sort_index() if len(reg) else pd.Series(dtype=str))
    pcr = pd.DataFrame([dict(r) for r in con.execute("SELECT ticker, pcr, fetched_at FROM options_data").fetchall()])
    if len(pcr):
        pcr["d"] = pd.to_datetime(pcr.fetched_at.str[:10])

    rows, drop = [], {}
    for e in ev.itertuples(index=False):
        df = prices.get(e.ticker)
        if df is None or df.empty:
            drop["keine Kurse"] = drop.get("keine Kurse", 0) + 1
            continue
        rec, why = price_features(df, e.date)
        if rec is None:
            drop[why] = drop.get(why, 0) + 1
            continue
        f = mention_features(ment, e.ticker, e.date)
        rec.update(f)
        rec["conv_hand"] = hand_conviction(f)
        prior = reg_s[reg_s.index <= e.date]
        regime = prior.iloc[-1] if len(prior) else "sideways"
        asset_type = get_asset_type(sectors.get(e.ticker) or "Other")
        rec["live_pnl"], rec["live_outcome"] = live_sim(df, rec, asset_type, regime)
        if len(pcr):
            p = pcr[(pcr.ticker == e.ticker) & (pcr.d <= e.date) & (pcr.d >= e.date - pd.Timedelta(days=PCR_MAX_AGE))]
            rec["pcr"] = float(p.sort_values("d").pcr.iloc[-1]) if len(p) else np.nan
        else:
            rec["pcr"] = np.nan
        rec.update(ticker=e.ticker, date=e.date, regime=regime, asset_type=asset_type)
        rows.append(rec)
    out = pd.DataFrame(rows)
    print(f"Ereignisse mit Kursmerkmalen: {len(out)} | ausgeschlossen: {drop}", flush=True)
    if len(out):
        out.to_csv(EVENTS, index=False)
        print(f"geschrieben: {EVENTS}", flush=True)
    return out


# ─────────────────────────────────────────────────────────────── Statistik
def add_weeks(ev):
    ev = ev.copy()
    ev["entry_date"] = pd.to_datetime(ev["entry_date"])
    iso = ev["entry_date"].dt.isocalendar()
    ev["week"] = iso.year.astype(int) * 100 + iso.week.astype(int)
    ev["week_n"] = ev.groupby("week")["week"].transform("size")
    for col in ("fwd5", "fwd21", "live_pnl"):
        if col in ev:
            ev[col + "_dm"] = ev[col] - ev.groupby("week")[col].transform("mean")
    return ev


def _spear(x, y):
    ok = ~(np.isnan(x) | np.isnan(y))
    x, y = x[ok], y[ok]
    if len(x) < 3 or np.unique(x).size < 2 or np.unique(y).size < 2:
        return np.nan
    return float(np.corrcoef(pd.Series(x).rank(), pd.Series(y).rank())[0, 1])


def week_table(ev, xcol, ycol):
    """Je Woche mit >= MIN_WEEK_N Ereignissen: Spearman und unteres-minus-oberes Drittel."""
    rows = []
    for w, g in ev.dropna(subset=[xcol, ycol]).groupby("week"):
        if len(g) < MIN_WEEK_N:
            continue
        pct = g[xcol].rank(pct=True)
        lo, hi = g.loc[pct <= 1 / 3, ycol], g.loc[pct > 2 / 3, ycol]
        rows.append({"week": w, "n": len(g), "ic": _spear(g[xcol].values, g[ycol].values),
                     "spread": float(lo.mean() - hi.mean()) if len(lo) and len(hi) else np.nan})
    return pd.DataFrame(rows)


def boot_ab(ev, xcol, ycol, seed=1):
    """Bootstrap von (A, B): Bloecke = Wochen, Cluster = Ticker. Liefert zwei Arrays (n_boot, 2)."""
    rng = np.random.default_rng(seed)
    t = week_table(ev, xcol, ycol)
    wk = t[["ic", "spread"]].to_numpy()
    bw = np.array([np.nanmean(wk[rng.integers(0, len(wk), len(wk))], axis=0) for _ in range(BOOT_WEEK)])
    groups = {k: g for k, g in ev.groupby("ticker")}
    keys = list(groups)
    bt = []
    for _ in range(BOOT_TICKER):
        pick = rng.integers(0, len(keys), len(keys))
        s = pd.concat([groups[keys[i]] for i in pick], ignore_index=True)
        tt = week_table(s, xcol, ycol)
        bt.append([tt.ic.mean(), tt.spread.mean()] if len(tt) else [np.nan, np.nan])
    return bw, np.array(bt)


def sample_ok(ev):
    e = ev.dropna(subset=["fwd5"])
    weeks = e.groupby("week").size()
    return (len(e) >= MIN_EVENTS and e.ticker.nunique() >= MIN_TICKERS
            and int((weeks >= MIN_WEEK_N).sum()) >= MIN_WEEKS), len(e), e.ticker.nunique(), int((weeks >= MIN_WEEK_N).sum())


def analyze_p2(ev):
    t = week_table(ev, "z_runup20", "fwd5_dm")
    A, B = float(t.ic.mean()), float(t.spread.mean())
    bw, bt = boot_ab(ev, "z_runup20", "fwd5_dm")
    q = lambda a, k, p: float(np.nanquantile(a[:, k], p))  # noqa: E731
    A_hi = max(q(bw, 0, 0.975), q(bt, 0, 0.975))
    A_lo = min(q(bw, 0, 0.025), q(bt, 0, 0.025))
    B_lo = min(q(bw, 1, 0.025), q(bt, 1, 0.025))
    B_hi = max(q(bw, 1, 0.975), q(bt, 1, 0.975))
    weeks = sorted(t.week)
    half = len(weeks) // 2
    A1 = float(t[t.week.isin(weeks[:half])].ic.mean())
    A2 = float(t[t.week.isin(weeks[half:])].ic.mean())
    if A_hi < 0 and B_lo > 0 and A1 < 0 and A2 < 0:
        verdict = "HINTERHERLAUFEN BESTAETIGT"
    elif A_lo > 0 and B_hi < 0 and A1 > 0 and A2 > 0:
        verdict = "MOMENTUM (Gegenteil)"
    else:
        verdict = "KEIN BELEGBARER EFFEKT"
    return {"A": A, "B": B, "A_lo": A_lo, "A_hi": A_hi, "B_lo": B_lo, "B_hi": B_hi, "A1": A1, "A2": A2,
            "weeks": len(t), "verdict": verdict}


def quintiles(ev, xcol, ycols):
    e = ev.dropna(subset=[xcol]).copy()
    e["q"] = pd.qcut(e[xcol], 5, labels=False, duplicates="drop") + 1
    rows = []
    for q, g in e.groupby("q"):
        r = {"q": int(q), "n": len(g), "x_min": g[xcol].min(), "x_max": g[xcol].max()}
        for c in ycols:
            v = g[c].dropna()
            r[c + "_mean"], r[c + "_median"] = v.mean(), v.median()
            r[c + "_loss"] = (v < 0).mean() if len(v) else np.nan
        rows.append(r)
    return rows


def fit_logit(X, y, ridge=RIDGE, iters=50):
    """IRLS mit Ridge (Achsenabschnitt unbestraft). X ohne Konstante; Rueckgabe [b0, b1..bk]."""
    Xc = np.column_stack([np.ones(len(X)), X])
    b = np.zeros(Xc.shape[1])
    pen = np.eye(Xc.shape[1]) * ridge
    pen[0, 0] = 0.0
    for _ in range(iters):
        p = 1 / (1 + np.exp(-np.clip(Xc @ b, -30, 30)))
        w = p * (1 - p)
        H = Xc.T @ (Xc * w[:, None]) + pen
        g = Xc.T @ (y - p) - pen @ b
        step = np.linalg.solve(H, g)
        b = b + step
        if np.max(np.abs(step)) < 1e-8:
            break
    return b


def _std(train, test, cols):
    mu, sd = train[cols].mean(), train[cols].std().replace(0, 1)
    return ((train[cols] - mu) / sd).to_numpy(), ((test[cols] - mu) / sd).to_numpy()


def analyze_p1(ev, seed=2):
    rng = np.random.default_rng(seed)
    e = ev[ev.week_n >= MIN_WEEK_N].dropna(subset=FEATURES + ["fwd5_dm", "conv_hand"]).reset_index(drop=True)
    y = (e.fwd5_dm > 0).astype(float).to_numpy()
    X, _ = _std(e, e, FEATURES)
    coef = fit_logit(X, y)[1:]
    wk_groups = [np.flatnonzero(e.week.to_numpy() == w) for w in sorted(e.week.unique())]
    tk_groups = [np.flatnonzero(e.ticker.to_numpy() == t) for t in e.ticker.unique()]
    cw, ct = [], []
    for groups, sink, n in ((wk_groups, cw, BOOT_WEEK // 4), (tk_groups, ct, BOOT_TICKER // 2)):
        for _ in range(n):
            idx = np.concatenate([groups[i] for i in rng.integers(0, len(groups), len(groups))])
            sink.append(fit_logit(X[idx], y[idx])[1:])
    cw, ct = np.array(cw), np.array(ct)
    coefs = []
    for k, name in enumerate(FEATURES):
        lo = min(np.quantile(cw[:, k], 0.025), np.quantile(ct[:, k], 0.025))
        hi = max(np.quantile(cw[:, k], 0.975), np.quantile(ct[:, k], 0.975))
        coefs.append({"feature": name, "coef": float(coef[k]), "lo": float(lo), "hi": float(hi)})
    # Ausserhalb der Stichprobe
    weeks = sorted(e.week.unique())
    cut = weeks[int(len(weeks) * TRAIN_SHARE)]
    tr, te = e[e.week < cut], e[e.week >= cut].copy()
    Xtr, Xte = _std(tr, te, FEATURES)
    b = fit_logit(Xtr, (tr.fwd5_dm > 0).astype(float).to_numpy())
    te["score_reg"] = 1 / (1 + np.exp(-(b[0] + Xte @ b[1:])))
    t_reg = week_table(te, "score_reg", "fwd5_dm")
    t_conv = week_table(te, "conv_hand", "fwd5_dm")
    m = t_reg.merge(t_conv, on="week", suffixes=("_reg", "_conv"))
    d = (m.ic_reg - m.ic_conv).to_numpy()
    boots = [np.nanmean(d[rng.integers(0, len(d), len(d))]) for _ in range(BOOT_WEEK)] if len(d) else [np.nan]
    diff_lo = float(np.nanquantile(boots, 0.025))
    full_conv = week_table(e, "conv_hand", "fwd5_dm")
    return {"n": len(e), "coefs": coefs, "test_weeks": len(m), "test_n": len(te),
            "ic_reg": float(m.ic_reg.mean()) if len(m) else np.nan,
            "ic_conv": float(m.ic_conv.mean()) if len(m) else np.nan,
            "diff": float(np.nanmean(d)) if len(d) else np.nan, "diff_lo": diff_lo,
            "ic_conv_full": float(full_conv.ic.mean()) if len(full_conv) else np.nan,
            "verdict": "DATEN-SCORE BESSER" if diff_lo > 0 else "NICHT BESSER"}


def analyze_p3(ev, seed=3):
    e = ev[ev.week_n >= MIN_WEEK_N].dropna(subset=["pcr", "fwd5_dm"])
    if len(e) < MIN_PCR:
        return {"n": len(e), "verdict": "NICHT AUSSAGEKRAEFTIG"}
    rng = np.random.default_rng(seed)
    rho = _spear(e.pcr.values, e.fwd5_dm.values)
    groups = [g for _w, g in e.groupby("week")]
    bs = []
    for _ in range(BOOT_WEEK):
        s = pd.concat([groups[i] for i in rng.integers(0, len(groups), len(groups))])
        bs.append(_spear(s.pcr.values, s.fwd5_dm.values))
    lo, hi = float(np.nanquantile(bs, 0.025)), float(np.nanquantile(bs, 0.975))
    return {"n": len(e), "rho": rho, "lo": lo, "hi": hi,
            "verdict": "ZUSAMMENHANG" if (lo > 0 or hi < 0) else "KEIN BELEGBARER ZUSAMMENHANG"}


# ─────────────────────────────────────────────────────────────── Bericht
def _p(x, nd=3):
    return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else "%+.*f" % (nd, x)


def _pct(x):
    return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else "%+.2f %%" % (100 * x)


def report(ev, today=None):
    today = today or date.today()
    ev = add_weeks(ev)
    ok, n, nt, nw = sample_ok(ev)
    L = [f"Nennung vor/nach der Kursbewegung — Probe {today:%d.%m.%Y}", "",
         f"Ereignisse mit 5-Tage-Ergebnis {n} | Ticker {nt} | Wochen mit >= {MIN_WEEK_N} Ereignissen {nw} "
         f"(Soll {MIN_EVENTS} / {MIN_TICKERS} / {MIN_WEEKS})",
         f"Zeitraum Nennungen {pd.to_datetime(ev.date).min():%d.%m.%Y} bis {pd.to_datetime(ev.date).max():%d.%m.%Y}"]
    if not ok:
        return "\n".join(L + ["", "NICHT AUSSAGEKRAEFTIG: Stichprobe zu klein. Keine Kennzahlen (vorab festgelegt)."]), None
    res = {"p2": analyze_p2(ev), "p1": analyze_p1(ev), "p3": analyze_p3(ev)}
    p2 = res["p2"]
    L += ["", "── P2: Anstieg VOR der Nennung → Ergebnis danach (Hauptfrage) ──",
          f"Kennzahl A (wochenweise Spearman z_runup20 ~ fwd5_dm, {p2['weeks']} Wochen): {_p(p2['A'])}, "
          f"95-%-KI [{_p(p2['A_lo'])}; {_p(p2['A_hi'])}] | Haelften {_p(p2['A1'])} / {_p(p2['A2'])}",
          f"Kennzahl B (unteres minus oberes Anstiegs-Drittel, fwd5 marktbereinigt): {_pct(p2['B'])}, "
          f"95-%-KI [{_pct(p2['B_lo'])}; {_pct(p2['B_hi'])}]",
          f"URTEIL P2: {p2['verdict']}", "",
          "Quintile nach z_runup20 (nur berichtet; Mittel/Median/Verlustanteil, marktbereinigt):"]
    for r in quintiles(ev, "z_runup20", ["fwd5_dm", "fwd21_dm", "live_pnl_dm"]):
        L.append(f"  Q{r['q']} (z {r['x_min']:+.1f}..{r['x_max']:+.1f}, n={r['n']}): "
                 f"5T {_pct(r['fwd5_dm_mean'])} / {_pct(r['fwd5_dm_median'])} / {r['fwd5_dm_loss']:.0%} | "
                 f"21T {_pct(r['fwd21_dm_mean'])} | Live-Sim {_pct(r['live_pnl_dm_mean'])}")
    for label, x, yc in (("z_runup5 ~ fwd5_dm", "z_runup5", "fwd5_dm"),
                         ("z_runup20 ~ fwd21_dm", "z_runup20", "fwd21_dm"),
                         ("z_runup20 ~ Live-Sim", "z_runup20", "live_pnl_dm")):
        t = week_table(ev, x, yc)
        L.append(f"  nur berichtet: {label}: A {_p(float(t.ic.mean()) if len(t) else np.nan)} "
                 f"({len(t)} Wochen), B {_pct(float(t.spread.mean()) if len(t) else np.nan)}")
    p1 = res["p1"]
    L += ["", f"── P1: Gewichte aus Daten (logistisch, [fwd5_dm > 0], n={p1['n']}, standardisierte Merkmale) ──"]
    for c in p1["coefs"]:
        sig = "" if c["lo"] <= 0 <= c["hi"] else ("  ← positiv belegt" if c["lo"] > 0 else "  ← negativ belegt")
        L.append(f"  {c['feature']:16} {_p(c['coef'])}  KI [{_p(c['lo'])}; {_p(c['hi'])}]{sig}")
    L += [f"Handscore (calculate_conviction) ganze Stichprobe, wochenweise IC mit fwd5_dm: {_p(p1['ic_conv_full'])}",
          f"Ausserhalb der Stichprobe ({p1['test_weeks']} Testwochen, n={p1['test_n']}): IC Daten-Score "
          f"{_p(p1['ic_reg'])} vs Handscore {_p(p1['ic_conv'])}, Differenz {_p(p1['diff'])}, "
          f"untere 95-%-Grenze {_p(p1['diff_lo'])}",
          f"URTEIL P1: {p1['verdict']}"]
    p3 = res["p3"]
    L += ["", "── P3: Put/Call-Ratio und Insider ──",
          f"PCR-Messung in den {PCR_MAX_AGE} Tagen bis zur Nennung: {p3['n']} Ereignisse (Soll {MIN_PCR})."]
    if "rho" in p3:
        L.append(f"  Spearman PCR ~ fwd5_dm {_p(p3['rho'])}, 95-%-KI [{_p(p3['lo'])}; {_p(p3['hi'])}]")
    L += [f"URTEIL P3 (PCR): {p3['verdict']}",
          "Insider: nicht testbar. fetch_insider_trades() speichert nur Einreicher-Namen aus einer Volltextsuche, "
          "ohne Kauf/Verkauf, Stueckzahl oder Datum; Signal ist fest 'neutral'."]
    return "\n".join(L), res


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--build", action="store_true")
    g.add_argument("--analyze", action="store_true")
    a = ap.parse_args()
    if a.dry_run or a.build:
        from config import db_connect
        con = db_connect()
        build(con, dry_run=a.dry_run)
        return
    ev = pd.read_csv(EVENTS, parse_dates=["date", "entry_date"])
    text, _res = report(ev)
    print(text)
    path = os.path.join(OUT_DIR, f"report_{date.today():%Y-%m-%d}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(f"\ngespeichert: {path}")


if __name__ == "__main__":
    main()
