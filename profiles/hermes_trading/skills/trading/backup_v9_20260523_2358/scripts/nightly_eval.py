"""
Nightly Eval - Tägliche Qualitätsmessung
Läuft täglich 05:00 (nach trading_pipeline)
Läuft sonntags 06:00 (Wochenaggregat vor strategy_optimizer)
"""
import sqlite3, json, os, requests
from datetime import datetime, timedelta

DB_PATH    = "/root/.hermes/profiles/hermes_trading/skills/trading/data/trading.db"
TG_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN")
TG_CHAT    = os.environ.get("TELEGRAM_CHAT_ID")
IS_SUNDAY  = datetime.now().weekday() == 6

def send_telegram(msg):
    if not TG_TOKEN or not TG_CHAT:
        print(msg); return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except: pass

def calc_signal_metrics(con, today, yesterday):
    """Vergleicht Signale heute vs gestern."""
    today_names = set(r[0] for r in con.execute(
        "SELECT DISTINCT name FROM watchlist_mentions WHERE mention_date=?", (today,)
    ).fetchall())
    yesterday_names = set(r[0] for r in con.execute(
        "SELECT DISTINCT name FROM watchlist_mentions WHERE mention_date=?", (yesterday,)
    ).fetchall())

    # Sentiment heute
    today_sent = {}
    for row in con.execute("""
        SELECT name, sentiment FROM watchlist_mentions WHERE mention_date=?
    """, (today,)).fetchall():
        today_sent.setdefault(row[0], []).append(row[1])

    yesterday_sent = {}
    for row in con.execute("""
        SELECT name, sentiment FROM watchlist_mentions WHERE mention_date=?
    """, (yesterday,)).fetchall():
        yesterday_sent.setdefault(row[0], []).append(row[1])

    new_companies = len(today_names - yesterday_names)
    confirmed     = 0
    contradicted  = 0

    for name in today_names & yesterday_names:
        t_bull = today_sent.get(name, []).count("bullish")
        t_bear = today_sent.get(name, []).count("bearish")
        y_bull = yesterday_sent.get(name, []).count("bullish")
        y_bear = yesterday_sent.get(name, []).count("bearish")

        t_dominant = "bullish" if t_bull > t_bear else "bearish" if t_bear > t_bull else "neutral"
        y_dominant = "bullish" if y_bull > y_bear else "bearish" if y_bear > y_bull else "neutral"

        if t_dominant == y_dominant and t_dominant != "neutral":
            confirmed += 1
        elif t_dominant != y_dominant and "neutral" not in [t_dominant, y_dominant]:
            contradicted += 1

    # Avg conviction
    avg_conv = con.execute("""
        SELECT AVG(conviction_score) FROM watchlist
        WHERE last_seen=? AND conviction_score > 0
    """, (today,)).fetchone()[0] or 0

    # Signale die heute gekauft wurden
    signals_bought = con.execute("""
        SELECT COUNT(*) FROM positions
        WHERE entry_date LIKE ? AND status='open'
    """, (f"{today}%",)).fetchone()[0]

    return {
        "new_companies":  new_companies,
        "confirmed":      confirmed,
        "contradicted":   contradicted,
        "avg_conviction": round(avg_conv, 3),
        "signals_bought": signals_bought,
    }

def calc_portfolio_metrics(con):
    """Berechnet Portfolio-Performance Metriken."""
    now   = datetime.now()
    d7    = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    d30   = (now - timedelta(days=30)).strftime("%Y-%m-%d")

    def win_rate(since):
        rows = con.execute("""
            SELECT pnl_eur FROM positions
            WHERE status='closed' AND exit_date >= ?
        """, (since,)).fetchall()
        if not rows: return 0
        wins = sum(1 for r in rows if (r[0] or 0) > 0)
        return round(wins / len(rows), 3)

    def profit_factor(since):
        rows = con.execute("""
            SELECT pnl_eur FROM positions
            WHERE status='closed' AND exit_date >= ?
        """, (since,)).fetchall()
        gains  = sum(r[0] for r in rows if (r[0] or 0) > 0)
        losses = abs(sum(r[0] for r in rows if (r[0] or 0) < 0))
        return round(gains / losses, 2) if losses > 0 else gains

    # Haltedauer
    holding = con.execute("""
        SELECT AVG(julianday(exit_date) - julianday(entry_date))
        FROM positions WHERE status='closed'
    """).fetchone()[0] or 0

    # Exit-Gründe
    exits = con.execute("""
        SELECT exit_reason, COUNT(*) FROM positions
        WHERE status='closed' AND exit_date >= ?
        GROUP BY exit_reason
    """, (d30,)).fetchall()
    total_exits = sum(e[1] for e in exits) or 1
    exit_map    = {e[0]: e[1] for e in exits}

    open_pos = con.execute(
        "SELECT COUNT(*) FROM positions WHERE status='open'"
    ).fetchone()[0]

    return {
        "open_positions":   open_pos,
        "win_rate_7d":      win_rate(d7),
        "win_rate_30d":     win_rate(d30),
        "profit_factor_7d": profit_factor(d7),
        "avg_holding_days": round(holding, 1),
        "exit_sl_pct":      round(exit_map.get("SL_HIT", 0) / total_exits, 3),
        "exit_tp_pct":      round(exit_map.get("TARGET_HIT", 0) / total_exits, 3),
        "exit_tech_pct":    round(exit_map.get("TECH_BROKEN", 0) / total_exits, 3),
    }

