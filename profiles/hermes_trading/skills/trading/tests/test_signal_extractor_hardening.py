import concurrent.futures
import json
import sqlite3
import threading
import time

import pytest
import requests

from scripts import signal_extractor as extractor


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("```json\n{\"companies\": [], \"market_outlook\": \"neutral\", \"key_themes\": []}\n```", "neutral"),
        ("Analyse:\n{\"companies\": [], \"market_outlook\": \"bullish\", \"key_themes\": []}\nEnde", "bullish"),
        ("Vorwort {ignorieren} danach {\"companies\": [], \"market_outlook\": \"bearish\", \"key_themes\": [],}", "bearish"),
        ("{\"companies\": [{\"name\": \"Macy's\",}], \"market_outlook\": \"neutral\", \"key_themes\": [],}", "neutral"),
    ],
)
def test_try_parse_accepts_wrappers_embedded_json_and_trailing_commas(raw, expected):
    assert extractor._try_parse(raw)["market_outlook"] == expected


def test_request_timeout_is_configurable_and_defaults_above_sixty(monkeypatch):
    assert extractor.REQUEST_TIMEOUT >= 90
    monkeypatch.setenv("REQUEST_TIMEOUT", "95")
    assert extractor._env_int("REQUEST_TIMEOUT", 120, minimum=30, maximum=300) == 95
    seen = {}

    class Response:
        status_code = 200
        headers = {}

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "{}"}}], "usage": {}}

    def fake_post(*args, **kwargs):
        seen["timeout"] = kwargs["timeout"]
        return Response()

    monkeypatch.setattr(extractor.requests, "post", fake_post)
    extractor._call("model", "system", "user")
    assert seen["timeout"] == extractor.REQUEST_TIMEOUT


def test_call_retries_429_and_5xx_with_bounded_attempts(monkeypatch):
    statuses = iter([429, 503, 200])
    calls = []

    class Response:
        headers = {}

        def __init__(self, status):
            self.status_code = status

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError(str(self.status_code), response=self)

        def json(self):
            return {"choices": [{"message": {"content": "{}"}}], "usage": {}}

    def fake_post(*args, **kwargs):
        status = next(statuses)
        calls.append(status)
        return Response(status)

    monkeypatch.setattr(extractor.requests, "post", fake_post)
    monkeypatch.setattr(extractor.time, "sleep", lambda _seconds: None)
    assert extractor._call("model", "system", "user")[0] == "{}"
    assert calls == [429, 503, 200]


def test_scout_chunks_run_in_parallel_with_worker_cap_and_stable_order(monkeypatch):
    active = 0
    peak = 0
    lock = threading.Lock()

    def fake_scout(chunk, *_args):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.03)
        with lock:
            active -= 1
        return {"companies": [{"name": chunk, "context_snippet": chunk}], "market_outlook": "neutral", "key_themes": []}, 0, 0

    monkeypatch.setattr(extractor, "call_scout", fake_scout)
    chunks = [f"chunk-{i}" for i in range(6)]
    results = extractor._run_scout_chunks(chunks, "channel", "title", "20260827", max_workers=3)

    assert 1 < peak <= 3
    assert [r["companies"][0]["name"] for r in results] == chunks


def test_analyze_keeps_output_contract_and_waits_for_scouts_before_analyst(monkeypatch):
    scout_done = threading.Event()
    scout_count = 0
    lock = threading.Lock()

    def fake_scout(chunk, _channel, _title, _date, chunk_num, _total):
        nonlocal scout_count
        with lock:
            scout_count += 1
            if scout_count == 3:
                scout_done.set()
        name = f"company-{chunk_num}"
        return {"companies": [{"name": name, "context_snippet": chunk}], "market_outlook": "neutral", "key_themes": ["theme"]}, 0, 0

    def fake_analyst(_con, companies, *_args):
        assert scout_done.is_set()
        return [{"name": c["name"], "sentiment": "neutral", "strength": "weak", "reason": "", "mentioned_price": None, "price_target": None, "action_hint": "hold", "catalyst": "none"} for c in companies]

    monkeypatch.setattr(extractor, "CHUNK_SIZE", 10)
    monkeypatch.setattr(extractor, "OVERLAP", 0)
    monkeypatch.setattr(extractor, "call_scout", fake_scout)
    monkeypatch.setattr(extractor, "call_analyst", fake_analyst)
    monkeypatch.setattr(extractor, "EXTRACTOR_MODE", "two_pass")

    result = extractor.analyze("a" * 30, "channel", "title", "20260827", con=sqlite3.connect(":memory:"))
    assert set(result) == {"companies", "market_outlook", "key_themes"}
    assert len(result["companies"]) == 3
    assert result["market_outlook"] == "neutral"
    assert result["key_themes"] == ["theme"]


