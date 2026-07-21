"""
Strategy Optimizer - Stufe 2 Selbstverbesserung
Läuft sonntags, analysiert Trades, optimiert Parameter automatisch
wenn Verbesserung > 10%
"""
import sqlite3
import json
import os
import sys
sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")
import env_loader  # noqa: F401  (side-effect: laedt .env)
import math
import yfinance as yf
import pandas_ta as ta
from datetime import datetime, timedelta
import requests
import itertools
from config import DB_PATH, SIGNALS_PATH, STRATEGY_CONFIG_PATH, OPTIMIZATION_REPORT_PATH, SOURCES_CONFIG_PATH, db_connect


TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_HOME_CHANNEL = os.environ.get("TELEGRAM_HOME_CHANNEL") or os.environ.get("TELEGRAM_CHAT_ID", "")

MIN_TRADES       = 10      # Mindestanzahl Trades für Optimierung
IMPROVEMENT_THRESHOLD = 0.10  # 10% Verbesserung nötig

# Parameter-Grid für Optimierung
PARAM_GRID = {
    "atr_sl_multiplier": [1.0, 1.25, 1.5, 1.75, 2.0, 2.5],
    "atr_tp_multiplier": [2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0],
    "min_confidence":    [0.60, 0.65, 0.70, 0.75, 0.80, 0.85],
}

def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_HOME_CHANNEL:
        print(message)
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_HOME_CHANNEL, "text": message, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        print(f"Telegram Fehler: {e}")

def load_config():
    if os.path.exists(STRATEGY_CONFIG_PATH):
        with open(STRATEGY_CONFIG_PATH) as f:
            return json.load(f)
    return {
        "starting_capital": 10000.0,
        "max_position_pct": 0.30,
        "max_positions":    4,
        "atr_sl_multiplier": 1.5,
        "atr_tp_multiplier": 3.0,
        "min_confidence":    0.65,
        "consecutive_wins":  0,
        "consecutive_losses":0,
        "total_trades":      0,
        "winning_trades":    0,
    }

