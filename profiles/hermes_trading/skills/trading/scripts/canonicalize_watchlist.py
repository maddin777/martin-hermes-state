#!/usr/bin/env python3
"""
canonicalize_watchlist.py  —  Einmal-Migration (10.09.2026)

Wendet die canonical_tickers-Regeln auf BESTEHENDE Watchlist-Zeilen an.
Root-Cause-Fix zu den .SG/.MU/ISIN-Pseudo-Shorts: technical_validator
bevorzugte DE-Börsen → NetApp kam als NTA.SG rein (kein Sektor, kein
tech_score). Wenn nur die Export-Merge-Liste erweitert wird, bleiben die
DB-Zeilen auf dem Spiegel-Ticker und behalten tech_score=NULL + sector=Other.

Was das Script macht (pro canonical_regel source→target):
  1. Schreibend (--apply):
     - watchlist-Zeile mit ticker=source → ticker=target umbenennen
       (Bought-Status, mentions/channels/conviction bleiben erhalten)
     - Wenn target-Zeile bereits existiert: Zeilen MERGEN (höhere Conviction,
       Mentions/Bull/Bear/Channels addieren, bought-Status union) und Quellzeile löschen
     - company_aliases von source → target umhängen (damit resolve_ticker stabil wird)
     - companies-Zeile für source löschen, falls target keine eigene companies-Zeile
       hat → Copy von source (Sektor ggf. aus yfinance nachgezogen)
  2. Ohne --apply: Dry-Run — zeigt nur was passieren würde.

Danach:  PYTHONPATH=. venv/bin/python scripts/refresh_tech_scores.py
         um die umbenannten Ticker mit echten Tech-Scores zu füllen.
"""
import sys

sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")
import env_loader  # noqa
from config import db_connect  # noqa


_DE_NEBENBOERSEN = (".F", ".MU", ".SG", ".DU", ".HM", ".BE")


def resolve_primary(name, min_sim=0.6):
    """Löst einen Firmennamen auf das Primärlisting auf.

    Kandidaten von yf.Search werden nach Namensähnlichkeit (longName/shortName)
    geprüft — Nebenboersen-Listings sind ausgeschlossen, und nur ein Kandidat
    mit Ähnlichkeit ≥ min_sim wird akzeptiert. Ohne diesen Guard wurde
    "Contemporary Amperex Technology" (CATL, C7A0.F) fälschlich auf TSM
    (Taiwan Semiconductor) gemappt, weil TSM suffixlos = Priorität 0 hat.

    Bei Gleichstand gewinnt die bessere Börsen-Priorität
    (US > XETRA > Sonstige). Gibt None zurück wenn kein Kandidat passt
    → die Zeile bleibt für die Cleanup-Segregation übrig.
    """
    import yfinance as yf
    from difflib import SequenceMatcher

    try:
        quotes = (yf.Search(name, max_results=5).quotes or [])
    except Exception:
        return None

    def _prio(sym):
        if not sym:
            return 9
        if "." not in sym and "-" not in sym:
            return 0
        if sym.endswith(".DE"):
            return 1
        if sym.endswith(_DE_NEBENBOERSEN):
            return 3
        return 2

    ref = (name or "").lower().strip()
    # Priorität zuerst (US-Primär vor XETRA/Sonstigen), dann erst Ähnlichkeit:
    # sonst gewinnt ein XETRA-Mirror (0P0.DE "Galaxy Digital Holdings Ltd",
    # sim 0.90) gegen das liquide US-Primär (GLXY "Galaxy Digital", sim 0.85).
    for q in sorted(quotes, key=lambda q: _prio(q.get("symbol") or "")):
        sym = q.get("symbol")
        if not sym or sym.endswith(_DE_NEBENBOERSEN):
            continue
        cand_name = q.get("longname") or q.get("shortname") or ""
        if not cand_name:
            try:
                info = yf.Ticker(sym).info
                cand_name = info.get("longName") or info.get("shortName") or ""
            except Exception:
                cand_name = ""
        sim = SequenceMatcher(None, ref, cand_name.lower().strip()).ratio()
        if sim >= min_sim:
            return sym
    return None


