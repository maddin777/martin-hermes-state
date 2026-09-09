"""
Beneficiary Mapper — Multi-LLM-Intersection fuer Aktien zu Themen.
3 LLMs (Grok Lite, Gemini Flash, Llama) parallel → >=2/3 Konsens.
"""
import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from thematic.lib import llm_client, prompt_loader

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data", "trading.db"
)


def _db_connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _validate_ticker(ticker: str) -> bool:
    """Validiert ob Ticker via yfinance existiert."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        info = t.fast_info
        try:
            price = info.last_price
        except Exception:
            price = None
        if price and price > 0:
            return True
    except Exception:
        pass

    # Fallback: fuer internationale Ticker mit Su .DE,.T,.KS, etc.
    # die yfinance manchmal nicht findet, trotzdem akzeptieren
    suffixes = [".DE", ".T", ".KS", ".OL", ".MI", ".PA", ".AS", ".SW", ".MC"]
    for s in suffixes:
        if ticker.endswith(s):
            return True
    return False


def _call_one_llm(prompt: str, model: str, label: str) -> tuple:
    """Ein einzelner LLM-Call mit Fehlerbehandlung."""
    result = llm_client.call_llm(prompt, model, temperature=0.3, json_mode=True)
    data = llm_client.parse_json_response(result, {})
    return label, data


def _intersect_beneficiaries(results: dict) -> list:
    """
    Intersection-Logik: Ticker muss von >=2/3 LLMs genannt werden.
    Returns Liste von Beneficiaries mit konsolidierten Daten.
    """
    # Sammle alle Ticker mit Play-Types und Source-Models
    ticker_map = {}  # {ticker: {play_types: {type: count}, models: [labels]}}

    for label, data in results.items():
        for category in ["direct_plays", "picks_and_shovels",
                          "second_derivatives", "losers"]:
            for entry in data.get(category, []):
                ticker = entry.get("ticker", "").strip().upper()
                if not ticker:
                    continue

                if ticker not in ticker_map:
                    ticker_map[ticker] = {
                        "play_types": {},
                        "models": [],
                        "name": entry.get("name", ""),
                        "rationale": entry.get("rationale", ""),
                    }

                ticker_map[ticker]["play_types"].setdefault(category, 0)
                ticker_map[ticker]["play_types"][category] += 1
                ticker_map[ticker]["models"].append(label)

    # Filter: >= 2 LLMs
    beneficiaries = []
    for ticker, info in ticker_map.items():
        model_count = len(set(info["models"]))
        if model_count < 2:
            continue

        # Bestimme Play-Type per Mehrheitsentscheid
        play_types = info["play_types"]
        best_type = max(play_types, key=play_types.get)
        best_count = play_types[best_type]

        beneficiaries.append({
            "ticker": ticker,
            "company_name": info["name"],
            "play_type": best_type,
            "llm_confidence_count": model_count,
            "llm_models_picked": json.dumps(list(set(info["models"]))),
            "rationale": info["rationale"],
        })

    return beneficiaries



# ── Beneficiary-Lifecycle (08.09.2026) ──────────────────────────────────────
# Befund: `theme_beneficiaries.status` wurde von KEINER Codestelle je geaendert.
# Der Mapper schreibt 'candidate', nichts befoerdert und nichts archiviert —
# in der Live-DB standen alle 220 Eintraege auf 'candidate', 208 davon aelter
# als 60 Tage (juengstes last_updated: 13.07.). Die Filter `status != 'archived'`
# in watchlist_manager, briefing und dashboard waren damit wirkungslos, und
# 33 Ticker bekamen aus monatealten Mappings dauerhaft Conviction-Boost.
#
# Zustaende:
#   active    Theme aktiv UND letzter Thesis-Check INTACT  → voller Boost
#   candidate gemappt, aber (noch) unbestaetigt            → minimaler Boost
#   archived  Theme nicht mehr aktiv, These gebrochen oder Mapping veraltet
#             → kein Boost, faellt aus Briefing und Dashboard
#
# Rein ableitend: der Status wird bei jedem Lauf aus den Fakten neu bestimmt,
# es gibt keinen Zustand, den ein fehlgeschlagener Lauf dauerhaft verfaelscht.
BENEFICIARY_MAX_AGE_DAYS = 60


def sync_beneficiary_status(con, max_age_days: int = BENEFICIARY_MAX_AGE_DAYS) -> dict:
    """Leitet theme_beneficiaries.status aus Theme, Thesis und Alter ab."""
    rows = con.execute("""
        SELECT tb.id, tb.ticker, tb.status,
               td.status AS theme_status,
               julianday('now') - julianday(COALESCE(tb.last_updated, tb.added_date)) AS age,
               (SELECT l.status FROM thesis_status_log l
                 WHERE l.beneficiary_id = tb.id OR l.ticker = tb.ticker
                 ORDER BY (l.beneficiary_id IS NULL), l.id DESC LIMIT 1) AS thesis
        FROM theme_beneficiaries tb
        LEFT JOIN theme_definitions td ON td.id = tb.theme_id
    """).fetchall()

    counts = {"active": 0, "candidate": 0, "archived": 0, "changed": 0}
    for r in rows:
        thesis = (r["thesis"] or "").strip().lower()
        age = r["age"] if r["age"] is not None else 0

        if (r["theme_status"] != "active"
                or thesis in ("broken", "degraded")
                or age > max_age_days):
            new = "archived"
        elif thesis == "intact":
            new = "active"
        else:
            new = "candidate"

        counts[new] += 1
        if new != r["status"]:
            counts["changed"] += 1
            con.execute("UPDATE theme_beneficiaries SET status=? WHERE id=?", (new, r["id"]))

    con.commit()
    print(f"[Beneficiary Lifecycle] active={counts['active']} "
          f"candidate={counts['candidate']} archived={counts['archived']} "
          f"({counts['changed']} geaendert)", flush=True)
    return counts


def main():
    con = _db_connect()
    today = date.today().isoformat()

    # Themen heute: neu oder accelerating
    themes = con.execute("""
        SELECT * FROM theme_definitions
        WHERE status = 'active'
        AND (first_detected = ? OR momentum = 'accelerating')
        ORDER BY coverage_count DESC
    """, (today,)).fetchall()

    if not themes:
        print(f"[Beneficiary Mapper] Keine neuen/accelerating-Themen heute.")
        con.close()
        return

    print(f"[Beneficiary Mapper] Verarbeite {len(themes)} Themen...", flush=True)

    total_new = 0
    for theme in themes:
        theme_name = theme["name"]
        theme_desc = theme["description"]

        prompt = prompt_loader.load_prompt(
            "beneficiary_map_v1.md",
            theme_name=theme_name,
            theme_description=theme_desc,
        )

        models = {
            "grok-lite": llm_client.get_model("beneficiary_a"),
            "gemini-flash": llm_client.get_model("beneficiary_b"),
            "llama": llm_client.get_model("beneficiary_c"),
        }

        # Parallele LLM-Calls
        results = {}
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(_call_one_llm, prompt, model, label): label
                for label, model in models.items()
            }
            for future in as_completed(futures):
                try:
                    label, data = future.result()
                    results[label] = data
                except Exception as e:
                    print(f"  ⚠ LLM {futures[future]} fehlgeschlagen: {e}")

        if len(results) < 2:
            print(f"  ⚠ '{theme_name}': Zu wenige LLM-Ergebnisse ({len(results)})")
            continue

        # Intersection
        beneficiaries = _intersect_beneficiaries(results)
        print(f"  '{theme_name}': {len(beneficiaries)} Beneficiaries (Intersection)", flush=True)

        for b in beneficiaries:
            ticker = b["ticker"]

            # yfinance-Validation
            if not _validate_ticker(ticker):
                print(f"    ⚠ {ticker}: yfinance-Validation fehlgeschlagen, ueberspringe")
                continue

            # Check ob bereits vorhanden
            existing = con.execute(
                "SELECT id FROM theme_beneficiaries WHERE theme_id = ? AND ticker = ?",
                (theme["id"], ticker)
            ).fetchone()

            if existing:
                # Update
                con.execute("""
                    UPDATE theme_beneficiaries SET
                        company_name = ?,
                        play_type = ?,
                        llm_confidence_count = ?,
                        llm_models_picked = ?,
                        rationale = ?,
                        last_updated = ?
                    WHERE id = ?
                """, (
                    b.get("company_name", ""),
                    b.get("play_type", ""),
                    b.get("llm_confidence_count", 0),
                    b.get("llm_models_picked", "[]"),
                    b.get("rationale", ""),
                    today,
                    existing["id"],
                ))
            else:
                # Insert
                con.execute("""
                    INSERT INTO theme_beneficiaries
                    (theme_id, ticker, company_name, play_type,
                     llm_confidence_count, llm_models_picked,
                     rationale, added_date, last_updated, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'candidate')
                """, (
                    theme["id"],
                    ticker,
                    b.get("company_name", ""),
                    b.get("play_type", ""),
                    b.get("llm_confidence_count", 0),
                    b.get("llm_models_picked", "[]"),
                    b.get("rationale", ""),
                    today,
                    today,
                ))
                total_new += 1

    con.commit()

    # Status aus Theme/Thesis/Alter neu ableiten (siehe sync_beneficiary_status).
    try:
        sync_beneficiary_status(con)
    except Exception as e:
        print(f"[Beneficiary Lifecycle] uebersprungen: {e}", flush=True)

    con.close()
    print(f"[Beneficiary Mapper] DONE: {total_new} neue Beneficiaries", flush=True)


if __name__ == "__main__":
    main()