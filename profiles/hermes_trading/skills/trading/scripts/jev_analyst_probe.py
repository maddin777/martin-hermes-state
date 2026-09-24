#!/usr/bin/env python3
"""Jev-Probe fuer die Analyst-Klassifikation (sentiment, strength, action_hint, catalyst) — 23.09.2026.

Frage: Kann Jev die vier Auswahlfelder des Analysten so uebereinstimmend wie ein zweiter
DeepSeek-Lauf befuellen, und sind seine Konfidenzwerte kalibriert?

Referenz: die "saubere" DeepSeek-Paarung REFHI1/REFHI2 aus data/analyst_probe.jsonl
(max_tokens=16000, kein Abschneiden, kein Scout-Fallback). Die Uebereinstimmung REFHI1<->REFHI2
ist die Rauschgrenze. Jev laeuft zweimal (JEV1, JEV2), um sein Eigenrauschen zu messen.

NUR LESEND: schreibt nichts in trading.db und nichts in llm_budget_log. Ergebnisse:
data/jev_probe.jsonl (fortsetzbar).

Go/No-Go (vorab festgelegt, siehe Task jev-entscheidungsmodell-pilot.md, AC-4):
  Fuer sentiment UND action_hint muss gelten
    (a) untere Grenze des 95%-KI von d = Uebereinstimmung(Jev, Ref) - Uebereinstimmung(Ref1, Ref2)
        liegt bei >= -0,03, und
    (b) im Konfidenz-Bucket > 0,9 stimmt Jev bei stabilen Referenzlabels (REFHI1 == REFHI2)
        zu >= 95 % ueberein (nur belastbar bei n >= 30).

Aufruf:
    venv/bin/python scripts/jev_analyst_probe.py --dry-run
    venv/bin/python scripts/jev_analyst_probe.py --run [--videos N]
    venv/bin/python scripts/jev_analyst_probe.py --analyze
"""
import argparse
import json
import os
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

T = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, T)
sys.path.insert(0, os.path.join(T, "scripts"))

IN_PATH = os.path.join(T, "data", "analyst_probe_inputs.jsonl")
REF_PATH = os.path.join(T, "data", "analyst_probe.jsonl")
OUT_PATH = os.path.join(T, "data", "jev_probe.jsonl")
R1, R2 = "REFHI1", "REFHI2"
ARMS = ("JEV1", "JEV2")
WORKERS = 8
FIELDS = ("sentiment", "strength", "action_hint", "catalyst")
GATE_FIELDS = ("sentiment", "action_hint")
BUCKETS = ((0.0, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 1.0001))
D_LOWER_LIMIT = -0.03
TOP_BUCKET_MIN_AGREEMENT = 0.95
MIN_N_TOP_BUCKET = 30

TASK = ("A German financial YouTube channel mentioned a company. `quotes` are verbatim transcript "
        "excerpts. Judge ONLY what the quotes say about the company, not your own market opinion. "
        "If the quotes are too thin for a judgement, sentiment is neutral and strength is weak. "
        "If no concrete trigger is named in the quotes, the catalyst is none.")

QUESTIONS = {
    "sentiment": {"type": "choice", "instructions": "What is the channel's sentiment toward this company, according to the quotes?",
                  "criteria": {"bullish": "the quotes are positive about the company or its stock",
                               "bearish": "the quotes are negative about the company or its stock",
                               "neutral": "no clear positive or negative stance"}},
    "strength": {"type": "choice", "instructions": "How strongly and how concretely is this opinion expressed in the quotes?",
                 "criteria": {"strong": "explicit, emphatic, well-founded statement",
                              "moderate": "clear but ordinary statement",
                              "weak": "passing mention or thin, vague statement"}},
    "action_hint": {"type": "choice", "instructions": "What action does the channel suggest for this stock, according to the quotes?",
                    "criteria": {"buy": "recommends buying or accumulating",
                                 "sell": "recommends selling or reducing",
                                 "watch_for_reversal": "stock is weak or beaten down, channel suggests watching for a turnaround",
                                 "avoid": "recommends staying away",
                                 "hold": "recommends keeping an existing position"}},
    "catalyst": {"type": "choice", "instructions": "What concrete trigger does the quote name for the opinion?",
                 "criteria": {"earnings": "quarterly results, guidance, earnings expectations",
                              "product": "product launch, product news, business segment news",
                              "macro": "interest rates, economy, sector-wide or geopolitical developments",
                              "legal": "lawsuits, regulation, investigations",
                              "technical": "chart pattern, price levels, technical analysis",
                              "none": "no concrete trigger named"}},
}
OPTIONS = {f: list(q["criteria"]) for f, q in QUESTIONS.items()}

