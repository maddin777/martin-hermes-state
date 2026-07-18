"""
roles/budget.py — Harte Tages-Token-Budgets pro Rolle.

Bewusst NICHT in der Strategy-Config: der strategy_optimizer soll an den
Kostenbremsen nicht drehen duerfen.

Bei Ueberschreitung: check_and_reserve() liefert False → der Aufrufer geht in
den Fail-Open-Pfad (heutiges Verhalten) und printet eine "⚠ Budget"-Zeile.
"""
import sys

sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")

from roles import ensure_roles_schema

DAILY_TOKEN_BUDGET = {
    "committee":         150_000,   # ~6 Kandidaten x 3 Rollen
    "devils_advocate":    60_000,
    "extractor_analyst": 400_000,   # ersetzt teilweise heutige Chunk-Calls
}


def _spent_today(con, role: str, date: str) -> int:
    row = con.execute("""
        SELECT COALESCE(SUM(tokens_in), 0) + COALESCE(SUM(tokens_out), 0) AS total
        FROM llm_budget_log
        WHERE date = ? AND role = ?
    """, (date, role)).fetchone()
    if not row:
        return 0
    return int(row["total"] or 0)


def check_and_reserve(con, role: str, date: str) -> bool:
    """
    Prueft, ob fuer `role` am `date` noch Budget uebrig ist.

    Returns:
        True  → Aufrufer darf den LLM-Call machen.
        False → Budget erschoepft, Aufrufer geht in den Fail-Open-Pfad.

    Fehler (DB, Schema, ...) fuehren bewusst zu True: eine kaputte Budget-Zeile
    darf die Pipeline nicht faktisch abschalten. Die Kosten sind durch die
    max_checks_per_run-Deckel im Aufrufer ohnehin begrenzt.
    """
    try:
        ensure_roles_schema(con)
        limit = DAILY_TOKEN_BUDGET.get(role)
        if not limit:
            return True
        spent = _spent_today(con, role, date)
        if spent >= limit:
            print(f"  ⚠ Budget: Rolle '{role}' hat Tageslimit erreicht "
                  f"({spent:,}/{limit:,} Tokens) → Fail-Open", flush=True)
            return False
        return True
    except Exception as e:
        print(f"  ⚠ Budget-Check fehlgeschlagen ({role}): {e} → erlaube Call", flush=True)
        return True


def record_spend(con, role: str, date: str, tokens_in: int,
                 tokens_out: int, model: str) -> None:
    """
    Bucht den Verbrauch eines Calls. UPSERT ueber UNIQUE(date, role, model).

    Fehler werden geschluckt: Buchhaltung darf nie einen Trade-Pfad stoppen.
    """
    try:
        ensure_roles_schema(con)
        con.execute("""
            INSERT INTO llm_budget_log (date, role, tokens_in, tokens_out, calls, model)
            VALUES (?, ?, ?, ?, 1, ?)
            ON CONFLICT(date, role, model) DO UPDATE SET
                tokens_in  = tokens_in  + excluded.tokens_in,
                tokens_out = tokens_out + excluded.tokens_out,
                calls      = calls + 1
        """, (date, role, int(tokens_in or 0), int(tokens_out or 0), model or "unknown"))
        con.commit()
    except Exception as e:
        print(f"  ⚠ Budget-Buchung fehlgeschlagen ({role}): {e}", flush=True)


def remaining(con, role: str, date: str) -> int:
    """Restbudget in Tokens (fuer Reports/Debug)."""
    try:
        limit = DAILY_TOKEN_BUDGET.get(role, 0)
        return max(0, limit - _spent_today(con, role, date))
    except Exception:
        return 0
