"""Welle 8 (thematic, ruhender Code): N13 briefing, N14 weekly_review, N15 losers, N16 Theme-Merge, N17 Lifecycle,
N18 fundamental_screener, N19 Kleinkram, N20 setup_thematic.sh. Alle Datenbanken im Speicher, keine Netzaufrufe."""
import json
import os
import sqlite3
import stat
import subprocess
from datetime import date, datetime, timedelta

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(__file__))
MIG = os.path.join(ROOT, "thematic", "migrations")


def mem(*migrations):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    for m in migrations:
        con.executescript(open(os.path.join(MIG, m), encoding="utf-8").read())
    return con


def add_theme(con, name="AI Power", status="active", first=None, last=None, embedding=None):
    today = date.today().isoformat()
    con.execute("INSERT INTO theme_definitions (name, description, first_detected, last_seen, status, momentum, "
                "underreported_score, coverage_count, embedding_vector) VALUES (?,?,?,?,?,?,?,?,?)",
                (name, f"{name} Beschreibung", first or today, last or today, status, "steady", 0.5, 1,
                 json.dumps(embedding) if embedding else None))
    con.commit()
    return con.execute("SELECT id FROM theme_definitions WHERE name=?", (name,)).fetchone()[0]


# ── N20 ─────────────────────────────────────────────────────────────────────────────────────
def test_setup_script_refuses_without_force_and_touches_nothing(tmp_path):
    shim = tmp_path / "bin"
    shim.mkdir()
    log = tmp_path / "calls.log"
    for cmd in ("crontab", "cp", "sqlite3", "python3"):
        f = shim / cmd
        f.write_text(f"#!/bin/sh\necho {cmd} >> {log}\n")
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    env = {"PATH": f"{shim}:/usr/bin:/bin", "HOME": str(tmp_path)}
    r = subprocess.run(["bash", os.path.join(ROOT, "thematic", "setup_thematic.sh")], env=env, capture_output=True, text=True)
    assert r.returncode == 1 and "N20" in r.stderr
    assert not log.exists()


def test_the_guard_comes_before_any_command():
    lines = open(os.path.join(ROOT, "thematic", "setup_thematic.sh"), encoding="utf-8").read().splitlines()
    guard = next(i for i, l in enumerate(lines) if "FORCE_THEMATIC_SETUP" in l and "!=" in l)
    first_cmd = next(i for i, l in enumerate(lines) if l.strip().startswith(("cp ", "crontab", "sqlite3", "mktemp")))
    assert guard < first_cmd


# ── N13 ─────────────────────────────────────────────────────────────────────────────────────
def _briefing_db():
    con = mem("001_initial_schema.sql")
    con.execute("""CREATE TABLE positions (id INTEGER PRIMARY KEY, name TEXT, ticker TEXT, status TEXT, entry_date TEXT,
        entry_price REAL, pnl_eur REAL, thesis_current_status TEXT)""")
    tid = add_theme(con, "Neues Thema", first=date.today().isoformat())
    for tick, pt in [("A", "direct_plays"), ("B", "picks_and_shovels"), ("C", "second_derivatives"), ("D", "losers")]:
        con.execute("INSERT INTO theme_beneficiaries (theme_id, ticker, play_type, status, llm_confidence_count, added_date) "
                    "VALUES (?,?,?,'candidate',3,?)", (tid, tick, pt, date.today().isoformat()))
    for i in range(5):
        con.execute("INSERT INTO positions (name, ticker, status, entry_price, pnl_eur) VALUES (?,?, 'open', 10, 1)",
                    (f"Pos{i}", f"P{i}"))
        con.execute("INSERT INTO thesis_status_log (position_id, ticker, check_date, status, confidence, rationale) "
                    "VALUES (?,?,?,?,?,?)", (i + 1, f"P{i}", date.today().isoformat(),
                                             "BROKEN" if i < 3 else "WEAKENING", 0.9, "Grund"))
    con.commit()
    return con


def test_briefing_lists_all_four_play_types_and_counts_alerts_correctly(monkeypatch, tmp_path):
    from thematic import briefing
    con = _briefing_db()
    md = briefing._build_briefing_md(con, date.today().isoformat())
    for label in ("Direct Plays", "Picks And Shovels", "Second Derivatives", "Verlierer"):
        assert label in md
    assert briefing._count_from_md(md, r"RED ALERTS \((\d+)\)") == 3
    assert briefing._count_from_md(md, r"YELLOW \((\d+)\)") == 2
    assert briefing._count_from_md(md, r"Neue Themen \((\d+)\)") == 1


