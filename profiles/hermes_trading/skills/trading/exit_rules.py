"""Pure, shared exit-rule calculations for all live and shadow paths."""
from __future__ import annotations

from datetime import date, datetime


# M5 (30.09.2026): Replay und Shadow-Buecher fuellten Stops exakt zum Stop-Preis, live rutscht der Ausstieg im Schnitt
# 0,35 ATR durch (64 SL-Trades). Seit dem Stichtag 30.09.2026 wirkt der Wert ueber die Config (stop_slippage_atr) in allen
# Replays (Optimizer, Backtester, verify_exit_profile, Shadow-Selection, Crabel-Shadow). Zu diesem Zeitpunkt hatte die
# Shadow-Selection noch keine einzige Exit-Bewertung (pnl_live_net leer), die Vorab-Kriterien sind also nicht verschoben.
LIVE_STOP_SLIPPAGE_ATR = 0.35


def stop_fill_price(stop: float, atr: float, direction: str, slippage_atr: float = 0.0) -> float:
    """Fuellpreis eines Stop-Treffers: der Stop, schlechter um slippage_atr * ATR."""
    delta = slippage_atr * atr
    return stop - delta if direction == "LONG" else stop + delta


def replay_fill_settings(cfg: dict | None) -> dict:
    """Fill-Annahmen der Replays aus der Config (M5 stop_slippage_atr, N9 time_stop_protected_fill).

    Ohne die Schluessel gilt das alte Verhalten (Stop exakt, Time-Stop nie schlechter als der Anfangs-Stop).
    Als ``**``-Argument an replay_exit_path gedacht.
    """
    cfg = cfg or {}
    return {"stop_slippage_atr": float(cfg.get("stop_slippage_atr", 0.0) or 0.0),
            "protect_time_stop": bool(cfg.get("time_stop_protected_fill", True))}


def trading_days_held(entry_date: str, as_of: date | None = None) -> int:
    """Count weekdays after entry through ``as_of`` (exchange holidays excluded)."""
    start = datetime.fromisoformat(entry_date).date()
    end = as_of or date.today()
    if end <= start:
        return 0
    return sum(1 for offset in range(1, (end - start).days + 1)
               if date.fromordinal(start.toordinal() + offset).weekday() < 5)


def time_stop_due(entry_date: str, limit: int = 7, as_of: date | None = None) -> bool:
    return trading_days_held(entry_date, as_of) >= limit


# ── YT-Fade (28.09.2026) ────────────────────────────────────────────────────
# YouTube-Long-Kandidaten werden geshortet und nur ueber Haltedauer bzw. einen
# weiten Notfallstop geschlossen. Probe 28.09. auf 49 YT-Long-Entries
# (gespiegelt): ATR-Stops und Stops unter ~+25 % zerstoeren den Effekt, weil
# die Titel vor dem Abverkauf erst noch 10-25 % steigen. Der Notfallstop
# (yt_fade_stop_pct, Nutzer-Entscheidung 28.09.: +40 %) kappt nur die
# Extremlaeufer (2 von 49) und begrenzt den Verlust pro Position; geprueft
# wird auf dem Kurs zum Check-Zeitpunkt, nicht auf dem Intraday-Hoch — so
# arbeitet auch der Live-Check. Weder Trail noch Tech-Exit noch der globale
# Time-Stop gelten; beide Exit-Engines rufen fade_exit_decision() und sonst
# nichts, das Schattenbuch simulate_fade_close().
YT_FADE_MODE = "yt_fade_40d"
# 1x-Short-Zertifikat: bei Kursverdopplung wertlos — mehr als 100 % kann die
# Position auch nach einer Kursluecke nicht verlieren.
FADE_MAX_LOSS_MULT = 2.0


def _fade_fill(entry: float, price: float) -> float:
    return min(price, entry * FADE_MAX_LOSS_MULT)


def fade_exit_decision(pos, current_price: float, hold_days: int = 40):
    """(reason, exit_price) fuer eine YT-Fade-Position, sonst (None, None).

    FADE_STOP:      Kurs auf/ueber stop_loss (Notfallstop). Fill zum aktuellen
                    Kurs, nicht zum Stop-Level — nach einer Luecke wird
                    schlechter ausgefuehrt; gedeckelt bei Totalverlust.
    FADE_TIME_EXIT: Haltedauer erreicht — Fill zum aktuellen Kurs.
    """
    sl = pos["stop_loss"]
    if sl and current_price >= sl:
        return "FADE_STOP", _fade_fill(pos["entry_price"], current_price)
    if time_stop_due(pos["entry_date"], hold_days):
        return "FADE_TIME_EXIT", _fade_fill(pos["entry_price"], current_price)
    return None, None