def calculate_metrics(trades):
    """Berechnet Performance-Metriken aus einer Liste von Trades."""
    if not trades:
        return None

    pnls = [t["pnl_pct"] or 0 for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    win_rate = len(wins) / len(pnls) if pnls else 0
    avg_win  = sum(wins) / len(wins) if wins else 0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.001
    profit_factor = (sum(wins)) / abs(sum(losses)) if losses else float('inf')

    # Sharpe Ratio (vereinfacht, Daily Returns)
    if len(pnls) > 1:
        mean_pnl = sum(pnls) / len(pnls)
        variance = sum((p - mean_pnl)**2 for p in pnls) / len(pnls)
        std_pnl  = math.sqrt(variance) if variance > 0 else 0.001
        sharpe   = (mean_pnl / std_pnl) * math.sqrt(252) if std_pnl > 0 else 0
    else:
        sharpe = 0

    # Max Drawdown
    equity = 10000.0
    peak   = equity
    max_dd = 0
    for p in pnls:
        equity *= (1 + p/100)
        peak    = max(peak, equity)
        dd      = (peak - equity) / peak * 100
        max_dd  = max(max_dd, dd)

    # Asymmetrie-Kennzahlen (Turtle-Denkweise): nicht die Trefferquote zählt,
    # sondern Payoff-Ratio × Trefferquote = Erwartungswert pro Trade. Das
    # Turtle-System hatte ~35-40% Win-Rate und lebte allein davon, dass die
    # Gewinner 3-5× so groß waren wie die Verlierer.
    payoff_ratio = (avg_win / avg_loss) if avg_loss > 0 else float('inf')
    expectancy   = win_rate * avg_win - (1 - win_rate) * avg_loss  # % pro Trade

    # Composite Score (höher = besser) – bewusst OHNE eigenständigen Win-Rate-
    # Term. Ein Trendfolge-Profil darf nicht dafür bestraft werden, oft falsch
    # zu liegen, solange der Erwartungswert stimmt. Gewichtung:
    #   Expectancy 35% | Payoff-Ratio 20% | Profit Factor 20% | Sharpe 15% | -MaxDD 10%
    pf_score     = min(profit_factor, 5) / 5              # 0-1
    dd_score     = max(0, 1 - max_dd / 50)                # 50% DD = 0 Score
    exp_score    = max(0.0, min(expectancy / 2.0, 1.0))   # 2% Erwartung/Trade = voll
    payoff_score = 1.0 if payoff_ratio == float('inf') \
                   else max(0.0, min(payoff_ratio / 4.0, 1.0))  # 4:1 = voll (Ziel 3-5:1)
    composite = (
        exp_score    * 0.35 +
        payoff_score * 0.20 +
        pf_score     * 0.20 +
        min(max(sharpe, 0), 3) / 3 * 0.15 +
        dd_score     * 0.10
    )

    return {
        "total_trades":   len(trades),
        "win_rate":       round(win_rate * 100, 1),
        "avg_win":        round(avg_win, 2),
        "avg_loss":       round(avg_loss, 2),
        "payoff_ratio":   round(payoff_ratio, 2) if payoff_ratio != float('inf') else None,
        "expectancy":     round(expectancy, 3),
        "profit_factor":  round(profit_factor, 2),
        "sharpe":         round(sharpe, 2),
        "max_drawdown":   round(max_dd, 2),
        "composite":      round(composite, 4),
        "total_pnl":      round(sum(pnls), 2),
    }

def backtest_params(trades, sl_mult, tp_mult, min_conf):
    """
    Simuliert wie Trades mit anderen Parametern ausgesehen hätten.
    Nutzt ATR bei Entry und simuliert SL/TP Hits.

    #10 – Bekannte Grenzen dieser Vereinfachung (bewusst, keine Fundamentaldaten
    für einen echten Pfad-Backtest vorhanden):
    • positions.confidence enthält seit dem Short-Fix die RICHTUNGS-Conviction
      (bull bzw. bear), nicht den Tech-Confidence-Wert. min_conf filtert hier
      also über Conviction, während der LIVE-Entry-Filter min_confidence gegen
      tech_score prüft. Die Optimierung von min_confidence ist damit nur ein
      grober Proxy – primär sind SL/TP-Multiplikatoren aussagekräftig.
    • Es liegt nur der Exit-Preis vor, kein Intraday-Pfad. Ein WEITERER TP kann
      daher nie „getroffen" werden, wenn der Original-Exit früher lag → leichter
      Bias Richtung enger Parameter. Deshalb greift die Auto-Übernahme erst ab
      IMPROVEMENT_THRESHOLD (10%) und der Walk-Forward-Pfad ab 30 Trades.
    """
    simulated = []

    for trade in trades:
        # Konfidenz-Filter
        conf = trade.get("confidence") or 0
        if conf < min_conf:
            continue  # Trade wäre nicht eingegangen worden

        atr   = trade.get("atr_at_entry")
        entry = trade.get("entry_price")
        if not atr or not entry or atr == 0:
            # Kein ATR vorhanden – originalen Trade übernehmen
            simulated.append({"pnl_pct": trade.get("pnl_pct") or 0})
            continue

        direction = trade.get("direction", "LONG")

        if direction == "LONG":
            new_sl = entry - (sl_mult * atr)
            new_tp = entry + (tp_mult * atr)
        else:
            new_sl = entry + (sl_mult * atr)
            new_tp = entry - (tp_mult * atr)

        # Prüfe ob original SL oder TP zuerst getroffen wurde
        original_exit   = trade.get("exit_price") or entry
        original_reason = trade.get("exit_reason", "")

        sl_pct = abs(entry - new_sl) / entry * 100
        tp_pct = abs(new_tp - entry) / entry * 100

        if direction == "LONG":
            actual_pnl = (original_exit - entry) / entry * 100
            hit_sl = original_exit <= new_sl
            hit_tp = original_exit >= new_tp
        else:
            actual_pnl = (entry - original_exit) / entry * 100
            hit_sl = original_exit >= new_sl
            hit_tp = original_exit <= new_tp

        if hit_tp:
            simulated.append({"pnl_pct": tp_pct})
        elif hit_sl:
            simulated.append({"pnl_pct": -sl_pct})
        else:
            simulated.append({"pnl_pct": actual_pnl})

    return simulated

def run_grid_search(trades, current_config):
    """Testet alle Parameterkombinationen."""
    best_score  = -1
    best_params = None
    results     = []

    total_combos = (
        len(PARAM_GRID["atr_sl_multiplier"]) *
        len(PARAM_GRID["atr_tp_multiplier"]) *
        len(PARAM_GRID["min_confidence"])
    )
    print(f"  Grid Search: {total_combos} Kombinationen...", flush=True)

    for sl, tp, conf in itertools.product(
        PARAM_GRID["atr_sl_multiplier"],
        PARAM_GRID["atr_tp_multiplier"],
        PARAM_GRID["min_confidence"]
    ):
        # TP muss > SL sein (mind. 1.5x Ratio)
        if tp / sl < 1.5:
            continue

        sim_trades = backtest_params(trades, sl, tp, conf)
        if len(sim_trades) < 3:
            continue

        metrics = calculate_metrics(sim_trades)
        if not metrics:
            continue

        results.append({
            "sl": sl, "tp": tp, "conf": conf,
            "composite": metrics["composite"],
            "win_rate":  metrics["win_rate"],
            "p":        metrics["profit_factor"],
            "sharpe":    metrics["sharpe"],
            "trades":    len(sim_trades),
        })

        if metrics["composite"] > best_score:
            best_score  = metrics["composite"]
            best_params = {"atr_sl_multiplier": sl, "atr_tp_multiplier": tp,
                          "min_confidence": conf, "composite": best_score}

    # Top 5 sortiert
    results.sort(key=lambda x: x["composite"], reverse=True)
    return best_params, results[:5]

def main():
    print("🔬 Strategy Optimizer gestartet", flush=True)
    con = db_connect()
    # Abgeschlossene Trades laden (letzte 60 Tage)
    cutoff = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
    trades = con.execute("""
        SELECT * FROM positions
        WHERE status='closed'
        AND exit_date >= ?
        ORDER BY exit_date DESC
    """, (cutoff,)).fetchall()
    trades = [dict(t) for t in trades]
    con.close()

    print(f"  Abgeschlossene Trades: {len(trades)}", flush=True)

    if len(trades) < MIN_TRADES:
        msg = (
            "📊 <b>Strategy Optimizer</b>\n"
            f"Zu wenig Trades für Optimierung ({len(trades)}/{MIN_TRADES}).\n"
            "Weiter sammeln und nächste Woche erneut prüfen."
        )
        print(msg)
        send_telegram(msg)
        return

    cfg = load_config()

    # Aktuelle Performance
    print("  Berechne aktuelle Performance...", flush=True)
    current_metrics = calculate_metrics(trades)
    print(f"  Aktuell: Composite={current_metrics['composite']:.4f} "
          f"WR={current_metrics['win_rate']}% "
          f"PF={current_metrics['profit_factor']} "
          f"Payoff={current_metrics.get('payoff_ratio')} "
          f"Exp={current_metrics.get('expectancy')}%/Trade", flush=True)

    # Grid Search
    print("  Starte Grid Search...", flush=True)
    best_params, top5 = run_grid_search(trades, cfg)

    if not best_params:
        msg = "📊 <b>Strategy Optimizer</b>\nKeine besseren Parameter gefunden."
        send_telegram(msg)
        return

    improvement = (best_params["composite"] - current_metrics["composite"]) / \
                   max(current_metrics["composite"], 0.001)

    print(f"  Beste Parameter: SL={best_params['atr_sl_multiplier']}x "
          f"TP={best_params['atr_tp_multiplier']}x "
          f"Conf={best_params['min_confidence']:.0%}", flush=True)
    print(f"  Verbesserung: {improvement*100:+.1f}%", flush=True)

    # Report speichern
    report = {
        "timestamp":       datetime.now().isoformat(),
        "trades_analyzed": len(trades),
        "current_params": {
            "atr_sl_multiplier": cfg["atr_sl_multiplier"],
            "atr_tp_multiplier": cfg["atr_tp_multiplier"],
            "min_confidence":    cfg["min_confidence"],
        },
        "current_metrics":  current_metrics,
        "best_params":      best_params,
        "improvement_pct":  round(improvement * 100, 2),
        "top5_combinations": top5,
        "updated":          improvement >= IMPROVEMENT_THRESHOLD,
    }

    with open(OPTIMIZATION_REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # Automatisch updaten wenn > 10% besser
    if improvement >= IMPROVEMENT_THRESHOLD:
        cfg["atr_sl_multiplier"] = best_params["atr_sl_multiplier"]
        cfg["atr_tp_multiplier"] = best_params["atr_tp_multiplier"]
        cfg["min_confidence"]    = best_params["min_confidence"]

        with open(STRATEGY_CONFIG_PATH, "w") as f:
            json.dump(cfg, f, indent=2)

        msg = (
            "🔧 <b>Strategie automatisch verbessert!</b>\n\n"
            f"📈 Verbesserung: <b>{improvement*100:+.1f}%</b>\n\n"
            "<b>Neue Parameter:</b>\n"
            f"• Stop-Loss:    {best_params['atr_sl_multiplier']}x ATR "
            f"(vorher: {report['current_params']['atr_sl_multiplier']}x)\n"
            f"• Take-Profit:  {best_params['atr_tp_multiplier']}x ATR "
            f"(vorher: {report['current_params']['atr_tp_multiplier']}x)\n"
            f"• Min Konfidenz:{best_params['min_confidence']:.0%} "
            f"(vorher: {report['current_params']['min_confidence']:.0%})\n\n"
            "<b>Performance:</b>\n"
            f"• Win Rate:     {current_metrics['win_rate']}%\n"
            f"• Profit Factor:{current_metrics['profit_factor']}\n"
            f"• Sharpe Ratio: {current_metrics['sharpe']}\n"
            f"• Max Drawdown: {current_metrics['max_drawdown']}%\n\n"
            f"Trades analysiert: {len(trades)}"
        )
    else:
        msg = (
            "📊 <b>Wochenbericht Strategy Optimizer</b>\n\n"
            f"Verbesserung zu gering ({improvement*100:+.1f}% < 10%).\n"
            "Parameter bleiben unverändert.\n\n"
            "<b>Aktuelle Performance:</b>\n"
            f"• Win Rate:     {current_metrics['win_rate']}%\n"
            f"• Profit Factor:{current_metrics['profit_factor']}\n"
            f"• Sharpe Ratio: {current_metrics['sharpe']}\n"
            f"• Max Drawdown: {current_metrics['max_drawdown']}%\n"
            f"• Trades:       {len(trades)}\n\n"
            "<b>Beste gefundene Parameter (nicht übernommen):</b>\n"
            f"• SL: {best_params['atr_sl_multiplier']}x ATR\n"
            f"• TP: {best_params['atr_tp_multiplier']}x ATR\n"
            f"• Konfidenz: {best_params['min_confidence']:.0%}"
        )

    print(f"\n{msg}", flush=True)
    send_telegram(msg)
    print("\n✅ Optimizer abgeschlossen.", flush=True)

def adjust_source_weights(con):
    """Passt Source-Gewichte basierend auf quality_score an."""
    import json as _json
    SOURCES_PATH = SOURCES_CONFIG_PATH

    try:
        with open(SOURCES_PATH) as f:
            sources = _json.load(f)
    except Exception:
        print("  ⚠ sources.json nicht gefunden", flush=True)
        return []

    today = datetime.now().strftime("%Y-%m-%d")
    d30   = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    # Source Quality aus DB
    quality = {r[0]: {"score": r[1], "win_rate": r[2], "bought": r[3]}
               for r in con.execute("""
        SELECT channel, quality_score, win_rate_30d, bought_30d
        FROM source_quality
        WHERE date = (SELECT MAX(date) FROM source_quality)
    """).fetchall()}

    changes = []

    # YouTube Kanäle anpassen
    for feed in sources.get("rss_feeds", []):
        name = feed.get("name", "")
        q    = quality.get(name)
        if not q: continue
        old_w = feed.get("weight", 1.0)

        if q["score"] > 0.7:
            feed["weight"] = round(min(2.0, old_w * 1.10), 2)
            changes.append(f"📈 {name}: {old_w:.1f}→{feed['weight']:.1f} (Q:{q['score']:.2f})")
        elif q["score"] < 0.3 and q["bought"] >= 3:
            feed["weight"] = round(max(0.3, old_w * 0.90), 2)
            changes.append(f"📉 {name}: {old_w:.1f}→{feed['weight']:.1f} (Q:{q['score']:.2f})")

        # Blacklist bei sehr schlechter Win Rate
        if q["win_rate"] < 0.25 and q["bought"] >= 5:
            feed["enabled"] = False
            changes.append(f"🚫 {name} deaktiviert (WR:{q['win_rate']:.0%} bei {q['bought']} Trades)")

    with open(SOURCES_PATH, "w") as f:
        _json.dump(sources, f, indent=2, ensure_ascii=False)

    return changes

def adjust_from_eval_metrics(con, cfg):
    """Passt Parameter basierend auf eval_metrics an."""
    d7 = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    metrics = con.execute("""
        SELECT AVG(win_rate_7d), AVG(profit_factor_7d),
               AVG(exit_sl_pct), AVG(exit_tp_pct)
        FROM eval_metrics
        WHERE date >= ? AND metric_type='daily'
    """, (d7,)).fetchone()

    if not metrics or metrics[0] is None:
        print("  ⚠ Nicht genug eval_metrics Daten", flush=True)
        return cfg, []

    avg_wr, avg_pf, avg_sl, avg_tp = metrics
    changes = []
    pf = avg_pf if avg_pf is not None else 1.0

    # Min Confidence dynamisch — ASYMMETRIE-BEWUSST.
    # Eine niedrige Win-Rate allein ist KEIN Grund, strenger zu werden: ein
    # Trendfolge-Profil (WR ~35-40%) ist profitabel, solange die Payoff-Ratio
    # stimmt. Nur enger stellen, wenn zusätzlich der Profit Factor kippt
    # (echter Edge-Verlust, nicht nur „oft falsch, aber groß richtig").
    if avg_wr < 0.40 and pf < 1.1:
        old = cfg.get("min_confidence", 0.65)
        cfg["min_confidence"] = round(min(0.85, old + 0.05), 2)
        changes.append(f"📊 Min Konfidenz: {old:.0%}→{cfg['min_confidence']:.0%} "
                       f"(WR:{avg_wr:.0%} UND PF:{pf:.2f} < 1.1)")
    elif avg_wr > 0.65 and pf > 1.5:
        old = cfg.get("min_confidence", 0.65)
        cfg["min_confidence"] = round(max(0.55, old - 0.05), 2)
        changes.append(f"📊 Min Konfidenz: {old:.0%}→{cfg['min_confidence']:.0%} "
                       f"(WR:{avg_wr:.0%}, PF:{pf:.2f} – Edge robust)")

    # SL anpassen bei zu vielen SL-Hits (unverändert – Risikoschutz)
    if avg_sl and avg_sl > 0.60:
        old = cfg.get("atr_sl_multiplier", 1.5)
        cfg["atr_sl_multiplier"] = round(min(2.5, old + 0.25), 2)
        changes.append(f"🛑 SL: {old}x→{cfg['atr_sl_multiplier']}x ATR (SL-Hits:{avg_sl:.0%})")

    # TP NICHT reflexartig kürzen, nur weil er selten getroffen wird.
    # Bei einem Trendfolge-/Asymmetrie-Profil kommen die Gewinne aus dem
    # Trailing (Winner laufen lassen), nicht aus einem fixen TP – eine niedrige
    # TP-Hit-Quote ist dann ERWARTET und gesund. TP nur verengen, wenn der
    # Profit Factor gleichzeitig schwach ist (die weiten Ziele zahlen sich
    # also nicht aus).
    if avg_tp and avg_tp < 0.20 and pf < 1.2:
        old = cfg.get("atr_tp_multiplier", 3.0)
        cfg["atr_tp_multiplier"] = round(max(2.0, old - 0.25), 2)
        changes.append(f"🎯 TP: {old}x→{cfg['atr_tp_multiplier']}x ATR "
                       f"(TP-Hits:{avg_tp:.0%} UND PF:{pf:.2f} < 1.2)")

    return cfg, changes


# Original main() um eval_metrics erweitern
_original_main = main

def main():
    print("🔧 Strategy Optimizer v2 (mit eval_metrics + Source Weights)", flush=True)
    con = db_connect()
    cfg = load_config()
    all_changes = []

    # 1. Eval-Metrics basierte Anpassungen
    print("\n📊 Eval-Metrics Analyse...", flush=True)
    cfg, eval_changes = adjust_from_eval_metrics(con, cfg)
    all_changes.extend(eval_changes)
    for c in eval_changes:
        print(f"  {c}", flush=True)

    # 2. Source Weights anpassen
    print("\n📡 Source Weights anpassen...", flush=True)
    source_changes = adjust_source_weights(con)
    all_changes.extend(source_changes)
    for c in source_changes:
        print(f"  {c}", flush=True)

    # 3. Parameter-Optimierung (Walk-Forward ab 30 Trades, sonst Grid Search)
    trade_count = con.execute(
        "SELECT COUNT(*) FROM positions WHERE status='closed'"
    ).fetchone()[0]

    # #4: Eval-Metrics- und Source-Weight-Anpassungen SOFORT persistieren, bevor
    # _original_main() (Grid Search) die Config frisch von Platte liest. Sonst
    # gingen diese Änderungen verloren, weil _original_main cfg neu lädt.
    with open(STRATEGY_CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)

    if trade_count >= 30:
        print(f"\n🔬 Walk-Forward Optimierung ({trade_count} Trades)...", flush=True)
        try:
            from backtester import walk_forward_optimize
            trades = [dict(t) for t in con.execute(
                "SELECT * FROM positions WHERE status='closed' ORDER BY entry_date ASC"
            ).fetchall()]
            new_params = walk_forward_optimize(trades, n_folds=4)
            if new_params:
                cfg["atr_sl_multiplier"] = new_params["atr_sl_multiplier"]
                cfg["atr_tp_multiplier"] = new_params["atr_tp_multiplier"]
                cfg["min_confidence"] = new_params["min_confidence"]
                # #4: WF-Parameter wurden vorher NUR im Speicher gesetzt und nie
                # geschrieben – Telegram meldete "übernommen", auf Platte No-Op.
                with open(STRATEGY_CONFIG_PATH, "w") as f:
                    json.dump(cfg, f, indent=2)
                print(f"  ✅ WF-Parameter übernommen: SL={new_params['atr_sl_multiplier']}x "
                      f"TP={new_params['atr_tp_multiplier']}x Conf={new_params['min_confidence']:.0%}")
            else:
                print("  ⚠ WF nicht robust – Grid Search Fallback")
                _original_main()
        except Exception as e:
            print(f"  ⚠ Walk-Forward Fehler: {e} – Grid Search Fallback")
            _original_main()
    elif trade_count >= 10:
        print(f"\n🔬 Grid Search ({trade_count} Trades, noch kein WF)...", flush=True)
        _original_main()
    else:
        print(f"\n⏳ Optimierung übersprungen ({trade_count}/10 Trades)", flush=True)
        with open(STRATEGY_CONFIG_PATH, "w") as f:
            json.dump(cfg, f, indent=2)

    # 4. Telegram Wochenbericht
    if all_changes:
        changes_text = "\n".join(all_changes)
        msg = (
            "🔧 <b>Strategy Optimizer - Wochenbericht</b>\n\n"
            f"Anpassungen diese Woche:\n{changes_text}\n\n"
            f"SL: {cfg.get('atr_sl_multiplier',1.5)}x ATR | "
            f"TP: {cfg.get('atr_tp_multiplier',3.0)}x ATR | "
            f"Min Conf: {cfg.get('min_confidence',0.65):.0%}"
        )
    else:
        msg = (
            "🔧 <b>Strategy Optimizer</b>\n\n"
            "Keine Anpassungen notwendig.\n"
            f"SL: {cfg.get('atr_sl_multiplier',1.5)}x | "
            f"TP: {cfg.get('atr_tp_multiplier',3.0)}x | "
            f"Min Conf: {cfg.get('min_confidence',0.65):.0%}"
        )

    import requests as _req
    try:
        _req.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_HOME_CHANNEL,
                  "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception:
        pass

    # #4: Finaler Safety-Dump – stellt sicher, dass cfg (inkl. aller
    # in-memory-Anpassungen) in jedem Pfad auf Platte landet.
    try:
        with open(STRATEGY_CONFIG_PATH, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"  ⚠ Konnte strategy_config.json nicht schreiben: {e}", flush=True)

    con.close()
    print("\n✅ Strategy Optimizer v2 abgeschlossen", flush=True)


if __name__ == "__main__":
    main()
