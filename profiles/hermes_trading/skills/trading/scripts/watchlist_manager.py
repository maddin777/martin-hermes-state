"""

Watchlist Manager
- Liest analysierte Signale aus trading_signals.json
- Pflegt Watchlist über 14 Tage (reduziert von 30)
- Berechnet Conviction Score (bullish + bearish)
- Watchlist-Hygiene: Ticker-Drop, Tech-Score-Drop
"""
import sqlite3
import json
import os
import re
import math
import yfinance as yf
import pandas_ta as ta
from datetime import datetime, timedelta

# Validierungs-Pipeline aus Paket B
import sys as _sys
_sys.path.insert(0, '/root/.hermes/profiles/hermes_trading/skills/trading/scripts')
from company_validator import validate_and_register
# DRY: zentrale Funktionen aus Shared-Modulen
from utils import get_technical_score              # war lokale Kopie
from company_normalizer import (                   # war lokale Kopie

    normalize_company_name, NORMALIZE_ALIASES,
    LEGAL_SUFFIX_RE, BRACKET_NOTE_RE
)
from utils import get_logger
log = get_logger("watchlist_manager")
from config import (DB_PATH, SIGNALS_PATH, WATCHLIST_DAYS, MIN_MENTIONS, MIN_CONVICTION,
                    CONVICTION_HALF_LIFE_DAYS, CONVICTION_PRIOR_NEUTRAL)

def get_channel_weights(con):
    """
    Lädt aktive Quellen-Gewichte aus source_registry.
    Fallback: Gewicht 1.0 für unbekannte Kanäle.
    Stellt sicher dass Lifecycle-Anpassungen direkt auf Conviction wirken.
    """
    try:
        rows = con.execute("""
            SELECT display_name, weight
            FROM source_registry
            WHERE status IN ('active', 'probation') AND enabled = 1
        """).fetchall()
        return {r["display_name"]: r["weight"] for r in rows}
    except Exception:
        return {}

def _weighted_sentiment(mentions_list, channel_weights, sentiment):
    """
    Berechnet Anteil eines Sentiments gewichtet nach Channel-Gewichten.
    Wird aktuell nicht direkt aufgerufen, dient als Helfer für zukünftige Nutzung.
    """
    if not channel_weights or not mentions_list:
        return None
    total_weight = sum(channel_weights.get(ch.strip(), 1.0) for ch in mentions_list)
    return total_weight

# === Aged Conviction (Bayesian + Time-Decay) ===
# HALF_LIFE_DAYS und PRIOR_NEUTRAL kommen jetzt aus config.py
HALF_LIFE_DAYS = CONVICTION_HALF_LIFE_DAYS
PRIOR_NEUTRAL  = CONVICTION_PRIOR_NEUTRAL

