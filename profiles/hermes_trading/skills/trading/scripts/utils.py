"""
Gemeinsame Hilfsfunktionen für das Trading System.
- Liquiditätsfilter
- Slippage-Modell
- Commission-Berechnung
"""
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
