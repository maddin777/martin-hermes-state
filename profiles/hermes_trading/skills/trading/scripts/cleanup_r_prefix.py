#!/usr/bin/env python3
"""
cleanup_r_prefix.py

Bereinigt "R "-Prefix-Artefakte in watchlist.name und watchlist_mentions.name.
Diese entstehen wenn der LLM-Extractor Transkript-Artefakte wie "R Barrick Mining"
(aus einer OCR/TTS-Fehllesung) in den Namen übernimmt.

Erkennung:  Name beginnt mit "R " gefolgt von Großbuchstabe
Beispiele:  "R ABR0.F", "R YDX.MU", "Barrick Mining Corp. R ABR0.F"

Außerdem: Namen die einen Ticker am Ende haben ("Barrick Mining Corp. R ABR0.F")
werden auf den reinen Firmennamen reduziert falls der Ticker in watchlist.ticker steht.

AUSFÜHREN (einmalig):
    cd /root/.hermes/.../scripts
    python3 cleanup_r_prefix.py [--dry-run]
"""
import sqlite3, re, sys
sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading/scripts")
import env_loader  # noqa
from config import DB_PATH


# Muster 1: "R XYZ123.DE" am Ende (Ticker-Artefakt)
TICKER_SUFFIX_RE = re.compile(r'\s+R\s+[A-Z0-9]{1,6}(?:\.[A-Z]{1,3})?$')
# Muster 2: "R " am Anfang gefolgt von Großbuchstabe
R_PREFIX_RE = re.compile(r'^R\s+(?=[A-Z])')


def clean_name(name: str) -> str:
    n = TICKER_SUFFIX_RE.sub("", name).strip()
    n = R_PREFIX_RE.sub("", n).strip()
    return n


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    # watchlist
    wl_rows = con.execute("SELECT id, name FROM watchlist").fetchall()
    wl_fixes = [(r["id"], r["name"], clean_name(r["name"]))
                for r in wl_rows if clean_name(r["name"]) != r["name"]]

    print(f"watchlist: {len(wl_fixes)} zu bereinigen")
    for id_, old, new in wl_fixes:
        print(f"  id={id_:4}  {old!r:55} → {new!r}")
        if not args.dry_run:
            con.execute("UPDATE watchlist SET name=? WHERE id=?", (new, id_))

    # watchlist_mentions
    wm_rows = con.execute("SELECT id, name FROM watchlist_mentions").fetchall()
    wm_fixes = [(r["id"], r["name"], clean_name(r["name"]))
                for r in wm_rows if clean_name(r["name"]) != r["name"]]

    print(f"\nwatchlist_mentions: {len(wm_fixes)} zu bereinigen")
    for id_, old, new in wm_fixes[:20]:  # max 20 zeigen
        print(f"  id={id_:5}  {old!r:55} → {new!r}")
    if len(wm_fixes) > 20:
        print(f"  ... und {len(wm_fixes)-20} weitere")
    if not args.dry_run:
        for id_, old, new in wm_fixes:
            con.execute("UPDATE watchlist_mentions SET name=? WHERE id=?", (new, id_))

    if not args.dry_run:
        con.commit()
        print(f"\n✅ {len(wl_fixes)} watchlist + {len(wm_fixes)} mentions bereinigt")
    else:
        print("\n(Dry-Run – keine Änderungen)")

    con.close()


if __name__ == "__main__":
    main()