def test_briefing_main_stores_real_counts_and_sends_without_nameerror(monkeypatch, tmp_path):
    from thematic import briefing
    db = tmp_path / "t.db"
    src = _briefing_db()
    dst = sqlite3.connect(db)
    src.backup(dst)
    dst.close()
    monkeypatch.setattr(briefing, "DB_PATH", str(db))
    sent = []
    monkeypatch.setattr(briefing, "TELEGRAM_TOKEN", "x")
    monkeypatch.setattr(briefing, "TELEGRAM_HOME_CHANNEL", "chat")
    monkeypatch.setattr(briefing.requests, "post", lambda url, json=None, timeout=None: sent.append(json))
    briefing.main()
    row = sqlite3.connect(db).execute("SELECT red_alerts_count, yellow_alerts_count, new_themes_count FROM briefings").fetchone()
    assert row == (3, 2, 1) and sent and sent[0]["chat_id"] == "chat"


# ── N14 ─────────────────────────────────────────────────────────────────────────────────────
def test_weekly_review_position_check_works_with_sqlite_rows(monkeypatch):
    from thematic import weekly_review as wr
    con = mem("001_initial_schema.sql")
    con.execute("""CREATE TABLE positions (id INTEGER PRIMARY KEY, name TEXT, ticker TEXT, status TEXT, entry_date TEXT,
        thesis_text TEXT, thesis_theme_id INTEGER, pnl_pct REAL, thesis_current_status TEXT)""")
    old = (date.today() - timedelta(days=45)).isoformat()
    con.execute("INSERT INTO positions (name, ticker, status, entry_date, thesis_text, pnl_pct) VALUES ('X','X','open',?,'KI',2.0)", (old,))
    con.execute("INSERT INTO thesis_status_log (position_id, ticker, check_date, status, confidence, rationale) "
                "VALUES (1,'X','2026-09-20','INTACT',0.8,'ok')")
    con.commit()
    monkeypatch.setattr(wr.llm_client, "get_model", lambda t: "m")
    monkeypatch.setattr(wr.llm_client, "call_llm", lambda *a, **k: {"ok": True, "content": "{}"})
    monkeypatch.setattr(wr.llm_client, "parse_json_response", lambda r, default=None: {"action": "HOLD", "rationale": "ok"})
    monkeypatch.setattr(wr.prompt_loader, "load_prompt", lambda *a, **k: "prompt")
    wr._position_30day_review(con)


def test_exit_quality_review_skips_when_tables_are_missing():
    from thematic import weekly_review as wr
    con = mem("001_initial_schema.sql")
    assert wr.run_exit_quality_review(con) is None


# ── N15 ─────────────────────────────────────────────────────────────────────────────────────
def _boost_db(play_type):
    con = mem("001_initial_schema.sql")
    tid = add_theme(con, "Thema")
    con.execute("INSERT INTO theme_beneficiaries (theme_id, ticker, play_type, status, last_updated, added_date) "
                "VALUES (?,?,?,'candidate',?,?)", (tid, "TICK", play_type, date.today().isoformat(), date.today().isoformat()))
    con.commit()
    return con


def test_losers_get_no_positive_conviction_boost():
    from scripts import watchlist_manager as wm
    assert wm.get_thesis_conviction_boost(_boost_db("direct_plays"), "TICK") > 0
    assert wm.get_thesis_conviction_boost(_boost_db("losers"), "TICK") == 0.0


# ── N16 ─────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture()
def merge(monkeypatch):
    from thematic import theme_merge_engine as tm
    monkeypatch.setattr(tm, "embed_theme", lambda n, d: [0.1] * 8)
    con = mem("001_initial_schema.sql", "003_news_persistence.sql")
    return tm, con


def test_a_dormant_theme_reappearing_under_the_same_name_is_reactivated(merge):
    tm, con = merge
    tid = add_theme(con, "AI Datacenter Energy Crunch", status="dormant", last="2026-06-10")
    result = tm.check_and_merge({"name": "AI Datacenter Energy Crunch", "description": "wieder aktuell"}, con)   # vorher IntegrityError
    row = con.execute("SELECT status, coverage_count FROM theme_definitions WHERE id=?", (tid,)).fetchone()
    assert row["status"] == "active" and row["coverage_count"] == 2
    assert con.execute("SELECT COUNT(*) FROM theme_definitions").fetchone()[0] == 1


