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
from config import (DB_PATH, SIGNALS_PATH, STRATEGY_CONFIG_PATH, OPTIMIZATION_REPORT_PATH,
                    SOURCES_CONFIG_PATH, db_connect, get_exit_config, EXIT_PROFILES)
from exit_rules import replay_exit_path
from trade_paths import attach_paths


TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_HOME_CHANNEL = os.environ.get("TELEGRAM_HOME_CHANNEL") or os.environ.get("TELEGRAM_CHAT_ID", "")

# 18.09.2026 von 10 auf 30 angehoben, und das Analysefenster von 60 auf 180
# Tage erweitert. Grund: der Grid-Pfad optimierte auf den letzten 60 Tagen =
# 17 Trades, waehrend der Walk-Forward-Pfad alle 88 benutzte — zwei Pfade,
# zwei Datenbasen, widerspruechliche Empfehlungen. Auf 17 Trades gewann im
# Dry-Run das ENGSTE Profil, auf 86 Trades das weiteste. Das ist kein
# Erkenntnisgewinn, das ist Rauschen mit Echtgeldwirkung.
MIN_TRADES       = 30      # Mindestanzahl Trades für Optimierung
ANALYSIS_WINDOW_DAYS = 180 # Analysefenster (vorher 60)
MIN_PATH_COVERAGE = 0.70   # min. Anteil Trades mit echtem OHLC-Pfad
IMPROVEMENT_THRESHOLD = 0.10  # 10% Verbesserung nötig