def calc_source_quality(con, today):
    """Berechnet Qualitätsscore pro Quelle."""
    d30 = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    channels = con.execute("""
        SELECT DISTINCT channel FROM watchlist_mentions
        WHERE mention_date >= ?
    """, (d30,)).fetchall()

    results = []
    for (channel,) in channels:
        mentions = con.execute("""
            SELECT COUNT(*) FROM watchlist_mentions
            WHERE channel=? AND mention_date >= ?
        """, (channel, d30)).fetchone()[0]

        # Trades die aus diesem Kanal stammen
        trades = con.execute("""
            SELECT pnl_eur FROM positions
            WHERE source_channel LIKE ? AND status='closed'
            AND exit_date >= ?
        """, (f"%{channel}%", d30)).fetchall()

        bought   = len(trades)
        wins     = sum(1 for t in trades if (t[0] or 0) > 0)
        win_rate = round(wins / bought, 3) if bought > 0 else 0
        avg_pnl  = round(sum(t[0] or 0 for t in trades) / bought, 2) if bought > 0 else 0

        # Quality Score: Win Rate * 0.6 + Konsistenz * 0.4
        consistency = min(mentions / 10, 1.0)
        quality     = round(win_rate * 0.6 + consistency * 0.4, 3)

        results.append({
            "channel":     channel,
            "mentions_30d": mentions,
            "bought_30d":  bought,
            "win_rate_30d": win_rate,
            "avg_pnl_30d": avg_pnl,
            "quality_score": quality,
        })

        con.execute("""
            INSERT OR REPLACE INTO source_quality
            (date, channel, mentions_30d, bought_30d, win_rate_30d,
             avg_pnl_30d, quality_score)
            VALUES (?,?,?,?,?,?,?)
        """, (today, channel, mentions, bought, win_rate, avg_pnl, quality))

    con.commit()
    return sorted(results, key=lambda x: x["quality_score"], reverse=True)

def weekly_aggregate(con):
    """Wochenaggregat für strategy_optimizer."""
    d7 = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    metrics = con.execute("""
        SELECT AVG(win_rate_7d), AVG(profit_factor_7d),
               SUM(signals_bought), AVG(avg_conviction)
        FROM eval_metrics
        WHERE date >= ? AND metric_type='daily'
    """, (d7,)).fetchone()

    return {
        "avg_win_rate_7d":     round(metrics[0] or 0, 3),
        "avg_profit_factor_7d": round(metrics[1] or 0, 2),
        "total_signals_bought": metrics[2] or 0,
        "avg_conviction_7d":   round(metrics[3] or 0, 3),
    }

