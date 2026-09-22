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
        return {"companies": [{"name": chunk, "context_snippet": chunk}], "market_outlook": "neutral", "key_themes": []}

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
        return {"companies": [{"name": name, "context_snippet": chunk}], "market_outlook": "neutral", "key_themes": ["theme"]}

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
        return {"companies": [{"name": chunk}], "market_outlook": "neutral", "key_themes": []}

    monkeypatch.setattr(extractor, "call_scout", fake_scout)
    chunks = [str(i) for i in range(6)]

    start = time.perf_counter()
    extractor._run_scout_chunks(chunks, "c", "t", "d", max_workers=1)
    serial = time.perf_counter() - start
    start = time.perf_counter()
    extractor._run_scout_chunks(chunks, "c", "t", "d", max_workers=3)
    parallel = time.perf_counter() - start

    assert parallel < serial * 0.6, (serial, parallel)
