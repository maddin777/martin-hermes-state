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
    con.close()
    print(f"[Beneficiary Mapper] DONE: {total_new} neue Beneficiaries", flush=True)


if __name__ == "__main__":
    main()