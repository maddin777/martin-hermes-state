"""
Script 4: Signal Manager + Portfolio Manager
- Verwaltet offene Positionen (max 8)
- ATR-basierter SL/TP mit Slippage + Commission
- Position Sizing mit Cash-Reserve und Budget-Limit
- SHORT-Positionen (simuliert als Knockout-Zertifikat 1x Hebel)
- Partial Take-Profit bei +1.5x ATR
- Liquiditätsfilter
- Post-Trade-Analyse und Strategie-Anpassung
- Telegram-Benachrichtigungen
"""
import sqlite3
import json
import math
import os
import sys
sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")
import env_loader  # noqa: F401  (side-effect: laedt .env)
import requests
import yfinance as yf
import pandas_ta as ta
from datetime import datetime, timedelta
from utils import passes_liquidity_filter, apply_slippage, COMMISSION_EUR, get_price_data_cached, prefetch_prices
from utils import get_logger, price_to_eur, position_size_in_shares
log = get_logger("signal_manager")
from config import DB_PATH, SIGNALS_VALIDATED_PATH, STRATEGY_CONFIG_PATH, MACRO_SIGNAL_PATH, db_connect
CONFIG_PATH = STRATEGY_CONFIG_PATH


TELEGRAM_TOKEN        = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_HOME_CHANNEL = os.environ.get("TELEGRAM_HOME_CHANNEL") \
                        or os.environ.get("TELEGRAM_CHAT_ID")

DEFAULT_CONFIG = {
    "starting_capital":       10000.0,
    "max_position_pct":       0.15,
    "max_position_pct_high":  0.20,
    "max_position_pct_low":   0.10,
    "max_positions":          8,
    "max_portfolio_allocation": 0.70,
    "min_cash_reserve":       1500.0,
    "max_long_allocation":    0.70,
    "max_short_allocation":   0.30,
    "conviction_high":        0.80,
    "conviction_low":         0.60,
    "atr_sl_multiplier":      1.5,
    "atr_tp_multiplier":      2.5,
    "min_confidence":         0.60,
    "min_confidence_short":   0.65,   # BUGFIX: war 0.5 im Query, Default jetzt konsistent
    "min_conviction":         0.60,
    "min_mentions":           2,
    "min_mentions_short":     2,
    "partial_tp_enabled":     True,
    "partial_tp_atr":         1.5,
    "partial_tp_pct":         0.50,
    "profit_lock_atr":        2.0,
    "trailing_step_atr":      0.5,
    "slippage_pct":           0.001,
    "commission_eur":         1.0,
    "min_liquidity_eur":      500000,
    "earnings_blackout_days": 5,
    "max_correlation":        0.70,
    # Risiko-Parity: Zielrisiko pro Trade als % des Portfolios
    "risk_pct_per_trade":     0.015,  # 1.5% – jetzt konfigurierbar
    # Drawdown-Cooldown: N Handelstage nach close_all blockiert
    "drawdown_cooldown_days": 7,
    "drawdown_close_all_date": None,  # ISO-Datum letzter close_all
    # Performance-Tracking
    "consecutive_wins":       0,
    "consecutive_losses":     0,
    "total_trades":           0,
    "winning_trades":         0,
}

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
        for k, v in DEFAULT_CONFIG.items():
            if k not in cfg:
                cfg[k] = v
        return cfg
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)