def test_parallel_snapshot_is_measurably_faster_than_serial(monkeypatch):
    def fake_scout(chunk, *_args):
        time.sleep(0.04)
        return {"companies": [{"name": chunk}], "market_outlook": "neutral", "key_themes": []}, 0, 0

    monkeypatch.setattr(extractor, "call_scout", fake_scout)
    chunks = [str(i) for i in range(6)]

    start = time.perf_counter()
    extractor._run_scout_chunks(chunks, "c", "t", "d", max_workers=1)
    serial = time.perf_counter() - start
    start = time.perf_counter()
    extractor._run_scout_chunks(chunks, "c", "t", "d", max_workers=3)
    parallel = time.perf_counter() - start

    assert parallel < serial * 0.6, (serial, parallel)


# ── Abschneidung (finish_reason=length), 21.09.2026 ─────────────────────────

def _resp(content, finish="stop", usage=None):
    class Response:
        status_code = 200
        headers = {}

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": content},
                                 "finish_reason": finish}],
                    "usage": usage if usage is not None else {}}

    return Response()


def _install(monkeypatch, responses):
    """Fake requests.post: liefert die Antworten der Reihe nach, merkt sich die Modelle."""
    seen = []
    it = iter(responses)

    def fake_post(*args, **kwargs):
        seen.append(kwargs["json"]["model"])
        return next(it)

    monkeypatch.setattr(extractor.requests, "post", fake_post)
    monkeypatch.setattr(extractor.time, "sleep", lambda _s: None)
    return seen


_GOOD = '{"companies": [], "market_outlook": "neutral", "key_themes": []}'
_CUT_USAGE = {"prompt_tokens": 100, "completion_tokens": 4000,
              "completion_tokens_details": {"reasoning_tokens": 4000}}


def test_call_raises_truncated_on_finish_length_and_is_not_retried(monkeypatch):
    seen = _install(monkeypatch, [_resp(None, "length", _CUT_USAGE)] * 3)
    with pytest.raises(extractor._Truncated) as exc:
        extractor._call("m", "s", "u")
    assert len(seen) == 1                     # nicht als transienter KeyError wiederholt
    assert "4000" in exc.value.detail
    assert (exc.value.tokens_in, exc.value.tokens_out) == (100, 4000)


def test_call_treats_partial_content_with_finish_length_as_truncated(monkeypatch):
    partial = '{"companies": [{"name": "Nvidia", "rough_sentiment": "bullish"}, {"name": "Tes'
    _install(monkeypatch, [_resp(partial, "length", _CUT_USAGE)])
    with pytest.raises(extractor._Truncated):
        extractor._call("m", "s", "u")


def test_call_still_retries_empty_content_without_finish_length(monkeypatch):
    seen = _install(monkeypatch, [_resp(None, "stop")] * extractor.REQUEST_MAX_ATTEMPTS)
    with pytest.raises(KeyError):
        extractor._call("m", "s", "u")
    assert len(seen) == extractor.REQUEST_MAX_ATTEMPTS


def test_cascade_goes_straight_to_fallback_on_truncation(monkeypatch):
    seen = _install(monkeypatch, [
        _resp(None, "length", _CUT_USAGE),
        _resp(_GOOD, "stop", {"prompt_tokens": 50, "completion_tokens": 30}),
    ])
    parsed, t_in, t_out = extractor._call_cascade("s", "u")
    assert seen == [extractor.MODEL, extractor.FALLBACK_MODEL]   # KEIN zweiter Versuch mit MODEL
    assert parsed["market_outlook"] == "neutral"
    assert (t_in, t_out) == (150, 4030)                          # Budget zaehlt beide Antworten


