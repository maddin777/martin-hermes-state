"""
Tax Tracker — Hält tax_year_tracking aktuell.
Laeuft taeglich, konsolidiert Sonntags.
"""
import os
import sqlite3
from datetime import date, datetime

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data", "trading.db"
)


def _db_connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def main():
    con = _db_connect()
    today = date.today()
    current_year = today.year

    # Realisierte Gains/Losses
    closed = con.execute("""
        SELECT pnl_eur, pnl_fx_effect_eur, currency, exit_date
        FROM positions
        WHERE status = 'closed'
        AND exit_date LIKE ?
    """, (f"{current_year}%",)).fetchall()

    gains = 0.0
    losses = 0.0

    for pos in closed:
        pnl = pos["pnl_eur"] or 0
        fx = pos["pnl_fx_effect_eur"] or 0
        total = pnl + fx
        if total > 0:
            gains += total
        else:
            losses += abs(total)

    net = gains - losses
    sparer = 1000.0
    used = min(sparer, net) if net > 0 else 0
    taxable = max(net - used, 0)
    tax_est = taxable * 0.2638  # Abgeltungsteuer + Soli

    con.execute("""
        INSERT OR REPLACE INTO tax_year_tracking
        (year, realized_gains_eur, realized_losses_eur,
         net_realized_eur, sparerpauschbetrag_eur,
         sparerpauschbetrag_used, estimated_tax_liability_eur,
         last_recalculated)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        current_year,
        round(gains, 2),
        round(losses, 2),
        round(net, 2),
        sparer,
        round(used, 2),
        round(tax_est, 2),
        datetime.now().isoformat(),
    ))

    con.commit()
    con.close()

    print(
        f"[Tax Tracker] {current_year}: Gains={gains:.2f}€, "
        f"Losses={losses:.2f}€, Net={net:+.2f}€, "
        f"Tax est.={tax_est:.2f}€",
        flush=True,
    )


if __name__ == "__main__":
    main()