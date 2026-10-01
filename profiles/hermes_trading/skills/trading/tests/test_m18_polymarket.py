"""M18: Polymarket-Historie ueber die CLOB-Token-ID, echte 7-Tage-Deltas, Scanner liest die richtigen Schluessel.
Alle Antworten synthetisch (kein Netz)."""
import json
import time

import pytest

from thematic.lib import polymarket_client as pc
from thematic import prediction_market_scanner as scanner

NOW = 1_800_000_000.0


def hist(days_back, start_price, end_price, points=48):
    """gleichmaessige Historie ueber `days_back` Tage bis NOW"""
    out = []
    for i in range(points):
        frac = i / (points - 1)
        out.append({"t": NOW - days_back * 86400 * (1 - frac), "p": start_price + (end_price - start_price) * frac})
    return out


def test_price_days_ago_picks_the_point_closest_to_the_target():
    h = hist(8, 0.30, 0.70)
    p = pc.price_days_ago(h, 7, now_ts=NOW)
    assert 0.30 < p < 0.45                     # etwa der Wert 1 Tag nach dem Start
    assert abs(p - (0.30 + 0.40 * (1 / 8))) < 0.02


def test_price_days_ago_returns_none_when_history_is_too_short():
    assert pc.price_days_ago(hist(2, 0.4, 0.5), 7, now_ts=NOW) is None
    assert pc.price_days_ago([], 7, now_ts=NOW) is None


def test_the_old_second_to_last_point_is_not_used_as_seven_day_price():
    h = hist(8, 0.30, 0.70, points=200)
    assert h[-2]["p"] > 0.69                                   # das wäre der alte "Preis vor 7 Tagen"
    assert pc.price_days_ago(h, 7, now_ts=NOW) < 0.45


def _gamma_events():
    return [{"title": "Fed decision", "volume": "900000", "markets": [{
        "conditionId": "0xabc", "question": "Will the Fed cut rates?", "volume": "50000", "endDate": "2026-12-31T00:00:00Z",
        "outcomePrices": json.dumps(["0.62", "0.38"]), "clobTokenIds": json.dumps(["TOKEN_YES", "TOKEN_NO"]),
        "slug": "fed-cut"}]}]


def test_trending_markets_carry_the_clob_token_id(monkeypatch):
    monkeypatch.setattr(pc, "_get", lambda url: _gamma_events())
    m = pc.fetch_trending_markets()[0]
    assert m["market_id"] == "0xabc" and m["token_id"] == "TOKEN_YES" and m["current_yes_price"] == 0.62


def test_history_url_uses_the_given_reference_and_survives_http_errors(monkeypatch):
    urls = []
    monkeypatch.setattr(pc, "_get", lambda url: urls.append(url) or {"history": [{"t": 1, "p": 0.5}]})
    assert pc.fetch_market_history("TOKEN_YES", "1w", 60) == [{"t": 1, "p": 0.5}]
    assert "market=TOKEN_YES" in urls[0] and "fidelity=60" in urls[0]

    def boom(url):
        raise SystemExit(1)                       # _get beendet den Prozess bei HTTP-Fehlern
    monkeypatch.setattr(pc, "_get", boom)
    assert pc.fetch_market_history("X") == []


def test_top_movers_use_the_seven_day_price_not_the_previous_point(monkeypatch):
    monkeypatch.setattr(pc, "fetch_trending_markets", lambda **k: [
        {"market_id": "0xabc", "token_id": "TOKEN_YES", "category": "economics", "current_yes_price": 0.70,
         "question": "q"}])
    monkeypatch.setattr(pc, "fetch_market_history", lambda ref, interval="1w", fidelity=60: hist(8, 0.30, 0.70, 200)
                        if ref == "TOKEN_YES" else [])
    monkeypatch.setattr(pc.time, "time", lambda: NOW)
    movers = pc.fetch_top_movers(min_delta_7d=0.0)
    assert len(movers) == 1 and movers[0]["delta_7d"] > 0.2          # alt: ~0 (history[-2])


def test_top_movers_skip_markets_without_history(monkeypatch):
    monkeypatch.setattr(pc, "fetch_trending_markets", lambda **k: [
        {"market_id": "0xabc", "token_id": "T", "category": "economics", "current_yes_price": 0.7, "question": "q"}])
    monkeypatch.setattr(pc, "fetch_market_history", lambda *a, **k: [])
    assert pc.fetch_top_movers(min_delta_7d=0.0) == []


def test_enrich_sets_none_not_zero_when_history_is_missing(monkeypatch):
    monkeypatch.setattr(pc, "fetch_market_history", lambda *a, **k: [])
    m = {"token_id": "T", "current_yes_price": 0.5, "volume_24h_usd": 10}
    pc.enrich_with_history([m])
    assert m["delta_7d"] is None and m["price_7d_ago"] is None and m["price_30d_ago"] is None


def test_enrich_computes_delta_and_both_reference_prices(monkeypatch):
    monkeypatch.setattr(pc.time, "time", lambda: NOW)
    monkeypatch.setattr(pc, "fetch_market_history",
                        lambda ref, interval="1w", fidelity=60: hist(8, 0.30, 0.70) if interval == "1w" else hist(31, 0.10, 0.70))
    m = {"token_id": "T", "current_yes_price": 0.70, "volume_24h_usd": 10}
    pc.enrich_with_history([m])
    assert m["delta_7d"] > 0.2 and m["price_30d_ago"] < 0.2


def test_scanner_reads_price_and_volume_from_the_real_keys():
    raw = {"current_yes_price": 0.62, "total_volume_usd": 900_000, "volume_24h_usd": 50_000, "question": "q",
           "category": "economics", "resolution_date": "2026-12-31", "token_id": "T"}
    n = scanner._normalize_market(raw, "0xabc", "2026-09-30")
    assert n["current_yes_price"] == 0.62 and n["total_volume_usd"] == 900_000
    assert n["liquidity_score"] == pytest.approx(0.9) and n["delta_7d"] is None and n["token_id"] == "T"