def init_db(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker       TEXT,
            name         TEXT,
            direction    TEXT,
            entry_price  REAL,
            entry_date   TEXT,
            stop_loss    REAL,
            take_profit  REAL,
            trailing_sl  REAL,
            breakeven_set INTEGER DEFAULT 0,
            position_size REAL,
            shares       REAL,
            status       TEXT DEFAULT 'open',
            exit_price   REAL,
            exit_date    TEXT,
            exit_reason  TEXT,
            pnl_eur      REAL,
            pnl_pct      REAL,
            atr_at_entry REAL,
            confidence   REAL,
            source_channel TEXT,
            reason       TEXT,
            highest_price REAL DEFAULT 0,
            lowest_price  REAL DEFAULT 0,
            partial_exit_done INTEGER DEFAULT 0
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS portfolio (
            id           INTEGER PRIMARY KEY,
            cash         REAL,
            total_value  REAL,
            ath_value    REAL,
            updated_at   TEXT
        )
    """)
    existing = con.execute("SELECT id FROM portfolio WHERE id=1").fetchone()
    if not existing:
        cfg = load_config()
        con.execute("""
            INSERT INTO portfolio (id, cash, total_value, ath_value, updated_at)
            VALUES (1, ?, ?, ?, ?)
        """, (cfg["starting_capital"], cfg["starting_capital"],
              cfg["starting_capital"], datetime.now().isoformat()))
    else:
        # Migration: ath_value für bestehende DBs
        port_cols = [row[1] for row in con.execute("PRAGMA table_info(portfolio)")]
        if "ath_value" not in port_cols:
            con.execute("ALTER TABLE portfolio ADD COLUMN ath_value REAL")
            con.execute(
                "UPDATE portfolio SET ath_value = total_value WHERE id=1 AND ath_value IS NULL"
            )
            print("  📝 portfolio: Spalte ath_value hinzugefügt", flush=True)

    # Migration: neue Spalten hinzufügen wenn nicht vorhanden
    cols = [row[1] for row in con.execute("PRAGMA table_info(positions)")]
    if "highest_price" not in cols:
        con.execute("ALTER TABLE positions ADD COLUMN highest_price REAL DEFAULT 0")
    if "lowest_price" not in cols:
        con.execute("ALTER TABLE positions ADD COLUMN lowest_price REAL DEFAULT 0")
    if "partial_exit_done" not in cols:
        con.execute("ALTER TABLE positions ADD COLUMN partial_exit_done INTEGER DEFAULT 0")
    if "thesis_current_status" not in cols:
        con.execute("ALTER TABLE positions ADD COLUMN thesis_current_status TEXT DEFAULT 'no_thesis'")
    if "thesis_theme_id" not in cols:
        con.execute("ALTER TABLE positions ADD COLUMN thesis_theme_id INTEGER")

    # Migration: watchlist – conviction_score_raw (Audit-Trail vor LLM-Validierung)
    wl_cols = [row[1] for row in con.execute("PRAGMA table_info(watchlist)")]
    if "conviction_score_raw" not in wl_cols:
        con.execute(
            "ALTER TABLE watchlist ADD COLUMN conviction_score_raw REAL"
        )
        con.execute(
            "UPDATE watchlist SET conviction_score_raw = conviction_score "
            "WHERE conviction_score_raw IS NULL"
        )
        print("  📝 watchlist: Spalte conviction_score_raw hinzugefügt", flush=True)
    if "llm_verdict" not in wl_cols:
        con.execute("ALTER TABLE watchlist ADD COLUMN llm_verdict TEXT")
        print("  📝 watchlist: Spalte llm_verdict hinzugefügt", flush=True)
    if "llm_verdict_at" not in wl_cols:
        con.execute("ALTER TABLE watchlist ADD COLUMN llm_verdict_at TEXT")
        print("  📝 watchlist: Spalte llm_verdict_at hinzugefügt", flush=True)

    # Migration: canonical_tickers Tabelle (Duplikat-Merge + Fehlklassifikation)
    con.execute("""
        CREATE TABLE IF NOT EXISTS canonical_tickers (
            source_ticker TEXT PRIMARY KEY,
            target_ticker TEXT NOT NULL,
            reason TEXT
        )
    """)
    # Seed: bekannte Mappings (nur bei leerer Tabelle)
    existing_ct = con.execute("SELECT COUNT(*) FROM canonical_tickers").fetchone()[0]
    if existing_ct == 0:
        ct_seed = [
            ("YDX.MU", "NBIS", "Nebius Group: Frankfurter Mirror → NASDAQ"),
            ("639.F",  "SPOT", "Spotify: Frankfurter Mirror → NYSE"),
            ("6MK.F",  "MRK",  "Merck & Co: Frankfurter Mirror → NYSE"),
            ("ARMK",   "ARM",  "ARM Holdings: yfinance löst ARM fälschlich auf ARMK auf"),
        ]
        con.executemany(
            "INSERT INTO canonical_tickers (source_ticker, target_ticker, reason) VALUES (?, ?, ?)",
            ct_seed
        )
        print(f"  📝 canonical_tickers: {len(ct_seed)} Mappings angelegt", flush=True)

    con.commit()

def get_current_price_and_atr(ticker):
    """Wrapper → delegiert an zentralen Cache in utils.py (TTL 5 min)."""
    close, atr_val, _ = get_price_data_cached(ticker)
    return close, atr_val

def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_HOME_CHANNEL:
        print(f"\n{message}")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_HOME_CHANNEL,
                "text": message,
                "parse_mode": "HTML"
            },
            timeout=10
        )
    except Exception as e:
        print(f"  ⚠ Telegram Fehler: {e}")

def adapt_strategy(cfg, con):
    """Passt Strategie nach Trade-Performance an."""
    if cfg["total_trades"] < 3:
        return cfg

    win_rate = cfg["winning_trades"] / cfg["total_trades"] if cfg["total_trades"] > 0 else 0
    changes = []

    if cfg["consecutive_wins"] >= 3:
        cfg["atr_tp_multiplier"] = min(4.0, cfg["atr_tp_multiplier"] + 0.25)
        changes.append(f"TP erhöht auf {cfg['atr_tp_multiplier']}x ATR")
        cfg["consecutive_wins"] = 0

    if cfg["consecutive_losses"] >= 3:
        cfg["atr_sl_multiplier"] = max(1.0, cfg["atr_sl_multiplier"] - 0.25)
        changes.append(f"SL enger auf {cfg['atr_sl_multiplier']}x ATR")
        cfg["consecutive_losses"] = 0

    if win_rate < 0.40 and cfg["min_confidence"] < 0.80:
        cfg["min_confidence"] = min(0.80, cfg["min_confidence"] + 0.05)
        changes.append(f"Min. Konfidenz erhöht auf {cfg['min_confidence']:.0%}")

    if win_rate > 0.65 and cfg["min_confidence"] > 0.60:
        cfg["min_confidence"] = max(0.60, cfg["min_confidence"] - 0.05)
        changes.append(f"Min. Konfidenz gesenkt auf {cfg['min_confidence']:.0%}")

    if changes:
        msg = "🔧 <b>Strategie angepasst:</b>\n" + "\n".join(f"• {c}" for c in changes)
        msg += f"\n\nWin Rate: {win_rate:.0%} | Trades: {cfg['total_trades']}"
        send_telegram(msg)

    save_config(cfg)
    return cfg


def check_segment_performance(con, ticker, direction, conviction_score):
    """
    Loop 3: Pre-Entry Validation Gate
    Prüft ob der Setup-Typ (sector + conviction_tier + direction) historisch akzeptabel performt.
    Gibt (ok, reason) zurück.
    """
    try:
        sector_row = con.execute(
            "SELECT sector FROM companies WHERE ticker=?", (ticker,)
        ).fetchone()
        sector = (sector_row["sector"] if sector_row else "Other") or "Other"

        tier = "HIGH" if (conviction_score or 0) >= 0.8 else "NORMAL" if (conviction_score or 0) >= 0.6 else "LOW"

        row = con.execute("""
            SELECT trades_total, win_rate, avg_pnl_pct
            FROM segment_performance
            WHERE sector = ? AND conviction_tier = ? AND tech_direction = ?
            ORDER BY updated_at DESC
            LIMIT 1
        """, (sector, tier, direction)).fetchone()

        if not row or row["trades_total"] < 3:
            return True, None  # Zu wenig Daten → durchlassen

        win_rate = row["win_rate"]
        avg_pnl = row["avg_pnl_pct"]

        if win_rate < 0.30 and row["trades_total"] >= 5:
            return False, f"Segment (Sektor={sector}, {tier}, {direction}) WR {win_rate:.0%} bei {row['trades_total']} Trades – unter 30%-Schwelle"
        if win_rate < 0.35 and avg_pnl < -3.0 and row["trades_total"] >= 5:
            return False, f"Segment (Sektor={sector}, {tier}, {direction}) WR {win_rate:.0%} + Ø {avg_pnl:+.1f}% – negativ"

        return True, None
    except Exception:
        return True, None  # Bei Fehler durchlassen (fail open)


def has_upcoming_earnings(ticker, days_ahead=5):
    """Prüft ob Earnings innerhalb der nächsten N Tage anstehen.
    BUGFIX: yfinance gibt date-Objekte zurück, kein datetime – Subtraktion mit
    datetime.now() würde TypeError werfen. Beide auf date normalisieren.
    """
    try:
        from datetime import date as _date
        t = yf.Ticker(ticker)
        cal = t.calendar
        if cal is None:
            return False
        earnings_date = cal.get("Earnings Date")
        if not earnings_date:
            return False
        if isinstance(earnings_date, (list, tuple)):
            earnings_date = earnings_date[0]
        # Normalisierung auf date-Objekt (robust gegen date und datetime)
        if hasattr(earnings_date, "date"):
            earnings_date = earnings_date.date()
        today = _date.today()
        days_until = (earnings_date - today).days
        return 0 <= days_until <= days_ahead
    except Exception:
        return False  # Bei Fehler kein Blackout (fail open)

def check_open_positions(con, cfg):
    """Prüft offene Positionen auf SL/TP, Trailing Stop und Partial TP."""
    # Batch-Preisabfrage vorab (befüllt Cache für alle open positions)
    positions = con.execute(
        "SELECT * FROM positions WHERE status='open'"
    ).fetchall()

    # Batch-Download aller Position-Kurse in einem Aufruf (TTL-Cache)
    if positions:
        prefetch_prices([p["ticker"] for p in positions if p["ticker"]])

    portfolio = con.execute("SELECT * FROM portfolio WHERE id=1").fetchone()
    cash = portfolio["cash"]

    for pos in positions:
        ticker = pos["ticker"]
        current_price, atr = get_current_price_and_atr(ticker)
        if not current_price:
            continue

        if math.isnan(current_price):
            continue

        entry     = pos["entry_price"]
        sl        = pos["stop_loss"]
        tp        = pos["take_profit"]
        shares    = pos["shares"]
        direction = pos["direction"]
        # Snapshot der originalen Positionsgröße BEVOR Partial-TP sie verändern kann.
        # Verhindert Doppelbuchung wenn Partial-TP und SL/TP im selben Tick zünden.
        original_position_size = pos["position_size"]

        if direction == "LONG":
            pnl_pct = (current_price - entry) / entry
            hit_sl  = current_price <= sl
            hit_tp  = current_price >= tp
        else:  # SHORT
            pnl_pct = (entry - current_price) / entry
            hit_sl  = current_price >= sl
            hit_tp  = current_price <= tp

        pnl_eur = pnl_pct * original_position_size - COMMISSION_EUR

        # --- Partial Take-Profit ---
        if cfg.get("partial_tp_enabled") and not pos["partial_exit_done"] and atr:
            pnl_atr = (current_price - entry) / atr if direction == "LONG" \
                      else (entry - current_price) / atr
            if pnl_atr >= cfg.get("partial_tp_atr", 1.5):
                partial_pct = cfg.get("partial_tp_pct", 0.50)
                partial_pnl = pnl_pct * (pos["position_size"] * partial_pct)

                # 50% der Position schließen
                remaining_shares = shares * (1 - partial_pct)
                remaining_size   = pos["position_size"] * (1 - partial_pct)

                con.execute("""
                    UPDATE positions SET
                        shares = ?,
                        position_size = ?,
                        partial_exit_done = 1,
                        stop_loss = ?,
                        trailing_sl = ?
                    WHERE id = ?
                """, (round(remaining_shares, 4), round(remaining_size, 2),
                      round(entry, 2), round(entry, 2), pos["id"]))

                # Cash zurückbuchen (verkaufter Anteil + Gewinn)
                cash_return = pos["position_size"] * partial_pct + partial_pnl
                cash += cash_return

                con.execute("""
                    UPDATE portfolio SET cash=?, updated_at=? WHERE id=1
                """, (round(cash, 2), datetime.now().isoformat()))
                con.commit()

                send_telegram(
                    f"✂️ <b>Partial TP: {pos['name']}</b>\n"
                    f"Ticker: {ticker} | {direction}\n"
                    f"{partial_pct:.0%} geschlossen bei {current_price:.2f}\n"
                    f"P&L: {partial_pnl:+.2f}€\n"
                    f"SL → Breakeven ({entry:.2f})"
                )
                print(f"  ✂ Partial TP {pos['name']}: {partial_pct:.0%} geschlossen", flush=True)

        # --- Trailing Stop ---
        if atr:
            if direction == "LONG":
                prev_high = pos["highest_price"] or entry
                new_high  = max(prev_high, current_price)
                new_trailing_sl = new_high - (cfg["atr_sl_multiplier"] * atr)

                if new_trailing_sl > sl:
                    was_breakeven = not pos["breakeven_set"] and new_trailing_sl >= entry
                    con.execute(
                        "UPDATE positions SET stop_loss=?, trailing_sl=?, "
                        "highest_price=?, breakeven_set=? WHERE id=?",
                        (round(new_trailing_sl, 2), round(new_trailing_sl, 2),
                         round(new_high, 2),
                         1 if new_trailing_sl >= entry else pos["breakeven_set"],
                         pos["id"])
                    )
                    con.commit()
                    sl = new_trailing_sl
                    print(f"  📈 {pos['name']}: Trailing SL → {new_trailing_sl:.2f} "
                          f"(Hoch: {new_high:.2f})", flush=True)
                    if was_breakeven:
                        send_telegram(
                            "🔒 <b>Breakeven erreicht!</b>\n"
                            f"{pos['name']} ({ticker})\n"
                            f"Trailing SL: {new_trailing_sl:.2f}"
                        )
                elif new_high > prev_high:
                    con.execute(
                        "UPDATE positions SET highest_price=? WHERE id=?",
                        (round(new_high, 2), pos["id"])
                    )
                    con.commit()

            elif direction == "SHORT":
                prev_low = pos["lowest_price"] or entry
                new_low  = min(prev_low, current_price)
                new_trailing_sl = new_low + (cfg["atr_sl_multiplier"] * atr)

                if new_trailing_sl < sl:
                    con.execute(
                        "UPDATE positions SET stop_loss=?, trailing_sl=?, "
                        "lowest_price=?, breakeven_set=? WHERE id=?",
                        (round(new_trailing_sl, 2), round(new_trailing_sl, 2),
                         round(new_low, 2),
                         1 if new_trailing_sl <= entry else pos["breakeven_set"],
                         pos["id"])
                    )
                    con.commit()
                    sl = new_trailing_sl
                    print(f"  📉 {pos['name']}: Trailing SL → {new_trailing_sl:.2f} "
                          f"(Tief: {new_low:.2f})", flush=True)
                elif new_low < prev_low:
                    con.execute(
                        "UPDATE positions SET lowest_price=? WHERE id=?",
                        (round(new_low, 2), pos["id"])
                    )
                    con.commit()

        # --- Position schließen ---
        exit_reason = None
        if hit_sl:
            exit_reason = "SL_HIT"
        elif hit_tp:
            exit_reason = "TARGET_HIT"

        if exit_reason:
            # Cash-Rückbuchung mit original_position_size (vor Partial-TP-Reduktion)
            cash += original_position_size + pnl_eur
            con.execute("""
                UPDATE positions SET
                    status='closed', exit_price=?, exit_date=?,
                    exit_reason=?, pnl_eur=?, pnl_pct=?
                WHERE id=?
            """, (current_price, datetime.now().isoformat(),
                  exit_reason, round(pnl_eur, 2),
                  round(pnl_pct * 100, 2), pos["id"]))

            # Portfolio-Value live aktualisieren
            new_total = cash + sum(
                r["position_size"] for r in con.execute(
                    "SELECT position_size FROM positions WHERE status='open'"
                ).fetchall()
            )
            con.execute("""
                UPDATE portfolio SET cash=?, total_value=?, updated_at=?
                WHERE id=1
            """, (round(cash, 2), round(new_total, 2), datetime.now().isoformat()))
            con.commit()

            # Strategie-Config updaten
            won = pnl_eur > 0
            cfg["total_trades"] += 1
            if won:
                cfg["winning_trades"] += 1
                cfg["consecutive_wins"] += 1
                cfg["consecutive_losses"] = 0
            else:
                cfg["consecutive_losses"] += 1
                cfg["consecutive_wins"] = 0
            save_config(cfg)

            emoji = "✅" if won else "❌"
            msg = (
                f"{emoji} <b>Position geschlossen: {pos['name']}</b>\n"
                f"Ticker: {ticker} | {direction}\n"
                f"Grund: {exit_reason}\n"
                f"Entry: {entry:.2f} → Exit: {current_price:.2f}\n"
                f"P&L: {pnl_eur:+.2f}€ ({pnl_pct*100:+.1f}%)\n"
                f"💰 Cash: {cash:.2f}€"
            )
            print(f"\n{msg}")
            send_telegram(msg)

            cfg = adapt_strategy(cfg, con)

    return cfg

def get_macro_signal():
    """Liest aktuelles Makro-Signal + Regime."""
    import json as _json
    macro_file = MACRO_SIGNAL_PATH
    try:
        with open(macro_file) as f:
            data = _json.load(f)
        return data.get("signal", "neutral"), data.get("regime", "sideways")
    except Exception:
        return "neutral", "sideways"

def apply_regime_filter(conviction, direction, regime):
    """Passt Conviction Score basierend auf Markt-Regime an."""
    if regime == "bull":
        if direction == "LONG":
            return min(1.0, conviction * 1.10)
        else:
            return conviction * 0.90
    elif regime == "bear":
        if direction == "LONG":
            return conviction * 0.80
        else:
            return min(1.0, conviction * 1.20)
    return conviction



def check_drawdown(con):
    """
    Prüft Portfolio-Drawdown gegen ATH.
    Gibt (drawdown_pct, action) zurück:
      action = 'ok'       → normal weiter
      action = 'no_entry' → -15%: keine neuen Positionen
      action = 'close_all' → -25%: alle Positionen schließen
    """
    portfolio = con.execute("SELECT total_value, ath_value FROM portfolio WHERE id=1").fetchone()
    if not portfolio:
        return 0.0, "ok"

    total = portfolio["total_value"] or 0
    ath   = portfolio["ath_value"]   or total

    # ATH aktualisieren wenn neues Hoch
    if total > ath:
        con.execute("UPDATE portfolio SET ath_value=? WHERE id=1", (total,))
        con.commit()
        ath = total

    if ath == 0:
        return 0.0, "ok"

    drawdown = (ath - total) / ath

    if drawdown >= 0.25:
        return drawdown, "close_all"
    elif drawdown >= 0.15:
        return drawdown, "no_entry"
    else:
        return drawdown, "ok"


def _is_drawdown_cooldown_active(cfg) -> bool:
    """Prüft ob nach einem close_all-Event noch Cooldown-Sperre aktiv ist."""
    close_all_date_str = cfg.get("drawdown_close_all_date")
    if not close_all_date_str:
        return False
    try:
        from datetime import date as _date
        close_all_date = datetime.fromisoformat(close_all_date_str).date()
        days_elapsed = (_date.today() - close_all_date).days
        cooldown = cfg.get("drawdown_cooldown_days", 7)
        if days_elapsed < cooldown:
            print(f"  🕐 Drawdown-Cooldown aktiv: noch {cooldown - days_elapsed} Handelstage gesperrt",
                  flush=True)
            return True
    except Exception:
        pass
    return False


def _emergency_close_all(con, cfg):
    """Schließt alle offenen Positionen (Drawdown-Notbremse) und bucht Cash zurück."""
    positions = con.execute(
        "SELECT * FROM positions WHERE status='open'"
    ).fetchall()
    total_recovered = 0.0
    for pos in positions:
        ticker    = pos["ticker"]
        direction = pos["direction"]
        entry     = pos["entry_price"]
        current_price, _ = get_current_price_and_atr(ticker)
        if not current_price:
            current_price = entry  # Fallback: keine Bewegung angenommen

        if direction == "LONG":
            pnl_pct = (current_price - entry) / entry
        else:
            pnl_pct = (entry - current_price) / entry

        pnl_eur = pnl_pct * pos["position_size"] - COMMISSION_EUR
        total_recovered += pos["position_size"] + pnl_eur

        con.execute("""
            UPDATE positions SET
                status='closed', exit_price=?, exit_date=?,
                exit_reason='DRAWDOWN_EMERGENCY', pnl_eur=?, pnl_pct=?
            WHERE id=?
        """, (round(current_price, 2), datetime.now().isoformat(),
              round(pnl_eur, 2), round(pnl_pct * 100, 2), pos["id"]))

    # Portfolio zurücksetzen
    con.execute(
        "UPDATE portfolio SET cash=?, total_value=?, updated_at=? WHERE id=1",
        (round(total_recovered, 2), round(total_recovered, 2), datetime.now().isoformat())
    )
    con.commit()
    # Cooldown-Datum setzen
    cfg["drawdown_close_all_date"] = datetime.now().isoformat()
    save_config(cfg)
    print(f"  🚨 {len(positions)} Positionen geschlossen. Cash zurück: {total_recovered:.2f}€",
          flush=True)



def check_short_thesis(con, ticker: str, conviction_bear: float, cfg: dict) -> tuple:
    """
    Short-Thesis Score – SHORT nur wenn mindestens 2 von 4 Kriterien erfüllt:

      1. Neg. Sentiment:  conviction_score_bear >= min_confidence_short
      2. Hohe Bewertung:  P/E > Sektor-Median (aus fundamentals_snapshot)
      3. Neg. Revisionen: Analyst-Konsens negativ (aus fundamentals_snapshot)
      4. Tech. Schwäche:  tech_direction = 'SHORT'

    Returns (score: int, reasons: list)
    """
    score = 0
    reasons = []

    # Kriterium 1: Bearish Sentiment
    if conviction_bear >= cfg.get("min_confidence_short", 0.65):
        score += 1
        reasons.append(f"Bearish conviction {conviction_bear:.0%}")

    # Kriterium 2: Bewertung (P/E > Sektor-Median)
    try:
        snap = con.execute("""
            SELECT fs.pe_ratio, fs.pe_sector_median
            FROM fundamentals_snapshot fs
            WHERE fs.ticker = ?
            ORDER BY fs.updated_at DESC LIMIT 1
        """, (ticker,)).fetchone()
        if snap and snap["pe_ratio"] and snap["pe_sector_median"]:
            if snap["pe_ratio"] > snap["pe_sector_median"] * 1.2:  # 20% über Median
                score += 1
                reasons.append(f"P/E {snap['pe_ratio']:.0f} > Sektor-Median {snap['pe_sector_median']:.0f}")
    except Exception:
        pass

    # Kriterium 3: Negative Earnings-Revisionen
    try:
        snap = con.execute("""
            SELECT analyst_recommendation FROM fundamentals_snapshot
            WHERE ticker = ? ORDER BY updated_at DESC LIMIT 1
        """, (ticker,)).fetchone()
        if snap and snap["analyst_recommendation"]:
            neg_recs = ["sell", "underperform", "underweight", "reduce"]
            if any(r in snap["analyst_recommendation"].lower() for r in neg_recs):
                score += 1
                reasons.append(f"Analyst: {snap['analyst_recommendation']}")
    except Exception:
        pass

    # Kriterium 4: Technische Schwäche
    try:
        wl = con.execute(
            "SELECT tech_direction FROM watchlist WHERE ticker=? AND status='watching'",
            (ticker,)
        ).fetchone()
        if wl and wl["tech_direction"] == "SHORT":
            score += 1
            reasons.append("Tech-Direction: SHORT")
    except Exception:
        pass

    return score, reasons


# ── Correlation Cache ─────────────────────────────────────────────────────
_CORR_CACHE: dict = {}  # frozenset(t1,t2) → correlation
_CORR_TTL = 1800        # 30 Minuten

def get_correlation(t1: str, t2: str) -> float | None:
    """Pearson-Korrelation der Tagesrenditen (letzte 60 Tage). Gecached 30min."""
    key = frozenset([t1, t2])
    now = datetime.now().timestamp()
    if key in _CORR_CACHE:
        ts, val = _CORR_CACHE[key]
        if now - ts < _CORR_TTL:
            return val
    try:
        import pandas as pd
        import numpy as np
        import yfinance as yf
        df = yf.download([t1, t2], period="60d", interval="1d",
                         progress=False, auto_adjust=True)
        if df is None or df.empty or len(df) < 20:
            return None

        # yfinance MultiIndex: columns = (Price, Ticker) — Close ist level 0
        if isinstance(df.columns, pd.MultiIndex):
            close = df["Close"]
        else:
            close = df[["Close"]] if "Close" in df else df
        if close.shape[1] < 2:
            return None

        r1 = close.iloc[:, 0].pct_change().dropna()
        r2 = close.iloc[:, 1].pct_change().dropna()
        if len(r1) < 15 or len(r2) < 15:
            return None
        corr = float(r1.corr(r2))
        _CORR_CACHE[key] = (now, corr)
        return corr
    except Exception as e:
        log.debug(f"Correlation failed {t1}/{t2}: {e}")
        return None


def check_correlation_with_open(con, ticker: str, direction: str, cfg: dict) -> tuple[bool, str]:
    """Prüft ob der neue Ticker zu stark mit offenen Positionen korreliert.
    Returns (ok: bool, reason: str)."""
    max_corr = cfg.get("max_correlation", 0.70)
    open_positions = con.execute(
        "SELECT ticker, name, direction FROM positions WHERE status='open'"
    ).fetchall()
    if not open_positions:
        return True, ""

    # Nur gleichgerichtete Positionen prüfen (LONG korreliert mit LONG, SHORT mit SHORT)
    relevant = [p for p in open_positions if p["direction"] == direction]
    if not relevant:
        return True, ""

    correlated_with = []
    for pos in relevant:
        corr = get_correlation(ticker, pos["ticker"])
        if corr is not None and abs(corr) > max_corr:
            correlated_with.append((pos["name"], pos["ticker"], corr))

    if correlated_with:
        names = ", ".join(f"{n} ({t}: {c:.2f})" for n, t, c in correlated_with)
        return False, f"Korrelation > {max_corr} mit: {names}"
    return True, ""


# ── Canonical Ticker Lookup ────────────────────────────────────────────
def get_canonical_ticker(con, ticker: str) -> str:
    """Prüft ob ein Ticker ein kanonisches Mapping hat (Duplikat/Fork).
    Z.B. YDX.MU → NBIS, ARMK → ARM. Gibt target_ticker zurück oder
    den Original-Ticker wenn kein Mapping existiert."""
    row = con.execute(
        "SELECT target_ticker FROM canonical_tickers WHERE source_ticker=?",
        (ticker,)
    ).fetchone()
    if row:
        return row["target_ticker"]
    return ticker


def open_new_positions(con, cfg):
    """Öffnet neue Positionen aus der Watchlist (LONG + SHORT)."""
    # ── Drawdown-Cooldown ─────────────────────────────────────────────────
    if _is_drawdown_cooldown_active(cfg):
        return

    # ── Drawdown-Notbremse ────────────────────────────────────────────────
    drawdown_pct, dd_action = check_drawdown(con)
    if dd_action == "close_all":
        print(f"  🚨 DRAWDOWN NOTBREMSE: -{drawdown_pct:.1%} vom ATH → ALLE Positionen schließen!", flush=True)
        send_telegram(f"🚨 DRAWDOWN NOTBREMSE\n-{drawdown_pct:.1%} vom ATH\nAlle Positionen werden geschlossen!")
        _emergency_close_all(con, cfg)
        return
    elif dd_action == "no_entry":
        print(f"  ⚠️  Drawdown -{drawdown_pct:.1%} vom ATH → keine neuen Positionen", flush=True)
        return
    elif drawdown_pct > 0.05:
        print(f"  📉 Drawdown: -{drawdown_pct:.1%} vom ATH (noch OK)", flush=True)

    macro, regime = get_macro_signal()
    print(f"  🌍 Makro: {macro.upper()} | Regime: {regime.upper()}", flush=True)

    # Makro-Filter: Bei Bearish+Bear keine neuen LONGs
    allow_long = not (macro == "bearish" and regime == "bear")
    # SHORT erlaubt bei Bear oder neutral
    allow_short = regime in ("bear", "sideways") or macro in ("bearish", "neutral")

    if macro == "bearish":
        print("  ⚠️  Makro BEARISH – fahre mit reduzierter Conviction fort", flush=True)

    # Phase 5.3: Dynamische Max-Positions basierend auf Regime
    base_max = cfg["max_positions"]
    if regime == "bear":
        effective_max_long  = min(base_max, 4)   # Max 4 LONG im Bear-Markt
        effective_max_short = 4                   # SHORT-Slots erhöhen
    elif regime == "bull":
        effective_max_long  = base_max            # Volle Slots im Bull-Markt
        effective_max_short = 2                   # Wenig SHORT nötig
    else:  # sideways
        effective_max_long  = 6
        effective_max_short = 3

    # Tatsächlich offene Long/Short Counts
    open_long_count = con.execute(
        "SELECT COUNT(*) FROM positions WHERE status='open' AND direction='LONG'"
    ).fetchone()[0]
    open_short_count = con.execute(
        "SELECT COUNT(*) FROM positions WHERE status='open' AND direction='SHORT'"
    ).fetchone()[0]
    open_count = open_long_count + open_short_count

    if open_count >= base_max:
        print(f"  📊 Max. Positionen ({base_max}) erreicht")
        return

    print(f"  📐 Regime {regime.upper()}: Max LONG={effective_max_long}, MAX SHORT={effective_max_short} "
          f"| Offen: {open_long_count}L / {open_short_count}S", flush=True)

    # Portfolio-Value LIVE aus DB lesen
    portfolio_row = con.execute("SELECT cash, total_value FROM portfolio WHERE id=1").fetchone()
    cash = portfolio_row["cash"]
    portfolio_value = portfolio_row["total_value"] or cfg["starting_capital"]

    # Cash-Reserve prüfen
    min_cash = max(cfg.get("min_cash_reserve", 1500), portfolio_value * 0.15)
    if cash <= min_cash:
        print(f"  💰 Cash-Reserve geschützt: {cash:.0f}€ ≤ {min_cash:.0f}€ Minimum")
        return

    # Budget-Limit: Max 70% des Portfolios investieren
    max_total_invested = portfolio_value * cfg.get("max_portfolio_allocation", 0.70)
    currently_invested = sum(
        r["position_size"] for r in con.execute(
            "SELECT position_size FROM positions WHERE status='open'"
        ).fetchall()
    )
    remaining_budget = max(0, max_total_invested - currently_invested)

    if remaining_budget <= 0:
        print(f"  💰 Budget-Limit erreicht: {currently_invested:.0f}€/{max_total_invested:.0f}€ investiert")
        return

    # Bereits offene Ticker
    open_tickers = {r["ticker"] for r in con.execute(
        "SELECT ticker FROM positions WHERE status='open'"
    ).fetchall()}

    # Sektor-Zähler für offene Positionen (JOIN auf companies)
    MAX_POSITIONS_PER_SECTOR = 2
    sector_counts = {}
    for r in con.execute("""
        SELECT COALESCE(c.sector, 'Other') as sector, COUNT(*) as cnt
        FROM positions p
        LEFT JOIN companies c ON c.ticker = p.ticker
        WHERE p.status='open'
        GROUP BY sector
    """).fetchall():
        sector_counts[r["sector"]] = r["cnt"]

    # Heute bereits gehandelte Ticker (24h-Sperre korrekt per datetime)
    cutoff_24h = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M")
    recent_tickers = {r["ticker"] for r in con.execute(
        "SELECT ticker FROM positions WHERE entry_date >= ?", (cutoff_24h,)
    ).fetchall()}

    # Aktuell investierte Anteile nach Richtung
    long_invested = sum(
        r["position_size"] for r in con.execute(
            "SELECT position_size FROM positions WHERE status='open' AND direction='LONG'"
        ).fetchall()
    )
    short_invested = sum(
        r["position_size"] for r in con.execute(
            "SELECT position_size FROM positions WHERE status='open' AND direction='SHORT'"
        ).fetchall()
    )

    max_long = portfolio_value * cfg.get("max_long_allocation", 0.70)
    max_short = portfolio_value * cfg.get("max_short_allocation", 0.30)

    # Kandidaten laden (LONG + SHORT)
    candidates_long = []
    candidates_short = []

    if allow_long and open_long_count < effective_max_long:
        candidates_long = con.execute("""
            SELECT w.*,
                   json_array_length(channels) as channel_count
            FROM watchlist w
            WHERE w.status = 'watching'
            AND w.conviction_score >= ?
            AND w.mention_count >= ?
            AND w.tech_score >= ?
            AND w.tech_direction = 'LONG'
            AND w.ticker IS NOT NULL
        """, (
            cfg.get("min_conviction", 0.60),
            cfg.get("min_mentions", 2),
            cfg.get("min_confidence", 0.60)
        )).fetchall()

    if allow_short and open_short_count < effective_max_short:
        candidates_short = con.execute("""
            SELECT w.*,
                   json_array_length(channels) as channel_count
            FROM watchlist w
            WHERE w.status = 'watching'
            AND w.conviction_score_bear >= ?
            AND w.mention_count >= ?
            AND w.tech_score IS NOT NULL
            AND w.tech_direction = 'SHORT'
            AND w.ticker IS NOT NULL
        """, (
            cfg.get("min_confidence_short", 0.65),   # BUGFIX: war 0.5, jetzt konsistent
            cfg.get("min_mentions_short", 2)
        )).fetchall()

    all_candidates = []
    for c in candidates_long:
        all_candidates.append((c, "LONG"))
    for c in candidates_short:
        all_candidates.append((c, "SHORT"))

    if not all_candidates:
        print("  ℹ Keine Watchlist-Kandidaten die alle Kriterien erfüllen.")
        return

    # Priority Score berechnen
    def priority_score(item):
        c, direction = item
        channels = json.loads(c["channels"] or "[]")
        unique_channels = len(set(channels))
        channel_diversity = min(unique_channels / 3, 1.0)

        try:
            last_seen = datetime.strptime(c["last_seen"], "%Y-%m-%d")
            days_ago  = (datetime.now() - last_seen).days
            recency   = max(0, 1 - days_ago / 30)
        except Exception:
            recency = 0

        score = (
            (c["conviction_score"] or 0) * 0.40 +
            (c["tech_score"] or 0)       * 0.40 +
            channel_diversity             * 0.20
        )
        tiebreaker = (
            recency                      * 0.001 +
            (c["tech_score"] or 0)       * 0.0001 +
            min(c["mention_count"], 10)  * 0.00001
        )
        return score + tiebreaker

    all_candidates.sort(key=priority_score, reverse=True)

    slots_available = cfg["max_positions"] - open_count
    opened = 0

    for c, direction in all_candidates:
        if opened >= slots_available:
            break

        ticker = c["ticker"]
     # 🚫 Krypto-Filter (Notnagel): verhindert dass extrahierte Privatfirmen
        # wie "OpenAI"/"Anthropic" als CRYPTOCURRENCY-Ticker getradet werden.
        # yfinance liefert fuer XYZ-USD echte Preise/Volumen – Liquiditaetsfilter
        # blockt das nicht zuverlaessig.
        if ticker and (ticker.endswith(('-USD', '-EUR', '-USDT', '-BTC')) or '/' in ticker):
            print(f"  🚫 {c['name']}: Krypto-Ticker {ticker} – uebersprungen")
            continue

        channels = json.loads(c["channels"] or "[]")
        unique_channels = len(set(channels))

        # Filter
        if ticker in open_tickers:
            continue
        if ticker in recent_tickers:
            continue

        # Makro-Filter für SHORT
        if direction == "SHORT" and macro == "bullish" and regime == "bull":
            print(f"  ⛔ {c['name']}: SHORT nicht erlaubt bei BULLISH + BULL-Regime")
            continue

        # Short-Thesis Score: min. 2 von 4 Kriterien nötig
        if direction == "SHORT":
            short_score, short_reasons = check_short_thesis(
                con, ticker, c["conviction_score_bear"] or 0, cfg
            )
            if short_score < 2:
                print(f"  📊 {c['name']}: SHORT-Thesis Score {short_score}/4 "
                      f"(mind. 2 nötig) → übersprungen")
                continue
            print(f"  ✅ SHORT-Thesis {short_score}/4: {', '.join(short_reasons)}", flush=True)

        # Weekly Trend Filter: Don't fight the tape
        wt = c.get("weekly_trend", "neutral")
        if wt == "bearish" and direction == "LONG":
            print(f"  📉 {c['name']}: Weekly Trend BEARISH → LONG geblockt")
            continue
        if wt == "bullish" and direction == "SHORT":
            print(f"  📈 {c['name']}: Weekly Trend BULLISH → SHORT geblockt")
            continue

        # Allokations-Limit pro Richtung
        if direction == "LONG" and long_invested >= max_long:
            print(f"  💰 LONG-Allokation voll ({long_invested:.0f}€/{max_long:.0f}€)")
            continue
        if direction == "SHORT" and short_invested >= max_short:
            print(f"  💰 SHORT-Allokation voll ({short_invested:.0f}€/{max_short:.0f}€)")
            continue

        # Sektor-Cap: max 2 Positionen pro Sektor
        ticker_sector = "Other"
        sector_row = con.execute(
            "SELECT sector FROM companies WHERE ticker=?", (ticker,)
        ).fetchone()
        if sector_row and sector_row["sector"]:
            ticker_sector = sector_row["sector"]
        if sector_counts.get(ticker_sector, 0) >= MAX_POSITIONS_PER_SECTOR:
            print(f"  🏭 {c['name']}: Sektor '{ticker_sector}' bereits voll "
                  f"({sector_counts[ticker_sector]}/{MAX_POSITIONS_PER_SECTOR})")
            continue

        # Correlation Filter: Kein Einstieg wenn zu stark korreliert mit offenen Positionen
        corr_ok, corr_reason = check_correlation_with_open(con, ticker, direction, cfg)
        if not corr_ok:
            print(f"  🔗 {c['name']}: {corr_reason}")
            continue

        # Liquiditätsfilter
        if not passes_liquidity_filter(ticker, cfg.get("min_liquidity_eur", 500000)):
            print(f"  💧 {c['name']}: Liquidität zu gering – überspringe")
            continue

        # Earnings-Blackout
        if has_upcoming_earnings(ticker, cfg.get("earnings_blackout_days", 5)):
            print(f"  📅 {c['name']}: Earnings in <{cfg.get('earnings_blackout_days', 5)} Tagen – überspringe")
            continue

        # Loop 3: Pre-Entry Validation Gate – Segment-Historie prüfen
        seg_ok, seg_reason = check_segment_performance(con, ticker, direction, c.get("conviction_score") or 0)
        if not seg_ok:
            print(f"  🚫 {c['name']}: {seg_reason}")
            continue

        # Grok Breaking-News-Check: Negative Breaking News → kein Entry
        # Nur für HIGH-Conviction (spart Grok-Calls für schwächere Kandidaten)
        if (c["conviction_score"] or 0) >= cfg.get("conviction_high", 0.80):
            try:
                from xsearch_helper import breaking_news_check
                has_breaking, summary = breaking_news_check(ticker, c["name"])
                if has_breaking:
                    print(f"  🐦 {c['name']}: Grok meldet negative Breaking News → Entry abgebrochen")
                    print(f"     {summary}", flush=True)
                    continue
            except Exception:
                pass  # Grok-Fehler stoppen den Entry nicht

        # Preis und ATR holen
        current_price, atr = get_current_price_and_atr(ticker)
        if not current_price or not atr:
            continue

        if math.isnan(current_price) or math.isnan(atr):
            continue

        # VIX-Halving: Bei VIX > 30 Positionsgröße halbieren
        vix_factor = 1.0
        try:
            vix_row = con.execute("""
                SELECT value FROM macro_data
                WHERE indicator_id='vix' ORDER BY date DESC LIMIT 1
            """).fetchone()
            if vix_row and vix_row["value"] and float(vix_row["value"]) > 30:
                vix_factor = 0.5
                print(f"  ⚠️  VIX={vix_row['value']:.0f} > 30 → Positionsgröße halbiert",
                      flush=True)
        except Exception:
            pass

        # Position Sizing
        conviction = c["conviction_score"] or 0
        conviction = apply_regime_filter(conviction, direction, regime)

        if conviction >= cfg.get("conviction_high", 0.80):
            pct = cfg.get("max_position_pct_high", 0.20)
            sizing_label = "HIGH"
        elif conviction < cfg.get("conviction_low", 0.60) + 0.05:
            pct = cfg.get("max_position_pct_low", 0.10)
            sizing_label = "LOW"
        else:
            pct = cfg.get("max_position_pct", 0.15)
            sizing_label = "NORMAL"

        # VIX-Faktor anwenden (vor allen weiteren Caps)
        pct = pct * vix_factor

        # Volatilitätsbereinigtes Positionsgrößensystem (Risk-Parity)
        # Risiko pro Trade capped auf risk_pct_per_trade % des Gesamtportfolios
        risk_pct       = cfg.get("risk_pct_per_trade", 0.015)
        risk_amount    = portfolio_value * risk_pct
        sl_multiplier  = cfg.get("atr_sl_multiplier", 1.5)
        # ATR in EUR umrechnen (FX-aware) für korrektes Sizing
        atr_eur        = price_to_eur(atr, ticker)
        sl_distance_eur = sl_multiplier * atr_eur

        if sl_distance_eur > 0:
            vol_position_size = (risk_amount / sl_distance_eur) * price_to_eur(current_price, ticker)
            position_size = min(vol_position_size, pct * portfolio_value, cash, remaining_budget)
            sizing_label += f" | Vol-Adj (Risk: {risk_pct:.1%})"
        else:
            position_size = min(pct * portfolio_value, cash, remaining_budget)

        # Cash-Reserve intra-loop sichern (recheck nach vorangegangenen Eröffnungen)
        if cash - position_size < min_cash:
            position_size = max(0, cash - min_cash)

        print(f"  💰 Position Sizing: {sizing_label} = {position_size:.0f}€", flush=True)
        if position_size < 200:
            continue

        # Slippage auf Entry anwenden
        effective_entry = apply_slippage(current_price, direction, is_entry=True)

        # Commission abziehen und Stückzahl FX-korrekt berechnen
        position_size_after_commission = position_size - COMMISSION_EUR
        shares = position_size_in_shares(position_size_after_commission, effective_entry, ticker)

        # SL/TP berechnen
        if direction == "LONG":
            sl = effective_entry - (cfg["atr_sl_multiplier"] * atr)
            tp = effective_entry + (cfg["atr_tp_multiplier"] * atr)
            # Sicherheitscheck: SL darf nicht über Entry liegen
            sl = min(sl, effective_entry * 0.995)
        else:  # SHORT
            sl = effective_entry + (cfg["atr_sl_multiplier"] * atr)
            tp = effective_entry - (cfg["atr_tp_multiplier"] * atr)
            # Sicherheitscheck: SL darf nicht unter Entry liegen
            sl = max(sl, effective_entry * 1.005)

        sl_pct = abs(effective_entry - sl) / effective_entry * 100
        tp_pct = abs(tp - effective_entry) / effective_entry * 100

        # Position eintragen
        con.execute("""
            INSERT INTO positions
            (ticker, name, direction, entry_price, entry_date,
             stop_loss, take_profit, trailing_sl, position_size, shares,
             atr_at_entry, confidence, source_channel, reason,
             highest_price, lowest_price)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            ticker, c["name"], direction,
            round(effective_entry, 2),
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            round(sl, 2), round(tp, 2), round(sl, 2),
            round(position_size, 2), round(shares, 4),
            round(atr, 4), c["conviction_score"],
            ", ".join(set(channels[:3])),
            c["notes"] or "",
            effective_entry if direction == "LONG" else 0,
            effective_entry if direction == "SHORT" else 0
        ))

        # Watchlist Status updaten
        con.execute(
            "UPDATE watchlist SET status='bought' WHERE name=?",
            (c["name"],)
        )
        # Sektor-Zähler für nächste Iteration aktualisieren
        sector_counts[ticker_sector] = sector_counts.get(ticker_sector, 0) + 1

        # Cash reduzieren
        cash -= position_size
        remaining_budget -= position_size
        if direction == "LONG":
            long_invested += position_size
        else:
            short_invested += position_size

        # Portfolio-Value aktualisieren
        new_total = cash + sum(
            r["position_size"] for r in con.execute(
                "SELECT position_size FROM positions WHERE status='open'"
            ).fetchall()
        )
        con.execute(
            "UPDATE portfolio SET cash=?, total_value=?, updated_at=? WHERE id=1",
            (round(cash, 2), round(new_total, 2), datetime.now().isoformat())
        )
        con.commit()

        open_tickers.add(ticker)
        opened += 1

        msg = (
            f"📈 <b>NEUES SIGNAL: {c['name']}</b>\n"
            f"Ticker: {ticker} | {direction}\n"
            f"Entry: {effective_entry:.2f} (Slippage inkl.)\n"
            f"Stop-Loss: {sl:.2f} (-{sl_pct:.1f}%)\n"
            f"Take-Profit: {tp:.2f} (+{tp_pct:.1f}%)\n"
            f"Investiert: {position_size:.0f}€ ({shares:.2f} Anteile)\n\n"
            "📊 <b>Watchlist-Analyse:</b>\n"
            f"• Mentions: {c['mention_count']}x in 30 Tagen\n"
            f"• Kanäle: {', '.join(set(channels[:3]))} ({unique_channels} verschiedene)\n"
            f"• Conviction: {c['conviction_score']:.0%} {'bullish' if direction == 'LONG' else 'bearish'}\n"
            f"• Tech Score: {c['tech_score']:.2f}\n\n"
            f"💰 Cash verbleibend: {cash:.2f}€"
        )
        send_telegram(msg)

    if opened == 0:
        print("  ℹ Keine Watchlist-Kandidaten die alle Filter passieren.")


