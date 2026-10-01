"""
Weekly Review — Woechentliche Checks (Sonntag 08:00).
- Theme-Lifecycle-Review
- Position-30-Tage-Review
- Tax-Year-Summary konsolidieren
"""
import json
import os
import sqlite3
from datetime import date, datetime, timedelta
from thematic.lib import llm_client, prompt_loader

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data", "trading.db"
)


def _db_connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _theme_lifecycle_review(con):
    """Markiert Themen mit >14 Tagen without update als dormant."""
    cutoff = (date.today() - timedelta(days=14)).isoformat()
    con.execute("""
        UPDATE theme_definitions SET status = 'dormant'
        WHERE status = 'active' AND last_seen < ?
    """, (cutoff,))
    con.commit()
    print(f"[Weekly] Theme-Lifecycle done.", flush=True)


def _position_30day_review(con):
    """Review von Positionen die >=30 Tage offen sind."""
    cutoff = (date.today() - timedelta(days=30)).isoformat()

    positions = con.execute("""
        SELECT * FROM positions
        WHERE status = 'open' AND entry_date <= ?
    """, (cutoff,)).fetchall()

    if not positions:
        print("[Weekly] Keine 30d-Positionen.")
        return

    model = llm_client.get_model("thesis_monitor")

    for pos in positions:
        pos = dict(pos)     # N14: sqlite3.Row hat kein .get()
        thesis = pos.get("thesis_text") or "Keine These."

        # Thesis-Check-Historie
        checks = con.execute("""
            SELECT check_date, status, confidence, rationale FROM thesis_status_log
            WHERE position_id = ? ORDER BY check_date DESC LIMIT 10
        """, (pos["id"],)).fetchall()

        summary = "\n".join(
            f"- {c['check_date']}: {c['status']} (Conf={c['confidence']:.0%})"
            for c in checks
        )

        theme_row = con.execute(
            "SELECT * FROM theme_definitions WHERE id = ?",
            (pos.get("thesis_theme_id"),)
        ).fetchone()

        prompt = prompt_loader.load_prompt(
            "position_review_v1.md",
            ticker=pos["ticker"],
            company_name=pos.get("name", pos["ticker"]),
            entry_date=(pos.get("entry_date") or "")[:10],
            thesis_text=thesis,
            pnl_pct=f"{pos.get('pnl_pct') or 0:.1f}%",
            thesis_status=pos.get("thesis_current_status") or "intact",
            theme_momentum=dict(theme_row).get("momentum", "steady") if theme_row else "steady",
            thesis_check_summary=summary,
        )

        result = llm_client.call_llm(prompt, model, temperature=0.3, json_mode=True)
        data = llm_client.parse_json_response(result)

        action = data.get("action", "HOLD")
        rationale = data.get("rationale", "")

        print(f"  {pos['ticker']}: {action} — {rationale[:100]}", flush=True)

    con.commit()
    print(f"[Weekly] 30d-Review done: {len(positions)} Positionen.", flush=True)



def _get_price_after(ticker: str, exit_date: str, days: int) -> float | None:
    """Holt den Schlusskurs N Tage nach einem Datum."""
    try:
        import yfinance as yf
        from datetime import datetime, timedelta
        start = datetime.strptime(exit_date[:10], "%Y-%m-%d") + timedelta(days=days - 2)
        end   = datetime.strptime(exit_date[:10], "%Y-%m-%d") + timedelta(days=days + 5)
        df = yf.download(ticker, start=start.strftime("%Y-%m-%d"),
                         end=end.strftime("%Y-%m-%d"), progress=False, auto_adjust=True)
        if df.empty:
            return None
        return float(df["Close"].iloc[-1].iloc[0] if hasattr(df["Close"].iloc[-1], "iloc") else df["Close"].iloc[-1])
    except Exception:
        return None


