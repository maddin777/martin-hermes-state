"""
dukascopy_data.py — Dukascopy-Kerzen als Datenquelle des Forex-Bots (24.09.2026).

WARUM: yfinance liefert fuer Forex-Tageskerzen einen unbrauchbaren Close (Open-Close-Abstand im Median 0,6 Pips gegenueber
~32 Pips in echten Kursdaten; der Close entspricht praktisch dem Open). Alle Tages-Backtests und die Signale des Bots liefen
darauf. Dieses Modul baut Tages-/Wochen-/Stundenkerzen aus Dukascopy-Stundenkerzen (Bid + Ask, kostenlos, kein Key) und den
aktuellen Preis aus Dukascopy-Minutenkerzen.

Konventionen
- Preise sind MITTELKURSE (Bid + halber Spread); die Spread-Kosten rechnet der Bot separat (config.json).
- Handelstag: Beginn ~22 Uhr UTC (Verschiebung +2 h), Samstags-/Sonntags-Reste zaehlen zum Montag.
- Tages-Index: naive Datumswerte (Tag des Handelstags). Wochen-Index: FREITAG der Woche (Ende), damit ein Wochenwert im Backtest
  erst ab Freitag sichtbar ist (kein Lookahead). Intraday-Index: UTC, mit Zeitzone.
- Die letzte Tageszeile ist der laufende Tag (Close = aktueller Preis), wie bei yfinance.
- Lokaler Cache data/dukascopy/<PAAR>_H1.csv, inkrementell aktualisiert (Dateisperre, atomares Schreiben).
- FAIL-SAFE: ist Dukascopy nicht erreichbar, wird nur ein Cache verwendet, der juenger als MAX_CACHE_AGE ist; sonst liefern die
  Funktionen None (der Bot behandelt das als "keine Daten") — NIE stillschweigend beschaedigte Daten.
- WICHTIG: der Bibliotheksaufruf behandelt naive Zeitstempel als LOKALE Zeit; deshalb immer Zeitzonen-Objekte (UTC) uebergeben.
"""
import datetime as dt
import fcntl
import os
import time

import numpy as np
import pandas as pd

import config as cfg

UTC = dt.timezone.utc
SKILL_DIR = cfg.SKILL_DIR
CACHE_DIR = os.path.join(SKILL_DIR, cfg.CONFIG.get("data_cache_dir", "data/dukascopy"))
HISTORY_START = dt.datetime(2006, 5, 1, tzinfo=UTC)
MAX_CACHE_AGE = dt.timedelta(days=4)       # Wochenende + Reserve
COLS = ["bid_open", "bid_high", "bid_low", "bid_close", "ask_open", "ask_close", "spread", "volume"]


class DataUnavailable(Exception):
    pass


def symbol_of(pair):
    """'EURUSD=X' -> 'EUR/USD'."""
    p = pair.replace("=X", "")
    return p[:3] + "/" + p[3:6]


def _now():
    return dt.datetime.now(UTC)


def _fetch(symbol, interval, side, start, end, retries=3):
    import dukascopy_python as d
    last = None
    for a in range(retries):
        try:
            return d.fetch(symbol, interval, side, start, end)
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1 + 2 * a)
    raise DataUnavailable("Dukascopy-Abruf fehlgeschlagen (%s): %s" % (symbol, last))


def _fetch_h1(symbol, start, end):
    import dukascopy_python as d
    frames, cur = [], start
    while cur < end:
        nxt = min(dt.datetime(cur.year + 1, 1, 1, tzinfo=UTC), end)
        bid = _fetch(symbol, d.INTERVAL_HOUR_1, d.OFFER_SIDE_BID, cur, nxt)
        ask = _fetch(symbol, d.INTERVAL_HOUR_1, d.OFFER_SIDE_ASK, cur, nxt)
        if bid is not None and len(bid) and ask is not None and len(ask):
            b = bid.rename(columns={"open": "bid_open", "high": "bid_high", "low": "bid_low", "close": "bid_close"})
            a = ask[["open", "close"]].rename(columns={"open": "ask_open", "close": "ask_close"})
            frames.append(b.join(a, how="inner"))
        cur = nxt
    if not frames:
        return pd.DataFrame(columns=COLS)
    df = pd.concat(frames)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df.index = pd.to_datetime(df.index, utc=True)
    df.index.name = "time"
    df["spread"] = ((df["ask_open"] - df["bid_open"]) + (df["ask_close"] - df["bid_close"])) / 2
    return df[COLS]


