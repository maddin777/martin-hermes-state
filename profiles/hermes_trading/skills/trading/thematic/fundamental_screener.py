"""
Fundamental Screener — Reichert Kandidaten mit Finnhub-Fundamentaldaten an.
Setzt Flags (PE, Short Interest, Analyst Coverage, Earnings).
"""
import json
import os
import sqlite3
from datetime import date, datetime, timedelta
from thematic.lib import finnhub_client

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data", "trading.db"
)


def _db_connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


MIN_SECTOR_PEERS = 5


def _sector_of(con, ticker: str):
    try:
        row = con.execute("SELECT sector FROM companies WHERE ticker = ?", (ticker,)).fetchone()
        return row[0] if row and row[0] else None
    except Exception:
        return None


def _sector_median_pe(con, sector: str) -> float:
    """Ermittelt Sektor-Median P/E aus eigenen Snapshots (rolling 30d).

    N18 (30.09.2026): der Parameter `sector` wurde ignoriert (Median ueber ALLE Titel). Jetzt: Median der Peers im selben
    Sektor (Join auf companies.sector), erst bei weniger als MIN_SECTOR_PEERS Peers der Gesamtmedian."""
    cutoff = (date.today() - timedelta(days=30)).isoformat()
    rows = []
    if sector and sector != "all":
        try:
            rows = con.execute("""
                SELECT fs.pe_ttm FROM fundamentals_snapshot fs
                JOIN companies c ON c.ticker = fs.ticker
                WHERE fs.date >= ? AND fs.pe_ttm IS NOT NULL AND fs.pe_ttm > 0 AND c.sector = ?
                ORDER BY fs.pe_ttm
            """, (cutoff, sector)).fetchall()
        except Exception:
            rows = []
    if len(rows) < MIN_SECTOR_PEERS:
        rows = con.execute("""
            SELECT pe_ttm FROM fundamentals_snapshot
            WHERE date >= ? AND pe_ttm IS NOT NULL AND pe_ttm > 0
            ORDER BY pe_ttm
        """, (cutoff,)).fetchall()
    if not rows:
        return 18.0  # Fallback
    vals = [r["pe_ttm"] for r in rows]
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 == 1 else (vals[mid - 1] + vals[mid]) / 2


def _fcf_yield(metric_data: dict, profile: dict, market_cap):
    """FCF-Rendite. N18: der Fallback fcfPerShareTTM (pro Aktie) wurde wie ein Gesamtbetrag durch die Marktkapitalisierung
    geteilt. Finnhub: freeCashFlowTTM und marketCapitalization in Mio USD, fcfPerShareTTM in USD je Aktie,
    shareOutstanding in Mio. Rendite je Aktie = fcfPerShare / (Marktkapitalisierung / Aktienzahl)."""
    if not market_cap or market_cap <= 0:
        return None
    fcf_total = metric_data.get("freeCashFlowTTM")
    if fcf_total:
        return float(fcf_total) / float(market_cap)
    per_share = metric_data.get("fcfPerShareTTM")
    shares = (profile or {}).get("shareOutstanding")
    if per_share and shares and shares > 0:
        price = float(market_cap) / float(shares)
        return float(per_share) / price if price > 0 else None
    return None


def _check_flags(row: dict, sector_pe: float) -> list:
    """Erstellt Flags fuer einen Ticker."""
    flags = []
    mc = row.get("market_cap_eur") or 0
    pe = row.get("pe_ttm") or 0
    si = row.get("short_interest_pct") or 0
    ac = row.get("analyst_count") or 0
    earnings = row.get("next_earnings_date")

    if mc < 500_000_000:
        flags.append("too_small")
    if pe > sector_pe * 2 and pe > 0:
        flags.append("overvalued")
    if si > 20:
        flags.append("high_short")
    if earnings:
        try:
            edate = datetime.strptime(earnings, "%Y-%m-%d")
            if (edate - datetime.now()).days <= 7:
                flags.append("earnings_soon")
        except (ValueError, TypeError):
            pass
    if ac < 8:
        flags.append("low_coverage")

    return flags


