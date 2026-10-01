"""P10–P13 aus der Nachpruefung vom 30.09.2026.

P10 FX: SAR und TWD hatten keinen Kurs (EZB/Frankfurter fuehrt sie nicht) -> Umrechnung mit 1,0.
P11 Dashboard: ein Thread, POST-Body vor der Anmeldung gelesen, Login-Bremse blockierte alles, 4 s je Seitenaufbau.
P12 drawdown_monitor: ATH aus drawdown_log (ignorierte den Notbremse-Reset), jeden Werktag dieselbe Telegram-Meldung.
P13 Kleinkram: Notbremse ohne Slippage/Teil-TP/Fade-Deckel, Pre-Market-Vorzeichen, "Handelstage", Trade-Zaehler,
    `if True:` in timing_validator.
"""
import http.client
import os
import socket
import sqlite3
import sys
import threading
import time
import urllib.request
from datetime import datetime, timedelta
from unittest import mock

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import utils                                              # noqa: E402
from scripts import breaking_news_monitor as bnm          # noqa: E402
from scripts import dashboard as dash                     # noqa: E402
from scripts import signal_manager as sm                  # noqa: E402
from thematic import drawdown_monitor as dm               # noqa: E402
from tests.test_k1_notbremse import _make_db, _add_position   # noqa: E402


# ── P10 ─────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def fx(monkeypatch):
    monkeypatch.setattr(utils, "_fetch_fx_rates", lambda: {"EUR": 1.0, "USD": 1.17, "GBP": 0.86})
    monkeypatch.setattr(utils, "_fx_extra_cache", {}, raising=False)


def test_p10_saudi_riyal_follows_the_usd_peg(fx):
    assert utils.get_fx_rate_to_eur("SAR") == pytest.approx(1 / (1.17 * 3.75))
    assert utils.ticker_to_currency("2222.SR") == "SAR"
    assert utils.price_to_eur(25.0, "2222.SR") == pytest.approx(25.0 / (1.17 * 3.75))   # vorher 25,00


def test_p10_taiwan_dollar_comes_from_yfinance_once_per_day(fx, monkeypatch):
    calls = []

    def fake_download(sym, **kw):
        calls.append(sym)
        return pd.DataFrame({"Close": [35.0, 35.2]})

    monkeypatch.setattr(utils.yf, "download", fake_download)
    assert utils.get_fx_rate_to_eur("TWD") == pytest.approx(1 / 35.2)
    assert utils.get_fx_rate_to_eur("TWD") == pytest.approx(1 / 35.2)
    assert calls == ["EURTWD=X"]


def test_p10_static_fallback_when_yfinance_fails(fx, monkeypatch):
    monkeypatch.setattr(utils.yf, "download", mock.MagicMock(side_effect=RuntimeError("offline")))
    rate = utils.get_fx_rate_to_eur("TWD")
    assert rate != 1.0 and rate == pytest.approx(1 / utils._FX_FALLBACK["TWD"])


# ── P11 ─────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv("DASHBOARD_TOKEN", "geheim")
    monkeypatch.setattr(dash, "get_data", lambda: {})
    monkeypatch.setattr(dash, "build_html", lambda d: "<html><body>ok</body></html>")
    monkeypatch.setattr(dash, "LOGIN_FAIL_DELAY", 0.0, raising=False)
    monkeypatch.setattr(dash, "_LOGIN_FAILS", {}, raising=False)
    monkeypatch.setattr(dash, "_PAGE_CACHE", {"ts": 0.0, "html": None}, raising=False)
    srv = dash.make_server("127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _status_line(port, raw):
    s = socket.create_connection(("127.0.0.1", port), timeout=3)
    s.sendall(raw)
    line = s.recv(200).split(b"\r\n")[0]
    s.close()
    return line


def test_p11_anonymous_post_is_rejected_before_its_body_is_read(server):
    port = server.server_address[1]
    line = _status_line(port, b"POST /sources/rss/add HTTP/1.1\r\nHost: x\r\nContent-Length: 1000000000\r\n\r\n")
    assert b" 403 " in line                         # vorher: wartete auf 1 GB Body


def test_p11_oversized_authorized_post_gets_413(server):
    port = server.server_address[1]
    line = _status_line(port, b"POST /sources/rss/add HTTP/1.1\r\nHost: x\r\nX-Dashboard-Token: geheim\r\n"
                              b"Content-Length: 10000000\r\n\r\n")
    assert b" 413 " in line


def test_p11_a_hanging_client_does_not_block_other_requests(server):
    port = server.server_address[1]
    slow = socket.create_connection(("127.0.0.1", port), timeout=5)
    slow.sendall(b"GET / HTTP/1.1\r\n")             # Kopfzeilen werden nie beendet
    t0 = time.time()
    body = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3).read()
    assert b"ok" in body and time.time() - t0 < 3
    slow.close()


