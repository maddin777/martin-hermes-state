#!/usr/bin/env python3
"""Qualitaetspruefung der Scout-Extraktion (v2, 22.09.2026).

Hintergrund: deepseek-v4-flash ist ein Reasoning-Modell. Fuer die reine Namens-
Erkennung im Scout gehen ~90 % der Ausgabe-Tokens ins Reasoning, 36 % der Calls
laufen an max_tokens=4000 und liefern kein JSON. Erste Messreihe (64 Chunks):
"Reasoning aus" verfehlt mehr als die Haelfte der Firmen (Recall 0,43) und gpt-4o-mini
weicht ebenfalls ueber das Rauschen hinaus ab. Diese Fassung testet
  * begrenztes Reasoning (effort low/minimal, Budget 1000)
  * drei andere Modelle aus dem OpenRouter-Katalog
mit demselben Massstab.

Massstab: NICHT "stimmt mit REF1 ueberein", sondern: weicht ein Arm staerker von den
Referenzen ab, als die beiden Referenzen (REF1, REF2: volles Reasoning, zweimal
gemessen) untereinander abweichen? Fuer einen Arm X aus derselben Verteilung gilt
E[J(X,REF1)] = E[J(REF1,REF2)]; die Differenz je Chunk, gemittelt, mit Bootstrap-KI
ueber die Chunks, ist die Kennzahl d.

Aufruf:
    python3 scripts/scout_quality_probe.py --arms LOW,MINIMAL --limit 2   # Rauchtest
    python3 scripts/scout_quality_probe.py --arms LOW,MINIMAL,B1000,QWEN  # Lauf (fortsetzbar)
    python3 scripts/scout_quality_probe.py --analyze                       # auswerten

Schreibt NICHTS in trading.db (read-only) und nicht in llm_budget_log.
Ergebnisse: data/scout_quality_probe.jsonl (eine Zeile je Chunk und Arm).
"""
import argparse
import json
import os
import random
import re
import sqlite3
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

T = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, T)
sys.path.insert(0, os.path.join(T, "scripts"))

OUT = os.path.join(T, "data", "scout_quality_probe.jsonl")
DB = os.path.join(T, "data", "trading.db")
SEED = 42
DEFAULT_N = 64
WORKERS = 8
REQ_TIMEOUT = 420

BASE_ARMS = ["REF1", "REF2", "OFF", "MINI"]
NAMES_DE = {
    "REF1": "volles Reasoning (12000)", "REF2": "volles Reasoning, Wiederholung",
    "OFF": "Reasoning aus", "MINI": "gpt-4o-mini (bisheriger Fallback)",
    "LOW": "Reasoning effort=low", "MINIMAL": "Reasoning effort=minimal",
    "B1000": "Reasoning-Budget 1000", "QWEN": "qwen3-235b-a22b-2507",
    "MISTRAL": "mistral-small-3.2-24b", "GEMINI": "gemini-2.5-flash-lite",
    "LLAMA": "llama-3.3-70b-instruct",
}


def arm_config(se):
    return {
        "REF1": {"model": se.MODEL, "extra": {"max_tokens": 12000}},
        "REF2": {"model": se.MODEL, "extra": {"max_tokens": 12000}},
        "OFF": {"model": se.MODEL,
                "extra": {"max_tokens": 4000, "reasoning": {"enabled": False}}},
        "MINI": {"model": se.FALLBACK_MODEL, "extra": {"max_tokens": 4000}},
        # begrenztes Reasoning, mit der PRODUKTIONS-Grenze 4000 (Abschneidung wird mitgemessen)
        "LOW": {"model": se.MODEL,
                "extra": {"max_tokens": 4000, "reasoning": {"effort": "low"}}},
        "MINIMAL": {"model": se.MODEL,
                    "extra": {"max_tokens": 4000, "reasoning": {"effort": "minimal"}}},
        "B1000": {"model": se.MODEL,
                  "extra": {"max_tokens": 4000, "reasoning": {"max_tokens": 1000}}},
        # andere Modelle, ohne Reasoning-Parameter
        "QWEN": {"model": "qwen/qwen3-235b-a22b-2507", "extra": {"max_tokens": 4000}},
        "MISTRAL": {"model": "mistralai/mistral-small-3.2-24b-instruct",
                    "extra": {"max_tokens": 4000}},
        "GEMINI": {"model": "google/gemini-2.5-flash-lite", "extra": {"max_tokens": 4000}},
        "LLAMA": {"model": "meta-llama/llama-3.3-70b-instruct", "extra": {"max_tokens": 4000}},
    }


# ─────────────────────────────────────────────────────────── Namensabgleich
_STOP = {"inc", "corp", "corporation", "co", "company", "ag", "se", "plc", "ltd",
         "limited", "holdings", "holding", "group", "class", "a", "b", "c", "the",
         "sa", "nv", "llc", "lp", "and"}


