"""OHLC-Pfade zu geschlossenen Trades laden und cachen.

Hintergrund (18.09.2026): strategy_optimizer und backtester bewerteten
Parameter bisher nur am realisierten Exit-PREIS. Ob ein Stop unterwegs
getroffen worden waere, sah keiner der beiden — das belohnt systematisch zu
enge Stops. Der Fix braucht Intraday-High/Low je Trade; dieses Modul
beschafft sie einmal und haelt sie im Cache, damit eine Grid-Suche ueber
N Kombinationen nicht N-mal bei yfinance anklopft.

Cache-Datei: data/trade_paths_cache.json  (Key: ticker|entry_date)
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

from config import DATA_DIR

CACHE_PATH = os.path.join(DATA_DIR, "trade_paths_cache.json")

# Fenster um den Entry: genug Vorlauf fuer ATR(14) und das Donchian-Fenster,
# genug Nachlauf fuer Trades, die bis zum Time-Stop laufen.
LOOKBACK_DAYS = 45
LOOKAHEAD_DAYS = 75

_MEM: dict[str, list] = {}
_LOADED = False


def _key(ticker: str, entry_date: str) -> str:
    return f"{ticker}|{entry_date[:10]}"


def _load_cache() -> dict:
    global _MEM, _LOADED
    if _LOADED:
        return _MEM
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH) as fh:
                _MEM = json.load(fh)
        except Exception:
            _MEM = {}
    _LOADED = True
    return _MEM


def _save_cache() -> None:
    try:
        tmp = CACHE_PATH + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(_MEM, fh)
        os.replace(tmp, CACHE_PATH)
    except Exception as exc:
        print(f"  ⚠️  trade_paths: Cache nicht schreibbar ({exc})", flush=True)


def _download(ticker: str, entry_date: str) -> list:
    """Holt OHLC um den Entry. Gibt [] zurueck, wenn nichts verfuegbar ist."""
    import yfinance as yf
    import pandas as pd

    d0 = datetime.strptime(entry_date[:10], "%Y-%m-%d")
    start = (d0 - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    end = (d0 + timedelta(days=LOOKAHEAD_DAYS)).strftime("%Y-%m-%d")
    try:
        df = yf.download(ticker, start=start, end=end,
                         progress=False, auto_adjust=False)
    except Exception:
        return []
    if df is None or df.empty:
        return []
    if isinstance(df.columns, pd.MultiIndex):
        df = df.droplevel(1, axis=1)
    out = []
    for idx, row in df.iterrows():
        try:
            out.append({
                "time": idx.strftime("%Y-%m-%d"),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
            })
        except Exception:
            continue
    return out


def _seed_from_backtest_variants() -> int:
    """Uebernimmt die Bars aus data/backtest_variants_result.json in den Cache.

    Diese Datei enthaelt bereits OHLC zu ~81 historischen Trades. Sie zuerst
    einzulesen spart beim ersten Lauf ebenso viele yfinance-Abrufe.
    """
    path = os.path.join(DATA_DIR, "backtest_variants_result.json")
    if not os.path.exists(path):
        return 0
    try:
        with open(path) as fh:
            rows = json.load(fh).get("results", [])
    except Exception:
        return 0
    cache = _load_cache()
    added = 0
    for r in rows:
        bars = r.get("bars")
        if not bars or not r.get("ticker") or not r.get("entry_date"):
            continue
        k = _key(r["ticker"], r["entry_date"])
        if k not in cache:
            cache[k] = [{"time": b["time"], "high": b["high"],
                         "low": b["low"], "close": b["close"]} for b in bars]
            added += 1
    if added:
        _save_cache()
    return added


def get_bars(ticker: str, entry_date: str, allow_download: bool = True) -> list:
    """OHLC-Serie um einen Entry. Cache first, dann optional yfinance."""
    cache = _load_cache()
    k = _key(ticker, entry_date)
    if k in cache:
        return cache[k]
    if not allow_download:
        return []
    bars = _download(ticker, entry_date)
    cache[k] = bars          # auch [] cachen: verhindert Retry-Stuerme
    _save_cache()
    return bars


def atr_at_entry(bars: list, entry_idx: int, period: int = 14) -> float | None:
    """ATR ueber die ``period`` Bars VOR dem Entry (Rekonstruktion)."""
    seg = bars[max(0, entry_idx - period):entry_idx]
    if len(seg) < 5:
        return None
    trs = []
    for i in range(1, len(seg)):
        h, l, pc = seg[i]["high"], seg[i]["low"], seg[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / len(trs) if trs else None


def entry_index(bars: list, entry_date: str) -> int | None:
    """Index des ersten Bars am/nach dem Entry-Datum."""
    d = entry_date[:10]
    for i, b in enumerate(bars):
        if b["time"] >= d:
            return i
    return None


def attach_paths(trades: list, allow_download: bool = True, verbose: bool = True) -> dict:
    """Reichert Trade-Dicts um ``_bars`` / ``_entry_idx`` / ``_atr`` an.

    Mutiert die uebergebenen Dicts. Returns Coverage-Statistik — der Aufrufer
    MUSS die pruefen, bevor er Parameter uebernimmt: ohne Pfade faellt jede
    Bewertung auf die alte, verzerrte Logik zurueck.
    """
    seeded = _seed_from_backtest_variants()
    if seeded and verbose:
        print(f"  📥 {seeded} Pfade aus backtest_variants_result.json uebernommen",
              flush=True)

    ok = no_data = no_atr = 0
    for t in trades:
        ticker, entry_date = t.get("ticker"), t.get("entry_date")
        if not ticker or not entry_date:
            no_data += 1
            continue
        bars = get_bars(ticker, entry_date, allow_download=allow_download)
        idx = entry_index(bars, entry_date) if bars else None
        if idx is None or idx >= len(bars) - 1:
            no_data += 1
            continue
        # ATR bevorzugt aus der DB (der Wert, mit dem live gerechnet wurde),
        # sonst aus den Bars rekonstruiert.
        atr = t.get("atr_at_entry") or atr_at_entry(bars, idx)
        if not atr or atr <= 0:
            no_atr += 1
            continue
        t["_bars"], t["_entry_idx"], t["_atr"] = bars, idx, atr
        ok += 1

    total = len(trades) or 1
    stats = {"total": len(trades), "with_path": ok, "no_data": no_data,
             "no_atr": no_atr, "coverage": ok / total}
    if verbose:
        print(f"  🛤  Pfad-Abdeckung: {ok}/{len(trades)} "
              f"({stats['coverage']:.0%}) | ohne Kursdaten {no_data} | ohne ATR {no_atr}",
              flush=True)
    return stats