def print_portfolio_summary(con, cfg):
    """Gibt Portfolio-Übersicht aus."""
    portfolio = con.execute("SELECT * FROM portfolio WHERE id=1").fetchone()
    positions = con.execute("SELECT * FROM positions WHERE status='open'").fetchall()
    closed = con.execute("SELECT * FROM positions WHERE status='closed'").fetchall()

    total_pnl = sum(p["pnl_eur"] or 0 for p in closed)
    win_rate = (cfg["winning_trades"] / cfg["total_trades"] * 100
                if cfg["total_trades"] > 0 else 0)

    print(f"\n{'='*50}")
    print("PORTFOLIO ÜBERSICHT")
    print(f"{'='*50}")
    print(f"Cash:           {portfolio['cash']:.2f}€")
    print(f"Offene Pos.:    {len(positions)}/{cfg['max_positions']}")
    print(f"Abgeschlossen:  {cfg['total_trades']} Trades")
    print(f"Win Rate:       {win_rate:.0f}%")
    print(f"Gesamt P&L:     {total_pnl:+.2f}€")
    print(f"SL Multiplikator: {cfg['atr_sl_multiplier']}x ATR")
    print(f"TP Multiplikator: {cfg['atr_tp_multiplier']}x ATR")
    print(f"Min. Konfidenz: {cfg['min_confidence']:.0%}")

    if positions:
        print("\nOFFENE POSITIONEN:")
        for p in positions:
            entry = p["entry_price"]
            if not entry:
                print(f"  {p['name']:25} {p['ticker']:10} kein Preis verfügbar")
                continue
            price, _ = get_current_price_and_atr(p["ticker"])
            if not price:
                print(f"  {p['name']:25} {p['ticker']:10} aktueller Preis nicht abrufbar")
                continue
            pnl = (price - entry) / entry * 100
            if p["direction"] == "SHORT":
                pnl = -pnl
            print(f"  {p['name']:25} {p['ticker']:10} "
                  f"{p['direction']:5} Entry:{entry:.2f} "
                  f"Now:{price:.2f} P&L:{pnl:+.1f}%")


