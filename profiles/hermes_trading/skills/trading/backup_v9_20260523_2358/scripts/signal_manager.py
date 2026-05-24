"""
Script 4: Signal Manager + Portfolio Manager
- Verwaltet offene Positionen (max 4)
- ATR-basierter SL/TP
- Post-Trade-Analyse und Strategie-Anpassung
- Telegram-Benachrichtigungen
- Schreibt Daten für Dashboard
"""
import sqlite3
import json
import os
import requests
import yfinance as yf
import pandas_ta as ta
from datetime import datetime, timezone, timedelta

# Sektor-Mapping für Diversifikations-Check
SECTOR_MAP = {
    "AAPL":"Tech", "MSFT":"Tech", "GOOGL":"Tech", "NVDA":"Tech",
    "META":"Tech", "AMZN":"Tech", "NOW":"Tech", "SAP.DE":"Tech",
    "INTC":"Tech", "AMD":"Tech", "AVGO":"Tech", "ADBE":"Tech",
    "PLTR":"Tech", "CRM":"Tech", "PANW":"Tech", "CRWD":"Tech",
    "SNPS":"Tech", "ADSK":"Tech", "FSLY":"Tech", "APP":"Tech",
    "MSCI":"Finance", "CBK.DE":"Finance", "DBK.DE":"Finance",
    "ALV.DE":"Finance", "UCG.MI":"Finance", "BAC":"Finance",
    "JPM":"Finance", "GS":"Finance", "MS":"Finance",
    "ENR.DE":"Energy", "RWE.DE":"Energy", "EOAN.DE":"Energy",
    "HAL":"Energy", "BE":"Energy", "SLB":"Energy",
    "NKE":"Consumer", "ADS.DE":"Consumer", "AMZN":"Consumer",
    "LLY":"Health", "JNJ":"Health", "UNH":"Health", "GILD":"Health",
    "SGL.DE":"Materials", "BAS.DE":"Materials", "BAYN.DE":"Materials",
    "SIE.DE":"Industrial", "MTX.DE":"Industrial", "DTG.DE":"Industrial",
    "BMW.DE":"Auto", "VOW3.DE":"Auto", "MBG.DE":"Auto",
    "TSLA":"Auto", "IONQ":"Quantum", "IBM":"Tech",
}

def get_sector(ticker, con=None):
    """Liest Sektor aus Watchlist-DB, Fallback yfinance."""
    # 1. Aus SECTOR_MAP
    if ticker in SECTOR_MAP:
        return SECTOR_MAP[ticker]
    # 2. Aus Watchlist-DB
    if con:
        try:
            row = con.execute(
                "SELECT sector FROM watchlist WHERE ticker=? AND sector IS NOT NULL LIMIT 1",
                (ticker,)
            ).fetchone()
            if row and row["sector"] and row["sector"] != "Other":
                return row["sector"]
        except:
            pass
    # 3. yfinance Lookup
    try:
        info = yf.Ticker(ticker).info
        sector = info.get("sector")
        if sector:
            return sector
    except:
        pass
    return "Other"

