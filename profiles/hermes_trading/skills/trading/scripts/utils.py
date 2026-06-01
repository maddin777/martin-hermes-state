"""
Gemeinsame Hilfsfunktionen für das Trading System.
- Liquiditätsfilter
- Slippage-Modell
- Commission-Berechnung
"""

# ── Logging-Setup ─────────────────────────────────────────────────────────────
import logging
import logging.handlers
import os as _os

def _setup_logging():
    """
    Konfiguriert das zentrale Logging für Hermes Trading.
    - INFO+ → cron.log (rotierend, max 10 MB, 5 Backups)
    - WARNING+ → stderr (für Cron-Mails bei Fehlern)
    - Format: [2026-05-31 04:01:23] INFO signal_manager: Nachricht
    """
    from config import CRON_LOG_PATH
    _os.makedirs(_os.path.dirname(CRON_LOG_PATH), exist_ok=True)

    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    root = logging.getLogger()
    if root.handlers:
        return  # bereits initialisiert

    root.setLevel(logging.DEBUG)

    # Datei-Handler (rotierend)
    fh = logging.handlers.RotatingFileHandler(
        CRON_LOG_PATH, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    fh.setLevel(logging.INFO)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # Stderr-Handler (nur WARNING+)
    sh = logging.StreamHandler()
    sh.setLevel(logging.WARNING)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def get_logger(name: str) -> logging.Logger:
    """
    Gibt einen konfigurierten Logger zurück.
    
    Verwendung in jedem Modul:
        from utils import get_logger
        log = get_logger(__name__)
        log.info("Pipeline gestartet")
        log.warning("Kein Ticker für %s", name)
        log.error("Fehler: %s", e, exc_info=True)
    """
    _setup_logging()
    return logging.getLogger(name)

import yfinance as yf

SLIPPAGE_PCT = 0.001  # 0,1% pro Seite (konservativ für liquide Titel)
COMMISSION_EUR = 1.0  # Trade Republic: 1€ pro Trade


def passes_liquidity_filter(ticker, min_avg_volume_eur=500_000):
    """
    Filtert Ticker mit zu geringem Handelsvolumen.
    min_avg_volume_eur: Mindest-Tagesumsatz in EUR (Preis × Volumen).
    500k EUR = sinnvoller Mindestwert für realistisches Paper-Trading.
    """
    try:
        df = yf.download(ticker, period="30d", interval="1d",
                         progress=False, auto_adjust=True)
        if df.empty or len(df) < 10:
            return False
        close = df["Close"].iloc[:, 0]
        volume = df["Volume"].iloc[:, 0]
        avg_daily_turnover = (close * volume).mean()
        return avg_daily_turnover >= min_avg_volume_eur
    except:
        return False


def apply_slippage(price, direction, is_entry=True):
    """
    Wendet Slippage auf einen Preis an.
    Entry LONG: höherer Kaufpreis
    Entry SHORT: niedrigerer Kaufpreis
    Exit LONG: niedrigerer Verkaufspreis
    Exit SHORT: höherer Verkaufspreis
    """
    if is_entry:
        if direction == "LONG":
            return price * (1 + SLIPPAGE_PCT)
        else:  # SHORT
            return price * (1 - SLIPPAGE_PCT)
    else:  # Exit
        if direction == "LONG":
            return price * (1 - SLIPPAGE_PCT)
        else:  # SHORT
            return price * (1 + SLIPPAGE_PCT)


def calc_pnl_with_costs(entry_price, exit_price, position_size, direction):
    """
    Berechnet PnL in EUR inklusive Slippage und Commission (pro Seite).
    """
    if direction == "LONG":
        effective_entry = entry_price * (1 + SLIPPAGE_PCT)
        effective_exit = exit_price * (1 - SLIPPAGE_PCT)
        pnl_pct = (effective_exit - effective_entry) / effective_entry
    else:  # SHORT
        effective_entry = entry_price * (1 - SLIPPAGE_PCT)
        effective_exit = exit_price * (1 + SLIPPAGE_PCT)
        pnl_pct = (effective_entry - effective_exit) / effective_entry

    pnl_eur = pnl_pct * position_size - COMMISSION_EUR
    return pnl_eur, pnl_pct


# ── Technische Analyse ────────────────────────────────────────────────────────
# Zentrale Implementierung von get_technical_score() – war dreifach vorhanden in
# technical_validator.py, watchlist_manager.py und active_exit_check.py (dort
# als get_tech_status mit abweichendem Rückgabeformat – bleibt eigenständig).

import pandas_ta as ta  # noqa: E402 (nach dem Guard unten sicher)



# ── Retry-Decorator ───────────────────────────────────────────────────────────
import functools as _functools

def retry(max_attempts: int = 3, backoff: float = 2.0, exceptions=(Exception,)):
    """
    Decorator für Retry mit exponenziellem Backoff.
    
    Verwendung:
        @retry(max_attempts=3, backoff=2.0, exceptions=(requests.RequestException,))
        def call_api():
            ...
    """
    def decorator(func):
        @_functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt < max_attempts:
                        wait = backoff ** (attempt - 1)
                        _time.sleep(wait)
                    else:
                        raise
            raise last_exc
        return wrapper
    return decorator

def get_technical_score(ticker):
    """
    Berechnet den technischen Confluence Score für einen Ticker.

    Rückgabe: Dict mit folgenden Keys (oder None bei Fehler / zu wenig Daten):
        ticker, last_price, score, max_score, confidence (0.0–1.0),
        direction (LONG/SHORT/NEUTRAL), reasons, ema20, ema50, rsi

    Wird genutzt von:
        - technical_validator.py  (liest das komplette Dict)
        - watchlist_manager.py    (liest nur confidence + direction)
    """
    try:
        df = yf.download(ticker, period="2y", interval="1d",
                         progress=False, auto_adjust=True)
        df = df.dropna()
        if df.empty or len(df) < 50:
            return None

        close = df["Close"].iloc[:, 0]
        high  = df["High"].iloc[:, 0]
        low   = df["Low"].iloc[:, 0]
        vol   = df["Volume"].iloc[:, 0]

        score     = 0
        max_score = 10
        reasons   = []

        # 1. EMA Stack (20 > 50 > 200) — Gewicht 1
        ema20  = ta.ema(close, length=20)
        ema50  = ta.ema(close, length=50)
        ema200 = ta.ema(close, length=200)
        if ema200 is None or ema200.iloc[-1] is None:
            return None
        if ema20.iloc[-1] > ema50.iloc[-1] > ema200.iloc[-1]:
            score += 1
            reasons.append("EMA Stack bullish ✓")
        elif ema20.iloc[-1] < ema50.iloc[-1] < ema200.iloc[-1]:
            score -= 1
            reasons.append("EMA Stack bearish ✗")

        # 2. RSI — differenziert
        rsi     = ta.rsi(close, length=14)
        rsi_val = rsi.iloc[-1]
        if 50 < rsi_val < 60:
            score += 2
            reasons.append(f"RSI ideal ({rsi_val:.0f}) ✓✓")
        elif 40 < rsi_val < 70:
            score += 1
            reasons.append(f"RSI gesund ({rsi_val:.0f}) ✓")
        elif rsi_val > 75:
            score -= 2
            reasons.append(f"RSI überkauft ({rsi_val:.0f}) ✗✗")
        elif rsi_val < 25:
            score -= 2
            reasons.append(f"RSI stark überverkauft ({rsi_val:.0f}) ✗✗")
        elif rsi_val < 35:
            reasons.append(f"RSI leicht überverkauft ({rsi_val:.0f})")

        # 3. MACD Histogram — Trend und Vorzeichen
        macd     = ta.macd(close)
        hist_col = [c for c in macd.columns if "MACDh" in c][0]
        if macd[hist_col].iloc[-1] > 0 and macd[hist_col].iloc[-1] > macd[hist_col].iloc[-2]:
            score += 2
            reasons.append("MACD positiv + steigend ✓✓")
        elif macd[hist_col].iloc[-1] > macd[hist_col].iloc[-2]:
            score += 1
            reasons.append("MACD Momentum steigt ✓")
        elif macd[hist_col].iloc[-1] < 0 and macd[hist_col].iloc[-1] < macd[hist_col].iloc[-2]:
            score -= 2
            reasons.append("MACD negativ + fallend ✗✗")

        # 4. Preis vs. EMA50 — mit Abstandsgewichtung
        last_close = close.iloc[-1]
        dist_ema50 = (last_close - ema50.iloc[-1]) / ema50.iloc[-1]
        if dist_ema50 > 0.05:
            score += 1
            reasons.append("Preis deutlich über EMA50 ✓")
        elif dist_ema50 > 0:
            score += 0.5
            reasons.append("Preis über EMA50 ✓")
        elif dist_ema50 < -0.05:
            score -= 1
            reasons.append("Preis deutlich unter EMA50 ✗")
        else:
            score -= 0.5
            reasons.append("Preis unter EMA50 ✗")

        # 5. Volumen-Trend
        vol_avg20 = vol.rolling(20).mean().iloc[-1]
        vol_avg5  = vol.rolling(5).mean().iloc[-1]
        if vol_avg5 > vol_avg20 * 1.5:
            score += 1.5
            reasons.append("Volumen stark erhöht ✓✓")
        elif vol_avg5 > vol_avg20 * 1.2:
            score += 1
            reasons.append("Volumen erhöht ✓")

        # 6. Weekly Trend — Gewicht 1
        df_w = yf.download(ticker, period="1y", interval="1wk",
                           progress=False, auto_adjust=True)
        df_w = df_w.dropna()
        if not df_w.empty and len(df_w) > 20:
            close_w = df_w["Close"].iloc[:, 0]
            ema20_w = ta.ema(close_w, length=20)
            if close_w.iloc[-1] > ema20_w.iloc[-1]:
                score += 1
                reasons.append("Weekly Trend bullish ✓")
            else:
                score -= 1
                reasons.append("Weekly Trend bearish ✗")

        # 7. ADX (Trendstärke)
        try:
            adx_df  = ta.adx(high, low, close, length=14)
            adx_val = adx_df["ADX_14"].iloc[-1]
            if adx_val > 25:
                score += 1
                reasons.append(f"ADX starker Trend ({adx_val:.0f}) ✓")
            elif adx_val < 15:
                score -= 0.5
                reasons.append(f"ADX kein Trend ({adx_val:.0f}) ✗")
        except Exception:
            pass

        # Normalisierung: -10…+10 → 0.0…1.0
        confidence = round((score + max_score) / (2 * max_score), 3)
        confidence = max(0.0, min(1.0, confidence))
        direction  = "LONG" if score >= 2 else "SHORT" if score <= -2 else "NEUTRAL"

        return {
            "ticker":     ticker,
            "last_price": round(float(last_close), 2),
            "score":      score,
            "max_score":  max_score,
            "confidence": confidence,
            "direction":  direction,
            "reasons":    reasons,
            "ema20":      round(float(ema20.iloc[-1]), 2),
            "ema50":      round(float(ema50.iloc[-1]), 2),
            "rsi":        round(float(rsi_val), 1),
        }

    except Exception as e:
        print(f"     ✗ Technische Analyse Fehler ({ticker}): {e}", flush=True)
        return None


# ── Preis-Cache & Batch-Download ─────────────────────────────────────────────

import time as _time

_price_cache: dict = {}   # ticker → (timestamp, close, atr, df)
_PRICE_TTL = 300          # 5 Minuten

def _cache_key(ticker: str) -> str:
    return ticker.upper()

def get_price_data_cached(ticker: str):
    """
    Gibt (close, atr, df) für einen Ticker zurück – mit 5-min TTL-Cache.
    Ersetzt direkte yf.download()-Aufrufe in signal_manager, active_exit_check etc.
    """
    key = _cache_key(ticker)
    now = _time.time()
    if key in _price_cache:
        ts, close, atr_val, df = _price_cache[key]
        if now - ts < _PRICE_TTL:
            return close, atr_val, df

    try:
        df = yf.download(ticker, period="2y", interval="1d",
                         progress=False, auto_adjust=True)
        df = df.dropna()
        if df.empty or len(df) < 20:
            return None, None, None
        close_s = df["Close"].iloc[:, 0]
        high_s  = df["High"].iloc[:, 0]
        low_s   = df["Low"].iloc[:, 0]
        atr_s   = ta.atr(high_s, low_s, close_s, length=14)
        close_val = float(close_s.iloc[-1])
        atr_val   = float(atr_s.iloc[-1])
        _price_cache[key] = (now, close_val, atr_val, df)
        return close_val, atr_val, df
    except Exception as e:
        print(f"     ⚠ Preisfehler ({ticker}): {e}", flush=True)
        return None, None, None


def prefetch_prices(tickers: list):
    """
    Lädt Kursdaten für mehrere Ticker in einem Batch-Download.
    Befüllt den Cache vorab – danach sind get_price_data_cached()-Aufrufe
    sofort (aus dem Cache) beantwortet.

    Aufruf z.B. am Anfang von signal_manager.main():
        from utils import prefetch_prices
        prefetch_prices([p["ticker"] for p in open_positions])
    """
    tickers = [t for t in tickers if t]
    if not tickers:
        return
    print(f"  📦 Batch-Download für {len(tickers)} Ticker...", flush=True)
    try:
        data = yf.download(
            tickers, period="2y", interval="1d",
            progress=False, auto_adjust=True, group_by="ticker"
        )
        now = _time.time()
        for ticker in tickers:
            try:
                if len(tickers) == 1:
                    df = data
                else:
                    df = data[ticker]
                df = df.dropna()
                if df.empty or len(df) < 20:
                    continue
                close_s = df["Close"]
                high_s  = df["High"]
                low_s   = df["Low"]
                if hasattr(close_s, 'iloc') and close_s.ndim > 1:
                    close_s = close_s.iloc[:, 0]
                    high_s  = high_s.iloc[:, 0]
                    low_s   = low_s.iloc[:, 0]
                atr_s     = ta.atr(high_s, low_s, close_s, length=14)
                close_val = float(close_s.iloc[-1])
                atr_val   = float(atr_s.iloc[-1])
                _price_cache[_cache_key(ticker)] = (now, close_val, atr_val, df)
            except Exception:
                pass  # Einzelner Fehler überspringen, andere laufen weiter
        print(f"  ✅ Cache befüllt: {len(_price_cache)} Einträge", flush=True)
    except Exception as e:
        print(f"  ⚠ Batch-Download Fehler: {e} – falle auf Einzelabfragen zurück", flush=True)