def calculate_conviction_aged(con, name, channel_weights=None,
                              half_life=HALF_LIFE_DAYS,
                              prior_neutral=PRIOR_NEUTRAL,
                              ref_date=None):
    """
    Conviction-Score mit zeitlichem Decay + Bayesian Prior.
    
    Liest watchlist_mentions(mention_date, channel, sentiment) und berechnet:
      - time_weight   = 0.5 ^ (age_days / half_life)
      - channel_w     = source_registry.weight (fallback 1.0)
      - combined      = time_w * channel_w pro Mention
      - sentiment     = sum_w_bull / (sum_w_bull + sum_w_bear), default 0.5
      - confidence    = directional_w / (sum_w_all + prior_neutral)  ← Bayesian
      - volume        = log(directional_n + 1) / log(11), capped 1.0
      - conviction    = sentiment*0.5 + confidence*0.3 + volume*0.2
    
    Returns float [0,1] oder None bei keinen Daten.
    """
    ref_date = ref_date or datetime.now().date()

    # Sammle alle Mention-Name-Varianten die zum gleichen ticker gehoeren
    # Wir gehen ueber company_aliases -> ticker -> alle aliases -> alle mention-Namen
    cur = con.execute("""
        SELECT a2.alias
        FROM company_aliases a1
        JOIN company_aliases a2 ON a2.ticker = a1.ticker
        WHERE a1.alias = ?
    """, (name.lower().strip(),))
    aliases = [r[0] for r in cur.fetchall()]
    # Auch der original Name als Fallback (falls kein alias-match)
    if name.lower().strip() not in aliases:
        aliases.append(name.lower().strip())

    # Mentions koennen unter beliebiger Schreibweise gespeichert sein
    # -> Match per lower(name) IN (aliases)
    placeholders = ",".join("?" * len(aliases))
    rows = con.execute(
        f"SELECT mention_date, channel, sentiment FROM watchlist_mentions "
        f"WHERE lower(name) IN ({placeholders})",
        aliases
    ).fetchall()
    if not rows:
        return None

    sum_w_bull = sum_w_bear = sum_w_neut = sum_w_all = 0.0
    n_bull = n_bear = 0
    for r in rows:
        try:
            md = datetime.strptime(r["mention_date"], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        age = max(0, (ref_date - md).days)
        tw = 0.5 ** (age / half_life)
        chw = (channel_weights or {}).get(r["channel"], 1.0)
        w = tw * chw
        sum_w_all += w
        s = r["sentiment"]
        if s == "bullish":   sum_w_bull += w; n_bull += 1
        elif s == "bearish": sum_w_bear += w; n_bear += 1
        else:                sum_w_neut += w

    if sum_w_all == 0:
        return None

    directional_w   = sum_w_bull + sum_w_bear
    directional_n   = n_bull + n_bear
    sum_w_all_prior = sum_w_all + prior_neutral
    sentiment_score = sum_w_bull / directional_w if directional_w > 0 else 0.5
    confidence      = directional_w / sum_w_all_prior
    volume          = min(1.0, math.log(directional_n + 1) / math.log(11))
    conviction      = min(1.0, max(0.0,
        sentiment_score * 0.5 + confidence * 0.3 + volume * 0.2
    ))
    return round(conviction, 4)

def calculate_conviction(bullish, bearish, neutral, mention_count, unique_channels,
                         channels_list=None, channel_weights=None,
                         bullish_weighted=None):
    """
    Conviction Score 0-1 für bullish-Signale.
    
    bullish_weighted: Summe der Stärke-gewichteten Bull-Mentions
      (strong=1.0, moderate=0.6, weak=0.3).
      Falls None: einfache Zählung (Rückwärtskompatibilität).
    """
    if mention_count == 0:
        return 0.0

    # Effektive Bullish-Zahl: Stärke-gewichtet wenn vorhanden, sonst Rohzählung
    effective_bullish = bullish_weighted if bullish_weighted is not None else float(bullish)
    # Normierung auf [0, mention_count]-Skala
    effective_total   = (mention_count * 0.6) if bullish_weighted is not None else mention_count

    if channel_weights and channels_list and mention_count > 0:
        weights    = {ch.strip(): channel_weights.get(ch.strip(), 1.0) for ch in channels_list}
        avg_weight = sum(weights.values()) / len(weights) if weights else 1.0
        sentiment_score = (effective_bullish / effective_total) * avg_weight if effective_total > 0 else 0
    else:
        sentiment_score = effective_bullish / effective_total if effective_total > 0 else 0

    mention_weight = math.log(mention_count + 1) / math.log(11)
    channel_bonus  = min(unique_channels / 3, 1.0) * 0.2
    conviction = (sentiment_score * 0.6 + mention_weight * 0.4) * (1 + channel_bonus)
    return min(round(conviction, 3), 1.0)

def calculate_conviction_bear(bullish, bearish, neutral, mention_count, unique_channels,
                               channels_list=None, channel_weights=None,
                               bearish_weighted=None):
    """
    Conviction Score 0-1 für bearish/SHORT-Signale.
    
    bearish_weighted: Summe der Stärke-gewichteten Bear-Mentions.
    Falls None: einfache Zählung (Rückwärtskompatibilität).
    """
    if mention_count == 0:
        return 0.0

    effective_bearish = bearish_weighted if bearish_weighted is not None else float(bearish)
    effective_total   = (mention_count * 0.6) if bearish_weighted is not None else mention_count

    if channel_weights and channels_list and mention_count > 0:
        weights    = {ch.strip(): channel_weights.get(ch.strip(), 1.0) for ch in channels_list}
        avg_weight = sum(weights.values()) / len(weights) if weights else 1.0
        bear_ratio = (effective_bearish / effective_total) * avg_weight if effective_total > 0 else 0
    else:
        bear_ratio = effective_bearish / effective_total if effective_total > 0 else 0

    mention_weight = math.log(mention_count + 1) / math.log(11)
    channel_bonus  = min(unique_channels / 3, 1.0) * 0.2
    conviction = (bear_ratio * 0.6 + mention_weight * 0.4) * (1 + channel_bonus)
    return min(round(conviction, 3), 1.0)

# get_technical_score() ist nach utils.py ausgelagert (DRY).
# Import steht im Dateikopf: from utils import get_technical_score

# Normalisierungslogik ist nach company_normalizer.py ausgelagert (DRY).
# Import steht im Dateikopf: from company_normalizer import ...


def get_thesis_conviction_boost(con, ticker):
    """
    Gibt einen Conviction-Boost zurück wenn der Ticker:
      1. In theme_beneficiaries eingetragen ist (status != 'archived')
      2. Das Theme aktiv ist (theme_definitions.status = 'active')
      3. Der letzte Thesis-Check 'intact' war (oder kein Check vorhanden)

    Boost-Staffelung:
      +0.08  bei intact + hohem Theme-Momentum (bullish)
      +0.05  bei intact (Standard)
      +0.02  bei kein Check vorhanden (aber Beneficiary-Eintrag existiert)
       0.00  bei broken / degraded / archived
    """
    if not ticker:
        return 0.0
    try:
        row = con.execute("""
            SELECT tb.id, tb.status as bene_status,
                   td.status as theme_status, td.momentum
            FROM theme_beneficiaries tb
            JOIN theme_definitions td ON td.id = tb.theme_id
            WHERE tb.ticker = ?
              AND tb.status != 'archived'
              AND td.status = 'active'
            ORDER BY td.momentum DESC
            LIMIT 1
        """, (ticker,)).fetchone()

        if not row:
            return 0.0

        # Letzten Thesis-Status prüfen
        latest = con.execute("""
            SELECT status FROM thesis_status_log
            WHERE beneficiary_id = ?
            ORDER BY id DESC LIMIT 1
        """, (row["id"],)).fetchone()

        thesis_status = latest["status"] if latest else "no_check"

        if thesis_status == "broken" or thesis_status == "degraded":
            return 0.0
        elif thesis_status == "intact":
            # Extra-Boost bei bullishem Theme-Momentum
            if row["momentum"] == "bullish":
                return 0.08
            return 0.05
        else:  # no_check oder no_thesis
            return 0.02
    except Exception:
        return 0.0


def normalize_mentions(con):
    """Dedupliziert watchlist_mentions.name via normalize_company_name().

    Findet Duplikate wie 'Meta'/'Meta Platforms'/'Meta Platforms Inc.',
    merged sie auf den kürzesten/gebräuchlichsten Namen durch UPDATE.
    """
    import re as _re  # shadow import für re innerhalb der Funktion

    rows = con.execute(
        "SELECT DISTINCT name FROM watchlist_mentions ORDER BY name"
    ).fetchall()
    names = [r["name"] for r in rows]
    print(f"  🔍 Normalisiere {len(names)} unique Namen...", flush=True)

    # Gruppiere nach normalisiertem Namen
    groups = {}  # normalized -> [original_names]
    for n in names:
        norm = normalize_company_name(n)
        groups.setdefault(norm, []).append(n)

    # Merge: canonical = kürzester Name pro Gruppe
    merged = 0
    for norm, originals in groups.items():
        if len(originals) <= 1:
            continue
        # Canonical: bevorzuge Namen der dem norm-Wortlaut exakt entspricht,
        # sonst kürzesten. Vermeide Legal-Suffixe (Inc., Corp., AG, SE etc.)
        canon_candidates = [n for n in originals if n.lower() == norm.lower()]
        if canon_candidates:
            canonical = canon_candidates[0]
        else:
            canonical = min(originals, key=len)

        # Duplikat-Reihenfolge: zuerst alle alte Namen löschen die mit
        # canonical im selben video_id konfliktieren, DANN updaten
        for orig in originals:
            if orig == canonical:
                continue
            # Schritt 1: Konflikte vor dem UPDATE bereinigen
            con.execute(
                "DELETE FROM watchlist_mentions WHERE name=? AND "
                "EXISTS (SELECT 1 FROM watchlist_mentions AS w2 "
                "WHERE w2.name=? AND w2.video_id=watchlist_mentions.video_id)",
                (orig, canonical)
            )
            # Schritt 2: Bulk-UPDATE der restlichen
            updated = con.execute(
                "UPDATE watchlist_mentions SET name=? WHERE name=?",
                (canonical, orig)
            ).rowcount
            merged += updated

        print(f"  🔗 {len(originals)} → '{canonical}'  "
              f"(zusammengeführt: {', '.join(originals)})", flush=True)

    con.commit()
    if merged:
        print(f"  ✓ {merged} Mentions auf kanonische Namen aktualisiert", flush=True)
    else:
        print(f"  ✓ Keine Duplikate gefunden", flush=True)
    return merged

def main():
    print("📋 Watchlist Manager gestartet", flush=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA busy_timeout=30000;")  # 30s statt 5s
    con.row_factory = sqlite3.Row

    # Migration: conviction_score_bear Spalte hinzufügen
    cols = [row[1] for row in con.execute("PRAGMA table_info(watchlist)")]
    if "conviction_score_bear" not in cols:
        con.execute("ALTER TABLE watchlist ADD COLUMN conviction_score_bear REAL DEFAULT 0")

    # Migration: bestehende channel-Namen in watchlist_mentions normalisieren (einmalig)
    # Behebt den "der aktionaer" vs "der Aktionaer" Source-Case-Bug
    dirty = con.execute("""
        SELECT DISTINCT channel FROM watchlist_mentions
        WHERE channel != lower(trim(channel))
    """).fetchall()
    if dirty:
        print(f"  🔧 Normalisiere {len(dirty)} Kanal-Namen in watchlist_mentions...", flush=True)
        for row in dirty:
            old = row["channel"]
            new = old.lower().strip()
            con.execute("UPDATE watchlist_mentions SET channel=? WHERE channel=?", (new, old))
        con.commit()
        print(f"  ✓ Kanal-Namen normalisiert", flush=True)

    # Quellen-Gewichte aus source_registry laden (Lifecycle-Integration)
    channel_weights = get_channel_weights(con)
    if channel_weights:
        print(f"  ⚖️  {len(channel_weights)} Quellen-Gewichte aus source_registry geladen", flush=True)
    else:
        print("  ⚖️  source_registry leer – Standardgewichte (1.0) verwendet", flush=True)

    # 1. Alte Einträge bereinigen (> 14 Tage ohne Mention)
    cutoff = (datetime.now() - timedelta(days=WATCHLIST_DAYS)).strftime("%Y-%m-%d")
    dropped = con.execute("""
        UPDATE watchlist SET status='dropped'
        WHERE last_seen < ? AND status='watching'
    """, (cutoff,)).rowcount
    con.commit()
    if dropped:
        print(f"  🗑 {dropped} Einträge als 'dropped' markiert (>14 Tage)", flush=True)

    # 2. Einträge ohne Ticker nach 7 Tagen droppen
    cutoff_7d = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    dropped_no_ticker = con.execute("""
        UPDATE watchlist SET status='dropped'
        WHERE ticker IS NULL
        AND first_seen < ?
        AND status='watching'
    """, (cutoff_7d,)).rowcount
    con.commit()
    if dropped_no_ticker:
        print(f"  🗑 {dropped_no_ticker} Einträge ohne Ticker nach 7 Tagen gedropt", flush=True)

    # 3. Einträge mit tech_score < 0.3 nach 3 Tagen ohne neue Mention droppen
    cutoff_3d = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    dropped_low_tech = con.execute("""
        UPDATE watchlist SET status='dropped'
        WHERE tech_score < 0.30
        AND last_seen < ?
        AND status='watching'
    """, (cutoff_3d,)).rowcount
    con.commit()
    if dropped_low_tech:
        print(f"  🗑 {dropped_low_tech} Einträge mit Tech-Score < 0.3 gedropt", flush=True)

    # 4. Neue Mentions aus trading_signals.json einlesen
    if not os.path.exists(SIGNALS_PATH):
        print("  ⚠ Keine signals.json gefunden", flush=True)
        con.close()
        return

    with open(SIGNALS_PATH, encoding="utf-8") as f:
        signals = json.load(f)

    new_mentions = 0
    for signal in signals:
        source  = signal.get("source", {})
        channel = source.get("channel", "").lower().strip()  # Normalisierung: "der Aktionaer" == "der aktionaer"
        video_id= source.get("video_id", "")
        title   = source.get("title", "")
        date    = source.get("date", datetime.now().strftime("%Y%m%d"))

        try:
            mention_date = datetime.strptime(str(date), "%Y%m%d").strftime("%Y-%m-%d")
        except:
            mention_date = datetime.now().strftime("%Y-%m-%d")

        for company in signal.get("companies", []):
            name      = company.get("name", "").strip()
            sentiment = company.get("sentiment", "neutral")
            strength  = company.get("strength", "moderate")
            reason    = company.get("reason", "")

            if not name or len(name) < 2:
                continue

            try:
                con.execute("""
                    INSERT OR IGNORE INTO watchlist_mentions
                    (name, channel, video_id, video_title, sentiment, strength, reason, mention_date)
                    VALUES (?,?,?,?,?,?,?,?)
                """, (name, channel, video_id, title, sentiment,
                        company.get("strength", "moderate"), reason, mention_date))
                if con.execute("SELECT changes()").fetchone()[0] > 0:
                    new_mentions += 1
            except Exception as e:
                pass

    con.commit()
    print(f"  ✓ {new_mentions} neue Mentions gespeichert", flush=True)

    # 4b. Mention-Deduplizierung (vor Aggregation)
    normalize_mentions(con)

    # 5. Watchlist aggregieren
    mentions = con.execute("""
        SELECT name,
               COUNT(*) as mention_count,
               SUM(CASE WHEN sentiment='bullish' THEN 1 ELSE 0 END) as bullish,
               SUM(CASE WHEN sentiment='bearish' THEN 1 ELSE 0 END) as bearish,
               SUM(CASE WHEN sentiment='neutral' THEN 1 ELSE 0 END) as neutral,
               -- Gewichtete Counts: strong=1.0, moderate=0.6, weak=0.3
               SUM(CASE WHEN sentiment='bullish' THEN
                   CASE COALESCE(strength,'moderate')
                     WHEN 'strong'   THEN 1.0
                     WHEN 'moderate' THEN 0.6
                     WHEN 'weak'     THEN 0.3
                     ELSE 0.6 END
                   ELSE 0 END) as bullish_weighted,
               SUM(CASE WHEN sentiment='bearish' THEN
                   CASE COALESCE(strength,'moderate')
                     WHEN 'strong'   THEN 1.0
                     WHEN 'moderate' THEN 0.6
                     WHEN 'weak'     THEN 0.3
                     ELSE 0.6 END
                   ELSE 0 END) as bearish_weighted,
               COUNT(DISTINCT channel) as unique_channels,
               GROUP_CONCAT(DISTINCT channel) as channels,
               MIN(mention_date) as first_seen,
               MAX(mention_date) as last_seen
        FROM watchlist_mentions
        WHERE mention_date >= ?
        GROUP BY name
        ORDER BY mention_count DESC
    """, (cutoff,)).fetchall()

    print(f"  → {len(mentions)} Unternehmen in Watchlist", flush=True)

    for m in mentions:
        name       = m["name"]
        channels_list = m["channels"].split(",") if m["channels"] else []
        conviction = calculate_conviction(
            m["bullish"], m["bearish"], m["neutral"],
            m["mention_count"], m["unique_channels"],
            channels_list=channels_list, channel_weights=channel_weights,
            bullish_weighted=m["bullish_weighted"],
        )
        conviction_bear = calculate_conviction_bear(
            m["bullish"], m["bearish"], m["neutral"],
            m["mention_count"], m["unique_channels"],
            channels_list=channels_list, channel_weights=channel_weights,
            bearish_weighted=m["bearish_weighted"],
        )

        # --- Validierungs-Pipeline (Paket B): Cache-Hit, neue Firma anlegen, oder skippen ---
        result = validate_and_register(name)
        if result["status"] == "rejected":
            # Krypto, Indizes, abgeschnittene Namen, Mehrdeutigkeiten -> skip
            continue
        ticker = result["ticker"]
        if not ticker:
            # status='private' (OpenAI, SpaceX, ...) -> kein Trade moeglich
            continue

        # Sektor aus companies-Tabelle (single source of truth)
        sector_row = con.execute(
            "SELECT canonical_name, sector FROM companies WHERE ticker=?", (ticker,)
        ).fetchone()
        canonical_name = sector_row["canonical_name"] if sector_row else name
        sector         = (sector_row["sector"] if sector_row else None) or "Other"

        # Aged Conviction (Bayesian + Time-Decay) zusaetzlich berechnen
        conviction_aged = calculate_conviction_aged(con, name, channel_weights)
        if conviction_aged is None:
            conviction_aged = 0

        # Thesis-Boost: Wenn Ticker in aktiver positiver Thesis eingetragen ist
        thesis_boost = get_thesis_conviction_boost(con, ticker)
        if thesis_boost > 0:
            conviction = min(1.0, conviction + thesis_boost)
            print(f"    📋 Thesis-Boost +{thesis_boost:.0%} → conviction={conviction:.2f}", flush=True)

        # Grok X-Boost: Nur für High-Conviction-Kandidaten (≥70%) um API-Calls zu sparen
        if conviction >= 0.70 and ticker:
            try:
                from xsearch_helper import conviction_boost as x_conviction_boost
                new_conv, reason = x_conviction_boost(ticker, canonical_name, conviction)
                if new_conv != conviction:
                    conviction = new_conv
                    print(f"    🐦 Grok: {reason} → conviction={conviction:.2f}", flush=True)
            except Exception:
                pass  # Grok-Fehler stoppen die Pipeline nicht

        # INSERT: bei Ticker-Konflikt nichts tun, UPDATE-Pfad weiter unten kuemmert sich
        con.execute("""
            INSERT INTO watchlist (name, ticker, first_seen, last_seen,
                mention_count, bullish_count, bearish_count, neutral_count,
                conviction_score, conviction_score_bear, conviction_score_aged,
                channels, status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(ticker) DO NOTHING
        """, (canonical_name, ticker, m["first_seen"], m["last_seen"],
              m["mention_count"], m["bullish"], m["bearish"], m["neutral"],
              conviction, conviction_bear, conviction_aged,
              json.dumps(channels_list), "watching"))

        # UPDATE: existierenden Eintrag aktualisieren (auch dropped -> watching reaktivieren)
        con.execute("""
            UPDATE watchlist SET
                name=?, last_seen=?, mention_count=?,
                bullish_count=?, bearish_count=?, neutral_count=?,
                conviction_score=?, conviction_score_bear=?,
                conviction_score_aged=?, channels=?, status='watching'
            WHERE ticker=? AND status IN ('watching', 'dropped')
        """, (canonical_name, m["last_seen"], m["mention_count"],
              m["bullish"], m["bearish"], m["neutral"],
              conviction, conviction_bear, conviction_aged,
              json.dumps(channels_list), ticker))
    con.commit()

    # 6. Technische Scores für Top-Kandidaten aktualisieren
    top_candidates = con.execute("""
        SELECT * FROM watchlist
        WHERE status='watching'
        AND conviction_score >= ?
        AND mention_count >= ?
        AND ticker IS NOT NULL
        ORDER BY conviction_score DESC
        LIMIT 20
    """, (MIN_CONVICTION * 0.5, 1)).fetchall()

    print(f"\n  Technische Analyse für {len(top_candidates)} Kandidaten...", flush=True)
    for c in top_candidates:
        tech = get_technical_score(c["ticker"])  # gibt Dict zurück (utils.py)
        if tech:
            tech_score = tech["confidence"]
            direction  = tech["direction"]
            con.execute("""
                UPDATE watchlist SET tech_score=?, tech_direction=?
                WHERE name=?
            """, (tech_score, direction, c["name"]))
            print(f"  {c['name']:25} {c['ticker']:10} "
                  f"Conv:{c['conviction_score']:.2f} "
                  f"Tech:{tech_score} {direction}", flush=True)

    con.commit()

    # 7. Top Kandidaten ausgeben
    top = con.execute("""
        SELECT * FROM watchlist
        WHERE status='watching'
        ORDER BY conviction_score DESC
        LIMIT 10
    """).fetchall()

    print("\n📋 TOP WATCHLIST:")
    print(f"{'Name':25} {'Ticker':10} {'Mentions':8} {'Bull/Bear':10} {'Conv':6} {'Bear':6} {'Tech':6} {'Richtung'}")
    print("-" * 90)
    for w in top:
        channels = json.loads(w["channels"]) if w["channels"] else []
        print(f"  {w['name']:25} {(w['ticker'] or '?'):10} "
              f"{'':12} "  # sector jetzt per JOIN aus companies
              f"{w['mention_count']:4}x  "
              f"{w['bullish_count']}↑/{w['bearish_count']}↓  "
              f"Conv:{w['conviction_score']:.2f}  "
              f"Bear:{w['conviction_score_bear']:.2f}  "
              f"Tech:{w['tech_score'] or '–'}  "
              f"{w['tech_direction'] or '-'}")

    # 8. '?' Flagging: Unresolved Ticker reportieren
    unresolved = con.execute("""
        SELECT name, mention_count, conviction_score
        FROM watchlist
        WHERE status='watching' AND ticker IS NULL
        ORDER BY mention_count DESC
    """).fetchall()

    if unresolved:
        print(f"\n❓ UNRESOLVED TICKER ({len(unresolved)} Eintrage ohne Ticker):")
        print(f"  {'Name':30} {'Mentions':8} {'Conv':6}")
        print("  " + "-" * 48)
        for u in unresolved[:15]:  # Top 15
            print(f"  {u['name']:30} {u['mention_count']:4}x  "
                  f"Conv:{u['conviction_score']:.2f}")
        if len(unresolved) > 15:
            print(f"  ... und {len(unresolved) - 15} weitere (insg. {len(unresolved)})")
        print()

    con.close()
    print("\n✅ Watchlist Manager abgeschlossen", flush=True)

if __name__ == "__main__":
    main()
