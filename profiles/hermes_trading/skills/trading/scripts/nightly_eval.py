"""
Nightly Eval - Tägliche Qualitätsmessung
Läuft täglich 05:00 (nach trading_pipeline)
Läuft sonntags 06:00 (Wochenaggregat vor strategy_optimizer)
NEU: Sortino Ratio, Calmar Ratio, R-Multiple, Exposure (LONG/SHORT)
"""
import sqlite3, json, os, requests, math
import sys
sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")
import env_loader  # noqa: F401  (side-effect: laedt .env)
from datetime import datetime, timedelta
from config import DB_PATH, STRATEGY_CONFIG_PATH, SIGNALS_VALIDATED_PATH, db_connect

TG_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN")
TG_CHAT    = os.environ.get("TELEGRAM_HOME_CHANNEL") or os.environ.get("TELEGRAM_CHAT_ID", "")
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
    except Exception: pass

def calc_signal_metrics(con, today, yesterday):
    # FIX: Use the latest two mention_dates in the DB instead of datetime.now()
    # because watchlist_manager stores video upload dates, not pipeline run dates.
    last_dates = con.execute(
        "SELECT DISTINCT mention_date FROM watchlist_mentions ORDER BY mention_date DESC LIMIT 2"
    ).fetchall()
    if len(last_dates) >= 2:
        today = last_dates[0][0]
        yesterday = last_dates[1][0]
    elif len(last_dates) == 1:
        today = last_dates[0][0]
        yesterday = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        return {"new_companies": 0, "confirmed": 0, "contradicted": 0, "avg_conviction": 0, "signals_bought": 0}
    today_names = set(r[0] for r in con.execute(
        "SELECT DISTINCT name FROM watchlist_mentions WHERE mention_date=?", (today,)
    ).fetchall())
    yesterday_names = set(r[0] for r in con.execute(
        "SELECT DISTINCT name FROM watchlist_mentions WHERE mention_date=?", (yesterday,)
    ).fetchall())
    today_sent = {}
    for row in con.execute("SELECT name, sentiment FROM watchlist_mentions WHERE mention_date=?", (today,)).fetchall():
        today_sent.setdefault(row[0], []).append(row[1])
    yesterday_sent = {}
    for row in con.execute("SELECT name, sentiment FROM watchlist_mentions WHERE mention_date=?", (yesterday,)).fetchall():
        yesterday_sent.setdefault(row[0], []).append(row[1])
    new_companies = len(today_names - yesterday_names)
    confirmed = contradicted = 0
    for name in today_names & yesterday_names:
        t_bull = today_sent.get(name, []).count("bullish")
        t_bear = today_sent.get(name, []).count("bearish")
        y_bull = yesterday_sent.get(name, []).count("bullish")
        y_bear = yesterday_sent.get(name, []).count("bearish")
        t_dom = "bullish" if t_bull > t_bear else "bearish" if t_bear > t_bull else "neutral"
        y_dom = "bullish" if y_bull > y_bear else "bearish" if y_bear > y_bull else "neutral"
        if t_dom == y_dom and t_dom != "neutral": confirmed += 1
        elif t_dom != y_dom and "neutral" not in [t_dom, y_dom]: contradicted += 1
    avg_conv = con.execute("SELECT AVG(conviction_score) FROM watchlist WHERE last_seen=? AND conviction_score > 0", (today,)).fetchone()[0] or 0
    signals_bought = con.execute("SELECT COUNT(*) FROM positions WHERE entry_date LIKE ? AND status='open'", (f"{today}%",)).fetchone()[0]
    return {"new_companies": new_companies, "confirmed": confirmed, "contradicted": contradicted,
            "avg_conviction": round(avg_conv, 3), "signals_bought": signals_bought}

