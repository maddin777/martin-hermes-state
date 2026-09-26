import pytest
import requests

from thematic.lib import jev_client

# Echte Antwort vom 23.09.2026 (Decisions API, ~typesafe/jev-latest)
REAL = {
    "model": "typesafe/jev-1.13-20260917",
    "answers": {
        "bearish": {"type": "noul", "noul": 0.97},
        "sent": {"type": "choice", "choice": "bearish",
                 "probabilities": {"bullish": 0, "bearish": 1, "neutral": 0}, "confidence": 1},
        "strength": {"type": "score", "score": 1.91,
                     "legend": {"0": "weak opinion", "1": "moderate opinion", "2": "strong opinion"},
                     "probabilities": {"0": 0, "1": 0.08, "2": 0.92}, "confidence": 0.87},
    },
    "usage": {"input_tokens": 431, "output_tokens": 75, "cost": 0.000018102},
    "id": "gen-dec-1", "provider": "TypeSafe",
}


class Resp:
    def __init__(self, status=200, body=None, text=""):
        self.status_code = status
        self._body = body
        self.text = text or str(body)

    def json(self):
        if self._body is None:
            raise ValueError("kein JSON")
        return self._body


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(jev_client.time, "sleep", lambda _s: None)


def _post(monkeypatch, responses):
    it = iter(responses)
    seen = []

    def fake(url, headers=None, json=None, timeout=None):
        seen.append({"url": url, "json": json, "timeout": timeout})
        r = next(it)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(jev_client.requests, "post", fake)
    return seen


def test_decide_returns_parsed_answer_and_sends_expected_payload(monkeypatch):
    seen = _post(monkeypatch, [Resp(200, REAL)])
    out = jev_client.decide({"company": "Tesla"}, {"sent": {"type": "choice"}})
    assert out == REAL
    assert seen[0]["url"] == "https://openrouter.ai/api/alpha/decisions"
    assert seen[0]["json"]["model"] == "typesafe/jev-1.13-20260917"   # festgeschrieben, nicht der Alias
    assert seen[0]["json"]["state"] == {"company": "Tesla"}


def test_decide_without_key_returns_none_and_makes_no_request(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    seen = _post(monkeypatch, [])
    assert jev_client.decide({}, {}) is None
    assert seen == []


def test_decide_provider_blocked_404_is_not_retried(monkeypatch):
    seen = _post(monkeypatch, [Resp(404, {"error": "No allowed providers"})])
    assert jev_client.decide({}, {}) is None
    assert len(seen) == 1


def test_decide_retries_429_then_succeeds(monkeypatch):
    seen = _post(monkeypatch, [Resp(429, {}), Resp(503, {}), Resp(200, REAL)])
    assert jev_client.decide({}, {}) == REAL
    assert len(seen) == 3


def test_decide_gives_up_after_bounded_retries(monkeypatch):
    seen = _post(monkeypatch, [Resp(500, {})] * 5)
    assert jev_client.decide({}, {}) is None
    assert len(seen) == jev_client.MAX_RETRIES + 1


def test_decide_network_error_is_swallowed(monkeypatch):
    _post(monkeypatch, [requests.ConnectionError("x")] * 3)
    assert jev_client.decide({}, {}) is None


@pytest.mark.parametrize("bad", [Resp(200, None), Resp(200, []), Resp(200, {"answers": "x"}),
                                 Resp(200, {"no": "answers"})])
def test_decide_rejects_malformed_bodies(monkeypatch, bad):
    _post(monkeypatch, [bad])
    assert jev_client.decide({}, {}) is None


def test_usage_of_reads_tokens_and_cost_and_tolerates_missing():
    assert jev_client.usage_of(REAL) == (431, 75, 0.000018102)
    assert jev_client.usage_of({}) == (0, 0, 0.0)
    assert jev_client.usage_of(None) == (0, 0, 0.0)


def test_choice_of_parses_real_answer_and_validates_options():
    label, conf, probs = jev_client.choice_of(REAL, "sent", ["bullish", "bearish", "neutral"])
    assert (label, conf) == ("bearish", 1.0)
    assert probs["bearish"] == 1.0
    assert jev_client.choice_of(REAL, "sent", ["buy", "sell"]) is None
    assert jev_client.choice_of(REAL, "fehlt") is None
    assert jev_client.choice_of(REAL, "bearish") is None      # noul, kein choice


def test_noul_of_parses_probability_and_rejects_out_of_range():
    assert jev_client.noul_of(REAL, "bearish") == 0.97
    assert jev_client.noul_of(REAL, "sent") is None
    assert jev_client.noul_of({"answers": {"x": {"noul": 1.4}}}, "x") is None


# jev-pin-20260925
def test_model_is_pinned_not_the_latest_alias():
    assert jev_client.JEV_MODEL == "typesafe/jev-1.13-20260917"
    assert "latest" not in jev_client.JEV_MODEL


def test_model_of():
    assert jev_client.model_of(REAL) == "typesafe/jev-1.13-20260917"
    assert jev_client.model_of({"answers": {}}) == ""
    assert jev_client.model_of(None) == ""
