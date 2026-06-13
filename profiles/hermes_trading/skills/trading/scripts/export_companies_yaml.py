#!/usr/bin/env python3
"""
export_companies_yaml.py – Exportiert companies + aliases als YAML für git.
"""
import sqlite3, os, sys
sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")
import env_loader  # noqa
from config import DB_PATH, SCRIPTS_DIR, db_connect

OUTPUT_PATH = os.path.join(SCRIPTS_DIR, "companies.yaml")

def _yaml_val(val):
    if val is None:
        return "null"
    s = str(val)
    if not s:
        return "null"
    special = [':', '#', '&', '*', '?', '|', '<', '>', '=', '!', '"', "'", '{', '}', '[', ']', ',', '\n']
    if any(c in s for c in special):
        return "'" + s.replace("'", "\\'") + "'"
    return s

def main():
    con = db_connect()
    companies = con.execute("""
        SELECT ticker, canonical_name, sector, industry, country,
               currency, isin, status, source, notes
        FROM companies WHERE status != 'delisted'
        ORDER BY canonical_name COLLATE NOCASE
    """).fetchall()
    aliases_map = {}
    for row in con.execute("SELECT ticker, alias FROM company_aliases ORDER BY alias"):
        aliases_map.setdefault(row["ticker"], []).append(row["alias"])
    con.close()

    lines = [
        "# Hermes Trading – Company Knowledge Base",
        "# Automatisch generiert von export_companies_yaml.py",
        f"# Einträge: {len(companies)}",
        "",
        "companies:",
    ]
    for c in companies:
        ticker = c["ticker"]
        al = aliases_map.get(ticker, [])
        lines.append(f"  - ticker:         {_yaml_val(ticker)}")
        lines.append(f"    canonical_name:  {_yaml_val(c['canonical_name'])}")
        lines.append(f"    sector:          {_yaml_val(c['sector'])}")
        lines.append(f"    industry:        {_yaml_val(c['industry'])}")
        lines.append(f"    country:         {_yaml_val(c['country'])}")
        lines.append(f"    isin:            {_yaml_val(c['isin'])}")
        lines.append(f"    status:          {_yaml_val(c['status'])}")
        lines.append(f"    source:          {_yaml_val(c['source'])}")
        if c["notes"]:
            lines.append(f"    notes:           {_yaml_val(c['notes'])}")
        if al:
            alias_str = "[" + ", ".join('"' + a + '"' for a in al[:10]) + "]"
            lines.append(f"    aliases:         {alias_str}")
        lines.append("")

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"OK {len(companies)} Firmen → {OUTPUT_PATH}")

if __name__ == "__main__":
    main()
