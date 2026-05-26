"""
News Cleanup — Woechentlicher Job: Loescht Volltexte nach 30 Tagen TTL.
Laeuft Sonntag 04:00.
"""
import os
import sqlite3
from datetime import date, timedelta

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
    cutoff = (date.today() - timedelta(days=30)).isoformat()

    # Volltext-NULL setzen
    result = con.execute("""
        UPDATE news_references
        SET content_snippet = NULL
        WHERE fetched_at < ? AND content_snippet IS NOT NULL
    """, (cutoff,))

    cleaned = result.rowcount
    con.commit()

    # Duplikate bereinigen (gleicher content_hash, behalte aeltesten)
    dupes = con.execute("""
        DELETE FROM news_references
        WHERE id NOT IN (
            SELECT MIN(id) FROM news_references
            WHERE content_hash IS NOT NULL
            GROUP BY content_hash
        )
        AND content_hash IS NOT NULL
    """)

    dupes_removed = dupes.rowcount
    con.commit()
    con.close()

    print(
        f"[News Cleanup] {cleaned} Volltexte geloescht, "
        f"{dupes_removed} Duplikate entfernt",
        flush=True,
    )


if __name__ == "__main__":
    main()