def calc_portfolio_metrics(con):
    now = datetime.now()
    d7 = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    d30 = (now - timedelta(days=30)).strftime("%Y-%m-%d")

    def win_rate(since):
        rows = con.execute("SELECT pnl_eur FROM positions WHERE status='closed' AND exit_date >= ?", (since,)).fetchall()
        if not rows: return 0
        return round(sum(1 for r in rows if (r[0] or 0) > 0) / len(rows), 3)

    def profit_factor(since):
        rows = con.execute("SELECT pnl_eur FROM positions WHERE status='closed' AND exit_date >= ?", (since,)).fetchall()
        gains = sum(r[0] for r in rows if (r[0] or 0) > 0)
        losses = abs(sum(r[0] for r in rows if (r[0] or 0) < 0))
        return round(gains / losses, 2) if losses > 0 else gains

    # #16: Portfolio-Bezugsgröße für gewichtete Renditen. Vorher wurde pnl_pct
    # (Rendite auf die EINZELPOSITION) behandelt, als wäre es die Portfolio-
    # Rendite. Eine -10%-Position ≈ -1,5% aufs Portfolio → Sortino/Calmar/DD
    # waren dadurch stark überzeichnet. Jetzt: Beitrag = pnl_eur / portfolio_value.
    _pv_row = con.execute("SELECT total_value FROM portfolio WHERE id=1").fetchone()
    portfolio_base = (_pv_row[0] if _pv_row and _pv_row[0] else 10000.0)

    def _portfolio_returns_pct(since):
        """Liste der Portfolio-Renditen je Trade in % (pnl_eur / Portfolio-Wert)."""
        rows = con.execute(
            "SELECT pnl_eur FROM positions WHERE status='closed' AND exit_date >= ? ORDER BY exit_date",
            (since,)
        ).fetchall()
        return [((r[0] or 0) / portfolio_base) * 100 for r in rows]

    def sortino_ratio(since):
        pnls = _portfolio_returns_pct(since)
        if len(pnls) < 2: return 0
        avg = sum(pnls) / len(pnls)
        downside = [p for p in pnls if p < 0]
        if not downside: return 0
        dstd = math.sqrt(sum(p**2 for p in downside) / len(pnls))
        return round((avg / dstd) * math.sqrt(252), 2) if dstd > 0 else 0

    def max_drawdown(since):
        pnls = _portfolio_returns_pct(since)
        equity, peak, max_dd = portfolio_base, portfolio_base, 0
        for p in pnls:
            equity *= (1 + p / 100)
            peak = max(peak, equity)
            max_dd = max(max_dd, (peak - equity) / peak * 100)
        return round(max_dd, 2)

    def calmar_ratio(since):
        pnls = _portfolio_returns_pct(since)
        if not pnls: return 0
        total_ret = 1.0
        for p in pnls:
            total_ret *= (1 + p / 100)
        total_ret = (total_ret - 1) * 100
        dd = max_drawdown(since)
        return round(total_ret / dd, 2) if dd > 0 else 0

    def avg_r_multiple(since):
        rows = con.execute("SELECT pnl_eur, position_size FROM positions WHERE status='closed' AND exit_date >= ?", (since,)).fetchall()
        if not rows: return 0
        mults = [(r[0] or 0) / r[1] for r in rows if r[1] and r[1] > 0]
        return round(sum(mults) / len(mults), 2) if mults else 0

    def exposure():
        rows = con.execute("SELECT direction, position_size FROM positions WHERE status='open'").fetchall()
        long_val = sum(r[1] or 0 for r in rows if r[0] == "LONG")
        short_val = sum(r[1] or 0 for r in rows if r[0] == "SHORT")
        portfolio = con.execute("SELECT total_value FROM portfolio WHERE id=1").fetchone()
        pv = portfolio[0] if portfolio else 10000
        return {"long_pct": round(long_val / pv * 100, 1) if pv > 0 else 0,
                "short_pct": round(short_val / pv * 100, 1) if pv > 0 else 0,
                "net_pct": round((long_val - short_val) / pv * 100, 1) if pv > 0 else 0}

    holding = con.execute("SELECT AVG(julianday(exit_date) - julianday(entry_date)) FROM positions WHERE status='closed'").fetchone()[0] or 0
    exits = con.execute("SELECT exit_reason, COUNT(*) FROM positions WHERE status='closed' AND exit_date >= ? GROUP BY exit_reason", (d30,)).fetchall()
    total_exits = sum(e[1] for e in exits) or 1
    exit_map = {e[0]: e[1] for e in exits}
    open_pos = con.execute("SELECT COUNT(*) FROM positions WHERE status='open'").fetchone()[0]
    exp = exposure()

    return {
        "open_positions": open_pos, "win_rate_7d": win_rate(d7), "win_rate_30d": win_rate(d30),
        "profit_factor_7d": profit_factor(d7), "sortino_30d": sortino_ratio(d30),
        "calmar_30d": calmar_ratio(d30), "max_drawdown_30d": max_drawdown(d30),
        "avg_r_multiple": avg_r_multiple(d30), "exposure_long_pct": exp["long_pct"],
        "exposure_short_pct": exp["short_pct"], "exposure_net_pct": exp["net_pct"],
        "avg_holding_days": round(holding, 1),
        "exit_sl_pct": round(exit_map.get("SL_HIT", 0) / total_exits, 3),
        "exit_tp_pct": round(exit_map.get("TARGET_HIT", 0) / total_exits, 3),
        "exit_tech_pct": round(exit_map.get("TECH_BROKEN", 0) / total_exits, 3),
    }

