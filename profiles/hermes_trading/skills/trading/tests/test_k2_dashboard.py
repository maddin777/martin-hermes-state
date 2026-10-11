"""K2: Dashboard-Zugriffsschutz, Modellnamen-Whitelist, Quellen-Validierung.

Befund der Code-Pruefung (30.09.2026): Das Token stand als verstecktes Feld in 252 Formularen jeder
GET-Seite; POSTs aenderten sources.json und ueber /thematic/config/save beliebige LLM-Modellnamen.
Der Test startet den Handler lokal auf einem freien Port; alle Schreibzugriffe sind abgefangen.
"""
import http.client
import os
import sys
import threading
import unittest
from http.server import HTTPServer
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from scripts import dashboard as db
import dashboard_thematic as dth

TOKEN = "testtoken123"
PAGE = ('<html><body><h1>Dashboard</h1>'
        '<form method="POST" action="/sources/rss/add"><input name="name"></form>'
        '<form method="POST" action="/thematic/config/save"><input name="llm_committee_bull"></form>'
        '</body></html>')
THEMATIC_CFG = {
    "llm_models": {"committee_bull": "deepseek/deepseek-v4-pro", "devils_advocate": "deepseek/deepseek-v4.1-flash"},
    "thresholds": {"min_score": 0.5},
    "allowed_llm_models": ["openai/gpt-4o-mini"],
}


