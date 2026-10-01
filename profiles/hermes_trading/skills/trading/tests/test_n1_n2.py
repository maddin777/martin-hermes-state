"""N1 (technical_validator abschaltbar, _strength_val) und N2 (Waehrungszuordnung weiterer Boersen)."""
import json

import pytest

import utils
from scripts import technical_validator as tv
from scripts import trading_pipeline as tp


# ── N1 ──────────────────────────────────────────────────────────────────────────────────────
def _cfg(tmp_path, monkeypatch, content):
    p = tmp_path / "strategy_config.json"
    if content is not None:
        p.write_text(json.dumps(content))
    import config
    monkeypatch.setattr(config, "STRATEGY_CONFIG_PATH", str(p))


@pytest.mark.parametrize(("content", "expected"), [
    (None, False), ({}, False), ({"technical_validator_enabled": False}, False), ({"technical_validator_enabled": True}, True),
])
def test_validator_switch_defaults_to_off(tmp_path, monkeypatch, content, expected):
    _cfg(tmp_path, monkeypatch, content)
    assert tp._validator_enabled() is expected


def _run_pipeline(monkeypatch):
    ran = []
    monkeypatch.setattr(tp, "run", lambda script, label, args="": ran.append(script) or True)
    monkeypatch.setattr(tp, "_print", lambda msg: None)
    import config
    monkeypatch.setattr(config, "db_connect", lambda: (_ for _ in ()).throw(RuntimeError("kein DB-Zugriff im Test")))
    tp.main()
    return ran


def test_pipeline_skips_the_validator_when_switched_off(tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch, {"technical_validator_enabled": False})
    ran = _run_pipeline(monkeypatch)
    assert "technical_validator.py" not in ran and "llm_validator.py" in ran and "signal_manager.py" in ran


def test_pipeline_runs_the_validator_when_switched_on(tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch, {"technical_validator_enabled": True})
    assert "technical_validator.py" in _run_pipeline(monkeypatch)


def test_order_of_the_remaining_steps_is_unchanged(tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch, {})
    ran = _run_pipeline(monkeypatch)
    assert ran == ["yt_channel_monitor.py", "signal_extractor.py", "screener_source.py", "watchlist_manager.py",
                   "watchlist_dedup.py", "llm_validator.py", "signal_manager.py", "shadow_selection.py"]


@pytest.mark.parametrize(("value", "rank"), [("strong", 3.0), ("Moderate", 2.0), ("weak", 1.0), (0.7, 0.7), ("0.4", 0.4),
                                             (None, -1), ("unbekannt", -1)])
def test_strength_val_understands_the_text_scale(value, rank):
    assert tv._strength_val({"company": {"strength": value}}) == rank


def test_strongest_candidate_is_now_picked_by_strength():
    cands = [{"company": {"strength": "weak"}}, {"company": {"strength": "strong"}}, {"company": {"strength": "moderate"}}]
    assert max(cands, key=tv._strength_val)["company"]["strength"] == "strong"


# ── N2 ──────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(("ticker", "currency"), [
    ("EQNR.OL", "NOK"), ("PKN.WA", "PLN"), ("TCS.NS", "INR"), ("RELIANCE.BO", "INR"), ("TEVA.TA", "ILA"),
    ("000001.SZ", "CNY"), ("600519.SS", "CNY"), ("2222.SR", "SAR"), ("SAN.MC", "EUR"), ("EDP.LS", "EUR"),
    ("CRH.IR", "EUR"), ("2330.TW", "TWD"), ("AIR.NZ", "NZD"),
])
def test_additional_exchange_suffixes(ticker, currency):
    assert utils.ticker_to_currency(ticker) == currency


@pytest.mark.parametrize(("ticker", "currency"), [
    ("SAP.DE", "EUR"), ("SHEL.L", "GBp"), ("NESN.SW", "CHF"), ("VOLV-B.ST", "SEK"), ("RY.TO", "CAD"), ("7203.T", "JPY"),
    ("AAPL", "USD"), ("BTC-USD", "USD"), ("", "EUR"),
])
def test_existing_mappings_are_unchanged(ticker, currency):
    assert utils.ticker_to_currency(ticker) == currency


def test_unknown_suffix_warns_once_and_falls_back_to_usd(caplog):
    utils._WARNED_SUFFIXES.discard("QQ")
    with caplog.at_level("WARNING"):
        assert utils.ticker_to_currency("FOO.QQ") == "USD"
        assert utils.ticker_to_currency("BAR.QQ") == "USD"
    assert caplog.text.count("Unbekannter Börsensuffix '.QQ'") == 1


def test_tel_aviv_prices_are_converted_from_agorot(monkeypatch):
    monkeypatch.setattr(utils, "get_fx_rate_to_eur", lambda c: {"ILS": 0.25}[c])
    assert utils.price_to_eur(1000.0, "TEVA.TA") == pytest.approx(2.5)        # 1000 Agorot = 10 ILS = 2,50 EUR