def calc_source_quality(con, today):
    """
    Berechnet Quellen-Qualität mit zwei Metriken:

    1. Trade-Qualität (für etablierte Quellen mit ≥1 Trade):
       quality = win_rate * 0.6 + consistency * 0.4

    2. Signal-Qualität (Früh-Indikator, funktioniert ab Tag 1):
       signal_quality = watchlist_hits / mentions
       → Wieviel % der Mentions führten zu einer Watchlist-Aufnahme (conviction ≥ 0.55)?
       → Relevant für Twitter-Quellen die noch keine Trade-Historie haben

    Die signal_quality wird in source_quality.signal_quality gespeichert und
    von source_lifecycle.evaluate_active_sources() für Probation-Entscheidungen genutzt.
    """
    d30 = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    channels = con.execute(
        "SELECT DISTINCT channel FROM watchlist_mentions WHERE mention_date >= ?", (d30,)
    ).fetchall()
    results = []
    for (channel,) in channels:
        mentions = con.execute(
            "SELECT COUNT(*) FROM watchlist_mentions WHERE channel=? AND mention_date >= ?",
            (channel, d30)
        ).fetchone()[0]

        # #19: source_channel ist eine kommagetrennte Liste (", ".join(...)).
        # Substring-LIKE '%channel%' konnte Quellen quer-attribuieren, deren Name
        # Teilstring eines anderen ist (z.B. "Aktien" in "Aktien Mag"). Jetzt exakt
        # als ganzes Token in der Liste matchen.
        trades = con.execute(
            """SELECT pnl_eur FROM positions
               WHERE (source_channel = ?
                      OR source_channel LIKE ?
                      OR source_channel LIKE ?
                      OR source_channel LIKE ?)
                 AND status='closed' AND exit_date >= ?""",
            (channel, f"{channel}, %", f"%, {channel}", f"%, {channel}, %", d30)
        ).fetchall()
        bought   = len(trades)
        wins     = sum(1 for t in trades if (t[0] or 0) > 0)
        win_rate = round(wins / bought, 3) if bought > 0 else 0
        avg_pnl  = round(sum(t[0] or 0 for t in trades) / bought, 2) if bought > 0 else 0

        # Signal-Qualität: Mentions → Watchlist-Treffer (Früh-Indikator)
        watchlist_hits = con.execute("""
            SELECT COUNT(DISTINCT wm.name) FROM watchlist_mentions wm
            JOIN watchlist w ON lower(w.name) = lower(wm.name)
            WHERE wm.channel = ?
              AND wm.mention_date >= ?
              AND w.conviction_score >= 0.55
        """, (channel, d30)).fetchone()[0]
        signal_quality = round(watchlist_hits / mentions, 3) if mentions > 0 else 0

        # Kombinierter Score:
        # - Mit Trades: trade-basiert
        # - Ohne Trades (neue Quelle): signal_quality als Proxy
        consistency = min(mentions / 10, 1.0)
        if bought >= 3:
            quality = round(win_rate * 0.6 + consistency * 0.4, 3)
        else:
            # Neue Quelle: signal_quality (Relevanz der Mentions) als Proxy
            quality = round(signal_quality * 0.7 + consistency * 0.3, 3)

        results.append({
            "channel":        channel,
            "mentions_30d":   mentions,
            "bought_30d":     bought,
            "win_rate_30d":   win_rate,
            "avg_pnl_30d":    avg_pnl,
            "quality_score":  quality,
            "signal_quality": signal_quality,
            "watchlist_hits": watchlist_hits,
        })
        con.execute("""
            INSERT OR REPLACE INTO source_quality
            (date, channel, mentions_30d, bought_30d, win_rate_30d, avg_pnl_30d, quality_score)
            VALUES (?,?,?,?,?,?,?)
        """, (today, channel, mentions, bought, win_rate, avg_pnl, quality))
    con.commit()
    return sorted(results, key=lambda x: x["quality_score"], reverse=True)


