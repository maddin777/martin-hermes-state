import functools
import sqlite3
from datetime import date, timedelta

import numpy as np
import pytest

from scripts import jev_shadow_eval as ev


@pytest.fixture(autouse=True)
def _fast(monkeypatch, tmp_path):
    monkeypatch.setattr(ev, "BOOT_WEEK", 100)
    monkeypatch.setattr(ev, "BOOT_TICKER", 40)
    monkeypatch.setattr(ev, "_ROOT", str(tmp_path))          # keine Berichtsdatei ins echte data/


def make_con(n_days=25, per_day=40, n_tickers=60, signal=0.0, seed=0, status="evaluated"):
    rng = np.random.default_rng(seed)
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE shadow_selection (id INTEGER PRIMARY KEY, hypothesis TEXT, ticker TEXT,
        select_date TEXT, score REAL, rationale TEXT, eval_status TEXT, outcome TEXT, pnl_pct_sim REAL)""")
    start = date(2026, 9, 8)
    for d in range(n_days):
        day = (start + timedelta(days=d)).isoformat()
        tickers = rng.choice(n_tickers, per_day, replace=False)
        conv, tech = rng.uniform(0.2, 1, per_day), rng.uniform(0.7, 1, per_day)
        score = np.round(rng.uniform(0.3, 0.5, per_day), 3)
        pnl = signal * (score - score.mean()) / score.std() + rng.normal(0, 3, per_day)
        for i in range(per_day):
            con.execute("INSERT INTO shadow_selection (hypothesis, ticker, select_date, score, rationale, "
                        "eval_status, outcome, pnl_pct_sim) VALUES (?,?,?,?,?,?,?,?)",
                        ("h_jev", "T%d" % tickers[i], day, float(score[i]),
                         "jev=%.2f conv=%.2f tech=%.2f mentions30=3" % (score[i], conv[i], tech[i]),
                         status, "TP_HIT" if pnl[i] > 2 else "SL_HIT", float(pnl[i])))
    con.commit()
    return con


def test_small_sample_is_pending_and_report_shows_no_metrics():
    con = make_con(n_days=2, per_day=10)
    r = ev.analyze(ev.load_rows(con))
    assert r["verdict"] == "PENDING" and r["n_eval"] == 20
    text = ev.format_report(r, date(2026, 10, 15))
    assert "NICHT AUSSAGEKRAEFTIG" in text and "Kennzahl A" not in text and "URTEIL" not in text


def test_enough_rows_but_too_few_tickers_is_pending():
    con = make_con(n_days=30, per_day=20, n_tickers=30)
    r = ev.analyze(ev.load_rows(con))
    assert r["n_eval"] >= ev.MIN_ROWS and r["tickers"] < ev.MIN_TICKERS
    assert r["verdict"] == "PENDING"


def test_rows_not_yet_evaluated_are_not_counted():
    con = make_con(status="pending")
    r = ev.analyze(ev.load_rows(con))
    assert r["n_total"] == 1000 and r["n_eval"] == 0 and r["verdict"] == "PENDING"


def test_no_rows_at_all_is_pending():
    con = make_con(n_days=0)
    r = ev.analyze(ev.load_rows(con))
    assert r["verdict"] == "PENDING" and r["n_total"] == 0


def test_planted_signal_gives_go():
    r = cached(3.0, 1)
    assert r["verdict"] == "GO"
    assert r["dA_lo"] > 0 and r["B_lo"] > 0 and r["ic_jev"] > max(r["ic_conv"], r["ic_tech"])


def test_pure_noise_gives_no_go():
    r = cached(0.0, 2)
    assert r["verdict"] == "NO-GO"
    assert r["dA_lo"] <= 0 or r["B_lo"] <= 0


def test_report_for_verdicts_and_length():
    go = ev.format_report(cached(3.0, 1), date(2026, 10, 29))
    assert "URTEIL: GO" in go and "Kennzahl C" in go and len(go) < 4000
    no = ev.format_report(cached(0.0, 2), date(2026, 10, 29))
    assert "URTEIL: NO-GO" in no and "JEV_SHADOW" in no


def test_rationale_parsing_drops_rows_without_conv_and_tech():
    con = make_con(n_days=3, per_day=10)
    con.execute("UPDATE shadow_selection SET rationale='kaputt' WHERE id <= 5")
    e = ev.evaluated(ev.load_rows(con))
    assert len(e) == 25


@functools.lru_cache(maxsize=None)
def cached(signal, seed):
    ev.BOOT_WEEK, ev.BOOT_TICKER = 100, 40
    return ev.analyze(ev.load_rows(make_con(signal=signal, seed=seed)))


class Recorder:
    def __init__(self, monkeypatch, con, send_ok=True):
        self.sent, self.disabled = [], []
        monkeypatch.setattr(ev, "db_connect", lambda: con)
        monkeypatch.setattr(ev, "send_telegram", lambda m: (self.sent.append(m), (send_ok, "x"))[1])
        monkeypatch.setattr(ev, "disable_own_cron", lambda: self.disabled.append(1))


def test_cron_pending_before_last_date_sends_but_keeps_job(monkeypatch):
    rec = Recorder(monkeypatch, make_con(n_days=2, per_day=10))
    assert ev.main(["--cron"], today=date(2026, 10, 15)) == 0
    assert len(rec.sent) == 1 and "NICHT AUSSAGEKRAEFTIG" in rec.sent[0] and rec.disabled == []


def test_cron_verdict_sends_and_disables_job(monkeypatch):
    rec = Recorder(monkeypatch, make_con(n_days=2, per_day=10))
    monkeypatch.setattr(ev, "analyze", lambda df, today=None: cached(3.0, 1))
    assert ev.main(["--cron"], today=date(2026, 10, 29)) == 0
    assert "URTEIL: GO" in rec.sent[0] and rec.disabled == [1]


def test_cron_last_date_with_pending_ends_job_with_note(monkeypatch):
    rec = Recorder(monkeypatch, make_con(n_days=2, per_day=10))
    ev.main(["--cron"], today=ev.LAST_RUN_DATE)
    assert "letzte geplante Termin" in rec.sent[0] and rec.disabled == [1]


def test_cron_keeps_job_when_telegram_fails(monkeypatch):
    rec = Recorder(monkeypatch, make_con(n_days=2, per_day=10), send_ok=False)
    monkeypatch.setattr(ev, "analyze", lambda df, today=None: cached(3.0, 1))
    ev.main(["--cron"], today=date(2026, 10, 29))
    assert rec.disabled == []


def test_error_is_reported_via_telegram_and_job_stays(monkeypatch):
    sent, disabled = [], []
    monkeypatch.setattr(ev, "db_connect", lambda: (_ for _ in ()).throw(RuntimeError("db kaputt")))
    monkeypatch.setattr(ev, "send_telegram", lambda m: (sent.append(m), (True, "x"))[1])
    monkeypatch.setattr(ev, "disable_own_cron", lambda: disabled.append(1))
    assert ev.main(["--cron"], today=date(2026, 10, 15)) == 1
    assert "FEHLGESCHLAGEN" in sent[0] and "db kaputt" in sent[0] and disabled == []


def test_plain_run_without_flags_sends_nothing(monkeypatch):
    rec = Recorder(monkeypatch, make_con(n_days=2, per_day=10))
    assert ev.main([], today=date(2026, 10, 15)) == 0
    assert rec.sent == [] and rec.disabled == []


# jev-pin-20260925
def test_report_lists_model_versions_and_warns_on_mix():
    con = make_con(n_days=2, per_day=10)
    con.execute("UPDATE shadow_selection SET rationale = rationale || ' model=typesafe/jev-1.13-20260917' "
                "WHERE id <= 5")
    r = ev.analyze(ev.load_rows(con))
    assert r["models"] == {"typesafe/jev-1.13-20260917": 5, ev.NO_MODEL: 15}
    text = ev.format_report(r, date(2026, 10, 15))
    assert "Modellversion(en): ohne Angabe 15, typesafe/jev-1.13-20260917 5" in text
    assert "ACHTUNG" not in text                           # "ohne Angabe" zaehlt nicht als zweite Version
    con.execute("UPDATE shadow_selection SET rationale = rationale || ' model=typesafe/jev-1.14-20261001' "
                "WHERE id > 15")
    assert "ACHTUNG" in ev.format_report(ev.analyze(ev.load_rows(con)), date(2026, 10, 15))


def test_model_tag_does_not_break_conv_tech_parsing():
    con = make_con(n_days=2, per_day=10)
    con.execute("UPDATE shadow_selection SET rationale = rationale || ' model=typesafe/jev-1.13-20260917'")
    e = ev.evaluated(ev.load_rows(con))
    assert len(e) == 20 and e.conv.notna().all() and e.tech.notna().all()