def test_human_decision_merged_is_executed_once(merge):
    tm, con = merge
    tid = add_theme(con, "Grid Storage", embedding=[0.1] * 8)
    con.execute("INSERT INTO theme_merge_queue (new_theme_data, candidate_existing_id, similarity_score, status) VALUES (?,?,?,?)",
                (json.dumps({"name": "Battery Grid", "description": "d"}), tid, 0.8, "merged"))
    con.commit()
    assert tm.apply_merge_decisions(con) == 1
    assert con.execute("SELECT coverage_count FROM theme_definitions WHERE id=?", (tid,)).fetchone()[0] == 2
    assert tm.apply_merge_decisions(con) == 0                                   # nur einmal


def test_human_decision_kept_separate_creates_the_theme(merge):
    tm, con = merge
    tid = add_theme(con, "Grid Storage", embedding=[0.1] * 8)
    con.execute("INSERT INTO theme_merge_queue (new_theme_data, candidate_existing_id, similarity_score, status) VALUES (?,?,?,?)",
                (json.dumps({"name": "Battery Grid", "description": "d"}), tid, 0.8, "kept_separate"))
    con.commit()
    tm.apply_merge_decisions(con)
    assert con.execute("SELECT COUNT(*) FROM theme_definitions WHERE name='Battery Grid'").fetchone()[0] == 1


def test_the_same_theme_is_queued_only_once(merge):
    tm, con = merge
    tid = add_theme(con, "Grid Storage", embedding=[0.1] * 8)
    for _ in range(3):
        tm.queue_for_review(con, {"name": "Battery Grid", "description": "d"}, tid, 0.8)
    assert con.execute("SELECT COUNT(*) FROM theme_merge_queue WHERE status='pending'").fetchone()[0] == 1


# ── N17 ─────────────────────────────────────────────────────────────────────────────────────
def test_lifecycle_sync_runs_even_when_there_are_no_new_themes(monkeypatch, tmp_path):
    from thematic import beneficiary_mapper as bm
    db = tmp_path / "t.db"
    con = mem("001_initial_schema.sql")
    tid = add_theme(con, "Altes Thema", status="dormant", first="2026-01-01", last="2026-02-01")
    con.execute("INSERT INTO theme_beneficiaries (theme_id, ticker, status, last_updated, added_date) VALUES (?,?,?,?,?)",
                (tid, "OLD", "candidate", "2026-02-01", "2026-02-01"))
    con.commit()
    dst = sqlite3.connect(db)
    con.backup(dst)
    dst.close()
    monkeypatch.setattr(bm, "_db_connect", lambda: (lambda c: (setattr(c, "row_factory", sqlite3.Row), c)[1])(sqlite3.connect(db)))
    bm.main()
    assert sqlite3.connect(db).execute("SELECT status FROM theme_beneficiaries").fetchone()[0] == "archived"


@pytest.mark.parametrize("rel", ["thematic/fundamental_screener.py", "thematic/timing_validator.py"])
def test_active_beneficiaries_are_no_longer_dropped_by_screener_and_validator(rel):
    src = open(os.path.join(ROOT, rel), encoding="utf-8").read()
    assert "'active'" in src.split("status IN (")[1].split(")")[0]


