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