def main():
    print(f"📊 Nightly Eval {'(Woche)' if IS_SUNDAY else '(täglich)'} "
          f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}]", flush=True)

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    today     = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    # 1. Signal-Metriken
    print("\n📡 Signal-Metriken...", flush=True)
    sm = calc_signal_metrics(con, today, yesterday)
    print(f"  Neue Unternehmen:  {sm['new_companies']}", flush=True)
    print(f"  Bestätigungen:     {sm['confirmed']}", flush=True)
    print(f"  Widersprüche:      {sm['contradicted']}", flush=True)
    print(f"  Ø Conviction:      {sm['avg_conviction']:.1%}", flush=True)
    print(f"  Signale gekauft:   {sm['signals_bought']}", flush=True)

    # 2. Portfolio-Metriken
    print("\n💼 Portfolio-Metriken...", flush=True)
    pm = calc_portfolio_metrics(con)
    print(f"  Offene Positionen: {pm['open_positions']}", flush=True)
    print(f"  Win Rate (7d):     {pm['win_rate_7d']:.1%}", flush=True)
    print(f"  Win Rate (30d):    {pm['win_rate_30d']:.1%}", flush=True)
    print(f"  Profit Factor (7d):{pm['profit_factor_7d']:.2f}", flush=True)
    print(f"  Ø Haltedauer:      {pm['avg_holding_days']} Tage", flush=True)
    print(f"  SL/TP/Tech Exits:  {pm['exit_sl_pct']:.0%}/{pm['exit_tp_pct']:.0%}/{pm['exit_tech_pct']:.0%}", flush=True)

    # 3. In DB speichern
    metric_type = "weekly" if IS_SUNDAY else "daily"
    con.execute("""
        INSERT OR REPLACE INTO eval_metrics
        (date, metric_type, new_companies, confirmed, contradicted,
         avg_conviction, signals_bought, open_positions, win_rate_7d,
         win_rate_30d, profit_factor_7d, avg_holding_days,
         exit_sl_pct, exit_tp_pct, exit_tech_pct, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (today, metric_type,
          sm["new_companies"], sm["confirmed"], sm["contradicted"],
          sm["avg_conviction"], sm["signals_bought"],
          pm["open_positions"], pm["win_rate_7d"], pm["win_rate_30d"],
          pm["profit_factor_7d"], pm["avg_holding_days"],
          pm["exit_sl_pct"], pm["exit_tp_pct"], pm["exit_tech_pct"],
          datetime.now().isoformat()))
    con.commit()

    # 4. Source Quality
    print("\n🔍 Source-Qualität...", flush=True)
    sources = calc_source_quality(con, today)
    for s in sources[:5]:
        print(f"  {s['channel']:25} WR:{s['win_rate_30d']:.0%} "
              f"Q:{s['quality_score']:.2f} ({s['mentions_30d']}x)", flush=True)

    # 5. Telegram Tages-Report
    cons_ok  = "✅" if sm["confirmed"] >= sm["contradicted"] else "⚠️"
    wr_ok    = "✅" if pm["win_rate_7d"] >= 0.5 else "⚠️" if pm["win_rate_7d"] >= 0.35 else "❌"
    top_src  = sources[0] if sources else None
    top_line = f"Top-Quelle: <b>{top_src['channel']}</b> (WR:{top_src['win_rate_30d']:.0%}, Q:{top_src['quality_score']:.2f})" if top_src else ""

    if IS_SUNDAY:
        weekly = weekly_aggregate(con)
        msg = (
            f"📊 <b>Wochen-Report {today}</b>\n\n"
            f"Signal-Pipeline (7d):\n"
            f"  Ø Conviction: {weekly['avg_conviction_7d']:.0%}\n"
            f"  Signale gekauft: {weekly['total_signals_bought']}\n\n"
            f"Portfolio:\n"
            f"  Win Rate (7d): {pm['win_rate_7d']:.0%} {wr_ok}\n"
            f"  Profit Factor: {pm['profit_factor_7d']:.2f}\n"
            f"  SL/TP/Tech: {pm['exit_sl_pct']:.0%}/{pm['exit_tp_pct']:.0%}/{pm['exit_tech_pct']:.0%}\n\n"
            f"{top_line}\n\n"
            f"🔧 Strategy Optimizer läuft um 08:00..."
        )
    else:
        msg = (
            f"📊 <b>Tages-Report {today}</b>\n\n"
            f"Signal-Pipeline:\n"
            f"  Neue Unternehmen: {sm['new_companies']}\n"
            f"  Bestätigungen: {sm['confirmed']} {cons_ok}\n"
            f"  Widersprüche: {sm['contradicted']}\n"
            f"  Ø Conviction: {sm['avg_conviction']:.0%}\n\n"
            f"Portfolio:\n"
            f"  Offene Pos.: {pm['open_positions']}/8\n"
            f"  Win Rate (7d): {pm['win_rate_7d']:.0%} {wr_ok}\n"
            f"  Profit Factor: {pm['profit_factor_7d']:.2f}\n\n"
            f"{top_line}"
        )

    send_telegram(msg)
    con.close()
    print("\n✅ Nightly Eval abgeschlossen", flush=True)

if __name__ == "__main__":
    main()
