#!/usr/bin/env python3
"""Jev-Rueckwaertstest fuer den Forex Paper Bot (Tageskerzen) — 23.09.2026.

Fragen
  G1  Sagt Jev die Richtung der naechsten 5 Handelstage besser voraus als (a) die Basisrate
      und (b) eine simple Momentum-Regel?
  G2  Verbessert Jev als zusaetzlicher Gate das bestehende EMA-Signal des Bots
      (Trades, bei denen Jev zustimmt, netto besser als Trades, bei denen er widerspricht)?

Zwei Darstellungen desselben Zustands (Arme):
  NUM  Zahlen (Renditen in Basispunkten, ATR, EMA-Abstand)
  TXT  dieselbe Information in Worten (in ATR-Einheiten, ohne Zahlen)

Ablauf: Jev bekommt fuer jeden Handelstag t (ab 2016) NUR Daten bis t, keine Datumsangabe. Die Wahrheit
(Schlusskurs t+1 bzw. t+5) wird erst in der Auswertung dazugelegt. Zero-shot, es wird nichts angepasst.

VORAB FESTGELEGTE ENTSCHEIDUNGSREGEL (nicht nachtraeglich aendern)
  Primaere Tests: H=5, je Arm. Untere Grenze des 98-%-einseitigen Block-Bootstrap-KI (Bloecke = Monate,
  ueber alle Paare), 4000 Ziehungen.
  G1 bestanden, wenn fuer BEIDE Baselines gilt: Punktschaetzung Jev - Baseline >= +0,01 UND untere
     KI-Grenze > 0 UND Jev in beiden chronologischen Haelften besser als die Baseline dieser Haelfte.
  G2 bestanden, wenn: n(Jev stimmt zu) >= 150 UND mittlere Netto-Rendite(zustimmend) - (widersprechend)
     hat untere KI-Grenze > 0 UND mittlere Netto-Rendite(zustimmend) > 0.
  GO nur, wenn ein Arm G1 UND G2 besteht. H=1 wird nur berichtet (explorativ).
  Netto = Rendite in Signalrichtung ueber 5 Tage minus 2 x Spread (Entry + Exit, Spread je Paar aus config.json).

NUR LESEND: forex.db und der Bot bleiben unberuehrt. Keine Kopplung an hermes_trading (NG-2): eigener
Mini-Client, Key kommt aus der Umgebung (OPENROUTER_API_KEY), nicht aus dem Bot.

Aufruf (Key vorher exportieren):
    venv/bin/python scripts/jev_probe.py --dry-run
    venv/bin/python scripts/jev_probe.py --run [--limit N]
    venv/bin/python scripts/jev_probe.py --repeat 600
    venv/bin/python scripts/jev_probe.py --analyze
"""
import argparse
import json
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(HERE, "reports", "jev_probe")
CANDLES = os.path.join(OUT_DIR, "candles.csv")
RESULTS = os.path.join(OUT_DIR, "jev_results.jsonl")
CFG = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))

START_DATA = "2010-01-01"
START_EVAL = "2016-01-01"
ARMS = ("NUM", "TXT")
HORIZONS = (1, 5)
WORKERS = 8
BOOT = 4000
ALPHA_ONE_SIDED = 0.02
MIN_AGREE_N = 150
MIN_POINT_EDGE = 0.01
URL = "https://openrouter.ai/api/alpha/decisions"
MODEL = "~typesafe/jev-latest"

TASK = ("Daily candles of a currency pair, described as of the latest close. Judge the likely direction of "
        "the following closes using only the described price action.")
QUESTIONS = {
    "h1": {"type": "choice", "instructions": "Will the close 1 trading day from now be higher or lower than the latest close?",
           "criteria": {"up": "the close 1 trading day from now is higher than the latest close",
                        "down": "the close 1 trading day from now is lower than the latest close"}},
    "h5": {"type": "choice", "instructions": "Will the close 5 trading days from now be higher or lower than the latest close?",
           "criteria": {"up": "the close 5 trading days from now is higher than the latest close",
                        "down": "the close 5 trading days from now is lower than the latest close"}},
}
_LOCK = threading.Lock()