class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = mock.patch.dict(os.environ, {"DASHBOARD_TOKEN": TOKEN, "DASHBOARD_BIND": "127.0.0.1"})
        cls.env.start()
        cls.patches = [
            mock.patch.object(db, "get_data", return_value={}),
            mock.patch.object(db, "build_html", return_value=PAGE),
            mock.patch.object(db, "load_sources",
                              side_effect=lambda: {"rss_feeds": [], "twitter_accounts": [], "fred_indicators": []}),
            mock.patch.object(db, "save_sources"),
            mock.patch.object(dth, "load_thematic_config", side_effect=lambda: {
                k: (dict(v) if isinstance(v, dict) else list(v)) for k, v in THEMATIC_CFG.items()}),
            mock.patch.object(dth, "save_thematic_config"),
            mock.patch("time.sleep"),
        ]
        cls.mocks = [p.start() for p in cls.patches]
        cls.save_sources, cls.save_thematic = cls.mocks[3], cls.mocks[5]
        cls.server = HTTPServer(("127.0.0.1", 0), db.Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        for p in cls.patches:
            p.stop()
        cls.env.stop()

    def setUp(self):
        self.save_sources.reset_mock()
        self.save_thematic.reset_mock()

    def _req(self, method, path, body="", headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Content-Type": "application/x-www-form-urlencoded"}
        h.update(headers or {})
        conn.request(method, path, body=body, headers=h)
        r = conn.getresponse()
        data = r.read().decode("utf-8", "replace")
        out = (r.status, dict(r.getheaders()), data)
        conn.close()
        return out

    def _cookie(self):
        status, headers, _ = self._req("POST", "/login", f"token={TOKEN}")
        self.assertEqual(status, 303)
        return headers["Set-Cookie"].split(";")[0]

    # --- Token nicht mehr in Seiten ---------------------------------------
    def test_no_page_contains_the_token(self):
        for path in ("/", "/?tab=sources", "/login"):
            status, _, body = self._req("GET", path)
            self.assertEqual(status, 200)
            self.assertNotIn(TOKEN, body, path)
            self.assertNotIn('name="_token"', body, path)

    def test_unauthenticated_page_shows_login_hint(self):
        _, _, body = self._req("GET", "/")
        self.assertIn("/login", body)

    # --- POST-Schutz --------------------------------------------------------
    def test_post_without_auth_is_forbidden(self):
        status, _, _ = self._req("POST", "/sources/rss/add", "name=x&url=https://a.example/feed")
        self.assertEqual(status, 403)
        self.save_sources.assert_not_called()

    def test_old_form_field_token_is_no_longer_accepted(self):
        status, _, _ = self._req("POST", "/sources/rss/add", f"_token={TOKEN}&name=x&url=https://a.example/feed")
        self.assertEqual(status, 403)

    def test_header_token_still_works_for_scripts(self):
        status, _, _ = self._req("POST", "/sources/rss/add", "name=x&url=https://a.example/feed",
                                 {"X-Dashboard-Token": TOKEN})
        self.assertEqual(status, 303)
        self.save_sources.assert_called_once()

    def test_login_sets_httponly_strict_cookie_without_the_token(self):
        status, headers, _ = self._req("POST", "/login", f"token={TOKEN}")
        self.assertEqual(status, 303)
        cookie = headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertNotIn(TOKEN, cookie)

    def test_wrong_token_gets_no_cookie(self):
        status, headers, _ = self._req("POST", "/login", "token=falsch")
        self.assertEqual(status, 303)
        self.assertNotIn("Set-Cookie", headers)
        self.assertIn("/login", headers["Location"])

    def test_cookie_allows_post_but_foreign_origin_does_not(self):
        cookie = self._cookie()
        ok, _, _ = self._req("POST", "/sources/rss/add", "name=x&url=https://a.example/feed", {"Cookie": cookie})
        self.assertEqual(ok, 303)
        bad, _, _ = self._req("POST", "/sources/rss/add", "name=x&url=https://a.example/feed",
                              {"Cookie": cookie, "Origin": "http://evil.example"})
        self.assertEqual(bad, 403)

    # --- Modellnamen -------------------------------------------------------
    def test_unknown_model_is_rejected(self):
        cookie = self._cookie()
        status, _, body = self._req("POST", "/thematic/config/save", "llm_committee_bull=evil/expensive-model",
                                    {"Cookie": cookie})
        self.assertEqual(status, 400)
        self.assertIn("nicht erlaubt", body)
        self.save_thematic.assert_not_called()

    def test_known_model_and_allowed_list_are_accepted(self):
        cookie = self._cookie()
        for model in ("deepseek/deepseek-v4.1-flash", "openai/gpt-4o-mini"):
            status, _, _ = self._req("POST", "/thematic/config/save", f"llm_committee_bull={model}", {"Cookie": cookie})
            self.assertEqual(status, 303, model)
        self.assertEqual(self.save_thematic.call_count, 2)

    def test_unknown_role_is_rejected(self):
        cookie = self._cookie()
        status, _, _ = self._req("POST", "/thematic/config/save", "llm_neue_rolle=deepseek/deepseek-v4-pro",
                                 {"Cookie": cookie})
        self.assertEqual(status, 400)

    def test_threshold_is_saved_under_its_real_name(self):
        cookie = self._cookie()
        status, _, _ = self._req("POST", "/thematic/config/save", "thresh_min_score=0.6", {"Cookie": cookie})
        self.assertEqual(status, 303)
        saved = self.save_thematic.call_args[0][0]
        self.assertEqual(saved["thresholds"]["min_score"], 0.6)
        self.assertNotIn("esh_min_score", saved["thresholds"])

    # --- Quellen ------------------------------------------------------------
    def test_source_input_is_validated(self):
        cookie = self._cookie()
        bad = [
            "/sources/rss/add|name=x&url=file:///etc/passwd",
            "/sources/rss/add|name=x&url=https://a.example/feed&weight=99",
            "/sources/rss/add|name=x&url=https://a.example/feed&weight=nan",
            "/sources/twitter/add|handle=a b&name=x",
            "/sources/twitter/add|handle=abc&name=x&weight=-1",
            "/sources/yt/add|name=x&url=javascript:alert(1)",
        ]
        for item in bad:
            path, body = item.split("|", 1)
            status, _, _ = self._req("POST", path, body, {"Cookie": cookie})
            self.assertEqual(status, 400, item)
        self.save_sources.assert_not_called()

    def test_valid_sources_pass(self):
        cookie = self._cookie()
        status, _, _ = self._req("POST", "/sources/twitter/add", "handle=@abc_1&name=Abc&category=investor&weight=1.5",
                                 {"Cookie": cookie})
        self.assertEqual(status, 303)
        self.save_sources.assert_called_once()


if __name__ == "__main__":
    unittest.main()