def test_cascade_keeps_three_step_escalation_for_plain_json_errors(monkeypatch):
    seen = _install(monkeypatch, [_resp("kein json", "stop"),
                                  _resp("immer noch nicht", "stop"),
                                  _resp(_GOOD, "stop")])
    parsed, _ti, _to = extractor._call_cascade("s", "u")
    assert seen == [extractor.MODEL, extractor.MODEL, extractor.FALLBACK_MODEL]
    assert parsed["market_outlook"] == "neutral"


def test_cascade_returns_default_when_fallback_is_truncated_too(monkeypatch):
    seen = _install(monkeypatch, [_resp(None, "length"), _resp(None, "length")])
    parsed, _ti, _to = extractor._call_cascade("s", "u", default={"companies": []})
    assert parsed == {"companies": []}
    assert seen == [extractor.MODEL, extractor.FALLBACK_MODEL]   # keine Endlosschleife


# ── Scout-Reasoning (effort=low), 22.09.2026 ────────────────────────────────

def _install_payloads(monkeypatch, responses):
    """Fake requests.post: merkt sich die kompletten Payloads, liefert Antworten der Reihe nach."""
    payloads = []
    it = iter(responses)

    def fake_post(*args, **kwargs):
        payloads.append(kwargs["json"])
        return next(it)

    monkeypatch.setattr(extractor.requests, "post", fake_post)
    monkeypatch.setattr(extractor.time, "sleep", lambda _s: None)
    return payloads


def test_call_merges_extra_body_into_payload(monkeypatch):
    payloads = _install_payloads(monkeypatch, [_resp("{}", "stop")])
    extractor._call("m", "s", "u", extra_body={"reasoning": {"effort": "low"}})
    assert payloads[0]["reasoning"] == {"effort": "low"}
    assert payloads[0]["model"] == "m" and payloads[0]["max_tokens"] == 4000


def test_call_without_extra_body_sends_no_reasoning_field(monkeypatch):
    payloads = _install_payloads(monkeypatch, [_resp("{}", "stop")])
    extractor._call("m", "s", "u")
    assert "reasoning" not in payloads[0]


def test_cascade_sends_primary_extra_to_primary_attempts_only(monkeypatch):
    payloads = _install_payloads(monkeypatch, [_resp("kein json", "stop"),
                                               _resp("noch nicht", "stop"),
                                               _resp(_GOOD, "stop")])
    extractor._call_cascade("s", "u", primary_extra={"reasoning": {"effort": "low"}})
    assert [p["model"] for p in payloads] == [extractor.MODEL, extractor.MODEL,
                                              extractor.FALLBACK_MODEL]
    assert payloads[0]["reasoning"] == {"effort": "low"}
    assert payloads[1]["reasoning"] == {"effort": "low"}
    assert "reasoning" not in payloads[2]          # gpt-4o-mini bekommt den Parameter nie


def test_cascade_fallback_after_truncation_has_no_reasoning_field(monkeypatch):
    payloads = _install_payloads(monkeypatch, [_resp(None, "length", _CUT_USAGE),
                                               _resp(_GOOD, "stop")])
    extractor._call_cascade("s", "u", primary_extra={"reasoning": {"effort": "low"}})
    assert "reasoning" in payloads[0]
    assert "reasoning" not in payloads[1]


def test_cascade_default_leaves_other_callers_untouched(monkeypatch):
    payloads = _install_payloads(monkeypatch, [_resp(_GOOD, "stop")])
    extractor._call_cascade("s", "u")              # Analyst/Legacy rufen so auf
    assert "reasoning" not in payloads[0]


def test_scout_reasoning_extra_defaults_to_low_and_can_be_switched_off(monkeypatch):
    monkeypatch.delenv("SCOUT_REASONING_EFFORT", raising=False)
    assert extractor._scout_reasoning_extra() == {"reasoning": {"effort": "low"}}
    assert extractor._scout_reasoning_label() == "low"
    monkeypatch.setenv("SCOUT_REASONING_EFFORT", " HIGH ")
    assert extractor._scout_reasoning_extra() == {"reasoning": {"effort": "high"}}
    for off in ("off", "", "aus", "quatsch"):
        monkeypatch.setenv("SCOUT_REASONING_EFFORT", off)
        assert extractor._scout_reasoning_extra() is None
        assert extractor._scout_reasoning_label() == "voll"