def _llm_verdict(ticker, thesis, exit_reason, exit_price, entry_price,
                 pnl_at_exit, price_7d, price_14d, price_30d, con):
    """LLM bewertet ob Exit-Entscheidung rückblickend richtig war."""
    try:
        import os, requests, json
        key = os.environ.get("OPENROUTER_API_KEY")
        if not key:
            return "unknown", 0.5, "Kein API-Key"

        # Letzte Thesis-Einträge laden
        thesis_logs = con.execute("""
            SELECT status, confidence, rationale, check_date
            FROM thesis_status_log
            WHERE ticker = ?
            ORDER BY check_date DESC LIMIT 5
        """, (ticker,)).fetchall()
        thesis_history = ""
        for t in thesis_logs:
            thesis_history += f"  {t['check_date']}: {t['status']} (Conf={t['confidence']:.0%}) — {t['rationale'][:100]}\n"

        pnl_7d  = ((price_7d  - exit_price) / exit_price * 100) if price_7d  else None
        pnl_14d = ((price_14d - exit_price) / exit_price * 100) if price_14d else None
        pnl_30d = ((price_30d - exit_price) / exit_price * 100) if price_30d else None

        prompt = f"""Du bewertest rückblickend eine Trading-Exit-Entscheidung.

POSITION: {ticker}
URSPRÜNGLICHE THESE: {thesis or "Nicht dokumentiert"}
EXIT-GRUND: {exit_reason}
ENTRY: {entry_price:.2f} | EXIT: {exit_price:.2f} | PnL beim Exit: {pnl_at_exit:+.1f}%

KURSENTWICKLUNG NACH EXIT:
- 7 Tage danach:  {f"{price_7d:.2f} ({pnl_7d:+.1f}%)" if price_7d else "N/A"}
- 14 Tage danach: {f"{price_14d:.2f} ({pnl_14d:+.1f}%)" if price_14d else "N/A"}
- 30 Tage danach: {f"{price_30d:.2f} ({pnl_30d:+.1f}%)" if price_30d else "N/A"}

THESIS-MONITOR VERLAUF (letzte 5 Checks):
{thesis_history or "  Keine Einträge"}

Bewerte:
1. War der Exit zum richtigen Zeitpunkt? (too_early/correct/too_late)
2. Hat sich die These nach dem Exit erholt? (ja/nein)
3. Hätte ein engerer SL früher und besser getriggert? (ja/nein)
4. Hätte ein weiterer SL die Position durch die Schwächephase gerettet? (ja/nein)
5. Was ist die wichtigste Lektion aus diesem Trade?

Antworte NUR mit JSON:
{{
  "verdict": "too_early|correct|too_late",
  "confidence": 0.75,
  "thesis_recovered": true,
  "tighter_sl_better": false,
  "wider_sl_better": true,
  "rationale": "2-3 Sätze Begründung",
  "lesson": "1 Satz Lektion"
}}"""

        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": "anthropic/claude-sonnet-4",
                  "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": 300},
            timeout=30
        )
        msg_content = r.json()["choices"][0]["message"].get("content")
        if not msg_content:
            return "unknown", 0.5, "empty LLM response", False, False, False, ""
        text = msg_content.strip()
        text = text.strip("```json").strip("```").strip()
        data = json.loads(text)
        return (data.get("verdict", "unknown"),
                data.get("confidence", 0.5),
                data.get("rationale", ""),
                data.get("thesis_recovered", False),
                data.get("tighter_sl_better", False),
                data.get("wider_sl_better", False),
                data.get("lesson", ""))
    except Exception as e:
        return "unknown", 0.5, str(e), False, False, False, ""