# ── N18 ─────────────────────────────────────────────────────────────────────────────────────
def _pe_db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""CREATE TABLE fundamentals_snapshot (date TEXT, ticker TEXT, pe_ttm REAL);
                         CREATE TABLE companies (ticker TEXT, sector TEXT);""")
    today = date.today().isoformat()
    tech = [("T%d" % i, "Technology", 30 + i) for i in range(6)]
    banks = [("B%d" % i, "Financials", 8 + i) for i in range(6)]
    for t, s, pe in tech + banks:
        con.execute("INSERT INTO fundamentals_snapshot VALUES (?,?,?)", (today, t, pe))
        con.execute("INSERT INTO companies VALUES (?,?)", (t, s))
    con.commit()
    return con


def test_sector_median_uses_the_peers_of_the_sector():
    from thematic import fundamental_screener as fs
    con = _pe_db()
    assert fs._sector_median_pe(con, "Financials") == pytest.approx(10.5)
    assert fs._sector_median_pe(con, "Technology") == pytest.approx(32.5)
    assert 10.5 < fs._sector_median_pe(con, "all") < 32.5              # Gesamtmedian als Rueckfall
    assert fs._sector_median_pe(con, "Unbekannt") == fs._sector_median_pe(con, "all")   # < 5 Peers


def test_fcf_yield_keeps_units_apart():
    from thematic import fundamental_screener as fs
    assert fs._fcf_yield({"freeCashFlowTTM": 1000.0}, {}, 20000.0) == pytest.approx(0.05)
    assert fs._fcf_yield({"fcfPerShareTTM": 5.0}, {"shareOutstanding": 100.0}, 20000.0) == pytest.approx(0.025)
    assert fs._fcf_yield({"fcfPerShareTTM": 5.0}, {}, 20000.0) is None
    assert fs._fcf_yield({}, {}, 20000.0) is None and fs._fcf_yield({"freeCashFlowTTM": 1.0}, {}, None) is None


def test_missing_short_interest_is_none_not_zero(monkeypatch):
    from thematic.lib import finnhub_client as fh
    monkeypatch.setattr(fh, "_get", lambda *a, **k: {})
    assert fh.get_short_interest("X") is None
    monkeypatch.setattr(fh, "_get", lambda *a, **k: [{"shortPercentOfFloat": 0.05}])
    assert fh.get_short_interest("X") == pytest.approx(5.0)


# ── N19 ─────────────────────────────────────────────────────────────────────────────────────
def test_timing_overbought_warning_also_fires_on_ema_distance():
    from thematic import timing_validator as tv
    import inspect
    src = inspect.getsource(tv)
    assert "if rsi > 75 or distance_ema > 0.30:" in src and "if rsi > 75:\n        distance_ema" not in src


def test_finnhub_403_returns_immediately_without_waiting(monkeypatch):
    from thematic.lib import finnhub_client as fh
    calls, slept = [], []

    class R:
        status_code = 403

        def raise_for_status(self):
            raise AssertionError("nicht erreicht")

    monkeypatch.setattr(fh, "FINNHUB_KEY", "k")
    monkeypatch.setattr(fh, "_rate_limit", lambda: None)
    monkeypatch.setattr(fh.requests, "get", lambda *a, **k: calls.append(1) or R())
    monkeypatch.setattr(fh.time, "sleep", lambda s: slept.append(s))
    assert fh._get("/stock/metric") == {} and len(calls) == 1 and slept == []


def test_embedding_dimension_mismatch_is_an_explicit_error():
    from thematic.lib import embedding_client as ec
    assert ec.cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    with pytest.raises(ValueError, match="Dimensionen"):
        ec.cosine_similarity([1.0] * 384, [1.0] * 1536)


def test_universe_manager_backs_up_before_overwriting(monkeypatch, tmp_path):
    from thematic import universe_manager as um
    src = open(um.__file__, encoding="utf-8").read()
    assert "shutil.copy2(UNIVERSE_PATH" in src and src.index("shutil.copy2(UNIVERSE_PATH") < src.index("atomic_write_json(UNIVERSE_PATH")


def _llm_result(monkeypatch, content, finish, json_mode=True):
    from thematic.lib import llm_client as lc

    class R:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": content}, "finish_reason": finish}], "usage": {}}

    monkeypatch.setattr(lc, "OPENROUTER_KEY", "k")
    monkeypatch.setattr(lc.requests, "post", lambda *a, **k: R())
    return lc.call_llm("p", "m", json_mode=json_mode)


def test_llm_empty_content_is_an_error(monkeypatch):
    r = _llm_result(monkeypatch, None, "stop")
    assert r["ok"] is False and "leere Antwort" in r["error"]


def test_llm_truncated_json_is_an_error_but_truncated_text_is_flagged(monkeypatch):
    assert _llm_result(monkeypatch, '{"a": 1', "length", json_mode=True)["ok"] is False
    r = _llm_result(monkeypatch, "Text", "length", json_mode=False)
    assert r["ok"] is True and r["truncated"] is True
    assert _llm_result(monkeypatch, "{}", "stop")["truncated"] is False


def test_thesis_prompt_separates_example_from_data_and_uses_config_keys():
    text = open(os.path.join(ROOT, "thematic", "prompts", "thesis_check_v1.md"), encoding="utf-8").read()
    assert text.index("{prediction_markets_with_prices_and_deltas}") > text.index("KEINE echten Daten")
    cfg = json.load(open(os.path.join(ROOT, "thematic", "config", "thematic_config.json"), encoding="utf-8"))
    for key in cfg["pm_conviction_multipliers"]:
        assert key in text.split("pm_signal_assessment")[1].split("\n")[0]