def _tokens(name):
    n = (name or "").lower().replace("&", " and ")
    n = re.sub(r"[^\w\s]", " ", n)
    toks = [t for t in n.split() if t]
    core = [t for t in toks if t not in _STOP]
    return frozenset(core or toks)


def match_count(a_names, b_names):
    """1:1-Treffer; ein Name trifft, wenn eine Tokenmenge Teilmenge der anderen ist."""
    b_tok = [_tokens(x) for x in b_names]
    used = set()
    hits = []
    for i, an in enumerate(a_names):
        at = _tokens(an)
        if not at:
            continue
        for j, bt in enumerate(b_tok):
            if j in used or not bt:
                continue
            if at <= bt or bt <= at:
                used.add(j)
                hits.append((i, j))
                break
    return hits


def jaccard(a_names, b_names):
    if not a_names and not b_names:
        return 1.0
    m = len(match_count(a_names, b_names))
    return m / (len(a_names) + len(b_names) - m)


# ───────────────────────────────────────────────────────────── Datenauswahl
def pick_chunks(se, n):
    con = sqlite3.connect("file:" + DB + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT video_id, channel, title, upload_date, transcript FROM videos "
        "WHERE transcript IS NOT NULL AND created_at >= datetime('now','-7 days') "
        "ORDER BY video_id").fetchall()
    con.close()
    rows = list(rows)
    random.Random(SEED).shuffle(rows)          # stabile Reihenfolge: --limit ist ein Praefix
    out = []
    for r in rows[:n]:
        chunks = se._chunk_transcript(r["transcript"])
        if not chunks:
            continue
        rng = random.Random("%s-%s" % (SEED, r["video_id"]))
        idx = rng.randrange(len(chunks))
        out.append({"chunk_id": "%s#%d" % (r["video_id"], idx),
                    "channel": r["channel"], "title": r["title"],
                    "date": r["upload_date"], "num": idx + 1, "total": len(chunks),
                    "text": chunks[idx]})
    return out


# ───────────────────────────────────────────────────────────────── Aufruf
_LOCK = threading.Lock()