def run_exit_quality_review(con):
    """
    Bewertet rückblickend Exit-Entscheidungen der letzten 14 Tage.
    Nur für Exits mit Grund THESIS_BROKEN oder TECH_BROKEN.
    """
    print("\n[Exit Quality Review] Starte...", flush=True)
    have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"exit_quality_log", "exit_learnings"} <= have:
        # N14: die Tabellen existieren nicht (keine Migration); ohne Pruefung scheiterte die Abfrage mit OperationalError
        print("  ⚠ Tabellen exit_quality_log/exit_learnings fehlen: uebersprungen", flush=True)
        return
    cutoff = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")

    exits = con.execute("""
        SELECT p.id, p.ticker, p.exit_date, p.exit_reason,
               p.exit_price, p.entry_price, p.pnl_pct,
               p.thesis_text, p.direction
        FROM positions p
        LEFT JOIN exit_quality_log e ON e.position_id = p.id
        WHERE p.status = 'closed'
        AND p.exit_date >= ?
        AND p.exit_reason IN ('THESIS_BROKEN', 'TECH_BROKEN', 'WEAKENING')
        AND p.signal_source = 'thematic'
        AND e.id IS NULL
        ORDER BY p.exit_date DESC
    """, (cutoff,)).fetchall()

    print(f"  {len(exits)} Exits zu reviewen", flush=True)

    if not exits:
        print("  Keine neuen Exits zu reviewen.", flush=True)
        return

    results = []
    for pos in exits:
        ticker    = pos["ticker"]
        exit_date = (pos["exit_date"] or "")[:10]
        exit_price = pos["exit_price"] or 0
        entry_price = pos["entry_price"] or 0
        pnl_at_exit = pos["pnl_pct"] or 0

        print(f"  Reviewing {ticker} (Exit: {exit_date}, {pos['exit_reason']})...", flush=True)

        # Kurspreise nach Exit holen
        price_7d  = _get_price_after(ticker, exit_date, 7)
        price_14d = _get_price_after(ticker, exit_date, 14)
        price_30d = _get_price_after(ticker, exit_date, 30)

        # PnL wenn gehalten
        def pnl_if_held(price_after):
            if not price_after or not entry_price:
                return None
            if pos["direction"] == "SHORT":
                return (entry_price - price_after) / entry_price * 100
            return (price_after - entry_price) / entry_price * 100

        # LLM-Bewertung
        verdict_data = _llm_verdict(
            ticker, pos["thesis_text"], pos["exit_reason"],
            exit_price, entry_price, pnl_at_exit,
            price_7d, price_14d, price_30d, con
        )
        verdict, confidence, rationale = verdict_data[0], verdict_data[1], verdict_data[2]
        thesis_recovered = int(verdict_data[3]) if len(verdict_data) > 3 else 0
        tighter_sl_better = int(verdict_data[4]) if len(verdict_data) > 4 else 0
        wider_sl_better = int(verdict_data[5]) if len(verdict_data) > 5 else 0
        lesson = verdict_data[6] if len(verdict_data) > 6 else ""

        icon = {"too_early": "⚠️", "correct": "✅", "too_late": "🔴"}.get(verdict, "❓")
        print(f"    {icon} {verdict} (Conf={confidence:.0%}): {rationale[:80]}", flush=True)

        con.execute("""
            INSERT INTO exit_quality_log
            (position_id, ticker, exit_date, exit_reason, exit_price, entry_price,
             pnl_pct_at_exit, price_7d_after, price_14d_after, price_30d_after,
             pnl_if_held_7d, pnl_if_held_14d, pnl_if_held_30d,
             verdict, verdict_confidence, llm_rationale,
             thesis_recovered, tighter_sl_better, wider_sl_better)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            pos["id"], ticker, exit_date, pos["exit_reason"],
            exit_price, entry_price, pnl_at_exit,
            price_7d, price_14d, price_30d,
            pnl_if_held(price_7d), pnl_if_held(price_14d), pnl_if_held(price_30d),
            verdict, confidence, rationale,
            thesis_recovered, tighter_sl_better, wider_sl_better
        ))
        con.commit()
        results.append(verdict)

    # Aggregat berechnen wenn genug Daten
    if len(results) >= 3:
        too_early = results.count("too_early") / len(results) * 100
        correct   = results.count("correct")   / len(results) * 100
        too_late  = results.count("too_late")  / len(results) * 100

        # In exit_learnings speichern
        all_reviews = con.execute("""
            SELECT verdict, thesis_recovered, tighter_sl_better, wider_sl_better
            FROM exit_quality_log
            WHERE reviewed_at >= date('now', '-30 days')
        """).fetchall()

        if all_reviews:
            n = len(all_reviews)
            con.execute("""
                INSERT INTO exit_learnings
                (period_start, period_end, total_exits_reviewed,
                 too_early_pct, correct_pct, too_late_pct,
                 thesis_recovery_rate, tighter_sl_would_help_pct, wider_sl_would_help_pct,
                 top_insight)
                VALUES (date('now', '-30 days'), date('now'), ?,?,?,?,?,?,?,?)
            """, (
                n,
                sum(1 for r in all_reviews if r["verdict"] == "too_early") / n * 100,
                sum(1 for r in all_reviews if r["verdict"] == "correct")   / n * 100,
                sum(1 for r in all_reviews if r["verdict"] == "too_late")  / n * 100,
                sum(1 for r in all_reviews if r["thesis_recovered"]) / n * 100,
                sum(1 for r in all_reviews if r["tighter_sl_better"]) / n * 100,
                sum(1 for r in all_reviews if r["wider_sl_better"])   / n * 100,
                f"Too early: {too_early:.0f}% | Correct: {correct:.0f}% | Too late: {too_late:.0f}%"
            ))
            con.commit()

        print(f"\n  📊 Exit-Qualität (diese Woche):", flush=True)
        print(f"     Zu früh: {too_early:.0f}% | Korrekt: {correct:.0f}% | Zu spät: {too_late:.0f}%", flush=True)

    print("[Exit Quality Review] DONE.", flush=True)

# ── Crabel-Kohorten-Review ───────────────────────────────────────────────────
MIN_COHORT_N = 30   # unterhalb davon wird NICHT interpretiert (Rausch-Schutz)


def _cohort_stats(rows, pnl_key):
    """Aggregiert N / Ø-P&L / Win-Rate über eine Trade-Kohorte."""
    vals = [r[pnl_key] for r in rows if r[pnl_key] is not None]
    if not vals:
        return None
    wins = sum(1 for v in vals if v > 0)
    return {
        "n":        len(vals),
        "avg_pnl":  sum(vals) / len(vals),
        "win_rate": wins / len(vals) * 100,
    }


def crabel_cohort_review(con):
    """
    Stufe 1 der Crabel-Auswertung: MESSEN, nicht entscheiden.

    Vergleicht drei Kohorten:
      A) Echte Trades, bei denen das Gate scharf war und der Breakout bestätigt
         wurde (crabel_at_entry.contraction = true)
      B) Echte Trades ohne Kontraktions-Pattern (Gate griff nicht)
      C) Shadow: Trades, die das Gate verhindert hat (blocked_entries)

    Die Kernfrage beantwortet C: Hätten die geblockten Trades Geld verdient,
    kostet das Gate Performance. Verloren sie, hilft es. Diese Frage ist aus
    `positions` allein prinzipiell nicht beantwortbar — dort stehen nur die
    Trades, die der Filter durchgelassen hat.

    Bewusst KEINE automatische Anpassung: bei N<30 pro Kohorte wäre jede
    Parameter-Änderung Rauschen-Verfolgung. Die Config bleibt unangetastet.
    """
    print("\n[Crabel-Kohorten] Auswertung...", flush=True)

    # ── Echte Trades nach Pattern-State splitten ──
    closed = con.execute("""
        SELECT pnl_pct, crabel_at_entry FROM positions
        WHERE status='closed' AND crabel_at_entry IS NOT NULL
    """).fetchall()

    confirmed, no_pattern = [], []
    for r in closed:
        try:
            st = json.loads(r["crabel_at_entry"])
        except Exception:
            continue
        (confirmed if st.get("contraction") else no_pattern).append(
            {"pnl_pct": r["pnl_pct"]}
        )

    a = _cohort_stats(confirmed, "pnl_pct")
    b = _cohort_stats(no_pattern, "pnl_pct")

    # ── Shadow-Kohorte ──
    blocked = [dict(r) for r in con.execute("""
        SELECT pnl_pct_sim, later_entered, outcome FROM blocked_entries
        WHERE eval_status='evaluated'
    """).fetchall()]
    c = _cohort_stats(blocked, "pnl_pct_sim")

    def _fmt(label, s):
        if not s:
            return f"  {label:34} —  keine Daten"
        warn = "" if s["n"] >= MIN_COHORT_N else f"  ⚠ N<{MIN_COHORT_N}"
        return (f"  {label:34} N={s['n']:3}  Ø {s['avg_pnl']:+6.2f}%  "
                f"WR {s['win_rate']:3.0f}%{warn}")

    print(_fmt("A) Breakout bestätigt (real)", a), flush=True)
    print(_fmt("B) Kein Pattern (real)", b), flush=True)
    print(_fmt("C) Vom Gate geblockt (Shadow)", c), flush=True)

    if c:
        later = sum(1 for r in blocked if r["later_entered"])
        print(f"     davon später doch real eingekauft: {later}/{c['n']} "
              f"({later / c['n'] * 100:.0f}%)", flush=True)

    # ── Interpretation nur bei ausreichendem Sample ──
    if not c or c["n"] < MIN_COHORT_N:
        have = c["n"] if c else 0
        print(f"\n  ⏳ Shadow-Sample {have}/{MIN_COHORT_N} – noch keine belastbare "
              f"Aussage. Keine Anpassung.", flush=True)
        return

    verdict = ("Gate kostet Performance – geblockte Trades wären profitabel gewesen"
               if c["avg_pnl"] > 0 else
               "Gate hilft – geblockte Trades hätten Geld verloren")
    print(f"\n  📊 Befund: {verdict} (Ø {c['avg_pnl']:+.2f}%)", flush=True)

    if a and a["n"] >= MIN_COHORT_N and b and b["n"] >= MIN_COHORT_N:
        delta = a["avg_pnl"] - b["avg_pnl"]
        print(f"  📊 Bestätigte vs. musterlose Entries: {delta:+.2f}%-Punkte "
              f"Unterschied", flush=True)

    print("  → Entscheidung bleibt manuell (Stufe 2 der Adaption noch nicht aktiv).",
          flush=True)


def main():
    con = _db_connect()
    print(f"[Weekly Review] {date.today().isoformat()}", flush=True)

    _theme_lifecycle_review(con)
    _position_30day_review(con)
    crabel_cohort_review(con)

    con.close()
    print("[Weekly Review] DONE.", flush=True)


if __name__ == "__main__":
    main()