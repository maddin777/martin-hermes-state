"""
Gemeinsame Hilfsfunktionen für das Trading System.
- Logging-Setup
- FX-Umrechnung (EUR-Referenzkurse via Frankfurter API + GBp-Handling)
- Liquiditätsfilter (nutzt TTL-Cache)
- Slippage-Modell
- Commission-Berechnung
- Technischer Confluence Score (get_technical_score)
- Preis-Cache & Batch-Download (get_price_data_cached / prefetch_prices)
- Retry-Decorator
"""

# ── Logging-Setup ─────────────────────────────────────────────────────────────
import logging
import logging.handlers
import os as _os
import time as _time

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


# ── Imports ───────────────────────────────────────────────────────────────────
import functools as _functools
import requests as _requests
import yfinance as yf
import pandas_ta as ta


# ── Konstanten ────────────────────────────────────────────────────────────────
SLIPPAGE_PCT   = 0.001   # 0,1% pro Seite (konservativ für liquide Titel)
COMMISSION_EUR = 1.0     # Trade Republic: 1€ pro Trade


# ── FX-Umrechnung ─────────────────────────────────────────────────────────────
_fx_cache: dict = {}
_fx_cache_date = None

_FX_FALLBACK = {
    "EUR": 1.0, "USD": 1.08, "JPY": 156.0,
    "GBP": 0.85, "NOK": 11.5, "CHF": 0.95,
    "SEK": 11.2, "DKK": 7.46, "CAD": 1.47,
    "AUD": 1.65, "HKD": 8.43, "SGD": 1.44,
}