def check_half_life_calibration(con):
    """
    Prüft ob CONVICTION_HALF_LIFE_DAYS gut kalibriert ist.

    Wenn conviction_aged systematisch viel niedriger als conviction_score ist
    → Halbwertszeit möglicherweise zu kurz (Signale veralten zu schnell).
    Wenn beide fast identisch sind → viele Signale sind frisch, ok.

    Gibt einen Hinweis aus wenn Kalibrierung angepasst werden sollte.
    """
    try:
        rows = con.execute("""
            SELECT AVG(conviction_score) as avg_raw,
                   AVG(conviction_score_aged) as avg_aged,
                   COUNT(*) as cnt
            FROM watchlist
            WHERE status = 'watching'
              AND conviction_score >= 0.50
              AND conviction_score_aged IS NOT NULL
              AND conviction_score_aged > 0
        """).fetchone()

        if not rows or rows["cnt"] < 10:
            return

        avg_raw   = rows["avg_raw"]   or 0
        avg_aged  = rows["avg_aged"]  or 0
        cnt       = rows["cnt"]

        if avg_raw == 0:
            return

        decay_ratio = avg_aged / avg_raw

        print(f"\n⏱  Halbwertszeit-Kalibrierung ({cnt} Einträge):")
        print(f"   Ø conviction_raw:  {avg_raw:.2f}")
        print(f"   Ø conviction_aged: {avg_aged:.2f}")
        print(f"   Decay-Ratio: {decay_ratio:.2f}", flush=True)

        if decay_ratio < 0.60:
            print("   ⚠ Decay-Ratio < 0.60: Signale veralten sehr schnell.")
            print("     → CONVICTION_HALF_LIFE_DAYS erhöhen? (aktuell in config.py)")
        elif decay_ratio > 0.95:
            print("   ℹ Decay-Ratio > 0.95: Fast kein Decay – Signale sind sehr frisch")
            print("     oder Halbwertszeit sehr lang.")
        else:
            print("   ✅ Decay-Ratio im normalen Bereich (0.60–0.95)")
    except Exception as e:
        print(f"  ⚠ half_life_check Fehler: {e}")


def weekly_aggregate(con):
    d7 = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    metrics = con.execute("SELECT AVG(win_rate_7d), AVG(profit_factor_7d), SUM(signals_bought), AVG(avg_conviction) FROM eval_metrics WHERE date >= ? AND metric_type='daily'", (d7,)).fetchone()
    return {"avg_win_rate_7d": round(metrics[0] or 0, 3), "avg_profit_factor_7d": round(metrics[1] or 0, 2),
            "total_signals_bought": metrics[2] or 0, "avg_conviction_7d": round(metrics[3] or 0, 3)}

def get_benchmark_data(con):
    """Lädt aktuellste Benchmark-Daten aus benchmark-Tabelle."""
    try:
        row = con.execute(
            "SELECT * FROM benchmark ORDER BY date DESC LIMIT 1"
        ).fetchone()
        if row:
            return dict(row)
    except Exception:
        pass
    return None


