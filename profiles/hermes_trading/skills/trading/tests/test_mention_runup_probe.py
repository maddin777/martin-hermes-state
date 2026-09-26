import numpy as np
import pandas as pd
import pytest

from scripts import mention_runup_probe as pr


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(pr, "BOOT_WEEK", 200)
    monkeypatch.setattr(pr, "BOOT_TICKER", 60)


def ment_df(rows):
    df = pd.DataFrame(rows, columns=["ticker", "channel", "sentiment", "strength", "date"])
    df["date"] = pd.to_datetime(df["date"])
    df["det"] = df["channel"].isin(("screener", "screener_nasdaq"))
    return df


# ─────────────────────────────────────────────── Ereignisse und Nennungs-Merkmale
def test_events_need_gap_ignore_screener_and_skip_the_first_gap_of_the_data():
    m = ment_df([
        ("AAA", "kanal", "neutral", "moderate", "2026-04-01"),       # Datenbeginn
        ("AAA", "kanal", "bullish", "strong", "2026-04-20"),         # < 30 Tage nach Datenbeginn -> kein Ereignis
        ("AAA", "kanal", "bullish", "strong", "2026-05-15"),         # Abstand 25 Tage -> kein Ereignis
        ("AAA", "kanal", "bullish", "strong", "2026-06-20"),         # Abstand 36 Tage -> Ereignis
        ("BBB", "screener", "bullish", "strong", "2026-05-10"),      # Screener zaehlt nicht
        ("BBB", "kanal", "bullish", "weak", "2026-05-12"),           # Ereignis
        ("CCC", "kanal", "bearish", "strong", "2026-06-01"),         # bearish -> kein Ereignis
    ])
    ev = pr.find_events(m)
    assert sorted(zip(ev.ticker, ev.date.dt.strftime("%Y-%m-%d"))) == [("AAA", "2026-06-20"), ("BBB", "2026-05-12")]


def test_mention_features_use_only_the_past_window_and_split_screener():
    m = ment_df([
        ("AAA", "k1", "bullish", "strong", "2026-06-10"),
        ("AAA", "k2", "bearish", "weak", "2026-06-12"),
        ("AAA", "k1", "neutral", "moderate", "2026-06-15"),
        ("AAA", "screener", "bullish", "strong", "2026-06-14"),
        ("AAA", "k3", "bullish", "strong", "2026-06-16"),            # NACH t -> darf nicht zaehlen
        ("AAA", "k3", "bullish", "strong", "2026-05-01"),            # vor dem 30-Tage-Fenster
    ])
    f = pr.mention_features(m, "AAA", pd.Timestamp("2026-06-15"))
    assert (f["mentions30"], f["bull30"], f["bear30"], f["neutral30"], f["channels30"]) == (3, 1, 1, 1, 2)
    assert f["screener30"] == 1 and f["channel_list"] == "k1|k2"
    assert f["bull_share"] == pytest.approx(1 / 3) and f["bull_share_w"] == pytest.approx(1.0 / (0.6 * 3))


def test_hand_conviction_is_the_live_formula():
    from watchlist_manager import calculate_conviction
    f = {"bull30": 2, "bear30": 0, "neutral30": 1, "mentions30": 3, "channels30": 2,
         "channel_list": "a|b", "bull_weighted30": 1.6}
    assert pr.hand_conviction(f) == calculate_conviction(2, 0, 1, 3, 2, channels_list=["a", "b"], bullish_weighted=1.6)


# ─────────────────────────────────────────────── Kursmerkmale: Zeitachse
def prices(n=400, start="2025-01-01", seed=0, jump_on=None, jump=0.0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=n)
    close = 100 * np.cumprod(1 + rng.normal(0, 0.01, n))
    s = pd.Series(close, index=idx)
    if jump_on is not None:
        s[s.index >= pd.Timestamp(jump_on)] *= 1 + jump
    return pd.DataFrame({"Open": s, "High": s * 1.01, "Low": s * 0.99, "Close": s, "Volume": 1000.0})


