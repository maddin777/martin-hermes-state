"""
test_committee.py — Probe-Script fuer den Investment Committee (Sprint R1).

Ruft run_committee() isoliert auf, ohne den Entry-Loop anzufassen. Printet alle
drei Rollen-JSONs plus das Final-Verdict und schreibt (wie im Live-Betrieb) eine
Zeile nach committee_log.

Nutzung:
    cd /root/.hermes/profiles/hermes_trading/skills/trading
    python3 scripts/test_committee.py                 # echte Watchlist-Row, LONG
    python3 scripts/test_committee.py --direction SHORT
    python3 scripts/test_committee.py --ticker NVDA
    python3 scripts/test_committee.py --fake          # Fake-Kandidat, keine DB-Row noetig
    python3 scripts/test_committee.py --dry-run       # kein LLM-Call, nur Kontext-Dump

Verifikation danach:
    sqlite3 data/trading.db "SELECT ticker, final_verdict, would_block,
        tokens_in+tokens_out FROM committee_log ORDER BY id DESC LIMIT 5"
"""
import argparse
import json
import sys
from datetime import date

sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")
import env_loader  # noqa: F401  (side-effect: laedt .env)

from config import db_connect
from roles import ensure_roles_schema
from roles import budget, committee


FAKE_CANDIDATE = {
    "id": -1,
    "ticker": "NVDA",
    "name": "NVIDIA",
    "conviction_score": 0.82,
    "conviction_score_bear": 0.31,
    "tech_score": 0.74,
    "tech_direction": "LONG",
    "mention_count": 7,
    "channels": json.dumps(["Kanal A", "Kanal B", "Kanal C"]),
    "notes": "Fake-Kandidat aus test_committee.py – mehrfach als KI-Profiteur genannt.",
    "last_seen": "2026-07-17",
    "status": "watching",
}


def _load_candidate(con, args):
    if args.fake:
        return FAKE_CANDIDATE

    if args.ticker:
        row = con.execute(
            "SELECT * FROM watchlist WHERE ticker = ? LIMIT 1", (args.ticker,)
        ).fetchone()
        if not row:
            print(f"⚠ Kein Watchlist-Eintrag fuer {args.ticker} – nutze Fake-Kandidat.")
            return FAKE_CANDIDATE
        return row

    col = "conviction_score_bear" if args.direction == "SHORT" else "conviction_score"
    row = con.execute(f"""
        SELECT * FROM watchlist
        WHERE status='watching' AND ticker IS NOT NULL AND tech_score IS NOT NULL
        ORDER BY {col} DESC LIMIT 1
    """).fetchone()
    if not row:
        print("⚠ Keine passende Watchlist-Row – nutze Fake-Kandidat.")
        return FAKE_CANDIDATE
    return row


def _build_context(con, cand, direction, mode):
    """Baut denselben Kontext, den open_new_positions() befuellt."""
    pos_rows = con.execute("""
        SELECT ticker, name, direction, position_size, entry_price, entry_date
        FROM positions WHERE status='open' ORDER BY position_size DESC
    """).fetchall()
    pos_text = "\n".join(
        f"  - {r['name']} ({r['ticker']}) {r['direction']}: "
        f"{(r['position_size'] or 0):.0f} EUR, Entry {(r['entry_date'] or '')[:10]} "
        f"@ {(r['entry_price'] or 0):.2f}"
        for r in pos_rows
    ) or "  - keine"

    sector_exposure = {}
    for r in con.execute("""
        SELECT COALESCE(c.sector, 'Other') as sector, SUM(p.position_size) as exposure
        FROM positions p LEFT JOIN companies c ON c.ticker = p.ticker
        WHERE p.status='open' GROUP BY sector
    """).fetchall():
        sector_exposure[r["sector"]] = r["exposure"] or 0

    pf = con.execute("SELECT total_value FROM portfolio WHERE id=1").fetchone()
    portfolio_value = (pf["total_value"] if pf else None) or 10000.0

    ticker = cand["ticker"]
    sector_row = con.execute(
        "SELECT sector FROM companies WHERE ticker=?", (ticker,)
    ).fetchone()
    ticker_sector = (sector_row["sector"] if sector_row and sector_row["sector"]
                     else "Other")

    price = atr = None
    crabel = None
    try:
        from utils import get_price_data_cached, get_crabel_patterns
        price, atr, _df = get_price_data_cached(ticker)
        crabel = get_crabel_patterns(ticker, stretch_len=10)
    except Exception as e:
        print(f"⚠ Preisdaten fuer {ticker} nicht verfuegbar: {e}")

    macro, regime = "neutral", "sideways"
    try:
        from config import MACRO_SIGNAL_PATH
        with open(MACRO_SIGNAL_PATH) as f:
            m = json.load(f)
        macro = m.get("signal", macro)
        regime = m.get("regime", regime)
    except Exception:
        pass

    return {
        "mode": mode,
        "regime": regime,
        "macro": macro,
        "sector_exposure": sector_exposure,
        "open_positions_text": pos_text,
        "current_price": price,
        "atr": atr,
        "crabel": crabel,
        "ticker_sector": ticker_sector,
        "portfolio_value": portfolio_value,
        "drawdown_pct": 0.0,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--direction", default="LONG", choices=["LONG", "SHORT"])
    ap.add_argument("--ticker", default=None)
    ap.add_argument("--fake", action="store_true", help="Fake-Kandidat statt DB-Row")
    ap.add_argument("--dry-run", action="store_true",
                    help="Nur Kontext dumpen, kein LLM-Call")
    ap.add_argument("--mode", default="shadow", choices=["shadow", "active"],
                    help="Wird nur ins Log geschrieben – blockt hier nie etwas")
    args = ap.parse_args()

    con = db_connect()
    ensure_roles_schema(con)

    cand = _load_candidate(con, args)
    ctx = _build_context(con, cand, args.direction, args.mode)

    print("=" * 70)
    print(f"Kandidat : {cand['name']} ({cand['ticker']}) | {args.direction}")
    print(f"Sektor   : {ctx['ticker_sector']}")
    print(f"Kurs/ATR : {ctx['current_price']} / {ctx['atr']}")
    print(f"Regime   : {ctx['macro']} / {ctx['regime']}")
    print(f"Budget   : {budget.remaining(con, 'committee', date.today().isoformat()):,} Tokens uebrig")
    print("Offene Positionen:")
    print(ctx["open_positions_text"])
    print("=" * 70)

    if args.dry_run:
        print("\n--dry-run: kein LLM-Call ausgefuehrt.")
        con.close()
        return

    res = committee.run_committee(con, cand, args.direction, ctx)

    for role in ("bull", "bear", "risk"):
        print(f"\n── {role.upper()} " + "─" * 55)
        print(json.dumps(res.get(role) or {}, indent=2, ensure_ascii=False))

    print("\n" + "=" * 70)
    print(f"FINAL VERDICT : {res['final_verdict']}")
    print(f"SIZE FACTOR   : {res['size_factor']}")
    print(f"LOG ID        : {res['log_id']}")
    print(f"TOKENS        : {res.get('tokens_in', 0)} in / {res.get('tokens_out', 0)} out")
    print("=" * 70)

    con.close()


if __name__ == "__main__":
    main()
