"""Pure, shared exit-rule calculations for all live and shadow paths."""
from __future__ import annotations

from datetime import date, datetime


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
            return _result(banked + remaining * (sign * (stop - entry) / risk), n, "SL_HIT")

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
            fill = protected_time_stop_price(close, initial_stop(entry, atr, direction, sl_mult),
                                             direction)
            return _result(banked + remaining * (sign * (fill - entry) / risk), n, "TIME_STOP")

    close = bars[-1]["close"]
    return _result(banked + remaining * (sign * (close - entry) / risk),
                   len(bars) - entry_idx, "EOD")