# ─────────────────────────────────────────────────────────────── Daten
def load_candles():
    os.makedirs(OUT_DIR, exist_ok=True)
    if os.path.exists(CANDLES):
        df = pd.read_csv(CANDLES, parse_dates=["Date"])
        return {p: g.set_index("Date").drop(columns="pair") for p, g in df.groupby("pair")}
    import yfinance as yf
    frames = []
    for p in CFG["pairs"]:
        d = yf.download(p, start=START_DATA, interval="1d", progress=False, auto_adjust=False, threads=False)
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)
        d = d[["High", "Low", "Close"]].dropna()
        d.index = pd.to_datetime(d.index).tz_localize(None).normalize()
        d = d[~d.index.duplicated()]
        d["pair"] = p
        frames.append(d.reset_index().rename(columns={d.index.name or "index": "Date"}))
        print("  %s: %d Tageskerzen (%s bis %s)" % (p, len(d), d.index[0].date(), d.index[-1].date()), flush=True)
    df = pd.concat(frames)
    df.to_csv(CANDLES, index=False)
    return {p: g.set_index("Date").drop(columns="pair") for p, g in df.groupby("pair")}


def features(df):
    c, h, l = df["Close"].astype(float), df["High"].astype(float), df["Low"].astype(float)
    f = pd.DataFrame(index=df.index)
    f["close"] = c
    f["ret_bps"] = c.pct_change() * 1e4
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    f["atr_bps"] = tr.rolling(14).mean() / c * 1e4
    f["atr_med"] = f["atr_bps"].rolling(100).median()
    f["r5"] = (c / c.shift(5) - 1) * 1e4
    f["r20"] = (c / c.shift(20) - 1) * 1e4
    f["r60"] = (c / c.shift(60) - 1) * 1e4
    sig = CFG["signal"]
    fast = c.ewm(span=sig["ema_fast"], adjust=False).mean()
    slow = c.ewm(span=sig["ema_slow"], adjust=False).mean()
    f["ema_gap_bps"] = (fast / slow - 1) * 1e4
    wk = c.resample("W-FRI").last().dropna()
    wk_ema = wk.ewm(span=sig["h1_ema"], adjust=False).mean()
    wk_ref = wk_ema.reindex(c.index, method="ffill")
    f["wk_gap_bps"] = (c / wk_ref - 1) * 1e4
    # EMA-Signal des Bots (Logik aus forex_signal.py, auf Tagesbasis)
    cross_now = fast > slow
    cross_prev = cross_now.shift(1, fill_value=False)
    mom = c / c.shift(sig["momentum_lookback"]) - 1
    ms = sig.get("min_trend_strength", 0.0002)
    h1_bull, h1_bear = f["wk_gap_bps"] > 0, f["wk_gap_bps"] < 0
    long_ = (h1_bull & cross_now & (mom > ms)) | (h1_bull & cross_now & ~cross_prev)
    short_ = (h1_bear & ~cross_now & (mom < -ms)) | (h1_bear & ~cross_now & cross_prev)
    f["bot_signal"] = np.where(long_, 1, np.where(short_, -1, 0))
    for hz in HORIZONS:
        f["fwd%d" % hz] = c.shift(-hz) / c - 1
    return f.dropna(subset=["atr_bps", "atr_med", "r60", "wk_gap_bps"])


def samples(all_feats):
    out = []
    for p, f in all_feats.items():
        f2 = f[f.index >= START_EVAL]
        for t in f2.index:
            out.append((p, t))
    return out


# ─────────────────────────────────────────────────────────────── Zustand
def _word(r_bps, atr_bps):
    z = r_bps / max(atr_bps, 1e-9)
    mag = "flat" if abs(z) < 0.3 else ("slightly " if abs(z) < 1 else ("" if abs(z) < 2.5 else "strongly "))
    if mag == "flat":
        return "flat"
    return mag + ("up" if z > 0 else "down")