def update_segment_performance(con):
    """
    Loop 1: Post-Trade Learner
    Aggregiert geschlossene Positionen nach (sector, conviction_tier, tech_direction, regime)
    und schreibt/updatet segment_performance-Tabelle.
    """
    try:
        rows = con.execute("""
            SELECT 
                COALESCE(c.sector, 'Other') as sector,
                CASE 
                    WHEN p.entry_conviction_score >= 0.8 THEN 'HIGH'
                    WHEN p.entry_conviction_score >= 0.6 THEN 'NORMAL'
                    ELSE 'LOW'
                END as conviction_tier,
                p.direction as tech_direction,
                COALESCE(rh.regime, 'sideways') as regime_at_entry,
                COUNT(*) as trades_total,
                SUM(CASE WHEN p.pnl_eur > 0 THEN 1 ELSE 0 END) as trades_won,
                SUM(CASE WHEN p.pnl_eur < 0 THEN 1 ELSE 0 END) as trades_lost,
                ROUND(SUM(p.pnl_eur), 2) as sum_pnl_eur,
                ROUND(AVG(p.pnl_pct), 2) as avg_pnl_pct,
                ROUND(AVG(
                    julianday(COALESCE(p.exit_date, datetime('now'))) - julianday(p.entry_date)
                ), 1) as avg_holding_days
            FROM positions p
            LEFT JOIN companies c ON c.ticker = p.ticker
            LEFT JOIN regime_history rh ON rh.date = DATE(p.entry_date)
            WHERE p.status = 'closed'
              AND p.entry_conviction_score IS NOT NULL
            GROUP BY sector, conviction_tier, tech_direction, regime_at_entry
        """).fetchall()

        updated = 0
        for r in rows:
            total = r['trades_total']
            won = r['trades_won']
            if total == 0:
                continue
            win_rate = round(won / total, 3)
            con.execute("""
                INSERT INTO segment_performance
                    (sector, conviction_tier, tech_direction, regime_at_entry,
                     trades_total, trades_won, trades_lost, sum_pnl_eur,
                     avg_pnl_pct, avg_holding_days, win_rate, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
                ON CONFLICT(sector, conviction_tier, tech_direction, regime_at_entry)
                DO UPDATE SET
                    trades_total=excluded.trades_total,
                    trades_won=excluded.trades_won,
                    trades_lost=excluded.trades_lost,
                    sum_pnl_eur=excluded.sum_pnl_eur,
                    avg_pnl_pct=excluded.avg_pnl_pct,
                    avg_holding_days=excluded.avg_holding_days,
                    win_rate=excluded.win_rate,
                    updated_at=excluded.updated_at
            """, (r['sector'], r['conviction_tier'], r['tech_direction'],
                  r['regime_at_entry'], total, won, r['trades_lost'],
                  r['sum_pnl_eur'], r['avg_pnl_pct'], r['avg_holding_days'],
                  win_rate))
            updated += 1

        con.commit()
        print(f"\n🔄 Segment-Performance aktualisiert: {updated} Segmente", flush=True)
    except Exception as e:
        print(f"  ⚠ segment_performance Fehler: {e}", flush=True)


def calibrate_conviction(con):
    """
    Loop 2: Adaptive Conviction Calibration
    Prüft ob die Conviction-Tiers gut kalibriert sind (HIGH ≥ 70%, NORMAL ≥ 55%, LOW ≥ 40%).
    Gibt Warnung aus bei systematischer Abweichung.
    """
    try:
        tiers = {'HIGH': 0.70, 'NORMAL': 0.55, 'LOW': 0.40}
        print("\n📐 Conviction-Kalibrierung:", flush=True)
        for tier, expected_wr in tiers.items():
            row = con.execute("""
                SELECT COUNT(*) as cnt,
                       ROUND(AVG(win_rate), 3) as avg_wr,
                       ROUND(AVG(avg_pnl_pct), 2) as avg_pnl
                FROM segment_performance
                WHERE conviction_tier = ?
                  AND trades_total >= 3
            """, (tier,)).fetchone()
            if not row or row['cnt'] == 0:
                print(f"  {tier}: noch keine Daten", flush=True)
                continue
            delta = row['avg_wr'] - expected_wr
            icon = "✅" if abs(delta) < 0.10 else ("⚠️" if delta < 0 else "📈")
            adj = ""
            if delta < -0.10:
                adj = " → Prior erhöhen (konservativer)"
            elif delta > 0.10:
                adj = " → Prior senken (aggressiver)"
            print(f"  {icon} {tier}: WR {row['avg_wr']:.0%} (erwartet {expected_wr:.0%}, Δ{delta:+.0%})"
                  f" | {row['cnt']} Segmente | Ø {row['avg_pnl']:+.1f}%{adj}", flush=True)
    except Exception as e:
        print(f"  ⚠ calibration Fehler: {e}", flush=True)


