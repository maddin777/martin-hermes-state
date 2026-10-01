"""Social Scanner: K5 (Tweet-Datum), K6 (leere/abweichende LLM-Antworten), M16 (Feed-Timeout).

Befunde der Code-Pruefung (30.09.2026): 4.748 von 4.751 Tweets mit published_at 1900; ein leeres LLM-Ergebnis
beendete den ganzen Feed (1 von 4 Artikeln gespeichert); feedparser.parse(url) ohne Timeout.
Alle Netzaufrufe sind gemockt.
"""
import os
import sqlite3
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

try:
    import feedparser  # noqa: F401
except ImportError:    # im Projekt-venv nicht installiert (nur im Cron-Interpreter)
    fp = types.ModuleType("feedparser")
    fp.parse = lambda *a, **k: types.SimpleNamespace(entries=[])
    fp.USER_AGENT = "test"
    sys.modules["feedparser"] = fp

from scripts import social_scanner as ss


def make_db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE external_mentions (id INTEGER PRIMARY KEY, source_type, source_name, title, content, "
                "url UNIQUE, published_at, fetched_at, companies, sentiment)")
    con.execute("CREATE TABLE watchlist_mentions (id INTEGER PRIMARY KEY, name, channel, video_id, video_title, "
                "sentiment, reason, mention_date, UNIQUE(name, channel, video_id))")
    return con


class FakeResp:
    def __init__(self, content):
        self._c = content

    def json(self):
        return {"choices": [{"message": {"content": self._c}, "finish_reason": "stop"}]}


def llm(content):
    return mock.patch.object(ss.requests, "post", side_effect=lambda *a, **k: FakeResp(content))


class TweetDateTests(unittest.TestCase):   # K5
    def test_full_twitter_format_keeps_the_year(self):
        self.assertEqual(ss.parse_tweet_date("Tue Dec 10 07:00:30 +0000 2024"), "2024-12-10 07:00")

    def test_timezone_offset_is_converted_to_utc(self):
        self.assertEqual(ss.parse_tweet_date("Tue Dec 10 09:00:30 +0200 2024"), "2024-12-10 07:00")

    def test_iso_format_is_understood(self):
        self.assertEqual(ss.parse_tweet_date("2026-09-29T14:03:05.000Z"), "2026-09-29 14:03")

    def test_garbage_falls_back_to_now_never_to_1900(self):
        for bad in ("", None, "kaputt", "Tue Sep 29 14:03:05"):
            self.assertTrue(ss.parse_tweet_date(bad).startswith(str(datetime.now(timezone.utc).year)), bad)

    def test_recent_tweet_is_stored_with_real_date_and_injected(self):
        con = make_db()
        recent = datetime.now(timezone.utc) - timedelta(hours=1)
        created = recent.strftime("%a %b %d %H:%M:%S +0000 %Y")
        resp = mock.Mock(status_code=200)
        resp.json.return_value = {"tweets": [{"id": "1", "text": "Apple steigt", "createdAt": created}]}
        acc = {"handle": "abc", "name": "Abc", "enabled": True}
        with mock.patch.dict(os.environ, {"TWITTERAPI_IO_KEY": "x"}), \
             mock.patch.object(ss.requests, "get", return_value=resp), \
             mock.patch.object(ss, "extract_companies",
                               return_value={"companies": [{"name": "Apple", "sentiment": "bullish"}],
                                             "market_outlook": "neutral"}):
            ss.fetch_twitter(con, [acc])
        row = con.execute("SELECT published_at FROM external_mentions").fetchone()
        self.assertEqual(row["published_at"], recent.strftime("%Y-%m-%d %H:%M"))
        ss.inject_into_watchlist(con)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM watchlist_mentions").fetchone()[0], 1)