DB_PATH      = "/root/.hermes/profiles/hermes_trading/skills/trading/data/trading.db"
SIGNALS_PATH = "/root/.hermes/profiles/hermes_trading/skills/trading/data/trading_signals_validated.json"
CONFIG_PATH  = "/root/.hermes/profiles/hermes_trading/skills/trading/data/strategy_config.json"

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Startkonfiguration
DEFAULT_CONFIG = {
    "starting_capital":    10000.0,
    "max_position_pct":    0.30,
    "max_positions":       4,
    "atr_sl_multiplier":   1.5,
    "atr_tp_multiplier":   3.0,
    "min_confidence":      0.65,
    "consecutive_wins":    0,
    "consecutive_losses":  0,
    "total_trades":        0,
    "winning_trades":      0,
}

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
        # Fehlende Keys ergänzen
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
            reason       TEXT
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS portfolio (
            id           INTEGER PRIMARY KEY,
            cash         REAL,
            total_value  REAL,
            updated_at   TEXT
        )
    """)
    # Portfolio initialisieren falls leer
    existing = con.execute("SELECT id FROM portfolio WHERE id=1").fetchone()
    if not existing:
        cfg = load_config()
        con.execute("""
            INSERT INTO portfolio (id, cash, total_value, updated_at)
            VALUES (1, ?, ?, ?)
        """, (cfg["starting_capital"], cfg["starting_capital"],
              datetime.now().isoformat()))
    con.commit()

def get_current_price_and_atr(ticker):
    try:
        df = yf.download(ticker, period="2y", interval="1d",
                         progress=False, auto_adjust=True)
        df = df.dropna()
        if df.empty or len(df) < 20:
            return None, None
        close = df["Close"].iloc[:, 0]
        high  = df["High"].iloc[:, 0]
        low   = df["Low"].iloc[:, 0]
        atr   = ta.atr(high, low, close, length=14)
        return float(close.iloc[-1]), float(atr.iloc[-1])
    except Exception as e:
        print(f"  ⚠ Preisfehler {ticker}: {e}")
        return None, None

def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"\n{message}")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
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

    # 3 Gewinne in Folge → TP erhöhen
    if cfg["consecutive_wins"] >= 3:
        cfg["atr_tp_multiplier"] = min(4.0, cfg["atr_tp_multiplier"] + 0.25)
        changes.append(f"TP erhöht auf {cfg['atr_tp_multiplier']}x ATR")
        cfg["consecutive_wins"] = 0

    # 3 Verluste in Folge → SL enger
    if cfg["consecutive_losses"] >= 3:
        cfg["atr_sl_multiplier"] = max(1.0, cfg["atr_sl_multiplier"] - 0.25)
        changes.append(f"SL enger auf {cfg['atr_sl_multiplier']}x ATR")
        cfg["consecutive_losses"] = 0

    # Win Rate < 40% → Confidence-Schwelle erhöhen
    if win_rate < 0.40 and cfg["min_confidence"] < 0.80:
        cfg["min_confidence"] = min(0.80, cfg["min_confidence"] + 0.05)
        changes.append(f"Min. Konfidenz erhöht auf {cfg['min_confidence']:.0%}")

    # Win Rate > 65% → Confidence-Schwelle senken
    if win_rate > 0.65 and cfg["min_confidence"] > 0.60:
        cfg["min_confidence"] = max(0.60, cfg["min_confidence"] - 0.05)
        changes.append(f"Min. Konfidenz gesenkt auf {cfg['min_confidence']:.0%}")

    if changes:
        msg = "🔧 <b>Strategie angepasst:</b>\n" + "\n".join(f"• {c}" for c in changes)
        msg += f"\n\nWin Rate: {win_rate:.0%} | Trades: {cfg['total_trades']}"
        send_telegram(msg)

    save_config(cfg)
    return cfg

def check_open_positions(con, cfg):
    """Prüft offene Positionen auf SL/TP und Trailing Stop."""
    positions = con.execute(
        "SELECT * FROM positions WHERE status='open'"
    ).fetchall()

    portfolio = con.execute("SELECT * FROM portfolio WHERE id=1").fetchone()
    cash = portfolio["cash"]

    for pos in positions:
        ticker = pos["ticker"]
        current_price, atr = get_current_price_and_atr(ticker)
        if not current_price:
            continue

        entry  = pos["entry_price"]
        sl     = pos["stop_loss"]
        tp     = pos["take_profit"]
        shares = pos["shares"]
        direction = pos["direction"]

        if direction == "LONG":
            pnl_pct = (current_price - entry) / entry
            hit_sl  = current_price <= sl
            hit_tp  = current_price >= tp
        else:  # SHORT
            pnl_pct = (entry - current_price) / entry
            hit_sl  = current_price >= sl
            hit_tp  = current_price <= tp

        pnl_eur = pnl_pct * pos["position_size"]

        # Kontinuierlicher Trailing Stop
        if atr:
            if direction == "LONG":
                # Preishoch aktualisieren
                prev_high = pos["highest_price"] or entry
                new_high  = max(prev_high, current_price)

                # Neuer Trailing SL = Preishoch - 1.5x ATR
                new_trailing_sl = new_high - (cfg["atr_sl_multiplier"] * atr)

                # SL nur erhöhen, nie senken
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
                    sl = new_trailing_sl  # für SL-Hit Check unten
                    print(f"  📈 {pos['name']}: Trailing SL → {new_trailing_sl:.2f} "
                          f"(Hoch: {new_high:.2f})", flush=True)
                    if was_breakeven:
                        send_telegram(
                            f"🔒 <b>Breakeven erreicht!</b>\n"
                            f"{pos['name']} ({ticker})\n"
                            f"Trailing SL: {new_trailing_sl:.2f}"
                        )
                elif new_high > prev_high:
                    # Nur Preishoch updaten
                    con.execute(
                        "UPDATE positions SET highest_price=? WHERE id=?",
                        (round(new_high, 2), pos["id"])
                    )
                    con.commit()

            elif direction == "SHORT":
                # Preistief aktualisieren
                prev_low = pos["lowest_price"] or entry
                new_low  = min(prev_low, current_price)

                # Neuer Trailing SL = Preistief + 1.5x ATR
                new_trailing_sl = new_low + (cfg["atr_sl_multiplier"] * atr)

                # SL nur senken, nie erhöhen
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

        # Position schließen
        exit_reason = None
        if hit_sl:
            exit_reason = "SL_HIT"
        elif hit_tp:
            exit_reason = "TARGET_HIT"

        if exit_reason:
            cash += pos["position_size"] + pnl_eur
            con.execute("""
                UPDATE positions SET
                    status='closed', exit_price=?, exit_date=?,
                    exit_reason=?, pnl_eur=?, pnl_pct=?
                WHERE id=?
            """, (current_price, datetime.now().isoformat(),
                  exit_reason, round(pnl_eur, 2),
                  round(pnl_pct * 100, 2), pos["id"]))

            # Portfolio updaten
            total_value = cash + sum(
                p["position_size"] * (1 + (
                    (get_current_price_and_atr(p["ticker"])[0] or p["entry_price"])
                    - p["entry_price"]) / p["entry_price"])
                for p in con.execute(
                    "SELECT * FROM positions WHERE status='open' AND id!=?",
                    (pos["id"],)
                ).fetchall()
            )
            con.execute("""
                UPDATE portfolio SET cash=?, total_value=?, updated_at=?
                WHERE id=1
            """, (cash, cash, datetime.now().isoformat()))
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
                f"Ticker: {ticker}\n"
                f"Grund: {exit_reason}\n"
                f"Entry: {entry:.2f} → Exit: {current_price:.2f}\n"
                f"P&L: {pnl_eur:+.2f}€ ({pnl_pct*100:+.1f}%)\n"
                f"💰 Cash: {cash:.2f}€"
            )
            print(f"\n{msg}")
            send_telegram(msg)

            # Strategie anpassen
            cfg = adapt_strategy(cfg, con)

    return cfg

def get_macro_signal():
    """Liest aktuelles Makro-Signal + Regime."""
    import json as _json
    macro_file = "/root/.hermes/profiles/hermes_trading/skills/trading/data/macro_signal.json"
    try:
        with open(macro_file) as f:
            data = _json.load(f)
        return data.get("signal", "neutral"), data.get("regime", "sideways")
    except:
        return "neutral", "sideways"

def apply_regime_filter(conviction, direction, regime):
    """Passt Conviction Score basierend auf Markt-Regime an."""
    if regime == "bull":
        if direction == "LONG":
            return min(1.0, conviction * 1.10)   # +10% fuer LONG im Bull
        else:
            return conviction * 0.90              # -10% fuer SHORT im Bull
    elif regime == "bear":
        if direction == "LONG":
            return conviction * 0.80              # -20% fuer LONG im Bear
        else:
            return min(1.0, conviction * 1.20)   # +20% fuer SHORT im Bear
    return conviction  # Sideways: unveraendert


def open_new_positions(con, cfg):
    """Öffnet neue Positionen aus der Watchlist."""
    # Makro + Regime Filter
    macro, regime = get_macro_signal()
    print(f"  🌍 Makro: {macro.upper()} | Regime: {regime.upper()}", flush=True)
    if macro == "bearish" and regime == "bear":
        print(f"  ⛔ Makro BEARISH + Regime BEAR – kein neuer LONG-Kauf", flush=True)
        return
    if macro == "bearish":
        print(f"  ⚠️  Makro BEARISH – fahre mit reduzierter Conviction fort", flush=True)
    open_count = con.execute(
        "SELECT COUNT(*) FROM positions WHERE status='open'"
    ).fetchone()[0]

    if open_count >= cfg["max_positions"]:
        print(f"  📊 Max. Positionen ({cfg['max_positions']}) erreicht")
        return

    portfolio = con.execute("SELECT * FROM portfolio WHERE id=1").fetchone()
    cash = portfolio["cash"]

    if cash < 500:
        print(f"  💸 Zu wenig Cash: {cash:.2f}€")
        return

    # Bereits offene Ticker und Sektoren
    open_positions = con.execute(
        "SELECT ticker FROM positions WHERE status='open'"
    ).fetchall()
    open_tickers  = {r["ticker"] for r in open_positions}
    open_sectors  = {get_sector(r["ticker"]) for r in open_positions}

    # Heute bereits gehandelte Ticker
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    recent_tickers = {r["ticker"] for r in con.execute(
        "SELECT ticker FROM positions WHERE entry_date >= ?", (yesterday,)
    ).fetchall()}

    # Watchlist-Kandidaten laden
    candidates = con.execute("""
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
        cfg.get("min_confidence", 0.65)
    )).fetchall()

    if not candidates:
        print("  ℹ Keine Watchlist-Kandidaten die alle Kriterien erfüllen.")
        return

    # Priority Score berechnen + Tiebreaker
    def priority_score(c):
        channels = json.loads(c["channels"] or "[]")
        unique_channels = len(set(channels))
        channel_diversity = min(unique_channels / 3, 1.0)

        # Aktualität: je neuer desto besser (0-1)
        try:
            last_seen = datetime.strptime(c["last_seen"], "%Y-%m-%d")
            days_ago  = (datetime.now() - last_seen).days
            recency   = max(0, 1 - days_ago / 30)
        except:
            recency = 0

        score = (
            (c["conviction_score"] or 0) * 0.40 +
            (c["tech_score"] or 0)       * 0.40 +
            channel_diversity             * 0.20
        )
        # Tiebreaker als Dezimalstellen
        tiebreaker = (
            recency                      * 0.001 +
            (c["tech_score"] or 0)       * 0.0001 +
            min(c["mention_count"], 10)  * 0.00001
        )
        return score + tiebreaker

    candidates = sorted(candidates, key=priority_score, reverse=True)

    slots_available = cfg["max_positions"] - open_count
    opened = 0
    used_sectors = set()

    for c in candidates:
        if opened >= slots_available:
            break

        ticker    = c["ticker"]
        sector    = get_sector(ticker, con)
        channels  = json.loads(c["channels"] or "[]")
        unique_channels = len(set(channels))

        # Filter
        if ticker in open_tickers:
            continue
        if ticker in recent_tickers:
            continue

        # Sektor-Diversifikation: max 3 pro Sektor (bei max 8 Positionen)
        sector_count = sum(1 for s in list(open_sectors) if s == sector)
        if sector_count >= 3:
            print(f"  ⚖ {c['name']}: Sektor {sector} bereits 2x offen – überspringe")
            continue

        # Nicht gleichen Sektor zweimal in diesem Run kaufen
        if sector in used_sectors:
            print(f"  ⚖ {c['name']}: Sektor {sector} bereits in diesem Run – überspringe")
            continue

        # Preis und ATR holen
        current_price, atr = get_current_price_and_atr(ticker)
        if not current_price or not atr:
            continue

        import math
        if math.isnan(current_price) or math.isnan(atr):
            continue

        # Dynamisches Position Sizing nach Conviction Score
        portfolio_value = portfolio["total_value"] or cfg["starting_capital"]
        conviction = c["conviction_score"] or 0
        # Regime-Gewichtung anwenden
        conviction = apply_regime_filter(conviction, "LONG", regime)
        if conviction >= cfg.get("conviction_high", 0.80):
            pct = cfg.get("max_position_pct_high", 0.20)
            sizing_label = "HIGH"
        elif conviction < cfg.get("conviction_low", 0.60) + 0.05:
            pct = cfg.get("max_position_pct_low", 0.10)
            sizing_label = "LOW"
        else:
            pct = cfg.get("max_position_pct", 0.15)
            sizing_label = "NORMAL"

        position_size = min(pct * portfolio_value, cash)
        print(f"  💰 Position Sizing: {sizing_label} ({pct:.0%}) = {position_size:.0f}€", flush=True)
        if position_size < 200:
            continue

        shares = position_size / current_price
        sl = current_price - (cfg["atr_sl_multiplier"] * atr)
        tp = current_price + (cfg["atr_tp_multiplier"] * atr)
        sl_pct = abs(current_price - sl) / current_price * 100
        tp_pct = abs(tp - current_price) / current_price * 100

        # Position eintragen
        con.execute("""
            INSERT INTO positions
            (ticker, name, direction, entry_price, entry_date,
             stop_loss, take_profit, trailing_sl, position_size, shares,
             atr_at_entry, confidence, source_channel, reason)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            ticker, c["name"], "LONG",
            round(current_price, 2),
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            round(sl, 2), round(tp, 2), round(sl, 2),
            round(position_size, 2), round(shares, 4),
            round(atr, 4), c["conviction_score"],
            ", ".join(set(channels[:3])),
            c["notes"] or ""
        ))

        # Watchlist Status updaten
        con.execute(
            "UPDATE watchlist SET status='bought' WHERE name=?",
            (c["name"],)
        )

        # Cash reduzieren
        cash -= position_size
        con.execute(
            "UPDATE portfolio SET cash=?, updated_at=? WHERE id=1",
            (round(cash, 2), datetime.now().isoformat())
        )
        con.commit()

        open_tickers.add(ticker)
        open_sectors.add(sector)
        used_sectors.add(sector)
        opened += 1

        msg = (
            f"📈 <b>NEUES SIGNAL: {c['name']}</b>\n"
            f"Ticker: {ticker} | LONG | Sektor: {sector}\n"
            f"Entry: {current_price:.2f}\n"
            f"Stop-Loss: {sl:.2f} (-{sl_pct:.1f}%)\n"
            f"Take-Profit: {tp:.2f} (+{tp_pct:.1f}%)\n"
            f"Investiert: {position_size:.0f}€ ({shares:.2f} Anteile)\n\n"
            f"📊 <b>Watchlist-Analyse:</b>\n"
            f"• Mentions: {c['mention_count']}x in 30 Tagen\n"
            f"• Kanäle: {', '.join(set(channels[:3]))} ({unique_channels} verschiedene)\n"
            f"• Conviction: {c['conviction_score']:.0%} bullish\n"
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
    print(f"PORTFOLIO ÜBERSICHT")
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
        print(f"\nOFFENE POSITIONEN:")
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
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    init_db(con)

    cfg = load_config()
    print(f"📊 Signal Manager gestartet (Modus: {mode})", flush=True)

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


if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "full"
    main(mode)