def calc_committee_shadow(con, days=14):
    """
    Sprint R4: Auswertung des Investment Committees.

    Kernfrage der Shadow-Phase: Hätten die VETOs Verlusttrades verhindert oder
    Gewinner blockiert?

    Join committee_log × positions über (ticker, Datum). Nur Zeilen mit
    entry_happened=1 sind auswertbar – dort ist die Position tatsächlich
    eröffnet worden, und wir wissen im Nachhinein, was sie gebracht hat.

    Fail-Open: Tabelle fehlt (Sprint noch nicht deployed) → None.
    """
    try:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        rows = con.execute("""
            SELECT cl.final_verdict, cl.mode, cl.would_block, cl.entry_happened,
                   cl.ticker, cl.direction, cl.size_factor,
                   p.status, p.pnl_eur, p.entry_price, p.exit_price
            FROM committee_log cl
            LEFT JOIN positions p
              ON p.ticker = cl.ticker
             AND p.direction = cl.direction
             AND substr(p.entry_date, 1, 10) = cl.check_date
            WHERE cl.check_date >= ?
        """, (cutoff,)).fetchall()

        if not rows:
            return None

        stats = {
            "days": days,
            "total_checks": len(rows),
            "approve": 0, "reduce": 0, "veto": 0, "errors": 0,
            # Kernmetrik: Trades, die trotz VETO liefen (Shadow-Mode)
            "veto_entries": 0,
            "veto_pnl_eur": 0.0,
            "veto_closed": 0,
            "veto_losers": 0,
            "approve_entries": 0,
            "approve_pnl_eur": 0.0,
            "approve_closed": 0,
            "approve_losers": 0,
            "open_veto": 0,
        }

        for r in rows:
            v = r["final_verdict"]
            if v == "APPROVE":
                stats["approve"] += 1
            elif v == "REDUCE":
                stats["reduce"] += 1
            elif v == "VETO":
                stats["veto"] += 1
            else:
                stats["errors"] += 1

            if not r["entry_happened"]:
                continue

            bucket = "veto" if v == "VETO" else "approve" if v == "APPROVE" else None
            if bucket is None:
                continue
            stats[f"{bucket}_entries"] += 1

            if r["status"] == "closed" and r["pnl_eur"] is not None:
                stats[f"{bucket}_closed"] += 1
                stats[f"{bucket}_pnl_eur"] += float(r["pnl_eur"])
                if float(r["pnl_eur"]) < 0:
                    stats[f"{bucket}_losers"] += 1
            elif r["status"] == "open" and v == "VETO":
                stats["open_veto"] += 1

        # Trefferquote der VETOs: Anteil der VETO-Trades, die im Minus endeten.
        # >50% = das Committee hat überwiegend Verlierer erwischt (gut).
        stats["veto_hit_rate"] = (
            stats["veto_losers"] / stats["veto_closed"]
            if stats["veto_closed"] else 0.0
        )
        return stats

    except sqlite3.OperationalError:
        return None   # committee_log existiert noch nicht
    except Exception as e:
        print(f"  ⚠ Committee-Auswertung fehlgeschlagen: {e}", flush=True)
        return None