def main():
    con = _db_connect()
    today = date.today().isoformat()

    # Alle Candidate/Watching-Beneficiaries die heute Aktualisiert wurden
    candidates = con.execute("""
        SELECT * FROM theme_beneficiaries
        WHERE status IN ('candidate', 'watching', 'active')
        AND last_updated >= ?
    """, (today,)).fetchall()

    if not candidates:
        print("[Fundamental Screener] Keine neuen/aktualisierten Beneficiaries.")
        con.close()
        return

    print(f"[Fundamental Screener] {len(candidates)} Kandidaten...", flush=True)

    for c in candidates:
        ticker = c["ticker"]
        sector_pe = _sector_median_pe(con, _sector_of(con, ticker))
        profile = finnhub_client.get_company_profile(ticker)
        metrics = finnhub_client.get_basic_financials(ticker)
        metric_data = metrics.get("metric", {}) if metrics else {}

        # Earnings-Datum
        earnings = finnhub_client.get_earnings_calendar(ticker)
        next_earnings = None
        if isinstance(earnings, dict):
            ec_list = earnings.get("earningsCalendar", [])
            if ec_list:
                next_earnings = ec_list[0].get("date")

        market_cap = profile.get("marketCapitalization", 0) or metric_data.get("marketCapitalization", 0)
        # Market cap in Mio USD -> EUR (approx)
        market_cap_eur = market_cap * 1_000_000 * 0.93 if market_cap else None

        pe_ttm = metric_data.get("peBasicExclExtraTTM") or metric_data.get("peTTM")
        pe_forward = metric_data.get("peForward")

        # FCF Yield aus finnhub metrics (N18: Einheiten getrennt behandelt)
        fcf_yield = _fcf_yield(metric_data, profile, market_cap)

        rev_growth = metric_data.get("revenueGrowthTTMYoy")

        # Short Interest
        short_interest = finnhub_client.get_short_interest(ticker)

        # Analyst Coverage
        recs = finnhub_client.get_recommendation_trends(ticker)
        analyst_count = 0
        if recs:
            latest = recs[0] if recs else {}
            analyst_count = (
                (latest.get("strongBuy", 0) or 0) +
                (latest.get("buy", 0) or 0) +
                (latest.get("hold", 0) or 0) +
                (latest.get("sell", 0) or 0) +
                (latest.get("strongSell", 0) or 0)
            )

        debt_eq = metric_data.get("totalDebt/totalEquityQuarterly")
        roic = metric_data.get("roicTTM")

        row = {
            "market_cap_eur": market_cap_eur,
            "pe_ttm": pe_ttm,
            "pe_forward": pe_forward,
            "fcf_yield": fcf_yield,
            "revenue_growth_yoy": rev_growth,
            "short_interest_pct": short_interest,
            "analyst_count": analyst_count,
            "debt_to_equity": debt_eq,
            "roic": roic,
            "next_earnings_date": next_earnings,
        }
        flags = _check_flags(row, sector_pe)

        # UPSERT fundamentals_snapshot
        con.execute("DELETE FROM fundamentals_snapshot WHERE date = ? AND ticker = ?",
                     (today, ticker))
        con.execute("""
            INSERT INTO fundamentals_snapshot
            (date, ticker, market_cap_eur, pe_ttm, pe_forward, pe_sector_median,
             fcf_yield, revenue_growth_yoy, short_interest_pct, analyst_count,
             debt_to_equity, roic, next_earnings_date, flags_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            today, ticker,
            market_cap_eur, pe_ttm, pe_forward, sector_pe,
            fcf_yield, rev_growth, short_interest, analyst_count,
            debt_eq, roic, next_earnings,
            json.dumps(flags),
        ))

        print(f"  {ticker}: PE={pe_ttm}, FCF={fcf_yield}, "
              f"Short={short_interest}%, Analysts={analyst_count}, "
              f"Flags={flags}", flush=True)

    con.commit()
    con.close()
    print(f"[Fundamental Screener] DONE", flush=True)


if __name__ == "__main__":
    main()