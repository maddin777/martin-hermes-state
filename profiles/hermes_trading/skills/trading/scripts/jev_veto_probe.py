#!/usr/bin/env python3
"""Haeufigkeits-Probe: Nachrichten-Veto fuer den TradingView-Screener (h_tv_screener) — 29.09.2026.

Frage: Wie oft steckt hinter einem Screener-Kandidaten ein Ereignis, das das Kurs-Setup entwertet
(Uebernahme vereinbart, Kapitalerhoehung, Ermittlungen/Bilanzproblem, Prognosesenkung)? Und kann Jev
das so gut erkennen wie DeepSeek, bzw. reicht eine Stichwortsuche?

Muster "Code rechnet, Jev entscheidet, LLM nur bei Bedarf": Jev bekommt nur Schlagzeilen, keine Kurszahlen.

Menge: die Stage-1-Pools des TradingView-Screeners (bis 300 long / 100 short), markiert mit
Stage-2-Zugehoerigkeit und Rang nach Composite. Nachrichten: Finnhub company-news, letzte 14 Tage.
Methoden je Titel: KEYWORD (Regex), JEV1/JEV2 (choice, zweimal = Eigenrauschen),
DS1/DS2 (deepseek-v4-flash, zweimal = Rauschgrenze der Referenz).

NUR LESEND: schreibt nichts in trading.db und nichts in llm_budget_log.
Dateien: data/jev_veto_probe_inputs.jsonl (Eingaben), data/jev_veto_probe.jsonl (Antworten, fortsetzbar).

VORAB FESTGELEGT (29.09.2026, vor dem ersten Lauf; nicht nachtraeglich aendern):
  Referenz-Veto = DS1 und DS2 nennen dieselbe Kategorie != none (Titel mit DS1 != DS2 = "unklar", zaehlen
  in Precision/Recall nicht mit).
  F (Haeufigkeit): Anteil Referenz-Veto unter den Stage-2-Kandidaten >= 5 %.
  J (Jev taugt): Jev-Veto = argmax != none (JEV1). Gegen Referenz: Recall >= 0,80 und Precision >= 0,70,
     nur belastbar bei >= 15 Referenz-Veto-Faellen (sonst "nicht belastbar").
  K (Stichwort taugt): dieselben Schwellen fuer KEYWORD.
  Ergebnis: GO fuer eine Schattenspur h_tv_jev_veto nur, wenn F und (J oder K). Erfuellt K, wird die
  Stichwortsuche bevorzugt (einfacher, kein zusaetzlicher Anbieter).

Aufruf:
    venv/bin/python scripts/jev_veto_probe.py --collect     # Kandidaten + Nachrichten (Finnhub), ~10 Min.
    venv/bin/python scripts/jev_veto_probe.py --dry-run     # Tokens/Kosten schaetzen, nichts aufrufen
    venv/bin/python scripts/jev_veto_probe.py --run
    venv/bin/python scripts/jev_veto_probe.py --analyze
"""
import argparse
import json
import math
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