def build_state(arm, pair, f, t, hist):
    row = f.loc[t]
    disp = CFG["pairs"][pair]["display"]
    last = hist.loc[:t, "ret_bps"].iloc[-20:]
    if arm == "NUM":
        return {"task": TASK, "instrument": disp,
                "last_20_daily_returns_bps_oldest_first": [int(round(x)) for x in last],
                "return_bps": {"5d": int(round(row.r5)), "20d": int(round(row.r20)), "60d": int(round(row.r60))},
                "atr14_bps": int(round(row.atr_bps)),
                "ema13_vs_ema150_bps": int(round(row.ema_gap_bps)),
                "close_vs_weekly_ema20_bps": int(round(row.wk_gap_bps))}
    atr = row.atr_bps
    vol = row.atr_bps / row.atr_med
    vol_w = "low" if vol < 0.8 else ("high" if vol > 1.25 else "normal")
    gap_z = row.ema_gap_bps / max(atr, 1e-9)
    wk_z = row.wk_gap_bps / max(atr, 1e-9)

    def rel(z):
        a = abs(z)
        return "barely" if a < 1 else ("clearly" if a < 4 else "far")
    return {"task": TASK, "instrument": disp,
            "last_10_days_oldest_first": [_word(x, atr) for x in last.iloc[-10:]],
            "last_5_days": _word(row.r5, atr * 2.2), "last_20_days": _word(row.r20, atr * 4.5),
            "last_60_days": _word(row.r60, atr * 7.7),
            "volatility": vol_w,
            "medium_term_trend": "the 13-day average is %s %s the 150-day average"
                                 % (rel(gap_z), "above" if gap_z > 0 else "below"),
            "weekly_trend": "price is %s %s its weekly 20-period average"
                            % (rel(wk_z), "above" if wk_z > 0 else "below")}


def est_tokens(o):
    return len(json.dumps(o, ensure_ascii=False)) // 3


# ─────────────────────────────────────────────────────────────── Jev
def decide(state, timeout=60):
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise SystemExit("OPENROUTER_API_KEY nicht gesetzt")
    for attempt in range(3):
        try:
            r = requests.post(URL, headers={"Authorization": "Bearer " + key},
                              json={"model": MODEL, "state": state, "questions": QUESTIONS}, timeout=timeout)
        except requests.RequestException:
            time.sleep(2 ** attempt)
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(2 ** attempt)
            continue
        if r.status_code != 200:
            return None
        try:
            d = r.json()
            ans = {}
            for k in ("h1", "h5"):
                a = d["answers"][k]
                ans[k] = {"label": a["choice"], "p_up": float(a["probabilities"]["up"]), "conf": float(a["confidence"])}
                if ans[k]["label"] not in ("up", "down"):
                    return None
            u = d.get("usage") or {}
            return ans, [int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0), float(u.get("cost") or 0)]
        except (KeyError, TypeError, ValueError):
            return None
    return None