def main():
    import sqlite3  # noqa
    apply = "--apply" in sys.argv
    auto = "--auto" in sys.argv
    tag = "ANWENDEN" if apply else "DRY-RUN"
    print(f"\n=== Canonicalize Watchlist ({tag}) ===\n")

    con = db_connect()

    rules = con.execute(
        "SELECT source_ticker, target_ticker FROM canonical_tickers"
    ).fetchall()
    rules = {r[0]: r[1] for r in rules}

    # Phase 2 (--auto): Nebenboersen-Mirror ohne Tech-Score neu auflösen.
    # Vorschlag 3 (10.09.2026): .SG/.MU/.F-Symbole ohne Score werden auf das
    # Primärlisting gemappt statt einzeln gepflegt — sonst wächst die Liste
    # immer weiter (NetApp, Snowflake, Swatch, Dell, GitLab, monday.com ...).
    if auto:
        mirrors = con.execute(
            "SELECT rowid, ticker, name FROM watchlist "
            "WHERE status IN ('watching','bought') AND tech_score IS NULL "
            "AND (ticker LIKE '%.SG' OR ticker LIKE '%.MU' OR ticker LIKE '%.F' "
            "OR ticker LIKE '%.DU' OR ticker LIKE '%.HM' OR ticker LIKE '%.BE')"
        ).fetchall()
        print(f"--- Auto-Resolve: {len(mirrors)} Mirror-Zeilen ohne Tech-Score ---")
        for m in mirrors:
            primary = resolve_primary(m["name"])
            if primary and primary != m["ticker"]:
                print(f"  {m['ticker']:10} → {primary:10} ({m['name'][:32]})")
                rules.setdefault(m["ticker"], primary)
            else:
                print(f"  {m['ticker']:10} → KEIN Primärlisting gefunden "
                      f"({m['name'][:32]}) → bleibt für Cleanup-Segregation")
        print()

    rows = con.execute(
        "SELECT rowid, ticker, name, status, mention_count, bullish_count, "
        "bearish_count, conviction_score, conviction_score_bear, channels "
        "FROM watchlist WHERE status IN ('watching','bought') AND ticker IS NOT NULL"
    ).fetchall()

    renamed = merged = 0
    for row in rows:
        src = row["ticker"]
        tgt = rules.get(src)
        if not tgt:
            continue
        existing = con.execute(
            "SELECT rowid, status, conviction_score, conviction_score_bear, "
            "mention_count, bullish_count, bearish_count, channels "
            "FROM watchlist WHERE ticker=? AND status IN ('watching','bought') "
            "AND rowid != ?", (tgt, row["rowid"])
        ).fetchone()
        print(f"  {src:18} → {tgt:8}"
              f"  ({row['name'][:28]})  status={row['status']}")

        if existing:
            merged += 1
            print(f"    ↳ merge mit bestehender {tgt}-Zeile (rowid {existing['rowid']})")
            if not apply:
                continue
            new_conv = max(row["conviction_score"] or 0,
                           existing["conviction_score"] or 0)
            new_bear = max(row["conviction_score_bear"] or 0,
                           existing["conviction_score_bear"] or 0)
            new_mention = (existing["mention_count"] or 0) + (row["mention_count"] or 0)
            new_bull = (existing["bullish_count"] or 0) + (row["bullish_count"] or 0)
            new_bear_c = (existing["bearish_count"] or 0) + (row["bearish_count"] or 0)
            # channels ist eine JSON-Liste (export_watchlist liest json.loads) —
            # NICHT mit Komma joinen, das erzeugt "Extra data"-Crash beim Export.
            import json as _json

            def _chans(v):
                try:
                    if v:
                        return [str(x).strip() for x in _json.loads(v) if str(x).strip()]
                except Exception:
                    pass
                return [c.strip() for c in
                        (v or "").replace("[", " ").replace("]", " ").split(",")
                        if c.strip()]

            chans = _json.dumps(list(dict.fromkeys(
                _chans(existing["channels"]) + _chans(row["channels"]))))
            status = "bought" if (existing["status"] == "bought"
                                  or row["status"] == "bought") else existing["status"]
            con.execute(
                "UPDATE watchlist SET status=?, conviction_score=?, "
                "conviction_score_bear=?, mention_count=?, bullish_count=?, "
                "bearish_count=?, channels=? WHERE rowid=?",
                (status, new_conv, new_bear, new_mention, new_bull, new_bear_c,
                 chans, existing["rowid"]))
            con.execute("DELETE FROM watchlist WHERE rowid=?", (row["rowid"],))
        else:
            renamed += 1
            if apply:
                con.execute(
                    "UPDATE watchlist SET ticker=? WHERE rowid=?", (tgt, row["rowid"]))

        if apply:
            con.execute("UPDATE company_aliases SET ticker=? WHERE ticker=?",
                        (tgt, src))
            tgt_comp = con.execute(
                "SELECT COUNT(*) c FROM companies WHERE ticker=?", (tgt,)).fetchone()[0]
            if tgt_comp == 0:
                src_comp = con.execute(
                    "SELECT * FROM companies WHERE ticker=?", (src,)).fetchone()
                if src_comp:
                    con.execute(
                        "INSERT OR IGNORE INTO companies "
                        "(ticker, canonical_name, quote_type, sector, industry, "
                        "country, currency, isin, status, source, last_validated_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (tgt, src_comp["canonical_name"], src_comp["quote_type"],
                         src_comp["sector"], src_comp["industry"], src_comp["country"],
                         src_comp["currency"], src_comp["isin"], src_comp["status"],
                         src_comp["source"], src_comp["last_validated_at"]))
            con.execute("DELETE FROM companies WHERE ticker=?", (src,))
        con.commit()

    print(f"\n{'✓' if apply else '○'} {renamed} umbenannt, {merged} gemerged "
          f"({tag.upper()})")
    if not apply:
        print("→ mit --apply wirklich schreiben (Backup vorher!):\n"
              "  cp data/trading.db data/trading.db.bak")
    con.close()


if __name__ == "__main__":
    main()