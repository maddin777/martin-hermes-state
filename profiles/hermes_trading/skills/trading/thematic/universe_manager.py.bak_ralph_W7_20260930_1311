"""
Universe Manager — Pflegt das Anlage-Universum (~800 Ticker).
Woechentlicher Refresh.
"""
import json
import os
from datetime import date

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data", "trading.db"
)
THEMATIC_DIR = os.path.dirname(__file__)
UNIVERSE_PATH = os.path.join(THEMATIC_DIR, "config", "universe.json")


def main():
    with open(UNIVERSE_PATH) as f:
        universe = json.load(f)

    print(f"[Universe Manager] {len(universe)} Ticker im Universum.", flush=True)

    # Validierung: Ticker auf yfinance-Verfuegbarkeit pruefen
    valid = []
    invalid = []

    for ticker in universe:
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            info = t.fast_info
            price = info.get("last_price") or info.get("regular_market_price")
            if price and price > 0:
                valid.append(ticker)
            else:
                invalid.append(ticker)
        except Exception:
            invalid.append(ticker)

    if invalid:
        print(f"[Universe Manager] {len(invalid)} invalid: {', '.join(invalid[:10])}...")

    # Update universe.json mit validen Tickern
    with open(UNIVERSE_PATH, "w") as f:
        json.dump(valid, f, indent=2)

    print(f"[Universe Manager] DONE: {len(valid)} valid", flush=True)


if __name__ == "__main__":
    main()