def test_call_scout_passes_reasoning_only_via_primary_extra(monkeypatch):
    captured = {}

    def fake_cascade(system_prompt, user_content, **kwargs):
        captured.update(kwargs)
        return {"companies": []}, 0, 0

    monkeypatch.delenv("SCOUT_REASONING_EFFORT", raising=False)
    monkeypatch.setattr(extractor, "_call_cascade", fake_cascade)
    extractor.call_scout("text", "kanal", "titel", "20260922", 1, 1)
    assert captured["primary_extra"] == {"reasoning": {"effort": "low"}}


# ── Analyst-Reasoning (aus), 22.09.2026 ─────────────────────────────────────

def test_analyst_reasoning_extra_defaults_to_off_and_can_be_switched(monkeypatch):
    monkeypatch.delenv("ANALYST_REASONING", raising=False)
    assert extractor._analyst_reasoning_extra() == {"reasoning": {"enabled": False}}
    assert extractor._analyst_reasoning_label() == "aus"
    monkeypatch.setenv("ANALYST_REASONING", " Low ")
    assert extractor._analyst_reasoning_extra() == {"reasoning": {"effort": "low"}}
    assert extractor._analyst_reasoning_label() == "low"
    monkeypatch.setenv("ANALYST_REASONING", "AUS")
    assert extractor._analyst_reasoning_extra() == {"reasoning": {"enabled": False}}


def test_analyst_reasoning_full_and_unknown_values_keep_previous_behaviour(monkeypatch):
    for value in ("full", "voll", "", "quatsch", "offf"):
        monkeypatch.setenv("ANALYST_REASONING", value)
        assert extractor._analyst_reasoning_extra() is None      # Tippfehler aendert nie still etwas
        assert extractor._analyst_reasoning_label() == "voll"


def _stub_analyst_environment(monkeypatch, analyst_model):
    """call_analyst ohne Budgetbuchung/DB: Budget-Modul und Modellwahl ersetzen."""
    import roles.budget as budget
    from thematic.lib import llm_client
    monkeypatch.setattr(budget, "check_and_reserve", lambda *a, **k: True)
    monkeypatch.setattr(budget, "record_spend", lambda *a, **k: None)
    monkeypatch.setattr(llm_client, "get_model", lambda role: analyst_model)
    captured = {}

    def fake_cascade(system_prompt, user_content, **kwargs):
        captured.update(kwargs)
        return {"companies": [{"name": "Nvidia", "sentiment": "bullish", "strength": "weak",
                               "action_hint": "hold", "catalyst": "none"}]}, 0, 0

    monkeypatch.setattr(extractor, "_call_cascade", fake_cascade)
    return captured


_ONE_COMPANY = [{"name": "Nvidia", "snippets": ["stark"], "rough_sentiment": "bullish"}]


def test_call_analyst_sends_reasoning_off_to_the_measured_primary_model(monkeypatch):
    monkeypatch.delenv("ANALYST_REASONING", raising=False)
    captured = _stub_analyst_environment(monkeypatch, extractor.MODEL)
    extractor.call_analyst(None, _ONE_COMPANY, "kanal", "titel", "20260922")
    assert captured["primary_extra"] == {"reasoning": {"enabled": False}}
    assert captured["max_tokens"] == 4000 and captured["primary_model"] == extractor.MODEL


def test_call_analyst_does_not_send_reasoning_to_an_unmeasured_model(monkeypatch):
    monkeypatch.delenv("ANALYST_REASONING", raising=False)
    captured = _stub_analyst_environment(monkeypatch, "some/other-model")
    extractor.call_analyst(None, _ONE_COMPANY, "kanal", "titel", "20260922")
    assert captured["primary_extra"] is None


def test_call_analyst_full_reasoning_switch_restores_old_behaviour(monkeypatch):
    monkeypatch.setenv("ANALYST_REASONING", "full")
    captured = _stub_analyst_environment(monkeypatch, extractor.MODEL)
    extractor.call_analyst(None, _ONE_COMPANY, "kanal", "titel", "20260922")
    assert captured["primary_extra"] is None


# ── Analyst-Grenze waechst mit der Firmenzahl, 22.09.2026 ───────────────────