def load_results():
    out = []
    if os.path.exists(RESULTS):
        for line in open(RESULTS, encoding="utf-8"):
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def run(limit=None, dry=False, repeat=None):
    candles = load_candles()
    feats = {p: features(d) for p, d in candles.items()}
    S = samples(feats)
    done = {(r["pair"], r["date"], r["arm"], r.get("rep", 0)) for r in load_results() if r.get("ok")}
    if repeat:
        rnd = random.Random(7)
        done_main = sorted((r["pair"], r["date"], r["arm"]) for r in load_results() if r.get("ok") and not r.get("rep"))
        pick = rnd.sample(done_main, min(repeat, len(done_main)))
        todo = [(p, pd.Timestamp(d), a, 1) for p, d, a in pick if (p, d, a, 1) not in done]
    else:
        todo = [(p, t, a, 0) for (p, t) in S for a in ARMS if (p, str(t.date()), a, 0) not in done]
        if limit:
            random.Random(3).shuffle(todo)
            todo = todo[:limit]
    tok = 0
    for p, t, a, _ in todo[:200]:
        tok += est_tokens(build_state(a, p, feats[p], t, candles[p].assign(ret_bps=candles[p]["Close"].pct_change() * 1e4))) + est_tokens(QUESTIONS)
    tok = int(tok / max(min(len(todo), 200), 1) * len(todo))
    print("Handelstage x Paare: %d | offene Anfragen: %d | ~Eingabetokens %d -> ~$%.2f (0,042 $/Mio.)"
          % (len(S), len(todo), tok, tok * 0.042 / 1e6), flush=True)
    if dry or not todo:
        return
    hist = {p: candles[p].assign(ret_bps=candles[p]["Close"].pct_change() * 1e4) for p in candles}

    def work(item):
        p, t, a, rep = item
        res = decide(build_state(a, p, feats[p], t, hist[p]))
        rec = {"pair": p, "date": str(t.date()), "arm": a, "rep": rep, "ok": bool(res)}
        if res:
            rec["ans"], rec["usage"] = res
        with _LOCK:
            with open(RESULTS, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")
        return bool(res)

    t0 = time.time()
    n_ok = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for i, ok in enumerate(ex.map(work, todo), 1):
            n_ok += ok
            if i % 1000 == 0:
                print("  %d/%d (%.0f s)" % (i, len(todo), time.time() - t0), flush=True)
    print("Fertig: %d/%d ok in %.0f s" % (n_ok, len(todo), time.time() - t0), flush=True)


# ─────────────────────────────────────────────────────────────── Auswertung
def month_blocks(dates):
    keys = sorted({(d.year, d.month) for d in dates})
    idx = {k: i for i, k in enumerate(keys)}
    return np.array([idx[(d.year, d.month)] for d in dates]), len(keys)


def boot_ratio_diff(block, m, num_a, den_a, num_b, den_b, seed=5):
    """Bootstrap ueber Monatsbloecke fuer (sum num_a/sum den_a) - (sum num_b/sum den_b)."""
    def agg(x):
        return np.bincount(block, weights=x, minlength=m)
    na, da, nb, db = agg(num_a), agg(den_a), agg(num_b), agg(den_b)
    rnd = np.random.default_rng(seed)
    idx = rnd.integers(0, m, size=(BOOT, m))
    with np.errstate(divide="ignore", invalid="ignore"):
        vals = na[idx].sum(1) / da[idx].sum(1) - nb[idx].sum(1) / db[idx].sum(1)
    vals = vals[np.isfinite(vals)]
    point = na.sum() / da.sum() - nb.sum() / db.sum()
    return point, np.quantile(vals, ALPHA_ONE_SIDED), np.quantile(vals, 0.5), np.quantile(vals, 1 - ALPHA_ONE_SIDED)


def analyze():
    candles = load_candles()
    feats = {p: features(d) for p, d in candles.items()}
    recs = [r for r in load_results() if r.get("ok") and not r.get("rep")]
    total = len([r for r in load_results() if not r.get("rep")])
    print("=== Datenbasis ===")
    print("  Anfragen: %d | erfolgreich: %d (%.1f %%) | Kosten $%.3f"
          % (total, len(recs), 100 * len(recs) / max(total, 1), sum(r["usage"][2] for r in recs)))
    go_flags = {}
    for arm in ARMS:
        rows = []
        for r in recs:
            if r["arm"] != arm:
                continue
            p, t = r["pair"], pd.Timestamp(r["date"])
            fr = feats[p].loc[t]
            spread = 2 * CFG["pairs"][p]["spread_pips"] * CFG["pairs"][p]["pip_size"] / fr.close
            rows.append({"pair": p, "t": t, "mom": fr.r5, "sig": int(fr.bot_signal), "spread": spread,
                         "j1": 1 if r["ans"]["h1"]["label"] == "up" else -1,
                         "j5": 1 if r["ans"]["h5"]["label"] == "up" else -1,
                         "c5": r["ans"]["h5"]["conf"], "c1": r["ans"]["h1"]["conf"], "f1": fr.fwd1, "f5": fr.fwd5})
        D = pd.DataFrame(rows).sort_values("t").reset_index(drop=True)
        print("\n################ Arm %s | %d Bewertungen, %s bis %s ################"
              % (arm, len(D), D.t.min().date(), D.t.max().date()))
        for hz in HORIZONS:
            d = D.dropna(subset=["f%d" % hz]).copy()
            y = np.where(d["f%d" % hz] > 0, 1, -1)
            jev = d["j%d" % hz].to_numpy()
            mom = np.where(d.mom > 0, 1, -1)
            base_cls = 1 if (y == 1).mean() >= 0.5 else -1
            base = np.full(len(d), base_cls)
            blk, m = month_blocks(list(d.t))
            one = np.ones(len(d))
            cj, cb, cm = (jev == y).astype(float), (base == y).astype(float), (mom == y).astype(float)
            half = len(d) // 2
            print("\n--- Horizont %d Tag(e)%s ---" % (hz, "  [PRIMAER]" if hz == 5 else "  [explorativ]"))
            print("  Trefferquote: Jev %.3f | Basisrate (immer %s) %.3f | Momentum-Regel %.3f | Jev sagt 'up' in %.0f %% der Faelle"
                  % (cj.mean(), "up" if base_cls == 1 else "down", cb.mean(), cm.mean(), 100 * (jev == 1).mean()))
            g1_ok = True
            for name, cx in (("Basisrate", cb), ("Momentum", cm)):
                pt, lo, med, hi = boot_ratio_diff(blk, m, cj, one, cx, one)
                h1_ok = cj[:half].mean() > cx[:half].mean()
                h2_ok = cj[half:].mean() > cx[half:].mean()
                ok = pt >= MIN_POINT_EDGE and lo > 0 and h1_ok and h2_ok
                g1_ok &= ok
                print("  Jev - %-9s %+.4f  [untere Grenze %+.4f]  Haelfte1 %s, Haelfte2 %s  -> %s"
                      % (name, pt, lo, "besser" if h1_ok else "nicht besser", "besser" if h2_ok else "nicht besser",
                         "erfuellt" if ok else "verfehlt"))
            print("  Kalibrierung (|p_up-0,5| als Sicherheit) -> Trefferquote:")
            conf = d["c%d" % hz].to_numpy()
            for lo_b, hi_b in ((0, .5), (.5, .8), (.8, .95), (.95, 1.01)):
                mk = (conf >= lo_b) & (conf < hi_b)
                if mk.sum():
                    print("    Konfidenz %.2f-%.2f: n=%5d  Trefferquote %.3f" % (lo_b, min(hi_b, 1), mk.sum(), cj[mk].mean()))
            if hz == 5:
                go_flags[arm] = {"g1": g1_ok}
                s = d[d.sig != 0].copy()
                if len(s) == 0:
                    print("  Gate: keine Signaltage")
                    go_flags[arm]["g2"] = False
                    continue
                net = s.sig * s.f5 - s.spread
                agree = (s.j5 == s.sig).to_numpy()
                blk_s, m_s = month_blocks(list(s.t))
                netv = net.to_numpy()
                ag = agree.astype(float)
                dis = 1 - ag
                pt, lo, med, hi = boot_ratio_diff(blk_s, m_s, netv * ag, ag, netv * dis, dis)
                mean_ag = netv[agree].mean() if agree.any() else float("nan")
                mean_dis = netv[~agree].mean() if (~agree).any() else float("nan")
                g2 = agree.sum() >= MIN_AGREE_N and lo > 0 and mean_ag > 0
                go_flags[arm]["g2"] = bool(g2)
                print("  GATE auf das EMA-Signal des Bots (5-Tage-Ergebnis in Signalrichtung, netto nach 2 x Spread):")
                print("    Signaltage %d | Jev stimmt zu: %d | widerspricht: %d | alle Signale netto im Mittel %+.4f"
                      % (len(s), agree.sum(), (~agree).sum(), netv.mean()))
                print("    Netto zustimmend %+.4f | widersprechend %+.4f | Differenz %+.4f [untere Grenze %+.4f]  -> %s"
                      % (mean_ag, mean_dis, pt, lo, "erfuellt" if g2 else "verfehlt"))
                # Jev allein als Signal (informativ)
                allnet = d.j5 * d.f5 - d.spread
                print("  INFO Jev allein als Signal (jeden Tag in Jev-Richtung, netto): %+.4f je Trade | EMA-Signal allein: %+.4f"
                      % (allnet.mean(), netv.mean()))
    print("\n=== ENTSCHEIDUNG (vorab festgelegte Regel) ===")
    for arm, g in go_flags.items():
        print("  %s: G1 %s | G2 %s  -> %s" % (arm, "bestanden" if g["g1"] else "verfehlt",
                                              "bestanden" if g.get("g2") else "verfehlt",
                                              "GO" if g["g1"] and g.get("g2") else "NO-GO"))
    rep = [r for r in load_results() if r.get("ok") and r.get("rep")]
    if rep:
        first = {(r["pair"], r["date"], r["arm"]): r for r in load_results() if r.get("ok") and not r.get("rep")}
        same5 = np.mean([first[(r["pair"], r["date"], r["arm"])]["ans"]["h5"]["label"] == r["ans"]["h5"]["label"]
                         for r in rep if (r["pair"], r["date"], r["arm"]) in first])
        print("\n  Jev-Eigenrauschen (gleiche Anfrage wiederholt, n=%d): gleiche h5-Richtung in %.1f %% der Faelle" % (len(rep), 100 * same5))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--analyze", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--repeat", type=int)
    a = ap.parse_args()
    if a.analyze:
        analyze()
    elif a.repeat:
        run(repeat=a.repeat)
    elif a.run or a.dry_run:
        run(limit=a.limit, dry=a.dry_run)
    else:
        ap.print_help()
