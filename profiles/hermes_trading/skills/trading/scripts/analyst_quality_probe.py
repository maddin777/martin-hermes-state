#!/usr/bin/env python3
"""Messung der Analyst-Stufe (Pass B) von signal_extractor.py — 22.09.2026.

Fragen:
  1. Wie gross ist der Zeitanteil des Analysten gegenueber dem Scout?
  2. Wie oft faellt er auf die groben Scout-Daten zurueck (kein Kursziel, strength=moderate,
     action_hint=watch_for_reversal)?
  3. Verschlechtern effort=low, Reasoning aus oder gpt-4o-mini die Felder, die spaeter
     Entscheidungen treiben (sentiment, strength, action_hint, catalyst, price_target,
     mentioned_price)?

Aufbau:
  Phase A  echte Analyst-Eingaben: pro Video den PRODUKTIVEN Scout (aktuell effort=low)
           laufen lassen und merge_scout_results() aufrufen — exakt wie analyze().
  Phase B  pro Video und Variante die ECHTE call_analyst()-Funktion aufrufen. Nur Modell,
           Reasoning-Parameter und Grenze werden je Variante ausgetauscht; Prompt,
           Nachbearbeitung und Scout-Fallback bleiben die der Produktion. Budget-Buchung
           und trading.db werden NICHT angefasst.
Varianten: REF1, REF2 (Produktionskonfiguration, zweimal -> Rauschgrenze), LOW, OFF, MINI.

Weil die Firmennamen des Analysten immer aus dem Scout kommen, sind die Namensmengen aller
Varianten identisch — der Vergleich ist ein exakter Feldvergleich je Firma, ohne Namens-Matching.

Aufruf:
    python3 scripts/analyst_quality_probe.py --run --videos 2        # Rauchtest
    python3 scripts/analyst_quality_probe.py --run                   # voller Lauf (fortsetzbar)
    python3 scripts/analyst_quality_probe.py --analyze
Ergebnisse: data/analyst_probe_inputs.jsonl, data/analyst_probe.jsonl
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

IN_PATH = os.path.join(T, "data", "analyst_probe_inputs.jsonl")
OUT_PATH = os.path.join(T, "data", "analyst_probe.jsonl")
DB = os.path.join(T, "data", "trading.db")
SEED = 42
DEFAULT_VIDEOS = 30
CANDIDATES_PER_TARGET = 1.5          # so viele Videos ansehen, bis genug >= 2 Firmen haben
OUTER_SCOUT = 5                      # Videos parallel in Phase A (je 3 Scout-Worker)
WORKERS_B = 8
MIN_COMPANIES = 2
ARMS = ["REF1", "REF2", "LOW", "OFF", "MINI"]
HI_ARMS = ["REFHI1", "REFHI2"]      # saubere Referenz: Grenze 16000, kein Abschneiden
FIELDS = ("sentiment", "strength", "action_hint", "catalyst")

_LOCK = threading.Lock()
_TLS = threading.local()


# ───────────────────────────────────────────────────────────────── Phase A
def phase_a(se, n_videos):
    con = sqlite3.connect("file:" + DB + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT video_id, channel, title, upload_date, transcript FROM videos "
        "WHERE transcript IS NOT NULL AND created_at >= datetime('now','-7 days') "
        "ORDER BY video_id").fetchall()
    con.close()
    rows = list(rows)
    random.Random(SEED).shuffle(rows)
    done = {}
    if os.path.exists(IN_PATH):
        for line in open(IN_PATH, encoding="utf-8"):
            try:
                r = json.loads(line)
                done[r["video_id"]] = r
            except Exception:
                continue
    limit = int(n_videos * CANDIDATES_PER_TARGET)
    todo = [r for r in rows[:limit] if r["video_id"] not in done]
    print("Phase A: %d Kandidaten-Videos, %d bereits vorhanden, %d offen"
          % (limit, len(done), len(todo)), flush=True)

    def work(r):
        chunks = se._chunk_transcript(r["transcript"])
        t0 = time.time()
        results = se._run_scout_chunks(chunks, r["channel"], r["title"], r["upload_date"])
        wall = time.time() - t0
        merged = se.merge_scout_results(results)
        rec = {"video_id": r["video_id"], "channel": r["channel"], "title": r["title"],
               "date": r["upload_date"], "n_chunks": len(chunks), "chars": len(r["transcript"]),
               "scout_wall": round(wall, 1), "companies": merged["companies"]}
        with _LOCK:
            with open(IN_PATH, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            done[r["video_id"]] = rec
            print("  [A] %-13s %d Chunk(s) %5.0fs  %d Firmen"
                  % (r["video_id"], len(chunks), wall, len(merged["companies"])), flush=True)

    with ThreadPoolExecutor(max_workers=OUTER_SCOUT) as ex:
        list(ex.map(work, todo))
    usable = [done[r["video_id"]] for r in rows[:limit]
              if r["video_id"] in done and len(done[r["video_id"]]["companies"]) >= MIN_COMPANIES]
    return usable[:n_videos]


# ───────────────────────────────────────────────────────────────── Phase B
def install_patches(se):
    """Patches lesen ihren Kontext aus _TLS -> Varianten koennen parallel laufen."""
    import roles.budget as budget
    from thematic.lib import llm_client

    budget.check_and_reserve = lambda *a, **k: True
    budget.record_spend = lambda con, role, today, t_in, t_out, model: _TLS.spend.append(
        (t_in, t_out, model))

    orig_get_model = llm_client.get_model
    prod_model = orig_get_model("extractor_analyst")
    llm_client.get_model = lambda role: (_TLS.model if role == "extractor_analyst"
                                         and getattr(_TLS, "model", None)
                                         else orig_get_model(role))

    orig_cascade = se._call_cascade

    def cascade(system_prompt, user_content, **kw):
        kw["primary_extra"] = _TLS.extra
        kw["max_tokens"] = _TLS.max_tokens
        return orig_cascade(system_prompt, user_content, **kw)

    se._call_cascade = cascade

    orig_call = se._call

    def spy(model, *a, **k):
        t0 = time.time()
        status = "ok"
        try:
            return orig_call(model, *a, **k)
        except se._Truncated:
            status = "truncated"
            raise
        except Exception as exc:
            status = "error:" + type(exc).__name__
            raise
        finally:
            _TLS.attempts.append({"model": model, "dt": round(time.time() - t0, 1),
                                  "status": status, "reasoning": k.get("extra_body")})

    se._call = spy

    orig_fb = se._scout_fallback

    def fb(scout_companies):
        _TLS.fb_names.update(s["name"] for s in scout_companies)
        return orig_fb(scout_companies)

    se._scout_fallback = fb
    return prod_model


def arm_config(prod_model, se):
    return {
        "REF1": {"model": prod_model, "extra": None, "max_tokens": 4000},
        "REF2": {"model": prod_model, "extra": None, "max_tokens": 4000},
        "LOW":  {"model": prod_model, "extra": {"reasoning": {"effort": "low"}}, "max_tokens": 4000},
        "OFF":  {"model": prod_model, "extra": {"reasoning": {"enabled": False}}, "max_tokens": 4000},
        "MINI": {"model": se.FALLBACK_MODEL, "extra": None, "max_tokens": 4000},
        "REFHI1": {"model": prod_model, "extra": None, "max_tokens": 16000},
        "REFHI2": {"model": prod_model, "extra": None, "max_tokens": 16000},
    }


def run_one(se, cfgs, video, arm):
    cfg = cfgs[arm]
    _TLS.model, _TLS.extra, _TLS.max_tokens = cfg["model"], cfg["extra"], cfg["max_tokens"]
    _TLS.spend, _TLS.attempts, _TLS.fb_names = [], [], set()
    t0 = time.time()
    crash = None
    try:
        out = se.call_analyst(None, video["companies"], video["channel"], video["title"], video["date"])
    except Exception as exc:                             # ein Ausreisser darf den Lauf nicht kippen
        out, crash = [], "%s: %s" % (type(exc).__name__, str(exc)[:80])
    dt = time.time() - t0
    return {"video_id": video["video_id"], "arm": arm, "dt": round(dt, 1), "crash": crash,
            "n_scout": len(video["companies"]),
            "fb": sorted(_TLS.fb_names),
            "tok_in": sum(x[0] for x in _TLS.spend), "tok_out": sum(x[1] for x in _TLS.spend),
            "attempts": list(_TLS.attempts),
            "out": [{k: c.get(k) for k in ("name", "sentiment", "strength", "action_hint",
                                            "catalyst", "price_target", "mentioned_price")}
                    for c in out]}


def phase_b(se, videos, arms):
    prod_model = install_patches(se)
    cfgs = arm_config(prod_model, se)
    done = set()
    if os.path.exists(OUT_PATH):
        for line in open(OUT_PATH, encoding="utf-8"):
            try:
                r = json.loads(line)
                if not r.get("crash"):
                    done.add((r["video_id"], r["arm"]))
            except Exception:
                continue
    jobs = [(v, a) for v in videos for a in arms if (v["video_id"], a) not in done]
    jobs.sort(key=lambda j: 0 if j[1].startswith("REF") else 1)     # lange Laeufe zuerst
    print("Phase B: Modell %s | %d Videos x %d Varianten | offen: %d | Worker: %d"
          % (prod_model, len(videos), len(arms), len(jobs), WORKERS_B), flush=True)
    counter = {"n": 0}

    def work(job):
        v, a = job
        rec = run_one(se, cfgs, v, a)
        with _LOCK:
            with open(OUT_PATH, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            counter["n"] += 1
            print("  [B %3d/%d] %-13s %-5s %5.0fs  Firmen=%d Fallback=%d Versuche=%d %s"
                  % (counter["n"], len(jobs), v["video_id"], a, rec["dt"], rec["n_scout"],
                     len(rec["fb"]), len(rec["attempts"]), rec["crash"] or ""), flush=True)

    with ThreadPoolExecutor(max_workers=WORKERS_B) as ex:
        list(ex.map(work, jobs))
    print("Lauf beendet.", flush=True)


def run(n_videos, arms):
    import env_loader  # noqa: F401
    import signal_extractor as se

    usable = phase_a(se, n_videos)
    print("Phase A fertig: %d Videos mit >= %d Firmen" % (len(usable), MIN_COMPANIES), flush=True)
    phase_b(se, usable, arms)


# ─────────────────────────────────────────────────────────────── Auswertung
def to_num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"[-+]?\d+(?:[.,]\d+)?", str(v).replace(" ", ""))
    return float(m.group(0).replace(",", ".")) if m else None


def price_same(a, b):
    x, y = to_num(a), to_num(b)
    if x is None and y is None:
        return True
    if x is None or y is None:
        return False
    return abs(x - y) <= 0.02 * max(abs(x), abs(y), 1e-9)


def bootstrap_ci(values, n=2000, seed=11):
    rnd = random.Random(seed)
    means = sorted(statistics.mean(rnd.choices(values, k=len(values))) for _ in range(n))
    return means[int(n * 0.025)], means[int(n * 0.975)]


def analyze(ref="REF"):
    R1, R2 = ("REFHI1", "REFHI2") if ref == "HI" else ("REF1", "REF2")
    inputs = {}
    for line in open(IN_PATH, encoding="utf-8"):
        r = json.loads(line)
        inputs[r["video_id"]] = r
    recs = {}
    for line in open(OUT_PATH, encoding="utf-8"):
        r = json.loads(line)
        recs.setdefault(r["video_id"], {})[r["arm"]] = r

    vids = [v for v in recs if all(a in recs[v] and not recs[v][a].get("crash") for a in (R1, R2))]
    print("=== Datenbasis ===")
    print("  Videos mit Analyst-Lauf: %d | mit beiden Referenzen: %d | Firmen gesamt: %d"
          % (len(recs), len(vids), sum(inputs[v]["companies"].__len__() for v in vids)))
    if len(vids) < 8:
        print("  Zu wenige Videos.")
        return

    # 1. Zeitanteil
    sh, tot_s, tot_a = [], 0.0, 0.0
    for v in vids:
        sw, ad = inputs[v]["scout_wall"], recs[v]["REF1"]["dt"]
        sh.append(ad / (sw + ad))
        tot_s += sw
        tot_a += ad
    print("\n=== 1. Zeitanteil: Analyst vs. Scout (Produktionskonfiguration, je Video) ===")
    print("  Scout   : Median %4.0f s | Mittel %4.0f s | Summe %5.1f Min" % (
        statistics.median(inputs[v]["scout_wall"] for v in vids),
        statistics.mean(inputs[v]["scout_wall"] for v in vids), tot_s / 60))
    print("  Analyst : Median %4.0f s | Mittel %4.0f s | Summe %5.1f Min" % (
        statistics.median(recs[v]["REF1"]["dt"] for v in vids),
        statistics.mean(recs[v]["REF1"]["dt"] for v in vids), tot_a / 60))
    print("  Analyst-Anteil an (Scout + Analyst): Median %.0f %% | gesamt %.0f %%"
          % (100 * statistics.median(sh), 100 * tot_a / (tot_s + tot_a)))
    print("  (Scout-Zeit = Wanduhr der Chunks eines Videos, parallel; hier bereits mit effort=low)")

    # 2. Betrieb je Variante
    print("\n=== 2. Betrieb je Variante ===")
    print("  %-6s %4s %7s %7s %9s %10s %10s %9s %9s"
          % ("Arm", "n", "Zeit med", "Zeit max", "Tok out", "Video ganz", "Firmen", "abgesch.", "Mini-Anteil"))
    for a in ARMS + HI_ARMS:
        rs = [recs[v][a] for v in recs if a in recs[v] and not recs[v][a].get("crash")]
        if not rs:
            continue
        full = sum(1 for r in rs if r["n_scout"] and len(r["fb"]) >= r["n_scout"])
        fb_c = sum(len(r["fb"]) for r in rs)
        n_c = sum(r["n_scout"] for r in rs)
        trunc = sum(1 for r in rs if any(x["status"] == "truncated" for x in r["attempts"]))
        mini = sum(1 for r in rs if any("gpt-4o-mini" in x["model"] and a != "MINI" for x in r["attempts"]))
        print("  %-6s %4d %6.0fs %6.0fs %9.0f %9.0f%% %9.1f%% %8.0f%% %10.0f%%"
              % (a, len(rs), statistics.median(r["dt"] for r in rs), max(r["dt"] for r in rs),
                 statistics.mean(r["tok_out"] for r in rs), 100 * full / len(rs),
                 100 * fb_c / max(n_c, 1), 100 * trunc / len(rs), 100 * mini / len(rs)))
    print("  'Video ganz' = alle Firmen des Videos kamen aus dem Scout-Fallback (Analyst ausgefallen);")
    print("  'Firmen' = Anteil aller Firmen, die aus dem Scout-Fallback stammen;")
    print("  'abgesch.' = mindestens ein Versuch an max_tokens abgeschnitten; 'Mini-Anteil' = Kaskade ging an gpt-4o-mini")

    # 3. Qualitaet
    print("\n=== 3. Qualitaet gegen die Referenz (nur Firmen mit ECHTER Analyse in Variante und beiden Referenzen) ===")
    print("  d = mittlere Uebereinstimmung(Variante, REF1/REF2) minus Uebereinstimmung(REF1, REF2), je Video, Bootstrap ueber Videos")
    hdr = "  %-6s %-13s %5s %8s %8s  %-20s %s" % ("Arm", "Feld", "n", "Rausch", "Arm", "d [95%-KI]", "Urteil")
    print(hdr)
    for a in [x for x in ("REF1", "REF2", "LOW", "OFF", "MINI") if x not in (R1, R2)]:
        for f in FIELDS + ("price_target", "mentioned_price"):
            per_v_d, per_v_arm, per_v_noise, n_c = [], [], [], 0
            for v in vids:
                if a not in recs[v] or recs[v][a].get("crash"):
                    continue
                r1, r2, rx = recs[v][R1], recs[v][R2], recs[v][a]
                bad = set(r1["fb"]) | set(r2["fb"]) | set(rx["fb"])
                m1 = {c["name"]: c for c in r1["out"]}
                m2 = {c["name"]: c for c in r2["out"]}
                mx = {c["name"]: c for c in rx["out"]}
                names = [n for n in m1 if n in m2 and n in mx and n not in bad]
                if not names:
                    continue
                same = (price_same if f in ("price_target", "mentioned_price")
                        else (lambda p, q: p == q))
                a1 = sum(same(mx[n][f], m1[n][f]) for n in names) / len(names)
                a2 = sum(same(mx[n][f], m2[n][f]) for n in names) / len(names)
                a12 = sum(same(m1[n][f], m2[n][f]) for n in names) / len(names)
                per_v_d.append((a1 + a2) / 2 - a12)
                per_v_arm.append((a1 + a2) / 2)
                per_v_noise.append(a12)
                n_c += len(names)
            if len(per_v_d) < 6:
                continue
            lo, hi = bootstrap_ci(per_v_d)
            verdict = ("nicht unterscheidbar" if lo <= 0 <= hi
                       else ("SCHLECHTER als Rauschen" if hi < 0 else "uebereinstimmender"))
            print("  %-6s %-13s %5d %8.2f %8.2f  %+.3f [%+.3f,%+.3f]  %s"
                  % (a, f, n_c, statistics.mean(per_v_noise), statistics.mean(per_v_arm),
                     statistics.mean(per_v_d), lo, hi, verdict))
        print()

    # 4. Kursziele: erfunden oder verloren?
    print("=== 4. Kursziele: erfunden oder verloren? (nur Firmen mit ECHTER Analyse in Variante und beiden Referenzen) ===")
    both_pt = both_none = disagree = shared = 0
    for v in vids:
        r1, r2 = recs[v][R1], recs[v][R2]
        bad = set(r1["fb"]) | set(r2["fb"])
        m1 = {c["name"]: c for c in r1["out"]}
        m2 = {c["name"]: c for c in r2["out"]}
        for n in m1:
            if n in m2 and n not in bad:
                shared += 1
                p1, p2 = to_num(m1[n]["price_target"]), to_num(m2[n]["price_target"])
                both_pt += p1 is not None and p2 is not None
                both_none += p1 is None and p2 is None
                disagree += (p1 is None) != (p2 is None)
    print("  Rauschmass: bei %d Firmen nennen BEIDE Referenzen ein Kursziel, bei %d keines, bei %d (%.0f %%) sind sie"
          % (both_pt, both_none, disagree, 100 * disagree / max(shared, 1)))
    print("  uneinig, OB es ein Kursziel gibt. Kursziele sind also selbst bei identischer Konfiguration nicht stabil.")
    print("  %-6s %26s %28s" % ("Arm", "erfunden (Refs: beide leer)", "verloren (Refs: beide nennen eins)"))
    for a_ in [x for x in ("REF1", "REF2", "LOW", "OFF", "MINI") if x not in (R1, R2)]:
        inv = inv_n = lost = lost_n = 0
        for v in vids:
            if a_ not in recs[v] or recs[v][a_].get("crash"):
                continue
            r1, r2, rx = recs[v][R1], recs[v][R2], recs[v][a_]
            bad = set(r1["fb"]) | set(r2["fb"]) | set(rx["fb"])
            m1 = {c["name"]: c for c in r1["out"]}
            m2 = {c["name"]: c for c in r2["out"]}
            mx = {c["name"]: c for c in rx["out"]}
            for n in m1:
                if n in bad or n not in m2 or n not in mx:
                    continue
                p1, p2, px = (to_num(m1[n]["price_target"]), to_num(m2[n]["price_target"]),
                              to_num(mx[n]["price_target"]))
                if p1 is None and p2 is None:
                    inv_n += 1
                    inv += px is not None
                elif p1 is not None and p2 is not None:
                    lost_n += 1
                    lost += px is None
        print("  %-6s %14d von %-5d %s %14d von %-5d %s"
              % (a_, inv, inv_n, ("(%.0f%%)" % (100 * inv / inv_n)) if inv_n else "(-)",
                 lost, lost_n, ("(%.0f%%)" % (100 * lost / lost_n)) if lost_n else "(-)"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--videos", type=int, default=DEFAULT_VIDEOS)
    ap.add_argument("--analyze", action="store_true")
    ap.add_argument("--ref", default="REF", choices=["REF", "HI"],
                    help="Referenzpaar: REF = Produktionskonfiguration, HI = saubere Referenz (16000)")
    ap.add_argument("--arms", default=",".join(ARMS))
    args = ap.parse_args()
    if args.analyze:
        analyze(args.ref)
    elif args.run:
        run(args.videos, [x for x in args.arms.split(",") if x])
    else:
        ap.print_help()