def main(mode="full"):
    # Lockfile: verhindert parallelen full-Lauf während check_only läuft (und umgekehrt)
    import fcntl, tempfile
    lock_path = os.path.join(os.path.dirname(DB_PATH), "signal_manager.lock")
    lock_file = open(lock_path, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"⚠ signal_manager läuft bereits (Lockfile: {lock_path}) – Abbruch.", flush=True)
        lock_file.close()
        sys.exit(0)  # kein Fehler-Exit, Pipeline soll weiterlaufen

    try:
        con = db_connect()
        init_db(con)

        cfg = load_config()
        print(f"📊 Signal Manager gestartet (Modus: {mode})", flush=True)

        # Telegram-Konfiguration prüfen (einmalig beim Start)
        if TELEGRAM_TOKEN and TELEGRAM_HOME_CHANNEL:
            try:
                resp = requests.get(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getMe",
                    timeout=5
                )
                if not resp.json().get("ok"):
                    log.warning("⚠ Telegram-Token ungültig (getMe fehlgeschlagen) – "
                                "Benachrichtigungen werden nicht zugestellt!")
            except Exception as tg_exc:
                log.warning("⚠ Telegram nicht erreichbar: %s", tg_exc)
        elif not TELEGRAM_TOKEN:
            log.warning("⚠ TELEGRAM_BOT_TOKEN nicht gesetzt – keine Benachrichtigungen")

        # Immer: Offene Positionen prüfen (SL/TP/Trailing)
        print("\n1. Prüfe offene Positionen...", flush=True)
        cfg = check_open_positions(con, cfg)

        # Nur im Full-Modus: Neue Positionen öffnen
        if mode == "full":
            print("\n2. Prüfe neue Signale...", flush=True)
            open_new_positions(con, cfg)

        # Übersicht ausgeben
        print_portfolio_summary(con, cfg)

        con.close()
    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()


if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "full"
    main(mode)