def test_analyst_max_tokens_keeps_floor_for_typical_videos_and_scales_for_big_ones():
    f = extractor._analyst_max_tokens
    assert [f(0), f(1), f(10), f(27)] == [4000, 4000, 4000, 4010]
    assert f(20) == 4000                     # P95 der Videos: unveraendert
    assert f(48) == 6740                     # das gemessene 48-Firmen-Video
    assert f(52) == 7260                     # groesster Wert im Produktionslog
    assert f(500) == 16000                   # Deckel
    assert f(-3) == 4000                     # nie unter den Festwert


def test_analyst_max_tokens_covers_measured_tokens_per_company_with_margin():
    per_company_max = 101                    # gemessenes Maximum (Reasoning aus)
    for n in (30, 44, 48, 52, 80):
        assert extractor._analyst_max_tokens(n) >= per_company_max * n


def test_call_analyst_passes_scaled_max_tokens_and_keeps_4000_for_small_videos(monkeypatch):
    monkeypatch.delenv("ANALYST_REASONING", raising=False)
    captured = _stub_analyst_environment(monkeypatch, extractor.MODEL)
    extractor.call_analyst(None, _ONE_COMPANY, "kanal", "titel", "20260922")
    assert captured["max_tokens"] == 4000
    big = [{"name": "Firma %d" % i, "snippets": ["x"], "rough_sentiment": "neutral"}
           for i in range(48)]
    extractor.call_analyst(None, big, "kanal", "titel", "20260922")
    assert captured["max_tokens"] == 6740


# ── Scout-Buchung ins llm_budget_log, 23.09.2026 ────────────────────────────
# call_scout() gibt wie call_analyst()/_call_cascade() jetzt (parsed, t_in, t_out)
# zurueck. Gebucht wird NICHT in call_scout() selbst (laeuft im Worker-Thread des
# ThreadPoolExecutor -- db_connect() ist nicht thread-sicher), sondern gesammelt
# in _run_scout_chunks() NACH pool.map() (Haupt-Thread), als EINE Buchung je Video.

def test_call_scout_returns_token_counts_from_cascade(monkeypatch):
    monkeypatch.setattr(extractor, "_call_cascade",
                        lambda *a, **k: ({"companies": []}, 11, 22))
    parsed, t_in, t_out = extractor.call_scout("text", "kanal", "titel",
                                               "20260922", 1, 1)
    assert (parsed, t_in, t_out) == ({"companies": []}, 11, 22)


def test_run_scout_chunks_books_summed_tokens_once_after_pool(monkeypatch):
    import roles.budget as budget
    # Fake-Antwort haengt am chunk_num-Argument, nicht an der Aufrufreihenfolge:
    # die Chunks laufen parallel, eine gemeinsame pop-Liste waere ein Race.
    responses = {
        1: ({"companies": [{"name": "A"}]}, 10, 20),
        2: ({"companies": [{"name": "B"}]}, 5, 7),
    }

    def fake_scout(chunk, channel, title, date_str, chunk_num, total_chunks):
        return responses[chunk_num]

    monkeypatch.setattr(extractor, "call_scout", fake_scout)
    booked = {}

    def fake_record_spend(con, role, today, t_in, t_out, model):
        booked.update(con=con, role=role, t_in=t_in, t_out=t_out, model=model)

    monkeypatch.setattr(budget, "record_spend", fake_record_spend)
    fake_con = object()
    results = extractor._run_scout_chunks(["c1", "c2"], "kanal", "titel",
                                          "20260922", con=fake_con)
    assert results == [{"companies": [{"name": "A"}]},
                       {"companies": [{"name": "B"}]}]
    assert booked == {"con": fake_con, "role": "extractor_scout",
                      "t_in": 15, "t_out": 27, "model": extractor.MODEL}


def test_run_scout_chunks_without_con_books_nothing(monkeypatch):
    import roles.budget as budget
    monkeypatch.setattr(extractor, "call_scout",
                        lambda *a, **k: ({"companies": []}, 10, 20))
    booked = []
    monkeypatch.setattr(budget, "record_spend", lambda *a, **k: booked.append(1))
    extractor._run_scout_chunks(["c1"], "kanal", "titel", "20260922")
    assert booked == []