def call_arm(se, requests, key, chunk, arm, cfg):
    user = ("Kanal: %s\nTitel: %s\nDatum: %s\nTranskript-Abschnitt %d/%d:\n\n%s"
            % (chunk["channel"], chunk["title"], chunk["date"],
               chunk["num"], chunk["total"], chunk["text"]))
    payload = {"model": cfg["model"],
               "messages": [{"role": "system", "content": se.SCOUT_PROMPT},
                            {"role": "user", "content": user}],
               "usage": {"include": True}}
    payload.update(cfg["extra"])
    rec = {"chunk_id": chunk["chunk_id"], "arm": arm, "chars": len(chunk["text"])}
    t0 = time.time()
    resp = None
    for attempt in range(1, 4):
        try:
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": "Bearer " + key,
                         "Content-Type": "application/json"},
                json=payload, timeout=REQ_TIMEOUT)
        except Exception as exc:                       # Netzwerk/Timeout
            rec["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:80])
            time.sleep(2 ** attempt)
            continue
        if resp.status_code == 400 and "usage" in resp.text.lower() and "usage" in payload:
            payload.pop("usage")                       # Parameter nicht unterstuetzt
            continue
        if resp.status_code == 429 or 500 <= resp.status_code < 600:
            rec["error"] = "HTTP %d" % resp.status_code
            time.sleep(5 * 3 ** (attempt - 1))          # 5, 15, 45 s: Anbieter-Engpaesse dauern
            continue
        break
    rec["dt"] = round(time.time() - t0, 1)
    if resp is None or resp.status_code != 200:
        rec["parse"] = "http_fail"
        rec.setdefault("error", "HTTP %s" % (resp.status_code if resp is not None else "-"))
        if resp is not None:
            rec["error_body"] = resp.text[:160]
        return rec
    rec.pop("error", None)
    try:
        d = resp.json()
        ch = d["choices"][0]
    except Exception:
        rec["parse"] = "bad_body"                      # 200, aber kein auswertbares JSON
        rec["error_body"] = resp.text[:160]
        return rec
    u = d.get("usage", {}) or {}
    det = u.get("completion_tokens_details", {}) or {}
    rec.update({"finish": ch.get("finish_reason"),
                "tok_in": u.get("prompt_tokens"), "tok_out": u.get("completion_tokens"),
                "reasoning": det.get("reasoning_tokens"), "cost": u.get("cost")})
    content = (ch.get("message", {}) or {}).get("content")
    if not content:
        rec["parse"] = "empty"
        return rec
    try:
        parsed = se._try_parse(content.strip())
    except json.JSONDecodeError:
        rec["parse"] = "json_fail"
        return rec
    if not isinstance(parsed, dict) or "companies" not in parsed:
        rec["parse"] = "wrong_shape"
        return rec
    rec["parse"] = "ok"
    rec["companies"] = [{"name": (c.get("name") or "").strip(),
                         "sent": (c.get("rough_sentiment") or "").lower()}
                        for c in (parsed.get("companies") or []) if (c.get("name") or "").strip()]
    rec["outlook"] = (parsed.get("market_outlook") or "").lower()
    return rec


def run(limit, arms):
    import env_loader  # noqa: F401
    import requests
    import signal_extractor as se

    key = os.environ["OPENROUTER_API_KEY"]
    cfgs = arm_config(se)
    unknown = [a for a in arms if a not in cfgs]
    if unknown:
        sys.exit("Unbekannte Arme: %s (bekannt: %s)" % (unknown, list(cfgs)))
    chunks = pick_chunks(se, limit)
    done = set()
    if os.path.exists(OUT):
        for line in open(OUT, encoding="utf-8"):
            try:
                r = json.loads(line)
                if r.get("parse") in ("http_fail", "crash", "bad_body"):
                    continue                            # transienter Ausfall: erneut versuchen
                done.add((r["chunk_id"], r["arm"]))
            except Exception:
                continue
    jobs = [(c, a) for c in chunks for a in arms if (c["chunk_id"], a) not in done]
    print("Chunks: %d | Arme: %s | Jobs offen: %d (vorhanden: %d) | Worker: %d"
          % (len(chunks), ",".join(arms), len(jobs), len(done), WORKERS), flush=True)
    counter = {"n": 0}

    def work(job):
        chunk, arm = job
        try:
            rec = call_arm(se, requests, key, chunk, arm, cfgs[arm])
        except Exception as exc:                        # ein Ausreisser darf den Lauf nicht kippen
            rec = {"chunk_id": chunk["chunk_id"], "arm": arm, "parse": "crash",
                   "error": "%s: %s" % (type(exc).__name__, str(exc)[:80]), "dt": 0}
        with _LOCK:
            with open(OUT, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            counter["n"] += 1
            print("[%3d/%d] %-22s %-8s %-10s %6.0fs  reasoning=%s %s"
                  % (counter["n"], len(jobs), chunk["chunk_id"][:22], arm,
                     rec.get("parse"), rec.get("dt", 0), rec.get("reasoning"),
                     rec.get("error_body", "")[:60] if rec.get("parse") in ("http_fail", "bad_body") else ""),
                  flush=True)

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(ex.map(work, jobs))
    print("Lauf beendet.", flush=True)


# ─────────────────────────────────────────────────────────────── Auswertung
def bootstrap_ci(values, n=2000, seed=11):
    rnd = random.Random(seed)
    means = sorted(statistics.mean(rnd.choices(values, k=len(values))) for _ in range(n))
    return means[int(n * 0.025)], means[int(n * 0.975)]


def analyze():
    recs = {}
    for line in open(OUT, encoding="utf-8"):
        r = json.loads(line)
        recs.setdefault(r["chunk_id"], {})[r["arm"]] = r

    def ok(cid, arm):
        r = recs[cid].get(arm)
        return r is not None and r.get("parse") == "ok"

    base = [c for c in recs if ok(c, "REF1") and ok(c, "REF2")]
    print("=== Datenbasis ===")
    print("  Chunks gesamt: %d | Referenz vollstaendig (REF1+REF2 ok): %d | ohne Referenz: %d"
          % (len(recs), len(base), len(recs) - len(base)))
    if len(base) < 10:
        print("  Zu wenige Referenz-Chunks.")
        return

    def names(cid, arm):
        return [c["name"] for c in recs[cid][arm]["companies"]]

    j_ref = {c: jaccard(names(c, "REF1"), names(c, "REF2")) for c in base}
    inf_base = [c for c in base if names(c, "REF1") or names(c, "REF2")]
    print("\n=== Rauschgrenze: zwei Laeufe mit IDENTISCHER Konfiguration (REF1 vs REF2) ===")
    print("  Jaccard alle: %.3f (n=%d) | nur Chunks mit Treffer: %.3f (n=%d)"
          % (statistics.mean(j_ref.values()), len(base),
             statistics.mean(j_ref[c] for c in inf_base), len(inf_base)))

    arms_present = []
    for c in recs:
        for a in recs[c]:
            if a not in ("REF1", "REF2") and a not in arms_present:
                arms_present.append(a)
    order = [a for a in ("OFF", "MINI", "LOW", "MINIMAL", "B1000", "QWEN", "MISTRAL", "GEMINI", "LLAMA")
             if a in arms_present] + [a for a in arms_present if a not in
                                      ("OFF", "MINI", "LOW", "MINIMAL", "B1000", "QWEN", "MISTRAL", "GEMINI", "LLAMA")]

    print("\n=== Betrieb je Arm (ueber ALLE versuchten Chunks) ===")
    print("  %-8s %-32s %4s %7s %7s %7s %8s %8s %9s"
          % ("Arm", "Beschreibung", "n", "ausfall", "abgesch", "Zeit med", "Zeit max", "reasoning", "Kosten $"))
    for a in order:
        rs = [recs[c][a] for c in recs if a in recs[c]]
        fail = sum(1 for r in rs if r.get("parse") != "ok")
        cut = sum(1 for r in rs if r.get("finish") == "length")
        dts = [r["dt"] for r in rs if r.get("dt")]
        rt = [r.get("reasoning") or 0 for r in rs if r.get("parse") == "ok"]
        cost = [r["cost"] for r in rs if r.get("cost") is not None]
        print("  %-8s %-32s %4d %6.0f%% %6.0f%% %6.0fs %7.0fs %9.0f %9s"
              % (a, NAMES_DE.get(a, a)[:32], len(rs), 100 * fail / len(rs), 100 * cut / len(rs),
                 statistics.median(dts) if dts else 0, max(dts) if dts else 0,
                 statistics.mean(rt) if rt else 0, ("%.3f" % sum(cost)) if cost else "n/a"))

    print("\n=== Qualitaet gegen die Referenz (nur Chunks, in denen REF1, REF2 und der Arm ok sind) ===")
    print("  d = mittlere J(Arm, REF1/REF2) minus J(REF1, REF2); 0 = nicht vom Referenz-Rauschen unterscheidbar")
    print("  %-8s %5s %8s %-20s %7s %10s %9s  %s"
          % ("Arm", "n", "d", "95%-KI", "Recall", "Sentiment", "Ausblick", "Urteil"))
    for a in order:
        pool = [c for c in base if ok(c, a)]
        if len(pool) < 8:
            print("  %-8s zu wenige auswertbare Chunks (n=%d)" % (a, len(pool)))
            continue
        d = [(jaccard(names(c, a), names(c, "REF1")) + jaccard(names(c, a), names(c, "REF2"))) / 2
             - j_ref[c] for c in pool]
        lo, hi = bootstrap_ci(d)
        rec_v = []
        for c in pool:
            union = names(c, "REF1") + [n for n in names(c, "REF2")
                                        if not match_count([n], names(c, "REF1"))]
            if union:
                rec_v.append(len(match_count(union, names(c, a))) / len(union))
        agree = tot = 0
        for c in pool:
            an, bn = recs[c][a]["companies"], recs[c]["REF1"]["companies"]
            for i, j in match_count([x["name"] for x in an], [x["name"] for x in bn]):
                tot += 1
                agree += an[i]["sent"] == bn[j]["sent"]
        same = sum(1 for c in pool if recs[c][a].get("outlook") == recs[c]["REF1"].get("outlook"))
        verdict = ("nicht unterscheidbar" if lo <= 0 <= hi
                   else ("SCHLECHTER als Rauschen" if hi < 0 else "uebereinstimmender"))
        print("  %-8s %5d %+8.3f [%+.3f,%+.3f]  %7.2f %10.2f %8.0f%%  %s"
              % (a, len(pool), statistics.mean(d), lo, hi,
                 statistics.mean(rec_v) if rec_v else float("nan"),
                 agree / tot if tot else float("nan"), 100 * same / len(pool), verdict))
    # Vergleichswerte: die Referenzen untereinander, aus denselben Daten berechnet
    rr, ra, rt_ = [], 0, 0
    for c in inf_base:
        if names(c, "REF1"):
            rr.append(len(match_count(names(c, "REF1"), names(c, "REF2"))) / len(names(c, "REF1")))
    for c in base:
        an, bn = recs[c]["REF2"]["companies"], recs[c]["REF1"]["companies"]
        for i, j in match_count([x["name"] for x in an], [x["name"] for x in bn]):
            rt_ += 1
            ra += an[i]["sent"] == bn[j]["sent"]
    so = sum(1 for c in base if recs[c]["REF2"].get("outlook") == recs[c]["REF1"].get("outlook"))
    print("  Referenz-Massstab (REF2 gegen REF1): Recall %.2f | Sentiment %.2f | Ausblick %.0f%%"
          % (statistics.mean(rr) if rr else float("nan"), ra / rt_ if rt_ else float("nan"),
             100 * so / len(base)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=DEFAULT_N)
    ap.add_argument("--arms", default=",".join(BASE_ARMS))
    ap.add_argument("--analyze", action="store_true")
    args = ap.parse_args()
    if args.analyze:
        analyze()
    else:
        run(args.limit, [a for a in args.arms.split(",") if a])