T = "/root/.hermes/profiles/hermes_trading/skills/trading"
for _p in (T, os.path.join(T, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import env_loader  # noqa: F401,E402  (side-effect: laedt .env)
import requests  # noqa: E402

IN_PATH = os.path.join(T, "data", "jev_veto_probe_inputs.jsonl")
OUT_PATH = os.path.join(T, "data", "jev_veto_probe.jsonl")
NEWS_DAYS = 14
MAX_NEWS = 12
FINNHUB_PAUSE = 1.25            # < 50 Aufrufe je Minute
WORKERS = 8
DS_MODEL = "deepseek/deepseek-v4.1-flash"
ARMS = ("JEV1", "JEV2", "DS1", "DS2")
TOP_K = 15

CATS = {
    "acquisition_pending": "the company itself has agreed to be acquired or taken private, or is the target of a "
                           "pending tender offer or merger (it is the TARGET, not the buyer)",
    "offering_dilution": "the company announced or priced a share offering, secondary sale by the company, "
                         "convertible notes, an at-the-market program or another issuance that dilutes shareholders",
    "legal_accounting": "a credible, company-specific problem: regulator or government investigation, fraud "
                        "allegation, short-seller report, restatement, delayed filing or auditor resignation "
                        "(generic law-firm press releases soliciting investors do NOT count)",
    "guidance_cut": "the company lowered its guidance or outlook, issued a profit warning or clearly missed "
                    "earnings expectations",
    "none": "none of the above: routine, positive or unrelated news, or not enough information",
}
TASK = ("News items about one US-listed company from the last two weeks, newest first. Judge ONLY what the news "
        "says about this company. Pick the single most important development.")
QUESTIONS = {"event": {"type": "choice",
                       "instructions": "Which category best describes the most important company-specific "
                                       "development in these news items?",
                       "criteria": CATS}}

KEYWORDS = [  # Reihenfolge = Prioritaet
    ("acquisition_pending", r"to be acquired|agree[sd]? to be (acquired|bought)|take[- ]private|go(ing)?[- ]private"
                            r"|tender offer|buyout|acquired by"),
    ("offering_dilution", r"public offering|secondary offering|stock offering|share offering|priced .{0,40}offering"
                          r"|convertible (senior )?notes|at[- ]the[- ]market|share sale|dilut"),
    ("legal_accounting", r"investigat|subpoena|class action|fraud|short[- ]seller|short report|restat"
                         r"|delayed filing|auditor resign|department of justice|\bdoj\b"),
    ("guidance_cut", r"(cut|cuts|lower|lowers|lowered|slash|slashes|trims?) (its |full[- ]year )?(guidance|outlook|forecast)"
                     r"|profit warning|miss(es|ed)? (estimates|expectations)"),
]


# ── Sammeln ────────────────────────────────────────────────────────────────
def _tv_rows():
    from tradingview_screener import Query, col
    import shadow_selection as ss
    _n, df = (Query().set_markets("america")
              .select(*ss.TV_FIELDS, "description")
              .where(col("type") == "stock", col("subtype") == "common",
                     col("exchange").isin(ss.TV_EXCHANGES), col("is_primary") == True,  # noqa: E712
                     col("close") >= ss.TV_MIN_PRICE)
              .order_by("market_cap_basic", ascending=False)
              .limit(6000)
              .get_scanner_data())
    return df.to_dict("records")


def _finnhub_news(symbol, today):
    key = os.environ.get("FINNHUB_API_KEY")
    frm = (today - timedelta(days=NEWS_DAYS)).isoformat()
    for attempt in range(3):
        try:
            r = requests.get("https://finnhub.io/api/v1/company-news", timeout=20,
                             params={"symbol": symbol, "from": frm, "to": today.isoformat(), "token": key})
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            data = r.json() if r.status_code == 200 else []
            break
        except (requests.RequestException, ValueError):
            time.sleep(2)
            data = None
    if not isinstance(data, list):
        return None                     # Fehler (nicht: keine Nachrichten)
    items, seen = [], set()
    for n in sorted(data, key=lambda x: -(x.get("datetime") or 0)):
        h = (n.get("headline") or "").strip()
        if not h or h.lower() in seen:
            continue
        seen.add(h.lower())
        days = (today - datetime.fromtimestamp(n.get("datetime") or 0).date()).days
        items.append({"days_ago": days, "source": n.get("source") or "",
                      "headline": h[:220], "summary": (n.get("summary") or "").strip()[:300]})
        if len(items) >= MAX_NEWS:
            break
    return items


def collect():
    import screener_source as sc
    import shadow_selection as ss
    today = datetime.now().date()
    rows = _tv_rows()
    names = {ss.tv_to_yf(r["name"]): (r["name"], r.get("description") or r["name"]) for r in rows}
    regime, vix, overlay = sc._current_regime()
    p = sc.regime_params(regime, vix, overlay)
    bench_ret = sc._benchmark_return(sc.REL_STRENGTH_LOOKBACK)
    long_pool, short_pool = ss.tv_stage1(rows, bench_ret)
    stage2 = list(dict.fromkeys(long_pool + short_pool))
    for i in range(0, len(stage2), ss.TV_CHUNK):
        ss.prefetch_prices(stage2[i:i + ss.TV_CHUNK])
    longs, shorts = sc.screen_stage2(stage2, {t: "tradingview" for t in stage2}, p, bench_ret)
    s2 = {c["ticker"]: c for c in longs + shorts}
    ranked = sorted(sc.select_candidates(longs + shorts, p), key=lambda c: c["composite"], reverse=True)
    rank = {c["ticker"]: i + 1 for i, c in enumerate(ranked)}
    print(f"TradingView {len(rows)} → Stage 1 {len(long_pool)} L / {len(short_pool)} S → "
          f"Stage 2 {len(longs)} L / {len(shorts)} S (Regime {regime})", flush=True)

    out, fails = [], 0
    for i, t in enumerate(stage2, 1):
        sym, desc = names.get(t, (t, t))
        news = _finnhub_news(sym, today)
        if news is None:
            fails += 1
        c = s2.get(t)
        out.append({"ticker": t, "symbol": sym, "name": desc,
                    "pool": "long" if t in long_pool else "short",
                    "in_stage2": c is not None,
                    "direction": c["direction"] if c else None,
                    "composite": round(c["composite"], 3) if c else None,
                    "sel_rank": rank.get(t), "news": news or [], "news_error": news is None,
                    "as_of": today.isoformat()})
        if i % 50 == 0:
            print(f"  Nachrichten {i}/{len(stage2)} (Fehler {fails})", flush=True)
        time.sleep(FINNHUB_PAUSE)
    with open(IN_PATH, "w", encoding="utf-8") as f:
        for o in out:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
    no_news = sum(1 for o in out if not o["news"] and not o["news_error"])
    print(f"Geschrieben: {IN_PATH} — {len(out)} Titel, {fails} Abruffehler, {no_news} ohne Nachrichten", flush=True)


# ── Modelle ────────────────────────────────────────────────────────────────
def _load_inputs():
    with open(IN_PATH, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _state(o):
    return {"task": TASK, "company": o["name"], "ticker": o["ticker"],
            "news": [{"when": ("this week" if n["days_ago"] <= 6 else "last week"),
                      "headline": n["headline"], "summary": n["summary"]} for n in o["news"]]}


def _ask_jev(o):
    from thematic.lib import jev_client as jc
    resp = jc.decide(_state(o), QUESTIONS, timeout=60)
    if not resp:
        return None
    ch = jc.choice_of(resp, "event", options=CATS)
    if not ch:
        return None
    label, conf, probs = ch
    _, _, cost = jc.usage_of(resp)
    return {"label": label, "conf": conf, "probs": probs, "cost": cost, "model": jc.model_of(resp)}


def _ask_ds(o):
    cats = "\n".join(f"- {k}: {v}" for k, v in CATS.items())
    news = "\n".join(f"- ({'this week' if n['days_ago'] <= 6 else 'last week'}) {n['headline']}"
                     + (f" — {n['summary']}" if n["summary"] else "") for n in o["news"])
    prompt = (f"{TASK}\n\nCompany: {o['name']} ({o['ticker']})\n\nNews:\n{news}\n\nCategories:\n{cats}\n\n"
              'Answer ONLY with JSON: {"category": "<one of the category keys>"}')
    for attempt in range(3):
        try:
            r = requests.post("https://openrouter.ai/api/v1/chat/completions", timeout=60,
                              headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
                              json={"model": DS_MODEL, "max_tokens": 300, "reasoning": {"enabled": False},
                                    "usage": {"include": True},
                                    "messages": [{"role": "user", "content": prompt}]})
            d = r.json()
            text = (d["choices"][0]["message"].get("content") or "").replace("```json", "").replace("```", "")
            label = json.loads(text.strip())["category"]
            if label in CATS:
                return {"label": label, "cost": float((d.get("usage") or {}).get("cost") or 0.0)}
        except Exception:
            time.sleep(2 ** attempt)
    return None


def keyword_label(o):
    text = " ".join(f"{n['headline']} {n['summary']}" for n in o["news"]).lower()
    for cat, pat in KEYWORDS:
        if re.search(pat, text):
            return cat
    return "none"


def _done():
    done = set()
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    done.add((r["ticker"], r["arm"]))
    return done


def run(dry=False):
    inputs = [o for o in _load_inputs() if o["news"]]
    chars = sum(len(json.dumps(_state(o))) for o in inputs)
    tok = chars / 4
    print(f"{len(inputs)} Titel mit Nachrichten, ~{tok:,.0f} Eingabetokens je Durchlauf. "
          f"Jev 2x ≈ {2 * tok * 0.042e-6:.4f} $, DeepSeek 2x ≈ {2 * tok * 0.3e-6:.3f} $ (grob)", flush=True)
    if dry:
        o = max(inputs, key=lambda x: len(x["news"]))
        print(json.dumps(_state(o), ensure_ascii=False, indent=1)[:2500])
        print("Stichwort:", keyword_label(o))
        return
    done = _done()
    jobs = [(o, arm) for o in inputs for arm in ARMS if (o["ticker"], arm) not in done]
    print(f"{len(jobs)} offene Anfragen", flush=True)
    lock = threading.Lock()
    stats = {"ok": 0, "fail": 0}

    def one(job):
        o, arm = job
        res = _ask_jev(o) if arm.startswith("JEV") else _ask_ds(o)
        with lock:
            if res is None:
                stats["fail"] += 1
                return
            stats["ok"] += 1
            with open(OUT_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ticker": o["ticker"], "arm": arm, **res}, ensure_ascii=False) + "\n")

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(one, jobs))
    print(f"fertig: {stats['ok']} ok, {stats['fail']} Fehler", flush=True)


# ── Auswertung ─────────────────────────────────────────────────────────────
def _wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def _pct(k, n):
    lo, hi = _wilson(k, n)
    return f"{k}/{n} = {100 * k / n:.1f} % [{100 * lo:.1f}; {100 * hi:.1f}]" if n else "0/0"


def analyze():
    inputs = {o["ticker"]: o for o in _load_inputs()}
    res = {}
    with open(OUT_PATH, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                res.setdefault(r["ticker"], {})[r["arm"]] = r
    lab = {}
    for t, o in inputs.items():
        a = res.get(t, {})
        if not o["news"]:
            lab[t] = {"KEY": "none", "JEV1": "none", "JEV2": "none", "DS1": "none", "DS2": "none",
                      "REF": "none", "pveto": 0.0, "no_news": True}
            continue
        if not all(k in a for k in ARMS):
            continue
        ref = a["DS1"]["label"] if a["DS1"]["label"] == a["DS2"]["label"] else "unclear"
        lab[t] = {"KEY": keyword_label(o), "JEV1": a["JEV1"]["label"], "JEV2": a["JEV2"]["label"],
                  "DS1": a["DS1"]["label"], "DS2": a["DS2"]["label"], "REF": ref,
                  "pveto": 1.0 - a["JEV1"]["probs"].get("none", 0.0), "no_news": False}
    cost = sum(r.get("cost", 0.0) for a in res.values() for r in a.values())
    all_t = list(lab)
    s2 = [t for t in all_t if inputs[t]["in_stage2"]]
    top = [t for t in all_t if (inputs[t]["sel_rank"] or 999) <= TOP_K]
    n_news = sum(1 for t in all_t if not lab[t]["no_news"])
    errors = sum(1 for o in inputs.values() if o["news_error"])
    print(f"Titel ausgewertet: {len(all_t)} von {len(inputs)} (mit Nachrichten {n_news}, Abruffehler {errors}); "
          f"Stage 2: {len(s2)}, Top-{TOP_K}: {len(top)}; Modellkosten {cost:.4f} $\n")

    print("── Haeufigkeit Veto (Kategorie != none) ──")
    for name, ts in (("alle", all_t), ("Stage 2", s2), (f"Top-{TOP_K}", top)):
        print(f"  {name}:")
        for m in ("REF", "DS1", "JEV1", "KEY"):
            k = sum(1 for t in ts if lab[t][m] not in ("none", "unclear"))
            print(f"    {m:5s} {_pct(k, len(ts))}")
    print("\n── Kategorien (alle Titel) ──")
    for m in ("REF", "JEV1", "KEY"):
        cnt = {}
        for t in all_t:
            cnt[lab[t][m]] = cnt.get(lab[t][m], 0) + 1
        print(f"  {m:5s} " + ", ".join(f"{k}={v}" for k, v in sorted(cnt.items(), key=lambda x: -x[1])))

    news_t = [t for t in all_t if not lab[t]["no_news"]]
    print("\n── Uebereinstimmung Kategorie (Titel mit Nachrichten) ──")
    for a_, b_ in (("DS1", "DS2"), ("JEV1", "JEV2"), ("JEV1", "DS1"), ("KEY", "DS1")):
        k = sum(1 for t in news_t if lab[t][a_] == lab[t][b_])
        print(f"  {a_}↔{b_}: {_pct(k, len(news_t))}")

    stable = [t for t in all_t if lab[t]["REF"] != "unclear"]
    ref_veto = [t for t in stable if lab[t]["REF"] != "none"]
    print(f"\n── Veto gegen Referenz (stabile Referenz: {len(stable)} Titel, davon Veto {len(ref_veto)}) ──")
    verdict = {}
    for m in ("JEV1", "KEY"):
        pred = [t for t in stable if lab[t][m] != "none"]
        tp = len([t for t in pred if t in ref_veto])
        rec = tp / len(ref_veto) if ref_veto else 0.0
        prec = tp / len(pred) if pred else 0.0
        same_cat = sum(1 for t in ref_veto if lab[t][m] == lab[t]["REF"])
        print(f"  {m:5s} Recall {_pct(tp, len(ref_veto))} | Precision {_pct(tp, len(pred))} | "
              f"gleiche Kategorie {same_cat}/{len(ref_veto)}")
        verdict[m] = (len(ref_veto) >= 15, rec >= 0.80 and prec >= 0.70)

    print("\n── Kalibrierung Jev: P(Veto) = 1 − P(none) gegen Referenz-Veto ──")
    for lo, hi in ((0, .1), (.1, .3), (.3, .5), (.5, .7), (.7, .9), (.9, 1.01)):
        ts = [t for t in stable if not lab[t]["no_news"] and lo <= lab[t]["pveto"] < hi]
        k = sum(1 for t in ts if t in ref_veto)
        print(f"  {lo:.1f}–{min(hi, 1):.1f}: {_pct(k, len(ts))}")

    print(f"\n── Veto-Faelle in Stage 2 (Referenz, JEV1 oder Stichwort) ──")
    for t in sorted(s2, key=lambda x: inputs[x]["sel_rank"] or 999):
        L = lab[t]
        if {L["REF"], L["JEV1"], L["KEY"]} - {"none"}:
            o = inputs[t]
            print(f"  #{o['sel_rank'] or '-':>3} {t:6s} {o['direction'] or '':5s} REF={L['REF']:20s} "
                  f"JEV={L['JEV1']:20s}({L['pveto']:.2f}) KEY={L['KEY']}")
            for n in o["news"][:3]:
                print(f"        · ({n['days_ago']}d) {n['headline'][:110]}")

    k_s2 = sum(1 for t in s2 if lab[t]["REF"] not in ("none", "unclear"))
    F = len(s2) > 0 and k_s2 / len(s2) >= 0.05
    print("\n── Entscheidung (vorab festgelegt) ──")
    print(f"  F Haeufigkeit Stage 2 >= 5 %: {'erfüllt' if F else 'verfehlt'} ({_pct(k_s2, len(s2))})")
    for m, tag in (("JEV1", "J"), ("KEY", "K")):
        enough, ok = verdict[m]
        print(f"  {tag} {m}: " + ("nicht belastbar (< 15 Referenz-Vetos)" if not enough
                                  else ("erfüllt" if ok else "verfehlt")))
    J = all(verdict["JEV1"])
    K = all(verdict["KEY"])
    if F and K:
        print("  → GO für Schattenspur mit STICHWORT-Veto (Jev nicht nötig)")
    elif F and J:
        print("  → GO für Schattenspur h_tv_jev_veto mit Jev")
    else:
        print("  → NO-GO: keine Schattenspur")


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--collect", action="store_true")
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--run", action="store_true")
    g.add_argument("--analyze", action="store_true")
    a = ap.parse_args()
    if a.collect:
        collect()
    elif a.dry_run:
        run(dry=True)
    elif a.run:
        run()
    else:
        analyze()


if __name__ == "__main__":
    main()