def _login(port, token):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    c.request("POST", "/login", body=f"token={token}", headers={"Content-Type": "application/x-www-form-urlencoded"})
    r = c.getresponse()
    r.read()
    c.close()
    return r.status


def test_p11_login_is_locked_after_repeated_failures(server):
    port = server.server_address[1]
    for _ in range(dash.LOGIN_MAX_FAILS):
        assert _login(port, "falsch") == 303
    assert _login(port, "geheim") == 429


def test_p11_the_rendered_page_is_cached_briefly(server, monkeypatch):
    calls = []
    monkeypatch.setattr(dash, "get_data", lambda: calls.append(1) or {})
    port = server.server_address[1]
    for _ in range(3):
        urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3).read()
    assert len(calls) == 1


# ── P12 ─────────────────────────────────────────────────────────────────────────────────────
def _dm_db(path, cash, ath_value, last_trigger="hard", old_max=11207.85):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE portfolio (id INTEGER PRIMARY KEY, cash REAL, total_value REAL, ath_value REAL)")
    con.execute("INSERT INTO portfolio VALUES (1, ?, ?, ?)", (cash, cash, ath_value))
    con.execute("CREATE TABLE positions (id INTEGER PRIMARY KEY, ticker TEXT, direction TEXT, entry_price REAL, "
                "position_size REAL, status TEXT, pnl_eur REAL)")
    con.execute("CREATE TABLE drawdown_log (date TEXT, portfolio_value REAL, all_time_high REAL, drawdown_pct REAL, "
                "trigger_level TEXT, action_taken TEXT)")
    con.execute("CREATE TABLE system_state (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)")
    con.execute("INSERT INTO drawdown_log VALUES ('2026-06-05', ?, ?, 0, 'none', '')", (old_max, old_max))
    con.execute("INSERT INTO drawdown_log VALUES ('2026-09-29', 9063, ?, -19.1, ?, '')", (old_max, last_trigger))
    con.commit()
    con.close()


def _dm_run(path, monkeypatch):
    sent = []
    monkeypatch.setattr(dm, "DB_PATH", str(path))
    monkeypatch.setattr(dm, "_send_telegram", lambda m: sent.append(m))
    dm.main()
    con = sqlite3.connect(path)
    last = con.execute("SELECT all_time_high, drawdown_pct, trigger_level FROM drawdown_log "
                       "ORDER BY rowid DESC LIMIT 1").fetchone()
    con.close()
    return last, sent


