#!/usr/bin/env python3
"""Auswertung der Shadow-Hypothese h_jev (AC-6 aus jev-vorfilter-shadow.md) — 23.09.2026.

Frage: Ordnet der Jev-Score P(Take-Profit vor Stop-Loss) die spaeter simulierten Ergebnisse
(shadow_selection.pnl_pct_sim, 21 Tage Horizont) besser als conviction_score und tech_score?

VORAB FESTGELEGT (nicht nachtraeglich aendern)
  Stichprobe: mindestens 150 ausgewertete h_jev-Zeilen UND mindestens 40 verschiedene Ticker. Vorher gibt
  das Skript nur den Stand aus und schreibt ausdruecklich "nicht aussagekraeftig", ohne Kennzahlen.
  Kennzahl A (Rangguete): je Auswahltag (mind. 8 ausgewertete Zeilen) Spearman-Korrelation des Scores mit
     pnl_pct_sim, gemittelt ueber die Tage (querschnittlich, damit die Marktbewegung des Tages rausfaellt).
     Verglichen mit derselben Kennzahl fuer conviction und tech (aus der Begruendung der Zeile, also die Werte
     zum Auswahlzeitpunkt). dA = IC(Jev) - max(IC(conviction), IC(tech)).
  Kennzahl B (Vorfilter): je Tag mittleres pnl_pct_sim des obersten Jev-Drittels minus des untersten, Mittel ueber Tage.
  Kennzahl C (Kalibrierung, nur berichtet): Trefferquote TP_HIT je Score-Bucket.
  Unsicherheit: zwei Bootstraps, (1) Bloecke = Kalenderwochen der Auswahltage, (2) Cluster = Ticker.
  Es zaehlt die KLEINERE untere 95-%-Grenze. Die 21-Tage-Horizonte ueberlappen, daher die Bloecke.
  GO nur wenn untere Grenze von dA > 0 UND untere Grenze von B > 0. Sonst NO-GO.

Aufruf:
    venv/bin/python scripts/jev_shadow_eval.py                # Bericht auf stdout
    venv/bin/python scripts/jev_shadow_eval.py --telegram     # zusaetzlich an Telegram senden
    venv/bin/python scripts/jev_shadow_eval.py --cron         # Telegram + bei Urteil/Endtermin Cron-Zeile entfernen
Nur lesend (trading.db). Schreibt nur data/jev_shadow_eval_<datum>.txt.
"""
import argparse
import os
import re
import subprocess
import sys
import traceback
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