_LOCK = threading.Lock()


def load_jsonl(path):
    out = []
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def load_base():
    """{video_id: {"in": Eingabesatz, "refs": {R1: {name: out}, R2: {...}}, "bad": set(Fallback-Namen)}}"""
    inputs = {r["video_id"]: r for r in load_jsonl(IN_PATH)}
    recs = {}
    for r in load_jsonl(REF_PATH):
        recs.setdefault(r["video_id"], {})[r["arm"]] = r
    base = {}
    for v, arms in recs.items():
        if v not in inputs or not all(a in arms and not arms[a].get("crash") for a in (R1, R2)):
            continue
        bad = set(arms[R1]["fb"]) | set(arms[R2]["fb"])
        base[v] = {"in": inputs[v], "bad": bad,
                   "refs": {a: {c["name"]: c for c in arms[a]["out"]} for a in (R1, R2)}}
    return base


def usable_companies(b):
    for c in b["in"]["companies"]:
        n = c["name"]
        if n in b["bad"] or n not in b["refs"][R1] or n not in b["refs"][R2]:
            continue
        yield c


def build_state(b, c):
    i = b["in"]
    return {"task": TASK, "channel": i["channel"], "title": i["title"], "date": i["date"],
            "company": c["name"], "scout_rough_sentiment": c.get("rough_sentiment"),
            "quotes": c["snippets"] or ["(no quote)"]}


def est_tokens(obj):
    return len(json.dumps(obj, ensure_ascii=False)) // 3