def test_runup_stops_before_the_mention_day_and_entry_is_the_next_close():
    t = pd.Timestamp("2026-03-02")                                   # Montag
    base = prices()
    jumped = prices(jump_on=t, jump=0.30)                           # Sprung AM Nennungstag
    a, _ = pr.price_features(base, t)
    b, _ = pr.price_features(jumped, t)
    assert a["runup20"] == pytest.approx(b["runup20"])              # Nennungstag steckt nicht im Anstieg
    c = base["Close"]
    assert a["runup20"] == pytest.approx(c[c.index < t].iloc[-1] / c[c.index < t].iloc[-21] - 1)
    assert a["entry_date"] == pd.Timestamp("2026-03-03") and a["entry"] == pytest.approx(c.loc["2026-03-03"])
    after = c[c.index > pd.Timestamp("2026-03-03")]
    assert a["fwd5"] == pytest.approx(after.iloc[4] / a["entry"] - 1)


def test_stale_quotes_and_short_history_are_excluded():
    df = prices()
    df.loc[df.index[-120:], "Close"] = 50.0                          # keine Kursaenderung
    rec, why = pr.price_features(df, df.index[-10])
    assert rec is None and why == "ohne Handel"
    rec, why = pr.price_features(prices(n=60), prices(n=60).index[-5])
    assert rec is None and why == "kurze Historie"


def test_forward_returns_are_nan_when_the_future_is_not_there_yet():
    df = prices()
    rec, _ = pr.price_features(df, df.index[-4])
    assert np.isnan(rec["fwd5"]) and np.isnan(rec["fwd21"])


# ─────────────────────────────────────────────── Statistik
def synth(n_weeks=20, per_week=40, n_tickers=400, slope=0.0, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    start = pd.Timestamp("2026-05-04")
    for w in range(n_weeks):
        for i in range(per_week):
            z = rng.normal()
            rows.append({"ticker": "T%d" % rng.integers(n_tickers), "entry_date": start + pd.Timedelta(weeks=w, days=i % 5),
                         "z_runup20": z, "fwd5": 0.01 * w + slope * z + rng.normal(0, 0.03)})
    return pr.add_weeks(pd.DataFrame(rows))


def test_week_demeaning_removes_the_common_move():
    ev = synth()
    assert ev.groupby("week").fwd5_dm.mean().abs().max() < 1e-12
    assert ev.week_n.min() == 40


@pytest.mark.parametrize("slope,verdict", [(-0.02, "HINTERHERLAUFEN BESTAETIGT"),
                                           (0.02, "MOMENTUM (Gegenteil)"),
                                           (0.0, "KEIN BELEGBARER EFFEKT")])
def test_p2_decision_rule(slope, verdict):
    assert pr.analyze_p2(synth(slope=slope))["verdict"] == verdict


def test_logit_recovers_signs():
    rng = np.random.default_rng(1)
    X = rng.normal(size=(3000, 3))
    p = 1 / (1 + np.exp(-(0.2 + 1.0 * X[:, 0] - 0.8 * X[:, 1])))
    y = (rng.uniform(size=3000) < p).astype(float)
    b = pr.fit_logit(X, y)
    assert b[1] > 0.7 and b[2] < -0.5 and abs(b[3]) < 0.15


def test_report_small_sample_is_not_meaningful_and_shows_no_metrics():
    ev = synth(n_weeks=3, per_week=20)
    ev["date"] = ev["entry_date"]
    text, res = pr.report(ev.drop(columns=["week", "week_n", "fwd5_dm"]))
    assert "NICHT AUSSAGEKRAEFTIG" in text and res is None and "Kennzahl A" not in text


def test_p3_needs_minimum_pcr_sample():
    ev = synth(n_weeks=12)
    ev["pcr"] = np.nan
    ev.loc[ev.index[:100], "pcr"] = 0.8
    assert pr.analyze_p3(ev)["verdict"] == "NICHT AUSSAGEKRAEFTIG"