_ROOT = "/root/.hermes/profiles/hermes_trading/skills/trading"
for _p in (_ROOT, os.path.join(_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import env_loader  # noqa: F401  (side-effect: laedt .env)
from config import db_connect

HYP = "h_jev"
MIN_ROWS = 150
MIN_TICKERS = 40
MIN_DAY_ROWS = 8
BOOT_WEEK = 2000
BOOT_TICKER = 500
ALPHA = 0.025                       # untere Grenze eines zentralen 95-%-Intervalls
HORIZON_DAYS = 21
LAST_RUN_DATE = date(2026, 11, 26)  # letzter geplanter Termin, danach beendet sich der Job
CRON_MARKER = "jev_shadow_eval.py"
BUCKETS = ((0.0, 0.3), (0.3, 0.5), (0.5, 0.7), (0.7, 1.01))
_RAT = re.compile(r"conv=([0-9.]+)\s+tech=([0-9.]+)")
_MODEL = re.compile(r"model=(\S+)")   # jev-pin-20260925; Zeilen vor dem 25.09. haben keine Angabe
NO_MODEL = "ohne Angabe"


# ─────────────────────────────────────────────────────────────── Daten
def load_rows(con):
    rows = con.execute("""
        SELECT select_date, ticker, score, rationale, pnl_pct_sim, outcome, eval_status
        FROM shadow_selection WHERE hypothesis=?
    """, (HYP,)).fetchall()
    df = pd.DataFrame([dict(r) for r in rows])
    if df.empty:
        return df
    m = df["rationale"].fillna("").str.extract(_RAT)
    df["conv"] = pd.to_numeric(m[0], errors="coerce")
    df["tech"] = pd.to_numeric(m[1], errors="coerce")
    df["pnl"] = pd.to_numeric(df["pnl_pct_sim"], errors="coerce")
    df["model"] = df["rationale"].fillna("").str.extract(_MODEL)[0].fillna(NO_MODEL)
    return df


def evaluated(df):
    if df.empty:
        return df
    e = df[(df.eval_status == "evaluated")].dropna(subset=["pnl", "score", "conv", "tech"])
    return e


# ─────────────────────────────────────────────────────────────── Kennzahlen
def _ic(x, y):
    if x.nunique() < 2 or y.nunique() < 2:
        return np.nan
    return float(np.corrcoef(x.rank(), y.rank())[0, 1])


def day_table(e):
    out = []
    for d, g in e.groupby("select_date"):
        if len(g) < MIN_DAY_ROWS:
            continue
        pct = g["score"].rank(pct=True)
        top, bot = g.pnl[pct >= 2 / 3], g.pnl[pct <= 1 / 3]
        out.append({"date": d, "n": len(g), "ic_jev": _ic(g["score"], g["pnl"]),
                    "ic_conv": _ic(g["conv"], g["pnl"]), "ic_tech": _ic(g["tech"], g["pnl"]),
                    "spread": float(top.mean() - bot.mean()) if len(top) and len(bot) else np.nan})
    return pd.DataFrame(out)


def stats_from_days(t):
    if t.empty:
        return np.nan, np.nan, np.nan, np.nan, np.nan
    ij, ic, it = t.ic_jev.mean(), t.ic_conv.mean(), t.ic_tech.mean()
    return ij - max(ic, it), t.spread.mean(), ij, ic, it


def _week(d):
    y, w, _ = datetime.strptime(d, "%Y-%m-%d").isocalendar()
    return (y, w)


def boot_weeks(t, seed=1):
    rnd = np.random.default_rng(seed)
    wk = t["date"].map(_week)
    groups = [t[wk == w] for w in sorted(set(wk))]
    res = []
    for _ in range(BOOT_WEEK):
        pick = rnd.integers(0, len(groups), len(groups))
        res.append(stats_from_days(pd.concat([groups[i] for i in pick]))[:2])
    return np.array(res)


def boot_tickers(e, seed=2):
    rnd = np.random.default_rng(seed)
    groups = [g for _t, g in e.groupby("ticker")]
    res = []
    for _ in range(BOOT_TICKER):
        pick = rnd.integers(0, len(groups), len(groups))
        res.append(stats_from_days(day_table(pd.concat([groups[i] for i in pick])))[:2])
    return np.array(res)


def bucket_table(e):
    rows = []
    base = (e.outcome == "TP_HIT").mean()
    for lo, hi in BUCKETS:
        g = e[(e.score >= lo) & (e.score < hi)]
        rows.append({"bucket": "%.1f-%.1f" % (lo, min(hi, 1.0)), "n": len(g),
                     "tp_rate": float((g.outcome == "TP_HIT").mean()) if len(g) else np.nan,
                     "mean_pnl": float(g.pnl.mean()) if len(g) else np.nan})
    return base, rows


def analyze(df, today=None):
    """Liefert dict mit verdict in {PENDING, GO, NO-GO} und allen Zahlen."""
    today = today or date.today()
    e = evaluated(df)
    res = {"n_total": 0 if df.empty else len(df), "n_eval": len(e),
           "tickers": int(e.ticker.nunique()) if len(e) else 0}
    if not df.empty:
        res["score_min"], res["score_max"] = float(df.score.min()), float(df.score.max())
        res["score_std"] = float(df.score.std())
        res["models"] = {str(k): int(v) for k, v in df["model"].value_counts().items()}
        res["first_select"] = df.select_date.min()
        res["first_mature"] = (datetime.strptime(df.select_date.min(), "%Y-%m-%d").date()
                               + timedelta(days=HORIZON_DAYS)).isoformat()
    if res["n_eval"] < MIN_ROWS or res["tickers"] < MIN_TICKERS:
        res["verdict"] = "PENDING"
        return res
    t = day_table(e)
    res["days"] = len(t)
    if len(t) < 5:
        res["verdict"] = "PENDING"
        res["why"] = "weniger als 5 Auswahltage mit je %d ausgewerteten Zeilen" % MIN_DAY_ROWS
        return res
    dA, B, ij, ic, it = stats_from_days(t)
    bw = boot_weeks(t)
    bt = boot_tickers(e)
    lo = lambda arr, k: float(np.nanquantile(arr[:, k], ALPHA))  # noqa: E731
    res.update(dA=dA, B=B, ic_jev=ij, ic_conv=ic, ic_tech=it,
               dA_lo_week=lo(bw, 0), dA_lo_ticker=lo(bt, 0), B_lo_week=lo(bw, 1), B_lo_ticker=lo(bt, 1))
    res["dA_lo"] = min(res["dA_lo_week"], res["dA_lo_ticker"])
    res["B_lo"] = min(res["B_lo_week"], res["B_lo_ticker"])
    res["base_tp"], res["buckets"] = bucket_table(e)
    res["verdict"] = "GO" if (res["dA_lo"] > 0 and res["B_lo"] > 0) else "NO-GO"
    return res


# ─────────────────────────────────────────────────────────────── Bericht
def _f(x, nd=3):
    return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else ("%+.*f" % (nd, x))


def format_report(r, today=None):
    today = today or date.today()
    L = ["Jev-Shadow (h_jev) — Auswertung %s" % today.strftime("%d.%m.%Y"), ""]
    L.append("Zeilen gesamt %d | ausgewertet %d | verschiedene Ticker %d (Soll: %d / %d)"
             % (r["n_total"], r["n_eval"], r["tickers"], MIN_ROWS, MIN_TICKERS))
    if "score_std" in r:
        L.append("Jev-Score: Spanne %.2f bis %.2f, Streuung %.3f | erste Auswahl %s, erste Zeilen reif ab %s"
                 % (r["score_min"], r["score_max"], r["score_std"], r["first_select"], r["first_mature"]))
    if r.get("models"):
        L.append("Modellversion(en): " + ", ".join("%s %d" % (k, v) for k, v in sorted(r["models"].items())))
        known = [k for k in r["models"] if k != NO_MODEL]
        if len(known) > 1:
            L.append("ACHTUNG: Die Stichprobe mischt Modellversionen, das Urteil gilt fuer keine einzelne davon.")
    if r["verdict"] == "PENDING":
        L += ["", "NICHT AUSSAGEKRAEFTIG: Stichprobe zu klein." + (" " + r["why"] if r.get("why") else ""),
              "Es werden bewusst keine Kennzahlen bewertet (vorab festgelegt)."]
        return "\n".join(L)
    L += ["", "Kennzahl A (mittlere tagesweise Rangkorrelation mit pnl_pct_sim, %d Auswahltage):" % r["days"],
          "  Jev %s | conviction %s | tech %s" % (_f(r["ic_jev"]), _f(r["ic_conv"]), _f(r["ic_tech"])),
          "  dA = Jev - bester Vorhandener: %s, untere 95-%%-Grenze %s (Wochen %s, Ticker %s) -> %s"
          % (_f(r["dA"]), _f(r["dA_lo"]), _f(r["dA_lo_week"]), _f(r["dA_lo_ticker"]),
             "erfuellt" if r["dA_lo"] > 0 else "verfehlt"),
          "Kennzahl B (oberes minus unteres Jev-Drittel, mittleres pnl in Prozentpunkten je Tag):",
          "  %s, untere 95-%%-Grenze %s (Wochen %s, Ticker %s) -> %s"
          % (_f(r["B"], 2), _f(r["B_lo"], 2), _f(r["B_lo_week"], 2), _f(r["B_lo_ticker"], 2),
             "erfuellt" if r["B_lo"] > 0 else "verfehlt"),
          "Kennzahl C (Trefferquote TP je Score-Bucket, Basis %.0f %%):" % (100 * r["base_tp"])]
    for b in r["buckets"]:
        L.append("  %s: n=%d, TP-Rate %s, mittleres pnl %s"
                 % (b["bucket"], b["n"], "n/a" if np.isnan(b["tp_rate"]) else "%.0f %%" % (100 * b["tp_rate"]),
                    _f(b["mean_pnl"], 2)))
    L += ["", "URTEIL: " + ("GO — Vorfilter-Versuch ist gerechtfertigt (nur Shadow, Entscheidung bei dir)."
                          if r["verdict"] == "GO"
                          else "NO-GO — Jev bringt keinen belegbaren Vorteil. h_jev abschalten: JEV_SHADOW im "
                               ".env der Trading-Skills entfernen oder auf off setzen.")]
    return "\n".join(L)


def send_telegram(msg):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "") or os.environ.get("TELEGRAM_HOME_CHANNEL", "")
    if not token or not chat:
        return False, "TELEGRAM_BOT_TOKEN oder Chat-ID fehlt"
    try:
        import requests
        r = requests.post("https://api.telegram.org/bot%s/sendMessage" % token,
                          json={"chat_id": chat, "text": msg[:4000]}, timeout=15)
        return (r.status_code == 200), ("HTTP %d" % r.status_code)
    except Exception as e:
        return False, type(e).__name__


def disable_own_cron():
    try:
        cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        if cur.returncode != 0:
            print("Crontab nicht lesbar — Zeilen bitte manuell entfernen.")
            return
        lines = cur.stdout.splitlines()
        kept = [l for l in lines if CRON_MARKER not in l]
        if len(kept) == len(lines):
            return
        p = subprocess.run(["crontab", "-"], input="\n".join(kept) + "\n", text=True, capture_output=True)
        print("Eigene Cron-Zeilen entfernt." if p.returncode == 0
              else "Cron-Zeilen NICHT entfernt (%s) — bitte manuell." % p.stderr.strip())
    except Exception as e:
        print("Cron-Aufraeumen fehlgeschlagen (%s) — bitte manuell entfernen." % e)


def main(argv=None, today=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--telegram", action="store_true")
    ap.add_argument("--cron", action="store_true", help="Telegram + Selbstabschaltung bei Urteil oder Endtermin")
    a = ap.parse_args(argv)
    today = today or date.today()
    try:
        con = db_connect()
        try:
            res = analyze(load_rows(con), today)
        finally:
            con.close()
        text = format_report(res, today)
    except Exception as e:
        tb = traceback.format_exc()
        print(tb)
        if a.telegram or a.cron:
            send_telegram("Jev-Shadow-Auswertung FEHLGESCHLAGEN (%s: %s). Job bleibt aktiv, bitte pruefen."
                          % (type(e).__name__, str(e)[:200]))
        return 1
    print(text)
    try:
        with open(os.path.join(_ROOT, "data", "jev_shadow_eval_%s.txt" % today.isoformat()), "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    except OSError:
        pass
    if a.telegram or a.cron:
        msg = text
        last = today >= LAST_RUN_DATE
        if a.cron and res["verdict"] == "PENDING" and last:
            msg += ("\n\nDas war der letzte geplante Termin (%s). Der Job wird beendet; die Stichprobe reicht noch nicht, "
                    "Entscheidung bitte manuell." % LAST_RUN_DATE.strftime("%d.%m."))
        ok, info = send_telegram(msg)
        print("Telegram: %s (%s)" % ("gesendet" if ok else "NICHT gesendet", info))
        if a.cron and (res["verdict"] in ("GO", "NO-GO") or last) and ok:
            disable_own_cron()
    return 0


if __name__ == "__main__":
    sys.exit(main())