# Parameter-Grid für Optimierung
#
# min_confidence wurde am 08.09.2026 ENTFERNT (6 Stufen → Grid um Faktor 6
# kleiner). Grund: der Key wird vom Live-Entry-Pfad gar nicht gelesen — die
# wirksame Tech-Score-Schwelle kommt aus signal_manager.drawdown_params().
# Der Optimizer hat ihn trotzdem durchgesucht und das Ergebnis zurueck in
# strategy_config.json geschrieben. Zusaetzlich war die Simulation dafuer ein
# falscher Proxy: backtest_params filterte gegen positions.confidence, das seit
# dem Short-Fix die RICHTUNGS-Conviction enthaelt, nicht den tech_score
# (siehe alter Kommentar #10 in backtest_params).
# Zwei Parameter wurden aus dem Grid ENTFERNT, beide aus demselben Grund: der
# Live-Pfad liest sie nicht.
#
#   atr_tp_multiplier — active_exit_check.py:349 und signal_manager setzen
#     `hit_tp = False` ("TP ist Backup/Ergebnisziel, Chandelier primaer"). In 88
#     geschlossenen Trades hat keiner je 4.5x ATR erreicht (max. MFE 3.94x).
#
#   atr_sl_multiplier — wird nur ANGEZEIGT (dashboard.py:1067, backtest_gate.py:23)
#     und in signal_manager.py:462 sogar aus der Exit-Matrix ueberschrieben. Der
#     reale Stop kommt aus get_exit_config() -> pos_mult["sl"]. Der Optimizer hat
#     diesen Wert monatelang optimiert und zurueckgeschrieben, ohne dass sich am
#     Handelsverhalten irgendetwas geaendert haette.
#
# Gesucht wird stattdessen ueber die beiden Parameter, die tatsaechlich steuern:
#   exit_profile            — skaliert den Stop ueber die Exit-Matrix (config.py)
#   time_stop_trading_days  — gelesen in active_exit_check.py:228 + signal_manager.py:820
PARAM_GRID = {
    "exit_profile":           list(EXIT_PROFILES),
    "time_stop_trading_days": [5, 7, 10, 15],
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
    # FIX 18.09.2026: exp_score war `max(0.0, min(expectancy/2.0, 1.0))` und
    # damit fuer JEDEN negativen Erwartungswert exakt 0. Der mit 35% hoechst-
    # gewichtete Term konnte "verliert wenig" nicht von "verliert viel"
    # unterscheiden. Zusammen mit dem geklemmten Sharpe blieb fuer verlierende
    # Konfigurationen nur `0.20*payoff + 0.20*pf` uebrig — reine Verhaeltnis-
    # zahlen ohne Niveau. Ergebnis: SL 1.0x ATR landete mit PF 0.77 und
    # -0.65%/Trade auf Platz 3 von 24, weil ein enger Stop den Durchschnitts-
    # verlust klein haelt und die Payoff-Ratio dadurch gut aussieht.
    # Jetzt monoton ueber den gesamten Bereich [-2%, +2%] bzw. [-1, +3].
    exp_score    = max(0.0, min((expectancy + 2.0) / 4.0, 1.0))
    payoff_score = 1.0 if payoff_ratio == float('inf') \
                   else max(0.0, min(payoff_ratio / 4.0, 1.0))  # 4:1 = voll (Ziel 3-5:1)
    composite = (
        exp_score    * 0.35 +
        payoff_score * 0.20 +
        pf_score     * 0.20 +
        (min(max(sharpe, -1), 3) + 1) / 4 * 0.15 +
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

def backtest_params(trades, profile, time_stop_bars, min_conf=None):
    """Pfadgenaue Simulation: wie haetten die Trades mit anderen Exit-Parametern
    ausgesehen?

    FIX 18.09.2026 (a) — vorher wurde nur der realisierte Exit-PREIS gegen den
    hypothetischen SL/TP gehalten. Ob der Stop UNTERWEGS getroffen worden waere,
    sah die Funktion nicht: ein Gewinner, der zwischenzeitlich tief im Minus lag,
    behielt unter einem engen Stop seinen vollen Gewinn. Enge Stops wirkten
    dadurch kostenlos. Gegenrechnung auf 86 realen Trades:

        SL-Mult |  alte Logik  |  pfadgenau
          1.0   |  +0.64% (1.) |  PF 0.77, -0.65%/Trade (schlechteste)
          2.0   |  -0.27%      |  PF 1.02

    FIX 18.09.2026 (b) — `profile` statt `sl_mult`: der Stop wird ueber
    EXIT_PROFILES auf die ASSET-TYP-spezifische Matrix skaliert, weil genau das
    der Live-Pfad tut (get_exit_config -> pos_mult["sl"]). Ein flacher
    Multiplikator fuer alle Asset-Typen misst ein System, das so nicht laeuft:
    er verschob die IST-Basis von +0.006 auf -0.038 meanR.

    Trades ohne Kurspfad werden UEBERSPRUNGEN, nicht mit ihrem Original-PnL
    eingesetzt. Die Coverage-Pruefung liegt beim Aufrufer (main()).
    """
    scale = EXIT_PROFILES.get(profile, EXIT_PROFILES["current"])["sl_scale"]
    cfg = load_config()
    donchian_primary = (bool(cfg.get("donchian_exit_enabled"))
                        and cfg.get("donchian_exit_mode") == "primary")
    partial_pct = (cfg.get("partial_tp_pct", 0.5)
                   if cfg.get("partial_tp_enabled", True) else 0.0)
    simulated = []

    for trade in trades:
        if min_conf is not None and (trade.get("confidence") or 0) < min_conf:
            continue

        bars = trade.get("_bars")
        idx  = trade.get("_entry_idx")
        atr  = trade.get("_atr")
        entry = trade.get("entry_price")
        if not bars or idx is None or not atr or not entry:
            continue  # ohne Pfad keine ehrliche Aussage — siehe Docstring

        exit_cfg = get_exit_config(
            asset_type=trade.get("asset_type") or "STANDARD",
            regime="sideways",
        )
        sl_mult = round(exit_cfg["sl"] * scale, 2)
        res = replay_exit_path(
            bars, idx, entry, trade.get("direction", "LONG"), atr,
            sl_mult=sl_mult,
            partial_atr=exit_cfg["partial_atr"],
            partial_pct=partial_pct,
            profit_lock_atr=exit_cfg["profit_lock_atr"],
            chandelier_mult=exit_cfg["chandelier_mult"],
            donchian_primary=donchian_primary,
            donchian_period=cfg.get("donchian_exit_period", 10),
            time_stop_bars=time_stop_bars,
            tp_mult=None,   # Live setzt hit_tp=False — das TP feuert nie
        )
        if res["r_multiple"] is None:
            continue
        # calculate_metrics rechnet in Prozent; R in %-Risiko zurueckrechnen
        simulated.append({"pnl_pct": res["r_multiple"] * (sl_mult * atr / entry * 100)})

    return simulated


def run_grid_search(trades, current_config):
    """Testet alle Parameterkombinationen pfadgenau.

    Gibt zusaetzlich die Metriken der Bestkombination zurueck — main() braucht
    sie fuer die Profitabilitaets-Sperre vor dem Zurueckschreiben.
    """
    best_score  = -1
    best_params = None
    best_metrics = None
    results     = []

    total_combos = (len(PARAM_GRID["exit_profile"]) *
                    len(PARAM_GRID["time_stop_trading_days"]))
    print(f"  Grid Search: {total_combos} Kombinationen (pfadgenau)...", flush=True)

    # Sprossen-Begrenzung (18.09.2026): pro Lauf hoechstens EINE Stufe auf der
    # Profil-Leiter. Ohne das springt der Optimizer sofort auf die beste Zelle
    # eines 20-Zellen-Grids ueber ~86 Trades — klassische Ueberanpassung. Sagen
    # die Daten dauerhaft "weiter", kommt er in mehreren Woechen trotzdem dort
    # an, sammelt zwischendurch aber Live-Evidenz. Nach unten gilt dieselbe
    # Grenze, damit ein einzelner schlechter Monat die Stops nicht zusammenzieht.
    ladder = sorted(EXIT_PROFILES, key=lambda k: EXIT_PROFILES[k]["sl_scale"])
    cur_prof = (current_config or {}).get("exit_profile", "current")
    ci = ladder.index(cur_prof) if cur_prof in ladder else ladder.index("current")
    allowed = set(ladder[max(0, ci - 1): ci + 2])
    skipped = [p for p in ladder if p not in allowed]
    if skipped:
        print(f"    Sprossen-Limit: nur {sorted(allowed)} erlaubt "
              f"(aktuell '{cur_prof}'), uebersprungen: {skipped}", flush=True)

    for prof, ts in itertools.product(
        PARAM_GRID["exit_profile"],
        PARAM_GRID["time_stop_trading_days"]
    ):
        if prof not in allowed:
            continue
        sim_trades = backtest_params(trades, prof, ts)
        if len(sim_trades) < 3:
            continue

        metrics = calculate_metrics(sim_trades)
        if not metrics:
            continue

        results.append({
            "profile": prof, "time_stop": ts,
            "sl_scale":  EXIT_PROFILES[prof]["sl_scale"],
            "composite": metrics["composite"],
            "win_rate":  metrics["win_rate"],
            "p":        metrics["profit_factor"],
            "expectancy": metrics["expectancy"],
            "sharpe":    metrics["sharpe"],
            "trades":    len(sim_trades),
        })

        if metrics["composite"] > best_score:
            best_score   = metrics["composite"]
            best_metrics = metrics
            best_params  = {"exit_profile": prof,
                            "time_stop_trading_days": ts,
                            "composite": best_score}

    results.sort(key=lambda x: x["composite"], reverse=True)
    return best_params, results[:5], best_metrics


def main(dry_run=False):
    print("🔬 Strategy Optimizer gestartet"
          + ("  [DRY-RUN — schreibt nichts]" if dry_run else ""), flush=True)
    con = db_connect()
    # Abgeschlossene Trades laden (letzte 60 Tage)
    cutoff = (datetime.now() - timedelta(days=ANALYSIS_WINDOW_DAYS)).strftime("%Y-%m-%d")
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

    # Kurspfade beschaffen — ohne sie ist keine ehrliche Bewertung moeglich.
    print("  Lade Kurspfade (Cache first)...", flush=True)
    path_stats = attach_paths(trades)
    if path_stats["coverage"] < MIN_PATH_COVERAGE:
        msg = (
            "📊 <b>Strategy Optimizer</b>\n"
            f"Abbruch: nur {path_stats['with_path']}/{path_stats['total']} Trades "
            f"({path_stats['coverage']:.0%}) haben einen Kurspfad, "
            f"noetig sind {MIN_PATH_COVERAGE:.0%}.\n"
            "Ohne Intraday-High/Low waere jede Parameterempfehlung zugunsten "
            "zu enger Stops verzerrt — es wird nichts geaendert."
        )
        print(msg, flush=True)
        send_telegram(msg)
        return
    trades = [t for t in trades if t.get("_bars")]

    # Aktuelle Performance — ebenfalls pfadgenau, sonst vergleicht der
    # Improvement-Quotient zwei verschiedene Messverfahren miteinander.
    print("  Berechne aktuelle Performance (pfadgenau)...", flush=True)
    current_metrics = calculate_metrics(
        backtest_params(trades,
                        cfg.get("exit_profile", "current"),
                        cfg.get("time_stop_trading_days", 7))
    )
    print(f"  Aktuell: Composite={current_metrics['composite']:.4f} "
          f"WR={current_metrics['win_rate']}% "
          f"PF={current_metrics['profit_factor']} "
          f"Payoff={current_metrics.get('payoff_ratio')} "
          f"Exp={current_metrics.get('expectancy')}%/Trade", flush=True)

    # Grid Search
    print("  Starte Grid Search...", flush=True)
    best_params, top5, best_metrics = run_grid_search(trades, cfg)

    if not best_params:
        msg = "📊 <b>Strategy Optimizer</b>\nKeine besseren Parameter gefunden."
        send_telegram(msg)
        return

    improvement = (best_params["composite"] - current_metrics["composite"]) / \
                   max(current_metrics["composite"], 0.001)

    print(f"  Beste Parameter: Profil={best_params['exit_profile']} "
          f"(SL x{EXIT_PROFILES[best_params['exit_profile']]['sl_scale']}) "
          f"TimeStop={best_params['time_stop_trading_days']}d", flush=True)
    print(f"  Verbesserung: {improvement*100:+.1f}%", flush=True)

    # Report speichern
    report = {
        "timestamp":       datetime.now().isoformat(),
        "trades_analyzed": len(trades),
        "method":          "path_replay_v2",   # 18.09.2026, siehe backtest_params
        "path_coverage":   round(path_stats["coverage"], 3),
        "current_params": {
            "exit_profile":           cfg.get("exit_profile", "current"),
            "time_stop_trading_days": cfg.get("time_stop_trading_days", 7),
        },
        "best_metrics":    best_metrics,
        "current_metrics":  current_metrics,
        "best_params":      best_params,
        "improvement_pct":  round(improvement * 100, 2),
        "top5_combinations": top5,
        "updated":          improvement >= IMPROVEMENT_THRESHOLD,
    }

    with open(OPTIMIZATION_REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # Profitabilitaets-Sperre (18.09.2026): Eine Konfiguration, die im Replay
    # Geld verliert, darf NIE automatisch scharfgeschaltet werden — egal wie gut
    # ihr Composite relativ zur aktuellen aussieht. Vorher war das moeglich:
    # solange alle Kandidaten verloren, entschied nur noch das Verhaeltnis aus
    # Payoff-Ratio und Profit Factor, und "verliert etwas weniger" konnte
    # 10% "Verbesserung" ergeben und sich selbst in die Live-Config schreiben.
    profitable = (best_metrics is not None
                  and best_metrics["profit_factor"] >= 1.0
                  and best_metrics["expectancy"] > 0)
    if improvement >= IMPROVEMENT_THRESHOLD and not profitable:
        print(f"  ⛔ Uebernahme gesperrt: beste Kombination verliert weiterhin "
              f"(PF {best_metrics['profit_factor']:.2f}, "
              f"Exp {best_metrics['expectancy']:+.3f}%/Trade)", flush=True)
        report["updated"] = False
        report["blocked_reason"] = "best_config_not_profitable"
        with open(OPTIMIZATION_REPORT_PATH, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        send_telegram(
            "⛔ <b>Strategy Optimizer: Uebernahme gesperrt</b>" + "\n" + "\n"
            + f"Beste Kombination: Profil {best_params['exit_profile']}, "
              f"TimeStop {best_params['time_stop_trading_days']}d" + "\n"
            + f"Composite {improvement*100:+.1f}% besser — aber weiterhin "
              f"nicht profitabel (PF {best_metrics['profit_factor']:.2f}, "
              f"Exp {best_metrics['expectancy']:+.3f}%/Trade)." + "\n" + "\n"
            + "<i>Parameter bleiben unveraendert. Ein besseres Verhaeltnis "
              "zwischen Verlusten ist kein Grund, die Strategie umzustellen — "
              "das Problem liegt dann bei den Entries, nicht bei den Exits.</i>")
        print("\n✅ Optimizer abgeschlossen (ohne Aenderung).", flush=True)
        return

    if dry_run:
        print(f"  [DRY-RUN] Wuerde {'UEBERNEHMEN' if improvement >= IMPROVEMENT_THRESHOLD else 'NICHTS aendern'}: "
              f"Profil={best_params['exit_profile']} "
              f"TimeStop={best_params['time_stop_trading_days']}d "
              f"(Verbesserung {improvement*100:+.1f}%)", flush=True)
        return

    # Automatisch updaten wenn > 10% besser UND profitabel
    if improvement >= IMPROVEMENT_THRESHOLD:
        cfg["exit_profile"]           = best_params["exit_profile"]
        cfg["time_stop_trading_days"] = best_params["time_stop_trading_days"]

        with open(STRATEGY_CONFIG_PATH, "w") as f:
            json.dump(cfg, f, indent=2)

        msg = (
            "🔧 <b>Strategie automatisch verbessert!</b>\n\n"
            f"📈 Verbesserung: <b>{improvement*100:+.1f}%</b>\n\n"
            "<b>Neue Parameter:</b>\n"
            f"• Exit-Profil:  {best_params['exit_profile']} "
            f"(vorher: {report['current_params']['exit_profile']})\n"
            f"• Time-Stop:    {best_params['time_stop_trading_days']}d "
            f"(vorher: {report['current_params']['time_stop_trading_days']}d)\n\n"
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
            f"• Profil: {best_params['exit_profile']}\n"
            f"• Time-Stop: {best_params['time_stop_trading_days']}d"
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

    # Der frueher hier stehende min_confidence-Block wurde am 08.09.2026 entfernt:
    # der Key wird vom Entry-Pfad nicht gelesen (Deprecation siehe
    # signal_manager.DEFAULT_CONFIG), die Anpassung war wirkungslos und die
    # daraus erzeugten Telegram-Zeilen ("Min Konfidenz erhoeht") irrefuehrend.
    # Die Risikosteuerung nach schwacher Performance laeuft ueber die
    # Drawdown-Matrix (Size/Confidence/Positionslimit) in signal_manager.

    # SL anpassen bei zu vielen SL-Hits (unverändert – Risikoschutz)
    # 18.09.2026: wirkt jetzt ueber das Exit-Profil. Vorher wurde
    # cfg["atr_sl_multiplier"] erhoeht — ein Wert, den der Live-Pfad nicht liest
    # (nur Anzeige; signal_manager:462 ueberschreibt ihn aus der Exit-Matrix).
    # Die Regel meldete also seit jeher "SL erweitert", ohne dass sich am
    # tatsaechlichen Stop irgendetwas aenderte.
    if avg_sl and avg_sl > 0.60:
        ladder = sorted(EXIT_PROFILES, key=lambda k: EXIT_PROFILES[k]["sl_scale"])
        cur = cfg.get("exit_profile", "current")
        i = ladder.index(cur) if cur in ladder else ladder.index("current")
        if i + 1 < len(ladder):
            cfg["exit_profile"] = ladder[i + 1]
            changes.append(
                f"🛑 Exit-Profil: {cur}→{ladder[i + 1]} "
                f"(x{EXIT_PROFILES[ladder[i + 1]]['sl_scale']}, SL-Hits:{avg_sl:.0%})")
        else:
            changes.append(f"ℹ️ SL-Hits {avg_sl:.0%}, aber Profil '{cur}' "
                           f"ist bereits das weiteste — keine Aenderung.")

    # TP NICHT reflexartig kürzen, nur weil er selten getroffen wird.
    # Bei einem Trendfolge-/Asymmetrie-Profil kommen die Gewinne aus dem
    # Trailing (Winner laufen lassen), nicht aus einem fixen TP – eine niedrige
    # TP-Hit-Quote ist dann ERWARTET und gesund. TP nur verengen, wenn der
    # Profit Factor gleichzeitig schwach ist (die weiten Ziele zahlen sich
    # also nicht aus).
    # 18.09.2026 DEAKTIVIERT: Diese Regel hat den TP jede Woche weiter verengt,
    # ohne dass es etwas bewirken konnte. Der Live-Exit-Pfad setzt `hit_tp = False`
    # (active_exit_check.py, signal_manager) — das TP feuert NIE. Damit ist
    # avg_tp strukturell ~0 und die Bedingung dauerhaft wahr, sobald PF < 1.2.
    # Ergebnis waere eine Endlos-Ratsche auf einem Parameter ohne Wirkung.
    # Wer das TP wieder scharf stellen will, muss zuerst hit_tp aktivieren.
    if avg_tp and avg_tp < 0.20 and pf < 1.2:
        changes.append(f"ℹ️ TP unveraendert ({cfg.get('atr_tp_multiplier', 3.0)}x ATR): "
                       f"TP-Hits {avg_tp:.0%} sind erwartet, da der Live-Pfad "
                       f"hit_tp=False setzt — kein Steuerungsparameter.")

    return cfg, changes


# Original main() um eval_metrics erweitern
def clamp_profile_step(current_profile, proposed_profile):
    """Begrenzt einen Profilwechsel auf EINE Sprosse der Leiter.

    Choke-Point fuer alle Schreibpfade (Grid Search UND Walk-Forward). Der
    WF-Pfad umging die Begrenzung in run_grid_search sonst komplett und konnte
    von "current" direkt auf das aggressivste Profil springen — auf Basis von
    ~86 Trades waere das Ueberanpassung mit Echtgeldwirkung.
    """
    ladder = sorted(EXIT_PROFILES, key=lambda k: EXIT_PROFILES[k]["sl_scale"])
    if proposed_profile not in ladder:
        return current_profile, "unbekanntes Profil"
    ci = ladder.index(current_profile) if current_profile in ladder else ladder.index("current")
    pi = ladder.index(proposed_profile)
    if abs(pi - ci) <= 1:
        return proposed_profile, None
    step = ladder[ci + (1 if pi > ci else -1)]
    return step, (f"Sprung {current_profile}->{proposed_profile} auf eine Sprosse "
                  f"begrenzt ({step})")


_original_main = main

def main(dry_run=False):
    print("🔧 Strategy Optimizer v2 (mit eval_metrics + Source Weights)"
          + ("  [DRY-RUN — schreibt nichts]" if dry_run else ""), flush=True)

    def _save(cfg_obj):
        """Einziger Schreibpfad fuer strategy_config.json in diesem Lauf."""
        if dry_run:
            print("  [DRY-RUN] strategy_config.json NICHT geschrieben", flush=True)
            return
        with open(STRATEGY_CONFIG_PATH, "w") as f:
            json.dump(cfg_obj, f, indent=2)

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
    _save(cfg)

    if trade_count >= 30:
        print(f"\n🔬 Walk-Forward Optimierung ({trade_count} Trades)...", flush=True)
        try:
            from backtester import walk_forward_optimize
            trades = [dict(t) for t in con.execute(
                "SELECT * FROM positions WHERE status='closed' ORDER BY entry_date ASC"
            ).fetchall()]
            new_params = walk_forward_optimize(trades, n_folds=4)
            if new_params:
                # Weder atr_sl_multiplier noch atr_tp_multiplier werden
                # uebernommen — beides Parameter ohne Live-Wirkung, siehe
                # PARAM_GRID-Kommentar oben. Wirksam ist allein das Exit-Profil.
                if "exit_profile" in new_params:
                    stepped, note = clamp_profile_step(
                        cfg.get("exit_profile", "current"), new_params["exit_profile"])
                    if note:
                        print(f"  ⚠ {note}", flush=True)
                    cfg["exit_profile"] = stepped
                if "time_stop_trading_days" in new_params:
                    cfg["time_stop_trading_days"] = new_params["time_stop_trading_days"]
                # #4: WF-Parameter wurden vorher NUR im Speicher gesetzt und nie
                # geschrieben – Telegram meldete "übernommen", auf Platte No-Op.
                _save(cfg)
                print(f"  ✅ WF-Parameter übernommen: "
                      f"Profil={new_params.get('exit_profile', '-')} "
                      f"TimeStop={new_params.get('time_stop_trading_days', '-')}d")
            else:
                print("  ⚠ WF nicht robust – Grid Search Fallback")
                _original_main(dry_run=dry_run)
        except Exception as e:
            print(f"  ⚠ Walk-Forward Fehler: {e} – Grid Search Fallback")
            _original_main(dry_run=dry_run)
    elif trade_count >= 10:
        print(f"\n🔬 Grid Search ({trade_count} Trades, noch kein WF)...", flush=True)
        _original_main(dry_run=dry_run)
    else:
        print(f"\n⏳ Optimierung übersprungen ({trade_count}/10 Trades)", flush=True)
        _save(cfg)

    # 4. Telegram Wochenbericht
    if all_changes:
        changes_text = "\n".join(all_changes)
        msg = (
            "🔧 <b>Strategy Optimizer - Wochenbericht</b>\n\n"
            f"Anpassungen diese Woche:\n{changes_text}\n\n"
            f"Exit-Profil: {cfg.get('exit_profile','current')} | "
            f"TP: {cfg.get('atr_tp_multiplier',3.0)}x ATR"
        )
    else:
        msg = (
            "🔧 <b>Strategy Optimizer</b>\n\n"
            "Keine Anpassungen notwendig.\n"
            f"Exit-Profil: {cfg.get('exit_profile','current')} | "
            f"TP: {cfg.get('atr_tp_multiplier',3.0)}x"
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
    # 18.09.2026: laeuft ueber _save, damit --dry-run wirklich nichts schreibt.
    try:
        _save(cfg)
    except Exception as e:
        print(f"  ⚠ Konnte strategy_config.json nicht schreiben: {e}", flush=True)

    con.close()
    print("\n✅ Strategy Optimizer v2 abgeschlossen", flush=True)


if __name__ == "__main__":
    import sys as _sys
    main(dry_run="--dry-run" in _sys.argv)