def _cache_path(pair):
    return os.path.join(CACHE_DIR, pair.replace("=X", "") + "_H1.csv")


def _read_cache(pair):
    p = _cache_path(pair)
    if not os.path.exists(p):
        return None
    df = pd.read_csv(p, index_col="time", parse_dates=["time"]).sort_index()
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df


def _write_cache(pair, df):
    os.makedirs(CACHE_DIR, exist_ok=True)
    p = _cache_path(pair)
    tmp = p + ".tmp%d" % os.getpid()
    df.to_csv(tmp)
    os.replace(tmp, p)


def h1(pair):
    """Bereinigte Stundenkerzen (Cache, bei Bedarf inkrementell aktualisiert). Wirft DataUnavailable, wenn nur veraltete Daten da sind."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    now = _now()
    with open(os.path.join(CACHE_DIR, ".lock"), "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        df = _read_cache(pair)
        fresh_to = now.replace(minute=0, second=0, microsecond=0) - dt.timedelta(hours=1)   # letzte abgeschlossene Stunde
        need = df is None or df.index[-1] < fresh_to
        if need:
            start = HISTORY_START if df is None else (df.index[-1] - dt.timedelta(days=2)).to_pydatetime()
            try:
                new = _fetch_h1(symbol_of(pair), start, now)
                if len(new):
                    df = new if df is None else pd.concat([df[~df.index.isin(new.index)], new]).sort_index()
                    _write_cache(pair, df)
            except DataUnavailable:
                if df is None:
                    raise
        fcntl.flock(lk, fcntl.LOCK_UN)
    if df is None or len(df) == 0:
        raise DataUnavailable("keine Stundenkerzen fuer %s" % pair)
    if now - df.index[-1].to_pydatetime() > MAX_CACHE_AGE:
        raise DataUnavailable("Cache fuer %s ist veraltet (letzte Kerze %s)" % (pair, df.index[-1]))
    return df[~((df["volume"] == 0) & (df["bid_high"] == df["bid_low"]))]


def _mid(df):
    half = df["spread"] / 2
    return pd.DataFrame({"Open": df["bid_open"] + half, "High": df["bid_high"] + half, "Low": df["bid_low"] + half,
                         "Close": df["bid_close"] + half}, index=df.index)


def trading_day(index):
    """Handelstag-Datum je Zeitstempel (UTC): +2 h, Sonntag -> Montag, Samstag -> Montag."""
    ts = index.tz_convert("UTC").tz_localize(None) + pd.Timedelta(hours=2)
    day = ts.normalize()
    dow = day.dayofweek
    return day + pd.to_timedelta(np.where(dow == 6, 1, np.where(dow == 5, 2, 0)), unit="D")


def daily_from_h1(df, keep_running_day=True, now=None):
    m = _mid(df)
    day = trading_day(m.index)
    g = m.groupby(day)
    out = pd.DataFrame({"Open": g["Open"].first(), "High": g["High"].max(), "Low": g["Low"].min(), "Close": g["Close"].last(),
                        "n": g["Open"].size()})
    now = now or _now()
    today = trading_day(pd.DatetimeIndex([pd.Timestamp(now)]))[0]
    keep = (out["n"] >= 12) | ((out.index >= today) & keep_running_day)
    out = out[keep].drop(columns="n")
    out.index.name = None
    return out


def weekly_from_daily(daily):
    w = daily.resample("W-FRI").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna()
    return w


def _recent_mid(pair, minutes=180):
    """Aktueller Mittelkurs und Hoch/Tief der letzten Minuten aus Minutenkerzen (Bid und Ask)."""
    import dukascopy_python as d
    end = _now()
    start = end - dt.timedelta(minutes=minutes)
    b = _fetch(symbol_of(pair), d.INTERVAL_MIN_1, d.OFFER_SIDE_BID, start, end)
    a = _fetch(symbol_of(pair), d.INTERVAL_MIN_1, d.OFFER_SIDE_ASK, start, end)
    if b is None or a is None or len(b) == 0 or len(a) == 0:
        raise DataUnavailable("keine Minutenkerzen fuer %s" % pair)
    j = b.join(a[["open", "close", "high", "low"]].rename(columns={"open": "ao", "close": "ac", "high": "ah", "low": "al"}), how="inner")
    j.index = pd.to_datetime(j.index, utc=True)
    if end - j.index[-1].to_pydatetime() > dt.timedelta(minutes=30):
        raise DataUnavailable("Minutenkerzen fuer %s sind veraltet (%s)" % (pair, j.index[-1]))
    j["mid_open"] = (j["open"] + j["ao"]) / 2
    j["mid_close"] = (j["close"] + j["ac"]) / 2
    j["mid_high"] = (j["high"] + j["ah"]) / 2
    j["mid_low"] = (j["low"] + j["al"]) / 2
    return j


def latest_price(pair):
    return float(_recent_mid(pair, 60)["mid_close"].iloc[-1])


def daily(pair):
    df = daily_from_h1(h1(pair))
    today = trading_day(pd.DatetimeIndex([pd.Timestamp(_now())]))[0]
    if len(df) and df.index[-1] >= today:          # laufender Tag: aktuellen Preis und Spanne uebernehmen
        try:
            r = _recent_mid(pair, 180)
            i = df.index[-1]
            df.loc[i, "Close"] = float(r["mid_close"].iloc[-1])
            df.loc[i, "High"] = max(float(df.loc[i, "High"]), float(r["mid_high"].max()))
            df.loc[i, "Low"] = min(float(df.loc[i, "Low"]), float(r["mid_low"].min()))
        except DataUnavailable:
            df = df.iloc[:-1]                      # lieber ohne laufenden Tag als mit veraltetem Wert
    return df


def _tail_days(df, period_days):
    if df.index.tz is None:
        cutoff = pd.Timestamp(_now().replace(tzinfo=None)).normalize() - pd.Timedelta(days=int(period_days))
    else:
        cutoff = pd.Timestamp(_now()) - pd.Timedelta(days=int(period_days))
    return df[df.index >= cutoff]


def fetch_pair(pair, period_days=5, interval="15m"):
    """Gleiche Schnittstelle wie fetch.fetch_pair (yfinance): DataFrame Open/High/Low/Close oder None."""
    try:
        if interval == "1d":
            return _tail_days(daily(pair), period_days)
        if interval in ("1h", "60m"):
            return _tail_days(_mid(h1(pair)), period_days)
        if interval == "4h":
            return _tail_days(_mid(h1(pair)).resample("4h").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna(), period_days)
        if interval == "15m":
            r = _recent_mid(pair, 6 * 60)
            b = pd.DataFrame({"Open": r["mid_open"], "High": r["mid_high"], "Low": r["mid_low"], "Close": r["mid_close"]})
            return b.resample("15min").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna()
        raise ValueError("Intervall %s nicht unterstuetzt" % interval)
    except DataUnavailable as e:
        print("  ⚠️  %s: %s" % (pair, e), flush=True)
        return None


def fetch_trend_timeframe(pair, period_days=30, interval="1h"):
    try:
        if interval in ("1wk", "1w"):
            return _tail_days(weekly_from_daily(daily(pair)), period_days)
        return fetch_pair(pair, period_days, interval)
    except DataUnavailable as e:
        print("  ⚠️  %s: %s" % (pair, e), flush=True)
        return None