def _fetch_fx_rates() -> dict:
    """Holt EUR-Referenzkurse von Frankfurter API (kostenlos, kein Key)."""
    global _fx_cache, _fx_cache_date
    from datetime import date
    today = date.today()
    if _fx_cache and _fx_cache_date == today:
        return _fx_cache
    try:
        resp = _requests.get("https://api.frankfurter.app/latest", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        rates = data.get("rates", {})
        rates["EUR"] = 1.0
        _fx_cache = rates
        _fx_cache_date = today
        return rates
    except Exception as e:
        _log = get_logger("utils.fx")
        _log.warning("FX-Rates nicht abrufbar (%s) – nutze Fallback", e)
        return _fx_cache or _FX_FALLBACK.copy()


def get_fx_rate_to_eur(currency: str) -> float:
    """
    Gibt Kurs zurück um einen Betrag VON 'currency' IN EUR umzurechnen.
    Beispiel: get_fx_rate_to_eur("USD") → ~0.926 (= 1/1.08)
    """
    currency = currency.upper()
    if currency == "EUR":
        return 1.0
    rates = _fetch_fx_rates()
    eur_per_unit = rates.get(currency)
    if not eur_per_unit or eur_per_unit <= 0:
        # #15: Unbekannte Währung nicht mehr still als 1:1 behandeln.
        # Frankfurter kennt ~30 Währungen; fehlt eine (z.B. KRW im Fallback),
        # wäre 1.0 grob falsch. Fallback-Tabelle prüfen, sonst laut warnen.
        fb = _FX_FALLBACK.get(currency)
        if fb and fb > 0:
            return 1.0 / fb
        _log = get_logger("utils.fx")
        _log.warning("Unbekannte Währung '%s' – kein FX-Kurs, nutze 1.0 (Bewertung "
                     "potentiell falsch, Ticker sollte verworfen werden)", currency)
        return 1.0
    # rates ist EUR → currency, wir wollen currency → EUR
    return 1.0 / eur_per_unit


def ticker_to_currency(ticker: str) -> str:
    """
    Leitet die Handelswährung eines Tickers aus dem Börsensuffix ab.

    Wichtig: Londoner Börse (.L) handelt in GBp (Pence), nicht GBP.
    yfinance liefert für .L-Ticker Preise in GBp → Faktor 100 nötig.
    Alle anderen Preise kommen in der nativen Währung der Primärbörse.

    Rückgabe: Währungs-Code (z.B. "USD", "EUR", "GBP", "GBp", "CHF", …)
    """
    if not ticker:
        return "EUR"
    ticker = ticker.upper()

    # Krypto/FX-Paare früh raus
    if ticker.endswith(("-USD", "-EUR", "-USDT", "-BTC")):
        return "USD"

    suffix = ticker.split(".")[-1] if "." in ticker else ""

    suffix_map = {
        # EUR-Börsen
        "DE": "EUR", "PA": "EUR", "AS": "EUR", "HE": "EUR",
        "BR": "EUR", "VI": "EUR", "MI": "EUR", "SW": "CHF",
        "ST": "SEK", "CO": "DKK", "MX": "EUR",
        # Deutsche Nebenbörsen – ebenfalls EUR
        "MU": "EUR", "F": "EUR", "SG": "EUR", "BE": "EUR",
        "DU": "EUR", "BM": "EUR", "HA": "EUR", "HM": "EUR",
        # London: Preise in GBp (Pence!) → Umrechnung: GBp / 100 = GBP
        "L": "GBp", "IL": "GBp",
        # Sonstige
        "TO": "CAD", "V": "CAD", "AX": "AUD", "T": "JPY",
        "KS": "KRW", "HK": "HKD", "SI": "SGD",
    }

    if suffix in suffix_map:
        return suffix_map[suffix]

    # Kein Suffix → US-Börse
    if ticker.isalpha() and len(ticker) <= 5:
        return "USD"

    return "USD"  # konservativer Default


def price_to_eur(price: float, ticker: str) -> float:
    """
    Rechnet einen yfinance-Preis in EUR um.

    Berücksichtigt GBp (London): Preise werden durch 100 geteilt bevor
    die GBP→EUR-Konversion angewandt wird.
    """
    currency = ticker_to_currency(ticker)
    if currency == "EUR":
        return price
    if currency == "GBp":
        # London Preise kommen in Pence → erst in GBP umrechnen
        price_gbp = price / 100.0
        return price_gbp * get_fx_rate_to_eur("GBP")
    return price * get_fx_rate_to_eur(currency)


def position_size_in_shares(position_eur: float, price: float, ticker: str) -> float:
    """
    Rechnet eine Positionsgröße in EUR in Stückzahl um.
    Berücksichtigt FX damit price_in_native_currency korrekt skaliert wird.
    """
    price_eur = price_to_eur(price, ticker)
    if price_eur <= 0:
        return 0.0
    return position_eur / price_eur


# ── Gemeinsames Portfolio-Lock (#14) ──────────────────────────────────────────
import contextlib as _contextlib

@_contextlib.contextmanager
def portfolio_lock(blocking: bool = True):
    """
    Prozessübergreifendes Advisory-Lock für alle Skripte, die positions/portfolio
    schreiben (signal_manager, active_exit_check, breaking_news_monitor,
    drawdown_monitor). Verhindert Lost-Updates auf portfolio.cash bei zeitgleichem
    Lauf (WAL serialisiert nur einzelne Writes, nicht die Read-Modify-Write-Logik).

    blocking=True: wartet, bis das Lock frei ist (Skripte sind kurzlebig).
    blocking=False: yield True/False je nach Erfolg (Aufrufer prüft).
    """
    import fcntl
    from config import DATA_DIR
    _os.makedirs(DATA_DIR, exist_ok=True)
    lock_path = _os.path.join(DATA_DIR, "portfolio.lock")
    fh = open(lock_path, "w")
    acquired = False
    try:
        if blocking:
            fcntl.flock(fh, fcntl.LOCK_EX)
            acquired = True
        else:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except BlockingIOError:
                acquired = False
        yield acquired
    finally:
        if acquired:
            fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()


def turnover_to_eur(price: float, volume: float, ticker: str) -> float:
    """Tagesumsatz (Preis × Volumen) in EUR."""
    return price_to_eur(price, ticker) * volume


# ── Mark-to-Market (#3) ───────────────────────────────────────────────────────
def position_current_value_eur(pos, current_price_native) -> float:
    """
    Aktueller rückbuchbarer EUR-Wert einer offenen Position bei current_price.

    Entspricht dem, was beim Sofort-Close als Cash zurückkäme:
    position_size (Einstand) + unrealisierter PnL. Für LONG und SHORT gleich
    modelliert (bei Entry wurde für beide position_size vom Cash abgezogen).

    pos: sqlite Row/dict mit direction, entry_price, position_size.
    current_price_native: Kurs in der Heimwährung des Tickers (PnL-Ratio ist
    FX-invariant, daher keine EUR-Umrechnung nötig).
    Fallback bei fehlendem Kurs: Einstand (position_size).
    """
    size  = (pos["position_size"] if "position_size" in pos.keys() else pos.get("position_size")) or 0
    entry = (pos["entry_price"]   if "entry_price"   in pos.keys() else pos.get("entry_price"))   or 0
    if not current_price_native or not entry:
        return size
    direction = pos["direction"] if "direction" in pos.keys() else pos.get("direction")
    if direction == "LONG":
        pnl_pct = (current_price_native - entry) / entry
    else:
        pnl_pct = (entry - current_price_native) / entry
    return size + pnl_pct * size


def open_positions_market_value_eur(positions) -> float:
    """
    Summiert den Mark-to-Market-Wert aller offenen Positionen (EUR).
    Nutzt get_price_data_cached – Aufrufer sollte vorher prefetch_prices()
    aufrufen, damit keine Einzel-Downloads anfallen.
    """
    total = 0.0
    for pos in positions:
        ticker = pos["ticker"] if "ticker" in pos.keys() else pos.get("ticker")
        close, _, _ = get_price_data_cached(ticker) if ticker else (None, None, None)
        total += position_current_value_eur(pos, close)
    return total


# ── Retry-Decorator ───────────────────────────────────────────────────────────

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


# ── Liquiditätsfilter ────────────────────────────────────────────────────────

def passes_liquidity_filter(ticker, min_avg_volume_eur=500_000):
    """
    Filtert Ticker mit zu geringem Handelsvolumen.
    Nutzt TTL-Cache (get_price_data_cached) um doppelte yf.download-Calls zu vermeiden.
    Umsatz wird in EUR umgerechnet (FX + GBp-Handling).
    """
    try:
        _, _, df = get_price_data_cached(ticker)
        if df is None or df.empty or len(df) < 10:
            return False
        close  = df["Close"].iloc[:, 0] if df["Close"].ndim > 1 else df["Close"]
        volume = df["Volume"].iloc[:, 0] if df["Volume"].ndim > 1 else df["Volume"]
        # Umsatz in Heimwährung, dann in EUR
        avg_daily_turnover = turnover_to_eur(
            float(close.tail(20).mean()), float(volume.tail(20).mean()), ticker
        )
        return avg_daily_turnover >= min_avg_volume_eur
    except Exception as exc:
        _log = get_logger("utils.liquidity")
        _log.warning("Liquiditätsfilter Fehler (%s): %s", ticker, exc)
        return False


# ── Slippage-Modell ───────────────────────────────────────────────────────────

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


def realized_pnl_from_effective_entry(entry_effective_price, current_price,
                                      position_size, direction):
    """
    #11: Einheitliche Exit-PnL-Berechnung für BEIDE Exit-Engines
    (signal_manager.check_open_positions + active_exit_check).

    Wichtig: entry_price wird bereits SLIPPAGE-behaftet in der DB gespeichert
    (effective_entry beim Open). Daher hier NUR Exit-Slippage + Commission
    anwenden – sonst zählt die Entry-Slippage doppelt (alter Bug in
    active_exit_check) bzw. fehlt ganz (alter Zustand in signal_manager).
    """
    ex = apply_slippage(current_price, direction, is_entry=False)
    if direction == "LONG":
        pnl_pct = (ex - entry_effective_price) / entry_effective_price
    else:
        pnl_pct = (entry_effective_price - ex) / entry_effective_price
    pnl_eur = pnl_pct * position_size - COMMISSION_EUR
    return pnl_eur, pnl_pct


def calc_pnl_with_costs(entry_price, exit_price, position_size, direction):
    """
    Berechnet PnL in EUR inklusive Slippage und Commission (pro Seite).
    entry_price / exit_price müssen bereits in EUR übergeben werden.
    """
    if direction == "LONG":
        effective_entry = entry_price * (1 + SLIPPAGE_PCT)
        effective_exit  = exit_price  * (1 - SLIPPAGE_PCT)
        pnl_pct = (effective_exit - effective_entry) / effective_entry
    else:  # SHORT
        effective_entry = entry_price * (1 - SLIPPAGE_PCT)
        effective_exit  = exit_price  * (1 + SLIPPAGE_PCT)
        pnl_pct = (effective_entry - effective_exit) / effective_entry

    pnl_eur = pnl_pct * position_size - COMMISSION_EUR
    return pnl_eur, pnl_pct


# ── Technische Analyse ────────────────────────────────────────────────────────
# Zentrale Implementierung von get_technical_score().

def get_technical_score(ticker):
    """
    Berechnet den technischen Confluence Score für einen Ticker.

    Rückgabe: Dict mit folgenden Keys (oder None bei Fehler / zu wenig Daten):
        ticker, last_price, last_price_eur, score, max_score,
        confidence (0.0–1.0), direction (LONG/SHORT/NEUTRAL),
        reasons, ema20, ema50, rsi, weekly_trend

    Wird genutzt von:
        - technical_validator.py  (liest das komplette Dict)
        - watchlist_manager.py    (liest nur confidence + direction)
    """
    try:
        _, _, df = get_price_data_cached(ticker)
        if df is None or df.empty or len(df) < 50:
            return None

        close = df["Close"].iloc[:, 0] if df["Close"].ndim > 1 else df["Close"]
        high  = df["High"].iloc[:, 0]  if df["High"].ndim  > 1 else df["High"]
        low   = df["Low"].iloc[:, 0]   if df["Low"].ndim   > 1 else df["Low"]
        vol   = df["Volume"].iloc[:, 0] if df["Volume"].ndim > 1 else df["Volume"]

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

        # 6. Weekly Trend — Gewicht 1: Resample daily series locally
        close_w = close.resample('W').last()
        weekly_trend = "neutral"
        if len(close_w) > 20:
            ema20_w = ta.ema(close_w, length=20)
            if ema20_w is not None and not ema20_w.empty and close_w.iloc[-1] > ema20_w.iloc[-1]:
                score += 1
                reasons.append("Weekly Trend bullish ✓")
                weekly_trend = "bullish"
            elif ema20_w is not None and not ema20_w.empty:
                score -= 1
                reasons.append("Weekly Trend bearish ✗")
                weekly_trend = "bearish"

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

        # 8. Crabel Kontraktions-Patterns — Bonus NUR in Trendrichtung.
        # Crabel: Kontraktion in Richtung des übergeordneten Trends handeln.
        # Ohne klaren EMA-Stack kein Bonus (Kompression ohne Trend = Rauschen).
        # WS-Tag (Wide Spread): Expansion bereits erfolgt → Score Richtung
        # neutral dämpfen, Entry käme zu spät.
        crabel = get_crabel_patterns(ticker)
        if crabel:
            trend_bull = ema20.iloc[-1] > ema50.iloc[-1] > ema200.iloc[-1]
            trend_bear = ema20.iloc[-1] < ema50.iloc[-1] < ema200.iloc[-1]
            bonus, label = 0.0, None
            if crabel["id_nr4"]:
                bonus, label = 1.5, "ID/NR4"
            elif crabel["nr7"]:
                bonus, label = 1.0, "NR7"
            elif crabel["nr4"] or crabel["inside_day"] or crabel["two_bar_nr"]:
                bonus, label = 0.5, (crabel["patterns"][0] if crabel["patterns"] else "NR4")
            if bonus and trend_bull:
                score += bonus
                reasons.append(f"Crabel {label} im Aufwärtstrend ✓")
            elif bonus and trend_bear:
                score -= bonus
                reasons.append(f"Crabel {label} im Abwärtstrend ✗")
            if crabel["wide_spread"]:
                if trend_bull:
                    score -= 1
                    reasons.append("Crabel WS-Tag: Expansion bereits erfolgt ✗")
                elif trend_bear:
                    score += 1
                    reasons.append("Crabel WS-Tag: Expansion bereits erfolgt ✗")

        # 9. Donchian-Breakout (Turtle-Konfluenz) — Bonus in Ausbruchsrichtung.
        # Ein neues N-Tage-Hoch/Tief IST das Trendbestätigungs-Signal (Donchian
        # war die Grundlage des Turtle-Systems). Wirkt hier als ZUSÄTZLICHES
        # Konfluenz-Kriterium neben EMA/RSI/MACD, nicht als alleiniges Signal.
        # Gewichtung bewusst moderat (±1.0 max), damit ein reiner Range-Ausbruch
        # ohne sonstige Bestätigung keinen Trade allein trägt. Wie beim Crabel-
        # Bonus wird max_score NICHT angehoben (confidence-Clamp fängt die Summe).
        donchian = get_donchian_breakout(ticker)
        if donchian:
            if donchian["breakout_long_slow"]:
                score += 1.0
                reasons.append("Donchian 55-Tage-Hoch (S2-Ausbruch) ✓✓")
            elif donchian["breakout_long"]:
                score += 0.5
                reasons.append("Donchian 20-Tage-Hoch (S1-Ausbruch) ✓")
            elif donchian["breakout_short_slow"]:
                score -= 1.0
                reasons.append("Donchian 55-Tage-Tief (S2-Ausbruch) ✗✗")
            elif donchian["breakout_short"]:
                score -= 0.5
                reasons.append("Donchian 20-Tage-Tief (S1-Ausbruch) ✗")

        # Normalisierung: -10…+10 → 0.0…1.0
        # (max_score bleibt bewusst 10: Crabel-Bonus max ±1.5, Donchian ±1.0,
        #  Summe der Maximal-Gewichte war schon vorher ~9.5 – confidence wird
        #  geclampt. max_score anzuheben würde ALLE Confidences Richtung 0.5
        #  stauchen und die kalibrierten tech_score-Schwellen im signal_manager
        #  brechen.)
        confidence = round((score + max_score) / (2 * max_score), 3)
        confidence = max(0.0, min(1.0, confidence))
        direction  = "LONG" if score >= 2 else "SHORT" if score <= -2 else "NEUTRAL"

        last_price_eur = price_to_eur(float(last_close), ticker)

        return {
            "ticker":        ticker,
            "last_price":    round(float(last_close), 4),
            "last_price_eur": round(last_price_eur, 2),
            "score":         score,
            "max_score":     max_score,
            "confidence":    confidence,
            "direction":     direction,
            "reasons":       reasons,
            "ema20":         round(float(ema20.iloc[-1]), 4),
            "ema50":         round(float(ema50.iloc[-1]), 4),
            "rsi":           round(float(rsi_val), 1),
            "weekly_trend":  weekly_trend,
            "crabel":        crabel,   # Pattern-Flags + Breakout-Level (oder None)
            "donchian":      donchian, # Donchian-Kanäle + Breakout-Flags (oder None)
        }

    except Exception as e:
        _log = get_logger("utils.tech")
        _log.warning("Technische Analyse Fehler (%s): %s", ticker, e)
        return None


# ── Crabel Short-Term Price Patterns ─────────────────────────────────────────
# Daily-Bar-Adaption der Kontraktions-Patterns aus Toby Crabel,
# "Day Trading with Short Term Price Patterns and Opening Range Breakout" (1990).
# Kernprinzip: Volatilitäts-Kontraktion (enge Tage) → erhöhte Wahrscheinlichkeit
# einer Expansion (Trendtag). Hermes handelt EOD, daher wird der klassische
# Intraday-ORB als Bestätigungsprüfung adaptiert (siehe signal_manager).

def get_crabel_patterns(ticker: str, stretch_len: int = 10):
    """
    Erkennt Crabel-Kontraktions-Patterns auf dem letzten ABGESCHLOSSENEN Tagesbar.

    Nutzt get_price_data_cached() – bei bereits geladenem Ticker (z.B. nach
    get_technical_score) entstehen KEINE zusätzlichen API-Calls.

    Läuft der Handelstag noch (letzter Bar = heute), wird dieser unfertige Bar
    für die Pattern-Erkennung verworfen: Range/High/Low eines laufenden Tages
    sind noch nicht final und würden NR7/ID verfälschen.

    Patterns (alle auf dem letzten abgeschlossenen Bar):
        nr4         Range ist enger als die der 3 Vortage (Narrow Range 4)
        nr7         Range ist enger als die der 6 Vortage (Narrow Range 7)
        inside_day  High < Vortages-High UND Low > Vortages-Low
        id_nr4      Inside Day + NR4 kombiniert (Crabels stärkstes Setup)
        two_bar_nr  Engste 2-Tages-Range der letzten 20 Tage
        wide_spread Range > 2× 10-Tage-Ø-Range (Expansion bereits erfolgt)
        contraction True wenn mind. ein Kontraktions-Pattern aktiv

    Breakout-Level (EOD-ORB-Adaption, Heimwährung des Tickers):
        stretch              10-Tage-Ø der Distanz Open → näheres Tagesextrem
        breakout_long_level  ref_high + stretch  (LONG-Bestätigung)
        breakout_short_level ref_low  - stretch  (SHORT-Bestätigung)
        ref_high / ref_low   High/Low des letzten abgeschlossenen Bars

    Rückgabe: Dict (JSON-serialisierbar, reine Python-Typen) oder None.
    """
    import numpy as _np
    from datetime import date as _date
    try:
        _, _, df = get_price_data_cached(ticker)
        if df is None or df.empty or len(df) < 30 or "Open" not in df.columns:
            return None

        o = df["Open"].iloc[:, 0]  if df["Open"].ndim  > 1 else df["Open"]
        h = df["High"].iloc[:, 0]  if df["High"].ndim  > 1 else df["High"]
        l = df["Low"].iloc[:, 0]   if df["Low"].ndim   > 1 else df["Low"]

        # Laufenden (unfertigen) Bar abschneiden: Pattern nur auf finalen Bars
        try:
            is_partial = df.index[-1].date() >= _date.today()
        except Exception:
            is_partial = False
        if is_partial:
            o, h, l = o.iloc[:-1], h.iloc[:-1], l.iloc[:-1]
        if len(h) < 25:
            return None

        rng      = h - l
        last_rng = float(rng.iloc[-1])

        nr4 = last_rng < float(rng.iloc[-4:-1].min())
        nr7 = last_rng < float(rng.iloc[-7:-1].min())
        inside_day = (float(h.iloc[-1]) < float(h.iloc[-2])
                      and float(l.iloc[-1]) > float(l.iloc[-2]))
        id_nr4 = inside_day and nr4

        # 2Bar NR: engste 2-Tages-Range im 20-Tage-Fenster
        tb = h.rolling(2).max() - l.rolling(2).min()
        two_bar_nr = float(tb.iloc[-1]) < float(tb.iloc[-20:-1].min())

        # Wide Spread: Expansion bereits passiert → Entry wäre zu spät
        wide_spread = last_rng > 2.0 * float(rng.iloc[-11:-1].mean())

        # Stretch: Ø-Distanz vom Open zum NÄHEREN Tagesextrem (Crabel-Definition)
        stretch_series = _np.minimum(o - l, h - o).clip(lower=0)
        stretch = float(stretch_series.tail(stretch_len).mean())

        ref_high = float(h.iloc[-1])
        ref_low  = float(l.iloc[-1])

        patterns = [name for name, flag in (
            ("ID/NR4", id_nr4), ("NR7", nr7), ("NR4", nr4),
            ("Inside Day", inside_day), ("2Bar NR", two_bar_nr),
        ) if flag]

        return {
            "nr4":                  bool(nr4),
            "nr7":                  bool(nr7),
            "inside_day":           bool(inside_day),
            "id_nr4":               bool(id_nr4),
            "two_bar_nr":           bool(two_bar_nr),
            "wide_spread":          bool(wide_spread),
            "contraction":          bool(nr4 or nr7 or inside_day or two_bar_nr),
            "patterns":             patterns,
            "stretch":              round(stretch, 4),
            "ref_high":             round(ref_high, 4),
            "ref_low":              round(ref_low, 4),
            "breakout_long_level":  round(ref_high + stretch, 4),
            "breakout_short_level": round(ref_low - stretch, 4),
        }
    except Exception as e:
        _log = get_logger("utils.crabel")
        _log.warning("Crabel-Pattern Fehler (%s): %s", ticker, e)
        return None


# ── Donchian-Channel-Breakout (Turtle) ───────────────────────────────────────
# Kernindikator des Turtle-Systems (Richard Dennis / William Eckhardt, 1983).
# S1 (schnell): Entry 20-Tage-Ausbruch, Exit 10-Tage-Gegen-Extrem.
# S2 (langsam): Entry 55-Tage-Ausbruch, Exit 20-Tage-Gegen-Extrem.
# Hier nur als KONFLUENZ-Baustein neben den bestehenden Indikatoren –
# das eigentliche Turtle-System handelte einen diversifizierten Futures-Korb,
# nicht einen korrelierten Aktien-Basket. Deshalb bewusst kein Standalone-Trigger.

def get_donchian_breakout(ticker: str, entry_period: int = 20,
                          exit_period: int = 10, slow_period: int = 55):
    """
    Berechnet Donchian-Kanäle und Breakout-Flags im Turtle-Stil.

    Nutzt get_price_data_cached() – bei bereits geladenem Ticker (z.B. nach
    get_technical_score) entstehen KEINE zusätzlichen API-Calls.

    Der letzte (evtl. unfertige) Tagesbar wird für die Kanal-REFERENZ
    ausgeschlossen: ein Breakout gilt erst, wenn der aktuelle Close das Extrem
    der N vorherigen ABGESCHLOSSENEN Bars überschreitet (verhindert, dass ein
    laufender Tag sein eigenes Kanal-Extrem setzt und den Ausbruch maskiert).

    Alle Levels in der Heimwährung des Tickers (nicht EUR-umgerechnet) – für
    Trailing/Vergleich mit Kursen in derselben Skala nutzbar.

    Rückgabe: Dict (JSON-serialisierbar) oder None.
        entry_period / exit_period / slow_period  verwendete Lookbacks
        upper_20 / lower_20    Donchian-Grenzen über entry_period
        upper_55 / lower_55    Donchian-Grenzen über slow_period
        exit_low / exit_high   Gegen-Extrem über exit_period (Trailing-Referenz)
        breakout_long          Close > 20-Tage-Hoch (S1 Long-Trigger)
        breakout_short         Close < 20-Tage-Tief (S1 Short-Trigger)
        breakout_long_slow     Close > 55-Tage-Hoch (S2 Long-Trigger)
        breakout_short_slow    Close < 55-Tage-Tief (S2 Short-Trigger)
        last_close             letzter Close (Heimwährung)
    """
    from datetime import date as _date
    try:
        _, _, df = get_price_data_cached(ticker)
        if df is None or df.empty or len(df) < slow_period + 5:
            return None

        high  = df["High"].iloc[:, 0]  if df["High"].ndim  > 1 else df["High"]
        low   = df["Low"].iloc[:, 0]   if df["Low"].ndim   > 1 else df["Low"]
        close = df["Close"].iloc[:, 0] if df["Close"].ndim > 1 else df["Close"]

        last_close = float(close.iloc[-1])

        # Laufenden (unfertigen) Bar aus der Kanal-Referenz herausnehmen
        try:
            is_partial = df.index[-1].date() >= _date.today()
        except Exception:
            is_partial = False
        h = high.iloc[:-1] if is_partial else high
        l = low.iloc[:-1]  if is_partial else low
        if len(h) < slow_period + 1:
            return None

        upper_20 = float(h.iloc[-entry_period:].max())
        lower_20 = float(l.iloc[-entry_period:].min())
        upper_55 = float(h.iloc[-slow_period:].max())
        lower_55 = float(l.iloc[-slow_period:].min())
        exit_low  = float(l.iloc[-exit_period:].min())
        exit_high = float(h.iloc[-exit_period:].max())

        return {
            "entry_period":        entry_period,
            "exit_period":         exit_period,
            "slow_period":         slow_period,
            "upper_20":            round(upper_20, 4),
            "lower_20":            round(lower_20, 4),
            "upper_55":            round(upper_55, 4),
            "lower_55":            round(lower_55, 4),
            "exit_low":            round(exit_low, 4),
            "exit_high":           round(exit_high, 4),
            "breakout_long":       bool(last_close > upper_20),
            "breakout_short":      bool(last_close < lower_20),
            "breakout_long_slow":  bool(last_close > upper_55),
            "breakout_short_slow": bool(last_close < lower_55),
            "last_close":          round(last_close, 4),
        }
    except Exception as e:
        _log = get_logger("utils.donchian")
        _log.warning("Donchian-Breakout Fehler (%s): %s", ticker, e)
        return None


# ── Preis-Cache & Batch-Download ─────────────────────────────────────────────

_price_cache: dict = {}   # ticker → (timestamp, close, atr, df)
_PRICE_TTL = 300          # 5 Minuten
_PRICE_CACHE_MAX = 400    # #17: harte Obergrenze gegen unbegrenztes Wachstum


def _cache_key(ticker: str) -> str:
    return ticker.upper()


def _cache_store(key, value):
    """Schreibt in _price_cache und evictet abgelaufene bzw. älteste Einträge (#17)."""
    now = _time.time()
    if len(_price_cache) >= _PRICE_CACHE_MAX:
        # Zuerst abgelaufene entfernen
        stale = [k for k, v in _price_cache.items() if now - v[0] >= _PRICE_TTL]
        for k in stale:
            _price_cache.pop(k, None)
        # Falls immer noch voll: ältesten Eintrag verdrängen
        if len(_price_cache) >= _PRICE_CACHE_MAX:
            oldest = min(_price_cache, key=lambda k: _price_cache[k][0])
            _price_cache.pop(oldest, None)
    _price_cache[key] = value


def get_price_data_cached(ticker: str):
    """
    Gibt (close_native, atr_native, df) für einen Ticker zurück – mit 5-min TTL-Cache.
    close_native / atr_native sind in der Heimwährung des Tickers (nicht EUR-umgerechnet).
    Für EUR-Beträge price_to_eur() verwenden.
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
        close_s = df["Close"].iloc[:, 0] if df["Close"].ndim > 1 else df["Close"]
        high_s  = df["High"].iloc[:, 0]  if df["High"].ndim  > 1 else df["High"]
        low_s   = df["Low"].iloc[:, 0]   if df["Low"].ndim   > 1 else df["Low"]
        atr_s   = ta.atr(high_s, low_s, close_s, length=14)
        close_val = float(close_s.iloc[-1])
        atr_val   = float(atr_s.iloc[-1])
        _cache_store(key, (now, close_val, atr_val, df))
        return close_val, atr_val, df
    except Exception as e:
        _log = get_logger("utils.price")
        _log.warning("Preisfehler (%s): %s", ticker, e)
        return None, None, None


def prefetch_prices(tickers: list):
    """
    Lädt Kursdaten für mehrere Ticker in einem Batch-Download.
    Befüllt den Cache vorab – danach sind get_price_data_cached()-Aufrufe
    sofort (aus dem Cache) beantwortet.
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
                close_s = df["Close"].iloc[:, 0] if df["Close"].ndim > 1 else df["Close"]
                high_s  = df["High"].iloc[:, 0]  if df["High"].ndim  > 1 else df["High"]
                low_s   = df["Low"].iloc[:, 0]   if df["Low"].ndim   > 1 else df["Low"]
                atr_s     = ta.atr(high_s, low_s, close_s, length=14)
                close_val = float(close_s.iloc[-1])
                atr_val   = float(atr_s.iloc[-1])
                _cache_store(_cache_key(ticker), (now, close_val, atr_val, df))
            except Exception:
                pass  # Einzelner Fehler überspringen, andere laufen weiter
        print(f"  ✅ Cache befüllt: {len(_price_cache)} Einträge", flush=True)
    except Exception as e:
        _log = get_logger("utils.prefetch")
        _log.warning("Batch-Download Fehler: %s – falle auf Einzelabfragen zurück", e)