def main():
    print(f"📊 Nightly Eval {'(Woche)' if IS_SUNDAY else '(täglich)'} [{datetime.now().strftime('%Y-%m-%d %H:%M')}]", flush=True)
    con = db_connect()
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        print("\n📡 Signal-Metriken...", flush=True)
        sm = calc_signal_metrics(con, today, yesterday)
        print(f"  Neue Unternehmen: {sm['new_companies']}", flush=True)
        print(f"  Bestätigungen: {sm['confirmed']}", flush=True)
        print(f"  Widersprüche: {sm['contradicted']}", flush=True)
        print(f"  Ø Conviction: {sm['avg_conviction']:.1%}", flush=True)
        print(f"  Signale gekauft: {sm['signals_bought']}", flush=True)

        print("\n💼 Portfolio-Metriken...", flush=True)
        pm = calc_portfolio_metrics(con)
        print(f"  Offene Positionen: {pm['open_positions']}", flush=True)
        print(f"  Win Rate (7d): {pm['win_rate_7d']:.1%}", flush=True)
        print(f"  Win Rate (30d): {pm['win_rate_30d']:.1%}", flush=True)
        print(f"  Profit Factor (7d): {pm['profit_factor_7d']:.2f}", flush=True)
        print(f"  Sortino (30d): {pm['sortino_30d']:.2f}", flush=True)
        print(f"  Calmar (30d): {pm['calmar_30d']:.2f}", flush=True)
        print(f"  Max Drawdown (30d): {pm['max_drawdown_30d']:.1f}%", flush=True)
        print(f"  Ø R-Multiple: {pm['avg_r_multiple']:.2f}R", flush=True)
        print(f"  Exposure: LONG {pm['exposure_long_pct']:.0f}% | SHORT {pm['exposure_short_pct']:.0f}% | Net {pm['exposure_net_pct']:.0f}%", flush=True)
        print(f"  Ø Haltedauer: {pm['avg_holding_days']} Tage", flush=True)
        print(f"  SL/TP/Tech Exits: {pm['exit_sl_pct']:.0%}/{pm['exit_tp_pct']:.0%}/{pm['exit_tech_pct']:.0%}", flush=True)

        # Benchmark-Vergleich
        bm = get_benchmark_data(con)
        if bm:
            print(f"\n📈 Benchmark-Vergleich (YTD):", flush=True)
            print(f"  Portfolio:  {bm['portfolio_return_ytd']:+.1f}%", flush=True)
            print(f"  SPY:        {bm['spy_return_ytd']:+.1f}% | Alpha: {bm['alpha_spy']:+.1f}%", flush=True)
            print(f"  DAX:        {bm['dax_return_ytd']:+.1f}% | Alpha: {bm['alpha_dax']:+.1f}%", flush=True)

        metric_type = "weekly" if IS_SUNDAY else "daily"
        con.execute("""
            INSERT OR REPLACE INTO eval_metrics
            (date, metric_type, new_companies, confirmed, contradicted, avg_conviction, signals_bought,
             open_positions, win_rate_7d, win_rate_30d, profit_factor_7d, avg_holding_days,
             exit_sl_pct, exit_tp_pct, exit_tech_pct, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (today, metric_type, sm["new_companies"], sm["confirmed"], sm["contradicted"],
              sm["avg_conviction"], sm["signals_bought"], pm["open_positions"], pm["win_rate_7d"],
              pm["win_rate_30d"], pm["profit_factor_7d"], pm["avg_holding_days"],
              pm["exit_sl_pct"], pm["exit_tp_pct"], pm["exit_tech_pct"], datetime.now().isoformat()))
        con.commit()

        # ── Investment Committee (Sprint R4) ─────────────────────────────
        # Shadow-Auswertung: hätten die VETOs Verlusttrades verhindert oder
        # Gewinner blockiert? Grundlage für die Entscheidung, committee_mode
        # auf "active" zu setzen.
        committee_line = ""
        cshadow = calc_committee_shadow(con, days=30 if IS_SUNDAY else 14)
        if cshadow:
            print(f"\n🏛 Investment Committee ({cshadow['days']}d):", flush=True)
            print(f"  Checks: {cshadow['total_checks']} "
                  f"(APPROVE {cshadow['approve']} / REDUCE {cshadow['reduce']} / "
                  f"VETO {cshadow['veto']} / Fehler {cshadow['errors']})", flush=True)
            if cshadow["veto_closed"]:
                print(f"  VETO-Trades geschlossen: {cshadow['veto_closed']} | "
                      f"P&L: {cshadow['veto_pnl_eur']:+.2f}€ | "
                      f"davon Verlierer: {cshadow['veto_hit_rate']:.0%}", flush=True)
            if cshadow["approve_closed"]:
                print(f"  APPROVE-Trades geschlossen: {cshadow['approve_closed']} | "
                      f"P&L: {cshadow['approve_pnl_eur']:+.2f}€", flush=True)
            if cshadow["open_veto"]:
                print(f"  VETO-Trades noch offen: {cshadow['open_veto']} "
                      f"(noch nicht auswertbar)", flush=True)
            if cshadow["veto"]:
                icon = "✅" if cshadow["veto_hit_rate"] >= 0.5 else "⚠️"
                committee_line = (
                    f"\n🏛 Committee ({cshadow['days']}d):\n"
                    f"  VETOs: {cshadow['veto']} | "
                    f"Vermiedene P&L: {-cshadow['veto_pnl_eur']:+.0f}€ {icon}\n"
                )

        print("\n🔍 Source-Qualität...", flush=True)
        sources = calc_source_quality(con, today)
        for s in sources[:5]:
            print(f"  {s['channel']:25} WR:{s['win_rate_30d']:.0%} Q:{s['quality_score']:.2f} ({s['mentions_30d']}x)", flush=True)

        cons_ok = "✅" if sm["confirmed"] >= sm["contradicted"] else "⚠️"
        wr_ok = "✅" if pm["win_rate_7d"] >= 0.5 else "⚠️" if pm["win_rate_7d"] >= 0.35 else "❌"
        top_src = sources[0] if sources else None
        top_line = f"Top-Quelle: <b>{top_src['channel']}</b> (WR:{top_src['win_rate_30d']:.0%}, Q:{top_src['quality_score']:.2f})" if top_src else ""
        bm_line = ""
        if bm:
            a_spy_icon = "✅" if bm["alpha_spy"] >= 0 else "❌"
            a_dax_icon = "✅" if bm["alpha_dax"] >= 0 else "❌"
            bm_line = (
                f"\n📈 Benchmark (YTD):\n"
                f"  Portfolio: {bm['portfolio_return_ytd']:+.1f}%\n"
                f"  vs SPY: {bm['alpha_spy']:+.1f}% {a_spy_icon} | vs DAX: {bm['alpha_dax']:+.1f}% {a_dax_icon}\n"
            )

        if IS_SUNDAY:
            weekly = weekly_aggregate(con)
            msg = (
                f"📊 <b>Wochen-Report {today}</b>\n\n"
                "Signal-Pipeline (7d):\n"
                f"  Ø Conviction: {weekly['avg_conviction_7d']:.0%}\n"
                f"  Signale gekauft: {weekly['total_signals_bought']}\n\n"
                "Portfolio:\n"
                f"  Win Rate (7d): {pm['win_rate_7d']:.0%} {wr_ok}\n"
                f"  Profit Factor: {pm['profit_factor_7d']:.2f}\n"
                f"  Sortino: {pm['sortino_30d']:.2f} | Calmar: {pm['calmar_30d']:.2f}\n"
                f"  Max DD: {pm['max_drawdown_30d']:.1f}% | Ø R: {pm['avg_r_multiple']:.2f}R\n"
                f"  Exposure: LONG {pm['exposure_long_pct']:.0f}% SHORT {pm['exposure_short_pct']:.0f}%\n"
                f"  SL/TP/Tech: {pm['exit_sl_pct']:.0%}/{pm['exit_tp_pct']:.0%}/{pm['exit_tech_pct']:.0%}\n"
                f"{bm_line}"
                f"{committee_line}\n"
                f"{top_line}\n\n"
                "🔧 Strategy Optimizer läuft um 08:00..."
            )
        else:
            msg = (
                f"📊 <b>Tages-Report {today}</b>\n\n"
                "Signal-Pipeline:\n"
                f"  Neue Unternehmen: {sm['new_companies']}\n"
                f"  Bestätigungen: {sm['confirmed']} {cons_ok}\n"
                f"  Widersprüche: {sm['contradicted']}\n"
                f"  Ø Conviction: {sm['avg_conviction']:.0%}\n\n"
                "Portfolio:\n"
                f"  Offene Pos.: {pm['open_positions']}/8\n"
                f"  Win Rate (7d): {pm['win_rate_7d']:.0%} {wr_ok}\n"
                f"  Profit Factor: {pm['profit_factor_7d']:.2f}\n"
                f"  Sortino: {pm['sortino_30d']:.2f} | Calmar: {pm['calmar_30d']:.2f}\n"
                f"  Exposure: LONG {pm['exposure_long_pct']:.0f}% SHORT {pm['exposure_short_pct']:.0f}%\n"
                f"{bm_line}"
                f"{committee_line}\n"
                f"{top_line}"
            )

        send_telegram(msg)
        check_half_life_calibration(con)

        # Closed-Loop: Post-Trade Learning + Conviction Calibration
        update_segment_performance(con)
        calibrate_conviction(con)

        print("\n✅ Nightly Eval abgeschlossen", flush=True)
    finally:
        con.close()

if __name__ == "__main__":
    main()