def simulate_fade_close(bars: list, entry_idx: int, entry: float,
                        stop_pct: float, hold_bars: int = 40):
    """Dieselbe Regel wie fade_exit_decision auf Tages-Schlusskursen.

    Returns (reason, exit_price, bars_held) oder (None, None, 0), wenn der
    Pfad noch keine hold_bars Bars nach dem Entry hat.
    """
    stop = entry * (1 + stop_pct)
    path = bars[entry_idx + 1: entry_idx + 1 + hold_bars]
    for n, b in enumerate(path, 1):
        if b["close"] >= stop:
            return "FADE_STOP", _fade_fill(entry, b["close"]), n
    if len(path) < hold_bars:
        return None, None, 0
    return "FADE_TIME_EXIT", _fade_fill(entry, path[-1]["close"]), hold_bars


def initial_stop(entry: float, atr_at_entry: float, direction: str, sl_mult: float) -> float:
    risk = atr_at_entry * sl_mult
    return entry - risk if direction == "LONG" else entry + risk


def protected_time_stop_price(current: float, initial_sl: float, direction: str) -> float:
    """Paper-fill no worse than the initial risk boundary."""
    return max(current, initial_sl) if direction == "LONG" else min(current, initial_sl)


def peak_chandelier_stop(
    current_stop: float,
    current_price: float,
    peak: float,
    entry: float,
    atr: float,
    direction: str,
    profit_lock_atr: float,
    chandelier_mult: float,
) -> tuple[float, float, bool]:
    """Return (ratcheted stop, updated peak/trough, armed).

    The peak/trough is always recorded. The stop only ratchets once price has
    moved at least ``profit_lock_atr * ATR`` in the profitable direction.
    """
    if direction == "LONG":
        updated_peak = max(peak or entry, current_price)
        armed = updated_peak - entry >= profit_lock_atr * atr
        candidate = updated_peak - chandelier_mult * atr
        return (max(current_stop, candidate) if armed else current_stop,
                updated_peak, armed)
    updated_peak = min(peak or entry, current_price)
    armed = entry - updated_peak >= profit_lock_atr * atr
    candidate = updated_peak + chandelier_mult * atr
    return (min(current_stop, candidate) if armed else current_stop,
            updated_peak, armed)


def donchian_trail_stop(
    bars: list,
    idx: int,
    current_stop: float,
    direction: str,
    period: int,
) -> float:
    """Turtle-S1-Trail: Stop auf das ``period``-Gegenextrem der letzten Bars.

    ``bars`` ist die volle Marktserie, ``idx`` der aktuelle Bar. Das Fenster
    umfasst bewusst auch Bars VOR dem Entry — genau so arbeitet der Live-Pfad
    (``get_donchian_breakout`` holt die Historie am Ticker, nicht am Trade).
    Eine Fensterung ab Entry wuerde den Trail in kurzen Trades nie scharf
    stellen und die Simulation vom Live-Verhalten entkoppeln.
    """
    window = bars[max(0, idx - period + 1): idx + 1]
    if not window:
        return current_stop
    if direction == "LONG":
        return max(current_stop, min(b["low"] for b in window))
    return min(current_stop, max(b["high"] for b in window))