class ExtractCompaniesTests(unittest.TestCase):   # K6
    def _run(self, content):
        with llm(content):
            return ss.extract_companies("Titel", "Inhalt", "Quelle")

    def test_content_none_is_a_dict_marked_as_error(self):
        r = self._run(None)
        self.assertIsInstance(r, dict)
        self.assertTrue(r.get("error"))

    def test_empty_array_is_a_valid_empty_result_not_an_error(self):
        r = self._run("[]")
        self.assertEqual(r["companies"], [])
        self.assertFalse(r.get("error"))

    def test_list_of_company_objects_is_wrapped(self):
        r = self._run('[{"name": "Nike", "sentiment": "bearish"}]')
        self.assertEqual([c["name"] for c in r["companies"]], ["Nike"])

    def test_json_fence_is_stripped(self):
        r = self._run('```json\n{"companies": [{"name": "Apple", "sentiment": "bullish"}]}\n```')
        self.assertEqual([c["name"] for c in r["companies"]], ["Apple"])
        self.assertFalse(r.get("error"))

    def test_garbage_is_an_error(self):
        self.assertTrue(self._run("Das ist kein JSON").get("error"))


class Entry:
    def __init__(self, i):
        self.published_parsed = datetime.now(timezone.utc).timetuple()
        self._d = {"title": f"T{i}", "summary": "s", "link": f"http://x/{i}"}

    def get(self, k, d=None):
        return self._d.get(k, d)


class FeedTests(unittest.TestCase):
    def _feedparser(self, n=4):
        entries = [Entry(i) for i in range(n)]
        return mock.patch.object(ss.feedparser, "parse", return_value=types.SimpleNamespace(entries=entries), create=True)

    def _http(self, **kw):
        resp = mock.Mock(content=b"<rss/>")
        resp.raise_for_status.return_value = None
        return mock.patch.object(ss.requests, "get", return_value=resp, **kw)

    def test_one_bad_article_does_not_end_the_feed(self):        # K6
        con, calls = make_db(), []

        def fake(title, content, source):
            calls.append(title)
            if title == "T1":
                return {"companies": [], "market_outlook": "neutral"}          # leer, aber gueltig
            if title == "T2":
                return {"companies": [], "market_outlook": "neutral", "error": True}
            if title == "T3":
                raise RuntimeError("Boom")
            return {"companies": [{"name": "A"}], "market_outlook": "neutral"}

        with self._feedparser(), self._http(), mock.patch.object(ss, "extract_companies", side_effect=fake):
            ss.fetch_rss_feeds(con, [{"name": "F", "url": "http://f", "enabled": True}])
        self.assertEqual(calls, ["T0", "T1", "T2", "T3"])
        stored = {r[0] for r in con.execute("SELECT title FROM external_mentions")}
        self.assertEqual(stored, {"T0", "T1"})       # T2 (LLM-Fehler) und T3 (Ausnahme) bleiben fuer den naechsten Lauf offen

    def test_list_result_from_llm_is_handled_by_the_caller(self):    # K6, defensive
        con = make_db()
        with self._feedparser(1), self._http(), mock.patch.object(ss, "extract_companies", return_value=[]):
            ss.fetch_rss_feeds(con, [{"name": "F", "url": "http://f", "enabled": True}])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM external_mentions").fetchone()[0], 1)

    def test_feed_is_fetched_with_timeout_and_parsed_from_content(self):   # M16
        con = make_db()
        with self._feedparser(0) as parse, self._http() as get:
            ss.fetch_rss_feeds(con, [{"name": "F", "url": "http://f", "enabled": True}])
        self.assertEqual(get.call_args.kwargs["timeout"], ss.FEED_TIMEOUT)
        self.assertEqual(parse.call_args.args[0], b"<rss/>")

    def test_hanging_feed_is_skipped_and_the_next_one_runs(self):        # M16
        con = make_db()
        ok = mock.Mock(content=b"<rss/>")
        ok.raise_for_status.return_value = None
        seq = [ss.requests.Timeout("hängt"), ok]
        with self._feedparser(1), mock.patch.object(ss.requests, "get", side_effect=seq), \
             mock.patch.object(ss, "extract_companies", return_value={"companies": [], "market_outlook": "neutral"}):
            ss.fetch_rss_feeds(con, [{"name": "F1", "url": "http://f1", "enabled": True},
                                     {"name": "F2", "url": "http://f2", "enabled": True}])
        self.assertEqual(con.execute("SELECT source_name FROM external_mentions").fetchone()[0], "F2")


if __name__ == "__main__":
    unittest.main()