def test_p12_the_reset_reference_value_is_the_ath(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    _dm_db(db, cash=9000.0, ath_value=9500.0)          # nach K1b-Reset: ATH 9.500
    (ath, dd, trigger), _ = _dm_run(db, monkeypatch)
    assert ath == pytest.approx(9500.0) and dd == pytest.approx(-5.26, abs=0.01) and trigger == "none"


def test_p12_the_same_level_is_not_reported_again(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    _dm_db(db, cash=9048.86, ath_value=11207.85, last_trigger="hard")
    (_, _, trigger), sent = _dm_run(db, monkeypatch)
    assert trigger == "hard" and sent == []            # vorher jeden Werktag dieselbe Meldung


def test_p12_a_level_change_is_reported(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    _dm_db(db, cash=9048.86, ath_value=11207.85, last_trigger="soft")
    (_, _, trigger), sent = _dm_run(db, monkeypatch)
    assert trigger == "hard" and len(sent) == 1


# ── P13 ─────────────────────────────────────────────────────────────────────────────────────
def _close_all(con, prices):
    with mock.patch.object(sm, "get_current_price_and_atr", side_effect=lambda t: (prices[t], 1.0)), \
         mock.patch.object(sm, "save_config"):
        sm._emergency_close_all(con, {"drawdown_close_all_date": None})


def test_p13_emergency_close_books_slippage_and_the_partial_take_profit():
    con = _make_db(cash=5000.0)
    _add_position(con, "AAA", "LONG", 100.0, 300.0)
    con.execute("UPDATE positions SET partial_exit_done=1, partial_pnl_eur=40.0, partial_size_eur=300.0")
    con.commit()
    _close_all(con, {"AAA": 110.0})
    rest, _ = sm.realized_pnl_from_effective_entry(100.0, 110.0, 300.0, "LONG")
    rest -= sm.COMMISSION_EUR
    pnl = con.execute("SELECT pnl_eur FROM positions").fetchone()["pnl_eur"]
    assert pnl == pytest.approx(rest + 40.0, abs=0.01)                     # vorher 28 (ohne Teil-TP)
    cash = con.execute("SELECT cash FROM portfolio").fetchone()["cash"]
    assert cash == pytest.approx(5000.0 + 300.0 + rest, abs=0.01)


def test_p13_emergency_close_caps_a_yt_fade_loss_at_the_total_loss():
    con = _make_db(cash=5000.0)
    _add_position(con, "FAD", "SHORT", 100.0, 500.0)
    con.execute("UPDATE positions SET exit_mode=?", (sm.YT_FADE_MODE,))
    con.commit()
    _close_all(con, {"FAD": 250.0})                                         # Kurs +150 %
    pnl = con.execute("SELECT pnl_eur FROM positions").fetchone()["pnl_eur"]
    assert pnl >= -500.0 - 5.0                                               # vorher -752


def test_p13_premarket_alert_shows_the_real_direction():
    down = bnm._premarket_alert("Qualys", 95.0, 100.0)
    assert "-5.0%" in down and "📉" in down                                   # vorher "+5.0%"
    assert bnm._premarket_alert("Qualys", 103.0, 100.0) is None


def test_p13_cooldown_message_counts_calendar_days(capsys):
    cfg = {"drawdown_close_all_date": (datetime.now() - timedelta(days=2)).isoformat(), "drawdown_cooldown_days": 7}
    assert sm._is_drawdown_cooldown_active(cfg) is True
    out = capsys.readouterr().out
    assert "noch 5 Tage" in out and "Handelstage" not in out


def test_p13_trade_counters_in_the_config_follow_the_database():
    con = _make_db(cash=5000.0)
    for pnl in (10.0, -5.0, 20.0):
        con.execute("INSERT INTO positions (ticker, direction, status, pnl_eur, position_size) "
                    "VALUES ('X', 'LONG', 'closed', ?, 100)", (pnl,))
    con.commit()
    cfg = dict(sm.DEFAULT_CONFIG, total_trades=1, winning_trades=0)
    with mock.patch.object(sm, "save_config") as save, \
         mock.patch.object(sm, "get_current_regime", return_value=("sideways", 15.0)):
        cfg = sm.check_open_positions(con, cfg)
    assert (cfg["total_trades"], cfg["winning_trades"]) == (3, 2) and save.called


def test_p13_timing_validator_has_no_dead_branch():
    src = open(os.path.join(ROOT, "thematic", "timing_validator.py"), encoding="utf-8").read()
    assert "if True:" not in src