def replay_exit_path(
    bars: list,
    entry_idx: int,
    entry: float,
    direction: str,
    atr: float,
    *,
    sl_mult: float,
    partial_atr: float = 1.5,
    partial_pct: float = 0.5,
    profit_lock_atr: float = 1.0,
    chandelier_mult: float = 2.0,
    donchian_primary: bool = True,
    donchian_period: int = 10,
    time_stop_bars: int = 7,
    tp_mult: float | None = None,
    stop_slippage_atr: float = 0.0,
    protect_time_stop: bool = True,
) -> dict:
    """Pfadgenaues Replay der Exit-Logik auf echten OHLC-Bars.

    Der entscheidende Unterschied zu einer Bewertung am Exit-PREIS: hier wird
    geprueft, ob ein Stop UNTERWEGS (Intraday-Low/High) getroffen worden waere.
    Ohne das belohnt jede Parametersuche systematisch zu enge Stops, weil ein
    Gewinner, der zwischenzeitlich tief im Minus lag, seinen vollen Gewinn
    behaelt (siehe strategy_optimizer.backtest_params vor dem 18.09.2026).

    Reihenfolge je Bar entspricht dem Live-Pfad:
      1. Stop-Treffer (konservativ vor allem anderen)
      2. Partial-TP
      3. Voll-TP (nur wenn ``tp_mult`` gesetzt — der Live-Pfad setzt
         ``hit_tp = False``, das TP ist dort reines Ergebnisziel)
      4. Trail nachziehen (Donchian-primary ODER Chandelier, nie beides)
      5. Time-Stop

    Returns dict mit r_multiple (in Vielfachen des Anfangsrisikos), bars_held,
    reason, mfe_atr und mae_atr.
    """
    if not bars or atr is None or atr <= 0 or entry_idx >= len(bars) - 1:
        return {"r_multiple": None, "bars_held": 0, "reason": "NO_DATA",
                "mfe_atr": None, "mae_atr": None}

    is_long = direction == "LONG"
    sign = 1 if is_long else -1
    risk = sl_mult * atr
    stop = initial_stop(entry, atr, direction, sl_mult)
    partial_level = entry + sign * partial_atr * atr
    tp_level = entry + sign * tp_mult * atr if tp_mult else None

    peak = entry            # guenstigstes Extrem (fuer Chandelier + MFE)
    trough = entry          # unguenstigstes Extrem (fuer MAE)
    banked = 0.0            # bereits realisiertes R aus dem Partial
    remaining = 1.0
    partial_done = False

    def _result(r, n, why):
        return {"r_multiple": r, "bars_held": n, "reason": why,
                "mfe_atr": sign * (peak - entry) / atr,
                "mae_atr": sign * (entry - trough) / atr}

    for idx in range(entry_idx + 1, len(bars)):
        n = idx - entry_idx
        high, low, close = bars[idx]["high"], bars[idx]["low"], bars[idx]["close"]

        # Extremwerte immer fuehren — auch fuer den Bar, der den Exit ausloest.
        peak = max(peak, high) if is_long else min(peak, low)
        trough = min(trough, low) if is_long else max(trough, high)

        # 1. Stop zuerst: innerhalb eines Bars ist die Reihenfolge unbekannt,
        #    die pessimistische Annahme haelt die Simulation ehrlich.
        if (low <= stop) if is_long else (high >= stop):
            sl_fill = stop_fill_price(stop, atr, direction, stop_slippage_atr)
            return _result(banked + remaining * (sign * (sl_fill - entry) / risk), n, "SL_HIT")

        # 2. Partial-TP
        if partial_pct > 0 and not partial_done:
            if (high >= partial_level) if is_long else (low <= partial_level):
                banked += partial_pct * (sign * (partial_level - entry) / risk)
                remaining -= partial_pct
                partial_done = True

        # 3. Voll-TP (im Live-Pfad inaktiv)
        if tp_level is not None:
            if (high >= tp_level) if is_long else (low <= tp_level):
                return _result(banked + remaining * (sign * (tp_level - entry) / risk),
                               n, "TARGET_HIT")

        # 4. Trail — genau ein Mechanismus, wie live
        pnl_atr = sign * (close - entry) / atr
        if pnl_atr >= profit_lock_atr:
            if donchian_primary:
                stop = donchian_trail_stop(bars, idx, stop, direction, donchian_period)
            else:
                stop, peak, _ = peak_chandelier_stop(
                    stop, close, peak, entry, atr, direction,
                    profit_lock_atr, chandelier_mult)

        # 5. Time-Stop
        if time_stop_bars and n >= time_stop_bars:
            fill = (protected_time_stop_price(close, initial_stop(entry, atr, direction, sl_mult), direction)
                    if protect_time_stop else close)
            return _result(banked + remaining * (sign * (fill - entry) / risk), n, "TIME_STOP")

    close = bars[-1]["close"]
    return _result(banked + remaining * (sign * (close - entry) / risk),
                   len(bars) - entry_idx, "EOD")