# ───────────────────────────────────────────────────────────────── Lauf
def run(limit_videos=None, dry=False):
    from thematic.lib import jev_client as jc
    base = load_base()
    vids = sorted(base)[:limit_videos] if limit_videos else sorted(base)
    done = {(r["video_id"], r["arm"], r["name"]) for r in load_jsonl(OUT_PATH) if r.get("ok")}
    todo = [(v, arm, c) for v in vids for c in usable_companies(base[v]) for arm in ARMS
            if (v, arm, c["name"]) not in done]
    n_comp = sum(len(list(usable_companies(base[v]))) for v in vids)
    q_tokens = est_tokens(QUESTIONS)
    tok = sum(est_tokens(build_state(base[v], c)) + q_tokens for v, _a, c in todo)
    print("Videos: %d | Firmen (mit beiden sauberen Referenzen): %d | offene Anfragen: %d (je Firma %d Laeufe)"
          % (len(vids), n_comp, len(todo), len(ARMS)))
    print("Geschaetzte Eingabetokens: ~%d  ->  Kosten ~$%.4f (0,042 $/Mio.)" % (tok, tok * 0.042 / 1e6))
    if dry or not todo:
        return

    def work(item):
        v, arm, c = item
        t0 = time.time()
        resp = jc.decide(build_state(base[v], c), QUESTIONS, timeout=60)
        dt = round(time.time() - t0, 2)
        rec = {"video_id": v, "arm": arm, "name": c["name"], "dt": dt, "ok": False}
        if resp:
            ans = {}
            for f in FIELDS:
                ch = jc.choice_of(resp, f, OPTIONS[f])
                if ch:
                    ans[f] = {"label": ch[0], "conf": ch[1], "probs": ch[2]}
            if len(ans) == len(FIELDS):
                rec.update(ok=True, answers=ans, usage=list(jc.usage_of(resp)))
        with _LOCK:
            with open(OUT_PATH, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec["ok"]

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        oks = list(ex.map(work, todo))
    print("Fertig: %d/%d ok in %.0f s" % (sum(oks), len(oks), time.time() - t0))


# ───────────────────────────────────────────────────────────────── Auswertung
def bootstrap_ci(values, n=2000, seed=11):
    import random
    rnd = random.Random(seed)
    means = sorted(statistics.mean(rnd.choices(values, k=len(values))) for _ in range(n))
    return means[int(n * 0.025)], means[int(n * 0.975)]


def analyze():
    base = load_base()
    recs = [r for r in load_jsonl(OUT_PATH) if r.get("ok")]
    total_req = len(load_jsonl(OUT_PATH))
    by = {}
    for r in recs:
        by.setdefault(r["arm"], {})[(r["video_id"], r["name"])] = r
    if "JEV1" not in by:
        print("Keine Jev-Ergebnisse.")
        return
    j1, j2 = by["JEV1"], by.get("JEV2", {})
    print("=== Datenbasis ===")
    print("  Anfragen gesamt: %d | erfolgreich mit allen 4 Feldern: %d (%.1f %%)"
          % (total_req, len(recs), 100 * len(recs) / max(total_req, 1)))
    vids = sorted({v for v, _ in j1})
    print("  Videos: %d | Firmen (JEV1): %d" % (len(vids), len(j1)))
    lat = [r["dt"] for r in recs]
    cost = sum(r["usage"][2] for r in recs)
    tin = sum(r["usage"][0] for r in recs)
    print("  Latenz je Anfrage: Median %.2f s | P95 %.2f s | Kosten gesamt $%.4f (%.4f $/1000 Firmen-Laeufe) | Eingabetokens ~%d"
          % (statistics.median(lat), sorted(lat)[int(len(lat) * 0.95) - 1], cost, 1000 * cost / len(recs), tin))

    def ref_label(v, n, a, f):
        return base[v]["refs"][a][n][f]

    print("\n=== 1. Uebereinstimmung mit den sauberen Referenzen ===")
    print("  Rausch = REFHI1<->REFHI2, Jev = Jev(JEV1) gegen beide Referenzen gemittelt,")
    print("  Basis = immer die haeufigste Referenzklasse raten, d = Jev - Rausch je Video (Bootstrap ueber Videos)")
    print("  %-12s %5s %7s %7s %7s  %-22s %s" % ("Feld", "n", "Rausch", "Basis", "Jev", "d [95%-KI]", "Urteil"))
    verdict_d = {}
    for f in FIELDS:
        pv_d, pv_j, pv_n, pv_b, n_c = [], [], [], [], 0
        for v in vids:
            names = [n for (vv, n) in j1 if vv == v]
            if not names:
                continue
            a12 = statistics.mean(ref_label(v, n, R1, f) == ref_label(v, n, R2, f) for n in names)
            aj = statistics.mean((j1[(v, n)]["answers"][f]["label"] == ref_label(v, n, R1, f))
                                 + (j1[(v, n)]["answers"][f]["label"] == ref_label(v, n, R2, f))
                                 for n in names) / 2
            pv_d.append(aj - a12)
            pv_j.append(aj)
            pv_n.append(a12)
            n_c += len(names)
        # Basis global: haeufigste Klasse ueber alle Referenzlabels
        allref = [ref_label(v, n, a, f) for (v, n) in j1 for a in (R1, R2)]
        top = max(set(allref), key=allref.count)
        base_acc = statistics.mean(l == top for l in allref)
        lo, hi = bootstrap_ci(pv_d)
        if lo <= 0 <= hi:
            urteil = "nicht unterscheidbar"
        elif hi < 0:
            urteil = "SCHLECHTER als Rauschen"
        else:
            urteil = "uebereinstimmender"
        verdict_d[f] = lo
        print("  %-12s %5d %7.3f %7.3f %7.3f  %+.3f [%+.3f,%+.3f]  %s"
              % (f, n_c, statistics.mean(pv_n), base_acc, statistics.mean(pv_j),
                 statistics.mean(pv_d), lo, hi, urteil))

    if j2:
        print("\n=== 2. Jev-Eigenrauschen (JEV1 <-> JEV2, gleiche Anfrage zweimal) ===")
        common = [k for k in j1 if k in j2]
        for f in FIELDS:
            print("  %-12s %5d Firmen  gleiche Antwort: %.1f %%  | Konfidenz-Abweichung im Mittel: %.3f"
                  % (f, len(common),
                     100 * statistics.mean(j1[k]["answers"][f]["label"] == j2[k]["answers"][f]["label"] for k in common),
                     statistics.mean(abs(j1[k]["answers"][f]["conf"] - j2[k]["answers"][f]["conf"]) for k in common)))

    print("\n=== 3. Kalibrierung: stimmt Jev bei hoher Konfidenz haeufiger mit der Referenz ueberein? ===")
    print("  Nur Firmen mit STABILEM Referenzlabel (REFHI1 == REFHI2). Uebereinstimmung Jev <-> dieses Label.")
    print("  %-12s %-10s %5s %10s" % ("Feld", "Konfidenz", "n", "stimmt"))
    top_bucket = {}
    for f in FIELDS:
        for lo_b, hi_b in BUCKETS:
            hits = [j1[(v, n)]["answers"][f]["label"] == ref_label(v, n, R1, f)
                    for (v, n) in j1
                    if ref_label(v, n, R1, f) == ref_label(v, n, R2, f)
                    and lo_b <= j1[(v, n)]["answers"][f]["conf"] < hi_b]
            lab = "%.1f-%.1f" % (lo_b, min(hi_b, 1.0))
            rate = statistics.mean(hits) if hits else float("nan")
            print("  %-12s %-10s %5d %9.1f %%" % (f, lab, len(hits), 100 * rate))
            if hi_b > 1:
                top_bucket[f] = (len(hits), rate)
        confs = [j1[k]["answers"][f]["conf"] for k in j1]
        print("  %-12s Konfidenz-Verteilung: Median %.2f | Anteil > 0,9: %.0f %%"
              % (f, statistics.median(confs), 100 * statistics.mean(c > 0.9 for c in confs)))

    print("\n=== 4. Go/No-Go nach AC-4 ===")
    ok_all = True
    for f in GATE_FIELDS:
        n_top, rate_top = top_bucket[f]
        a = verdict_d[f] >= D_LOWER_LIMIT
        b_ = n_top >= MIN_N_TOP_BUCKET and rate_top >= TOP_BUCKET_MIN_AGREEMENT
        note = "" if n_top >= MIN_N_TOP_BUCKET else "  (n<%d: nicht belastbar)" % MIN_N_TOP_BUCKET
        print("  %-12s (a) untere KI-Grenze von d = %+.3f (Soll >= %+.2f): %s | (b) Bucket >0,9: %.1f %% bei n=%d (Soll >= 95 %%): %s%s"
              % (f, verdict_d[f], D_LOWER_LIMIT, "ERFUELLT" if a else "verfehlt",
                 100 * rate_top if n_top else float("nan"), n_top, "ERFUELLT" if b_ else "verfehlt", note))
        ok_all = ok_all and a and b_
    print("  => %s" % ("GO fuer Stufe 2 (Shadow-Logging)" if ok_all else "NO-GO: Kriterien nicht erfuellt"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--analyze", action="store_true")
    ap.add_argument("--videos", type=int, default=None)
    a = ap.parse_args()
    if a.analyze:
        analyze()
    elif a.run or a.dry_run:
        run(a.videos, dry=a.dry_run)
    else:
        ap.print_help()
