import json
import sys
from datetime import date, datetime
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import shadow_selection as ss  # noqa: E402
from thematic.lib import jev_client as jc  # noqa: E402
import roles.budget as budget  # noqa: E402

NEWS = [{"when": "this week", "headline": "Fox agrees to buy Roku", "summary": "cash and stock deal"}]


def picks():
    return [{"ticker": "ROKU", "name": "Roku", "direction": "LONG", "score": 4.6, "rationale": "tv: a"},
            {"ticker": "BRK-B", "name": "Berkshire", "direction": "LONG", "score": 4.5, "rationale": "tv: b"}]


def resp(label="acquisition_pending", p_none=0.01, tokens=100):
    probs = {k: 0.0 for k in ss.JEV_VETO_CATS}
    probs["none"] = p_none
    if label != "none":
        probs[label] = 1.0 - p_none
    return {"answers": {"event": {"type": "choice", "choice": label, "probabilities": probs, "confidence": 0.9}},
            "usage": {"input_tokens": tokens, "output_tokens": 0, "cost": 0.00001}, "model": jc.JEV_MODEL}


def forbid(*_a, **_k):
    raise AssertionError("darf nicht aufgerufen werden")


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("JEV_TV_VETO", "on")
    monkeypatch.setattr(ss, "tv_screener_picks", picks)


def test_switch_default_off_calls_nothing(monkeypatch):
    monkeypatch.delenv("JEV_TV_VETO", raising=False)
    monkeypatch.setattr(ss, "tv_screener_picks", picks)
    monkeypatch.setattr(ss, "_veto_news", forbid)
    monkeypatch.setattr(jc, "decide", forbid)
    assert ss.tv_screener_picks_annotated() == picks()


def test_unknown_switch_value_is_off(monkeypatch):
    monkeypatch.setenv("JEV_TV_VETO", "shadow")
    assert not ss._jev_veto_enabled()


def test_annotation_keeps_selection_order_and_scores(on, monkeypatch):
    monkeypatch.setattr(ss, "_veto_news", lambda t, d: NEWS)
    monkeypatch.setattr(jc, "decide", lambda s, q, timeout=60: resp())
    out = ss.tv_screener_picks_annotated()
    assert [(p["ticker"], p["score"]) for p in out] == [(p["ticker"], p["score"]) for p in picks()]
    assert out[0]["rationale"] == f"tv: a | veto=acquisition_pending;p=0.99;m={jc.JEV_MODEL}"


def test_none_label_gives_low_p(on, monkeypatch):
    monkeypatch.setattr(ss, "_veto_news", lambda t, d: NEWS)
    monkeypatch.setattr(jc, "decide", lambda s, q, timeout=60: resp("none", p_none=0.97))
    out = ss.tv_screener_picks_annotated()
    assert out[1]["rationale"].endswith("veto=none;p=0.03;m=" + jc.JEV_MODEL)


def test_no_news_skips_jev(on, monkeypatch):
    monkeypatch.setattr(ss, "_veto_news", lambda t, d: [])
    monkeypatch.setattr(jc, "decide", forbid)
    assert all(p["rationale"].endswith("| veto=no_news") for p in ss.tv_screener_picks_annotated())


def test_news_error_and_jev_failure_are_fail_open(on, monkeypatch):
    monkeypatch.setattr(ss, "_veto_news", lambda t, d: None if t == "ROKU" else NEWS)
    monkeypatch.setattr(jc, "decide", lambda s, q, timeout=60: None)
    out = ss.tv_screener_picks_annotated()
    assert [p["rationale"] for p in out] == ["tv: a | veto=n/a", "tv: b | veto=n/a"]


def test_exception_returns_unannotated_picks(on, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("kaputt")
    monkeypatch.setattr(ss, "_veto_news", boom)
    assert ss.tv_screener_picks_annotated() == picks()


def test_booking_only_with_connection(on, monkeypatch):
    calls = []
    monkeypatch.setattr(budget, "record_spend", lambda *a: calls.append(a))
    monkeypatch.setattr(ss, "_veto_news", lambda t, d: NEWS)
    monkeypatch.setattr(jc, "decide", lambda s, q, timeout=60: resp(tokens=150))
    ss.tv_screener_picks_annotated()                  # Trockenlauf: keine Buchung
    assert calls == []
    con = object()
    ss.tv_screener_picks_annotated(con)
    assert len(calls) == 1
    c, role, _day, t_in, t_out, model = calls[0]
    assert (c, role, t_in, t_out, model) == (con, "jev_tv_veto", 300, 0, jc.JEV_MODEL)


def test_no_booking_without_tokens(on, monkeypatch):
    calls = []
    monkeypatch.setattr(budget, "record_spend", lambda *a: calls.append(a))
    monkeypatch.setattr(ss, "_veto_news", lambda t, d: [])
    ss.tv_screener_picks_annotated(object())
    assert calls == []


def test_state_contains_only_text():
    st = ss._veto_state(picks()[0], NEWS)
    assert set(st) == {"task", "company", "ticker", "news"}
    assert "4.6" not in json.dumps(st)


def test_veto_news_symbol_dedup_order_and_limit(monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "x")
    today = date(2026, 9, 29)
    ts = lambda d: datetime(2026, 9, d, 12).timestamp()  # noqa: E731
    raw = [{"datetime": ts(20), "headline": "Old one", "summary": "s"},
           {"datetime": ts(28), "headline": "New one", "summary": "s"},
           {"datetime": ts(27), "headline": "new ONE", "summary": "dup"},
           {"datetime": ts(26), "headline": "", "summary": "leer"}]
    seen = {}

    class R:
        status_code = 200

        def json(self):
            return raw

    def fake_get(url, params=None, timeout=None):
        seen.update(params)
        return R()

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(ss, "JEV_VETO_MAX_NEWS", 5)
    items = ss._veto_news("BRK-B", today)
    assert seen["symbol"] == "BRK.B" and seen["from"] == "2026-09-15"
    assert [(i["when"], i["headline"]) for i in items] == [("this week", "New one"), ("last week", "Old one")]


def test_veto_news_error_is_none(monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "x")

    class R:
        status_code = 429

        def json(self):
            return {"error": "limit"}

    monkeypatch.setattr(requests, "get", lambda *a, **k: R())
    assert ss._veto_news("ROKU", date(2026, 9, 29)) is None
