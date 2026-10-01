"""M17 (Tavily liefert echte News) und M19 (thesis_monitor ehrlich). Kein Netzaufruf, alle Antworten synthetisch."""
import os
import sqlite3
from unittest import mock

import pytest

from thematic.lib import tavily_client as tc
from scripts import breaking_news_monitor as bn
from scripts import thesis_monitor as tm

ROOT = os.path.dirname(os.path.dirname(__file__))

QLYS = [
    {"title": "Qualys (QLYS) beats Q3 estimates", "url": "https://n/1", "content": "Qualys reported earnings", "score": .9},
    {"title": "QLYS stock price today", "url": "https://n/2", "content": "chart page", "score": .8},
    {"title": "Best dividend stocks of 2026", "url": "https://n/3", "content": "generic list", "score": .7},
    {"title": "Fed holds rates", "url": "https://n/4", "content": "macro", "score": .6},
]


class Resp:
    status_code = 200

    def __init__(self, results):
        self._r = results

    def raise_for_status(self):
        pass

    def json(self):
        return {"results": self._r}


@pytest.fixture()
def tavily(monkeypatch):
    monkeypatch.setattr(tc, "TAVILY_KEY", "test")
    monkeypatch.setattr(tc, "MIN_INTERVAL", 0)
    payloads = []
    monkeypatch.setattr(tc.requests, "post", lambda url, json=None, timeout=None: payloads.append(json) or Resp(QLYS))
    return payloads


def test_payload_contains_topic_news_and_a_days_window(tavily):
    tc.search_news("Qualys QLYS news")
    p = tavily[0]
    assert p["topic"] == "news" and p["days"] == tc.NEWS_DAYS == 7


def test_explicit_days_is_kept(tavily):
    tc.search_news("x", days=3)
    assert tavily[0]["days"] == 3


def test_relevance_filter_drops_articles_without_name_or_ticker():
    kept = tc.filter_relevant(QLYS, ["Qualys, Inc."], "QLYS")
    assert [r["url"] for r in kept] == ["https://n/1", "https://n/2"]


def test_filter_without_names_or_ticker_keeps_everything():
    assert tc.filter_relevant(QLYS) == QLYS


def test_short_ticker_symbols_are_not_used_for_matching():
    res = [{"title": "P is a letter", "content": "x"}, {"title": "Pinterest grows", "content": "Pinterest"}]
    assert [r["title"] for r in tc.filter_relevant(res, ["Pinterest, Inc."], "P")] == ["Pinterest grows"]


def test_fetch_ticker_news_uses_company_name_and_filters(tavily):
    out = tc.fetch_ticker_news("QLYS", company_name="Qualys, Inc.")
    assert {r["url"] for r in out} == {"https://n/1", "https://n/2"}
    assert all("Qualys" in q["query"] for q in tavily)


def test_breaking_news_monitor_sends_topic_days_and_filters(monkeypatch):
    seen = []
    monkeypatch.setattr(bn, "TAVILY_KEY", "test")
    monkeypatch.setattr(bn.requests, "post", lambda url, json=None, timeout=None: seen.append(json) or Resp(QLYS))
    items = bn._fetch_news("Qualys, Inc.", "QLYS")
    assert seen[0]["topic"] == "news" and seen[0]["days"] == bn.BREAKING_NEWS_DAYS
    assert {r["url"] for r in items} == {"https://n/1", "https://n/2"}


def test_breaking_news_without_relevant_articles_gives_no_news_and_score_zero(monkeypatch):
    monkeypatch.setattr(bn, "TAVILY_KEY", "test")
    monkeypatch.setattr(bn.requests, "post", lambda *a, **k: Resp(QLYS[2:]))
    items = bn._fetch_news("Qualys, Inc.", "QLYS")
    assert items == [] and bn._score_news_sentiment(items, "Qualys")[0] == 0.0


# ── M19 ─────────────────────────────────────────────────────────────────────────────────────
def _pos_db(rows):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE positions (id INTEGER PRIMARY KEY, thesis_text TEXT, thesis_theme_id INTEGER)")
    for text, theme in rows:
        con.execute("INSERT INTO positions (thesis_text, thesis_theme_id) VALUES (?,?)", (text, theme))
    return con.execute("SELECT * FROM positions").fetchall()


def test_thesis_coverage_counts_only_real_theses():
    rows = _pos_db([(None, None), ("", None), ("Keine These dokumentiert.", None), ("KI-Boom", None), (None, 7)])
    assert tm.thesis_coverage(rows) == (2, 5)
    assert tm.thesis_coverage([]) == (0, 0)


@pytest.mark.parametrize("rel", ["scripts/thesis_monitor.py", "thematic/thesis_monitor.py"])
def test_alert_text_no_longer_claims_an_automatic_stop_change(rel):
    src = open(os.path.join(ROOT, rel), encoding="utf-8").read()
    assert "SL wurde automatisch" not in src and "kein automatischer Eingriff" in src
    assert "fetch_ticker_news(ticker, days=1)" not in src
