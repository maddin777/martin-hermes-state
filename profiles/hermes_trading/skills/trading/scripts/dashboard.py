"""Trading Dashboard v4.1 - Mit Thematic Investing Interface"""
import sqlite3, json, os, subprocess, html, re, sys
from collections import deque
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from datetime import datetime
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DB_PATH, SCRIPTS_DIR, CRON_LOG_PATH, SOURCES_CONFIG_PATH, STRATEGY_CONFIG_PATH, THEMATIC_LOG_PATH, db_connect

# Aliase für dashboard.py (abweichende Namen im Skript)
CONFIG_PATH = STRATEGY_CONFIG_PATH
SOURCES_PATH = SOURCES_CONFIG_PATH
LOG_PATH = CRON_LOG_PATH

# Pfad fuer thematic-Import
THEMATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "thematic")
if THEMATIC_DIR not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

YT_MONITOR = os.path.join(SCRIPTS_DIR, "yt_channel_monitor.py")

# ─── Config ──────────────────────────────────────────────────────────────────

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {"starting_capital":10000,"total_trades":0,"winning_trades":0,
            "atr_sl_multiplier":1.5,"atr_tp_multiplier":3.0,"min_confidence":0.65,
            "max_positions":8}

def load_sources():
    if os.path.exists(SOURCES_PATH):
        with open(SOURCES_PATH) as f:
            return json.load(f)
    return {"rss_feeds": [], "twitter_accounts": [], "fred_indicators": []}

def save_sources(sources):
    with open(SOURCES_PATH, "w", encoding="utf-8") as f:
        json.dump(sources, f, indent=2, ensure_ascii=False)

def get_yt_channels():
    """Liest YouTube-Kanäle aus source_registry (DB), Fallback statische Liste.

    #1 Sicherheitsfix: früher wurde der Python-Quelltext von yt_channel_monitor.py
    geparst/beschrieben – das war ein Code-Injection-Vektor. Kanäle leben jetzt in
    der DB (source_registry), exakt wie RSS/Twitter.
    """
    channels = []
    try:
        con = db_connect()
        rows = con.execute("""
            SELECT display_name AS name, source_key AS url, enabled
            FROM source_registry
            WHERE source_type='youtube' AND status != 'removed'
            ORDER BY display_name
        """).fetchall()
        con.close()
        for r in rows:
            channels.append({"name": r["name"], "url": r["url"],
                             "enabled": bool(r["enabled"])})
        if channels:
            return channels
    except Exception:
        pass
    # Fallback: statische Liste aus dem Monitor (nur Lesen, kein Schreiben!)
    if os.path.exists(YT_MONITOR):
        try:
            with open(YT_MONITOR) as f:
                content = f.read()
            match = re.search(r'CHANNELS_FALLBACK\s*=\s*\[(.*?)\]', content, re.DOTALL)
            if match:
                for name, url in re.findall(r'\("([^"]+)",\s*"([^"]+)"\)', match.group(1)):
                    channels.append({"name": name, "url": url, "enabled": True})
        except Exception:
            pass
    return channels


# #1: Strenge Eingabe-Validierung. Namen/URLs landen NICHT mehr in Code,
# aber wir halten sie trotzdem sauber (kein Anführungszeichen/Steuerzeichen-Müll).
_YT_NAME_RE = re.compile(r'^[\w .,&()\-/+äöüÄÖÜß]{2,80}$')
_YT_URL_RE  = re.compile(
    r'^https://(www\.)?(youtube\.com/(channel/|@|c/|user/)[\w\-./]+|youtu\.be/[\w\-]+)$'
)


def _valid_yt_input(name: str, url: str) -> bool:
    return bool(name and url and _YT_NAME_RE.match(name) and _YT_URL_RE.match(url))


def add_yt_channel(name, url):
    """Fügt einen YouTube-Kanal in source_registry ein (DB statt Quellcode)."""
    if not _valid_yt_input(name, url):
        print(f"Ungültige YT-Eingabe abgelehnt: name={name!r} url={url!r}")
        return False
    try:
        con = db_connect()
        con.execute("""
            INSERT INTO source_registry
                (source_type, source_key, display_name, language, region,
                 category, status, weight, enabled, added_by, discovery_reason)
            VALUES ('youtube', ?, ?, 'de', 'DE', 'finance',
                    'active', 1.0, 1, 'dashboard', 'manuell im Dashboard hinzugefügt')
            ON CONFLICT(source_key) DO UPDATE SET
                status='active', enabled=1, display_name=excluded.display_name
        """, (url, name))
        con.commit()
        con.close()
        return True
    except Exception as e:
        print(f"Fehler beim Hinzufügen (DB): {e}")
        return False


def remove_yt_channel(name):
    """Deaktiviert einen YouTube-Kanal in source_registry (soft-remove)."""
    if not name:
        return False
    try:
        con = db_connect()
        cur = con.execute("""
            UPDATE source_registry SET status='removed', enabled=0
            WHERE source_type='youtube' AND display_name=?
        """, (name,))
        con.commit()
        changed = cur.rowcount
        con.close()
        return changed > 0
    except Exception:
        return False


# ─── Cron ────────────────────────────────────────────────────────────────────

def get_last_run(script_name):
    # Aliases für Pipeline-Schritte die anders geloggt werden
    LOG_ALIASES = {
        "watchlist_manager": "Watchlist Update",
        "signal_extractor": "KI Analyse",
    }
    search_name = LOG_ALIASES.get(script_name, script_name)
    
    last_done_ts = None
    last_start_ts = None
    last_status = "–"
    try:
        if not os.path.exists(LOG_PATH): return None, "kein Log"
        with open(LOG_PATH, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        for line in lines:
            line = line.strip()
            if search_name not in line: continue
            m = re.search(r"===\s+(.+?)\s+===", line)
            ts = m.group(1).strip() if m else None
            if "DONE" in line and ts:
                last_done_ts = ts; last_status = "OK"
            elif "START" in line and ts:
                last_start_ts = ts
            elif "---" in line and ts:
                last_done_ts = ts; last_status = "OK"
        if last_start_ts and not last_done_ts:
            return last_start_ts, "Fehler"
        return last_done_ts, last_status
    except Exception:
        return None, "Fehler"

def get_cron_jobs():
    descriptions = {
        "trading_pipeline":    "YouTube → Analyse → Watchlist → Signale",
        "yt_channel_monitor":  "YouTube Kanäle scannen (11 Kanäle)",
        "signal_extractor":    "KI-Analyse Transkripte (Gemini)",
        # watchlist_manager läuft embedded in trading_pipeline
        # technical_validator läuft embedded in trading_pipeline
        "signal_manager":      "Signale + Portfolio Management",
        "strategy_optimizer":  "Selbstverbesserung Grid Search (Sonntag)",
        "fundamental_data":    "FRED Makro + SEC Insider + PCR",
        "social_scanner":      "RSS Feeds + Twitter/X (24h)",
        "active_exit_check":   "Tech-Check + Profit-Sicherung",
        "db_backup":           "Datenbank Backup Obsidian",
        "nightly_eval":        "Tages-Metriken + Qualitäts-Report",
        "nightly_eval_weekly": "Wochenauswertung für Optimizer",
    }
    group_map = {
        "02": "🌙 Nacht", "03": "🌙 Nacht", "04": "🌙 Nacht", "05": "🌙 Nacht",
        "09": "📈 Börsenzeit", "10": "📈 Börsenzeit",
        "13": "📈 Börsenzeit", "14": "📈 Börsenzeit", "15": "📈 Börsenzeit",
        "16": "📈 Börsenzeit", "17": "📈 Börsenzeit", "18": "📈 Börsenzeit",
        "19": "📈 Börsenzeit", "20": "📈 Börsenzeit",
        "22": "🗄 System",
        "10_sunday": "📅 Wöchentlich",
    }
    try:
        output = subprocess.run(["crontab","-l"], capture_output=True, text=True).stdout
        jobs = []
        for line in output.splitlines():
            line = line.strip()
            if not line or line.startswith("#"): continue
            if not any(k in line for k in ["yt_channel","signal_",
                "strategy_optimizer","trading_db","fundamental_data",
                "social_scanner","active_exit_check","trading_pipe","nightly_eval"]): continue
            parts = line.split()
            if len(parts) < 6: continue
            minute, hour, dow = parts[0], parts[1], parts[4]
            script_path = next((p for p in parts if ".py" in p), "")
            if script_path:
                script_name = script_path.split("/")[-1].replace(".py","")
            elif "cp " in line and "trading.db" in line:
                script_name = "db_backup"
            else:
                script_name = ""
            desc = descriptions.get(script_name, script_name)
            dow_str = "Mo-Fr" if dow == "1-5" else dow
            time_display = f"{hour.zfill(2)}:{minute.zfill(2)}" if minute.isdigit() and hour.isdigit() else f"{hour}:{minute}"
            sort_time = f"{hour.zfill(2)}:{minute.zfill(2)}" if hour.isdigit() else "99:99"
            if "check_only" in line:
                time_display = f"{hour}:00 (h)"; desc = "SL/TP prüfen"
            mode = " [full]" if "full" in parts else " [check]" if "check_only" in parts else ""
            last_ts, last_status = get_last_run(script_name)
            hour_key = hour.zfill(2) if hour.isdigit() else "00"
            # Sonntag (dow=0) → Wöchentlich
            if dow == "0":
                group = "📅 Wöchentlich"
            # Freitag 20:00 → Börsenzeit
            elif dow == "5":
                group = "📈 Börsenzeit"
            # Stündlicher check (hour range wie 13-20)
            elif "-" in hour:
                group = "📈 Börsenzeit"
            else:
                group = group_map.get(hour_key, "⏰ Sonstige")
            jobs.append({"time": time_display, "sort_key": sort_time, "days": dow_str,
                        "script": script_name+mode, "desc": desc,
                        "last_run": last_ts or "–", "last_status": last_status,
                        "group": group})
        # Sortierung: erst nach Gruppe dann nach Zeit
        group_order = {"🌙 Nacht": 0, "📈 Börsenzeit": 1,
                       "📅 Wöchentlich": 2, "🗄 System": 3, "⏰ Sonstige": 4}
        jobs.sort(key=lambda x: (group_order.get(x.get("group","⏰ Sonstige"), 4), x["sort_key"]))
        return jobs
    except Exception:
        return []

def get_log_lines():
    try:
        lines = deque(maxlen=50)
        with open(LOG_PATH, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip(): lines.append(line.rstrip('\n'))
        return list(lines)
    except Exception: return ["Log nicht verfügbar"]

def get_thematic_log_lines():
    try:
        lines = deque(maxlen=100)
        with open(THEMATIC_LOG_PATH, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip(): lines.append(line.rstrip('\n'))
        return list(lines)
    except Exception: return ["Thematic Log nicht verfügbar — noch kein Run heute"]

# ─── Data ────────────────────────────────────────────────────────────────────

def get_data():
    con = db_connect()
    cfg = load_config()
    portfolio = con.execute("SELECT * FROM portfolio WHERE id=1").fetchone()
    open_pos  = con.execute("SELECT * FROM positions WHERE status='open' ORDER BY entry_date DESC").fetchall()
    closed    = con.execute("SELECT * FROM positions WHERE status='closed' ORDER BY exit_date DESC LIMIT 20").fetchall()
    total_pnl = sum(p["pnl_eur"] or 0 for p in con.execute("SELECT pnl_eur FROM positions WHERE status='closed'").fetchall())
    win_rate  = (cfg["winning_trades"]/cfg["total_trades"]*100 if cfg["total_trades"]>0 else 0)
    cash      = portfolio["cash"] if portfolio else cfg["starting_capital"]
    open_val  = sum(p["position_size"] or 0 for p in con.execute("SELECT position_size FROM positions WHERE status='open'").fetchall())
    open_pnl  = sum(p["pnl_eur"] or 0 for p in con.execute("SELECT pnl_eur FROM positions WHERE status='open'").fetchall())
    total_value  = cash + open_val + open_pnl
    total_return = (total_value - cfg["starting_capital"]) / cfg["starting_capital"] * 100
    try:
       watchlist = [dict(w) for w in con.execute("""
            SELECT w.*, c.canonical_name AS company_name, c.sector AS company_sector
            FROM watchlist w
            LEFT JOIN companies c ON c.ticker = w.ticker
            ORDER BY w.conviction_score DESC
        """).fetchall()]
    except Exception: watchlist = []

    # Watchlist Mentions pro Kanal (für Sources-Seite)
    try:
        channel_stats = {}
        rows = con.execute("""
            SELECT channel, COUNT(*) as cnt, MAX(mention_date) as last_date
            FROM watchlist_mentions
            WHERE mention_date >= date('now', '-30 days')
            GROUP BY channel
        """).fetchall()
        for r in rows:
            channel_stats[r["channel"]] = {"count": r["cnt"], "last": r["last_date"]}
    except Exception: channel_stats = {}

    # Benchmark-Daten (Phase 5)
    try:
        benchmark_rows = [dict(r) for r in con.execute("""
            SELECT * FROM benchmark ORDER BY date DESC LIMIT 90
        """).fetchall()]
        benchmark_latest = benchmark_rows[0] if benchmark_rows else {}
    except Exception:
        benchmark_rows = []
        benchmark_latest = {}

    # Equity-Kurve: tägliche Portfolio-Werte aus eval_metrics + benchmark
    try:
        equity_rows = [dict(r) for r in con.execute("""
            SELECT em.date, b.portfolio_value, b.spy_return_ytd, b.dax_return_ytd,
                   b.portfolio_return_ytd, b.alpha_spy, b.alpha_dax
            FROM benchmark b
            LEFT JOIN eval_metrics em ON em.date = b.date
            ORDER BY b.date ASC
            LIMIT 180
        """).fetchall()]
    except Exception:
        equity_rows = []

    # Qualitäts-Metriken (vor con.close())
    try:
        eval_rows = [dict(r) for r in con.execute("""
            SELECT * FROM eval_metrics
            ORDER BY date DESC LIMIT 7
        """).fetchall()]
    except Exception: eval_rows = []

    try:
        source_rows = [dict(r) for r in con.execute("""
            SELECT * FROM source_quality
            WHERE date = (SELECT MAX(date) FROM source_quality)
            ORDER BY quality_score DESC
        """).fetchall()]
    except Exception: source_rows = []

    try:
        regime_row = dict(con.execute("""
            SELECT * FROM regime_history ORDER BY date DESC LIMIT 1
        """).fetchone() or {})
    except Exception: regime_row = {}

    con.close()

    return {
        "eval_metrics": eval_rows, "source_quality": source_rows,
        "regime": regime_row,
        "watchlist": watchlist, "open_pos": [dict(p) for p in open_pos],
        "closed": [dict(p) for p in closed], "cfg": cfg,
        "cron_jobs": get_cron_jobs(), "log_lines": get_log_lines(), "thematic_log_lines": get_thematic_log_lines(),
        "sources": load_sources(), "yt_channels": get_yt_channels(),
        "channel_stats": channel_stats,
        "benchmark": benchmark_latest,
        "benchmark_history": benchmark_rows,
        "equity_curve": equity_rows,
        "stats": {
            "total_pnl": round(total_pnl,2), "win_rate": round(win_rate,1),
            "total_trades": cfg["total_trades"], "total_return": round(total_return,2),
            "total_value": round(total_value,2), "cash": round(cash,2),
            "start_cap": cfg["starting_capital"]
        }
    }

# ─── HTML ────────────────────────────────────────────────────────────────────

def build_sources_section(data):
    sources = data["sources"]
    yt_channels = data["yt_channels"]
    stats = data["channel_stats"]

    # YouTube Kanäle
    yt_rows = ""
    # Case-insensitive Channel-Match (DB speichert z.B. "urban jäkle", CHANNELS_FALLBACK hat "Urban Jäkle")
    stats_ci = {k.lower(): v for k, v in stats.items()}
    for ch in yt_channels:
        name = ch["name"]
        url  = ch["url"]
        s    = stats_ci.get(name.lower(), {})
        count = s.get("count", 0)
        last  = s.get("last", "–")
        yt_rows += f"""
        <tr>
            <td><b>{name}</b></td>
            <td style="font-size:0.8em;color:#888">{url}</td>
            <td style="text-align:center;color:#00e676">{count} Mentions</td>
            <td style="font-size:0.8em">{last}</td>
            <td>
                <form method="POST" action="/sources/yt/remove" style="display:inline">
                    <input type="hidden" name="name" value="{html.escape(name)}">
                    <button type="submit" style="background:#ff525233;border:1px solid #ff5252;color:#ff5252;padding:3px 10px;border-radius:4px;cursor:pointer;font-size:0.8em">
                        🗑 Entfernen
                    </button>
                </form>
            </td>
        </tr>"""

    # Neue YT Kanal Form
    yt_add_form = """
    <form method="POST" action="/sources/yt/add" style="display:flex;gap:10px;margin-top:15px;align-items:center">
        <input type="text" name="name" placeholder='Name z.B. "nik navarskij"'
            style="flex:1;background:#0a0a1a;border:1px solid #2a2a4a;color:#e0e0e0;padding:8px 12px;border-radius:6px">
        <input type="text" name="url" placeholder="https://www.youtube.com/@Handle"
            style="flex:2;background:#0a0a1a;border:1px solid #2a2a4a;color:#e0e0e0;padding:8px 12px;border-radius:6px">
        <button type="submit"
            style="background:#00d4ff22;border:1px solid #00d4ff;color:#00d4ff;padding:8px 16px;border-radius:6px;cursor:pointer">
            ➕ Hinzufügen
        </button>
    </form>"""

    # RSS Feeds
    rss_rows = ""
    for i, feed in enumerate(sources.get("rss_feeds", [])):
        enabled = feed.get("enabled", True)
        weight  = feed.get("weight", 1.0)
        toggle_label = "✅ Aktiv" if enabled else "❌ Inaktiv"
        toggle_action = "/sources/rss/disable" if enabled else "/sources/rss/enable"
        toggle_color  = "color:#00e676" if enabled else "color:#ff5252"
        rss_rows += f"""
        <tr style="{'opacity:0.5' if not enabled else ''}">
            <td><b>{html.escape(feed.get('name',''))}</b></td>
            <td style="font-size:0.75em;color:#888;max-width:300px;overflow:hidden;text-overflow:ellipsis">
                {html.escape(feed.get('url',''))}
            </td>
            <td style="text-align:center">{feed.get('language','?').upper()}</td>
            <td style="text-align:center">
                <form method="POST" action="/sources/rss/weight" style="display:inline">
                    <input type="hidden" name="idx" value="{i}">
                    <input type="number" name="weight" value="{weight}" min="0.1" max="3.0" step="0.1"
                        style="width:60px;background:#0a0a1a;border:1px solid #2a2a4a;color:#ffd740;padding:3px;border-radius:4px;text-align:center">
                    <button type="submit" style="background:transparent;border:none;color:#888;cursor:pointer">💾</button>
                </form>
            </td>
            <td>
                <form method="POST" action="{toggle_action}" style="display:inline">
                    <input type="hidden" name="idx" value="{i}">
                    <button type="submit" style="background:transparent;border:1px solid #333;padding:3px 10px;border-radius:4px;cursor:pointer;font-size:0.8em;{toggle_color}">
                        {toggle_label}
                    </button>
                </form>
                <form method="POST" action="/sources/rss/remove" style="display:inline;margin-left:5px">
                    <input type="hidden" name="idx" value="{i}">
                    <button type="submit" style="background:#ff525222;border:1px solid #ff5252;color:#ff5252;padding:3px 8px;border-radius:4px;cursor:pointer;font-size:0.8em">
                        🗑
                    </button>
                </form>
            </td>
        </tr>"""

    rss_add_form = """
    <form method="POST" action="/sources/rss/add" style="display:flex;gap:10px;margin-top:15px;align-items:center">
        <input type="text" name="name" placeholder="Name z.B. Seeking Alpha"
            style="flex:1;background:#0a0a1a;border:1px solid #2a2a4a;color:#e0e0e0;padding:8px 12px;border-radius:6px">
        <input type="text" name="url" placeholder="https://feeds.example.com/rss"
            style="flex:2;background:#0a0a1a;border:1px solid #2a2a4a;color:#e0e0e0;padding:8px 12px;border-radius:6px">
        <select name="language" style="background:#0a0a1a;border:1px solid #2a2a4a;color:#e0e0e0;padding:8px;border-radius:6px">
            <option value="de">DE</option>
            <option value="en">EN</option>
        </select>
        <input type="number" name="weight" value="1.0" min="0.1" max="3.0" step="0.1"
            style="width:70px;background:#0a0a1a;border:1px solid #2a2a4a;color:#e0e0e0;padding:8px;border-radius:6px">
        <button type="submit"
            style="background:#00d4ff22;border:1px solid #00d4ff;color:#00d4ff;padding:8px 16px;border-radius:6px;cursor:pointer">
            ➕
        </button>
    </form>"""

    # Twitter Accounts
    tw_rows = ""
    for i, acc in enumerate(sources.get("twitter_accounts", [])):
        enabled = acc.get("enabled", True)
        weight  = acc.get("weight", 1.0)
        toggle_action = "/sources/twitter/disable" if enabled else "/sources/twitter/enable"
        toggle_label  = "✅ Aktiv" if enabled else "❌ Inaktiv"
        toggle_color  = "color:#00e676" if enabled else "color:#ff5252"
        category = acc.get("category", "–")
        tw_rows += f"""
        <tr style="{'opacity:0.5' if not enabled else ''}">
            <td><b>@{html.escape(acc.get('handle',''))}</b></td>
            <td>{html.escape(acc.get('name',''))}</td>
            <td style="font-size:0.8em;color:#888">{category}</td>
            <td style="text-align:center">
                <form method="POST" action="/sources/twitter/weight" style="display:inline">
                    <input type="hidden" name="idx" value="{i}">
                    <input type="number" name="weight" value="{weight}" min="0.1" max="3.0" step="0.1"
                        style="width:60px;background:#0a0a1a;border:1px solid #2a2a4a;color:#ffd740;padding:3px;border-radius:4px;text-align:center">
                    <button type="submit" style="background:transparent;border:none;color:#888;cursor:pointer">💾</button>
                </form>
            </td>
            <td>
                <form method="POST" action="{toggle_action}" style="display:inline">
                    <input type="hidden" name="idx" value="{i}">
                    <button type="submit" style="background:transparent;border:1px solid #333;padding:3px 10px;border-radius:4px;cursor:pointer;font-size:0.8em;{toggle_color}">
                        {toggle_label}
                    </button>
                </form>
                <form method="POST" action="/sources/twitter/remove" style="display:inline;margin-left:5px">
                    <input type="hidden" name="idx" value="{i}">
                    <button type="submit" style="background:#ff525222;border:1px solid #ff5252;color:#ff5252;padding:3px 8px;border-radius:4px;cursor:pointer;font-size:0.8em">
                        🗑
                    </button>
                </form>
            </td>
        </tr>"""

    tw_add_form = """
    <form method="POST" action="/sources/twitter/add" style="display:flex;gap:10px;margin-top:15px;align-items:center">
        <input type="text" name="handle" placeholder="Handle (ohne @)"
            style="flex:1;background:#0a0a1a;border:1px solid #2a2a4a;color:#e0e0e0;padding:8px 12px;border-radius:6px">
        <input type="text" name="name" placeholder="Name z.B. Bill Ackman"
            style="flex:1;background:#0a0a1a;border:1px solid #2a2a4a;color:#e0e0e0;padding:8px 12px;border-radius:6px">
        <select name="category" style="background:#0a0a1a;border:1px solid #2a2a4a;color:#e0e0e0;padding:8px;border-radius:6px">
            <option value="investor">Investor</option>
            <option value="analyst">Analyst</option>
            <option value="news">News</option>
            <option value="institutional">Institutional</option>
            <option value="journalist_de">Journalist DE</option>
            <option value="central_bank">Zentralbank</option>
        </select>
        <input type="number" name="weight" value="1.0" min="0.1" max="3.0" step="0.1"
            style="width:70px;background:#0a0a1a;border:1px solid #2a2a4a;color:#e0e0e0;padding:8px;border-radius:6px">
        <button type="submit"
            style="background:#00d4ff22;border:1px solid #00d4ff;color:#00d4ff;padding:8px 16px;border-radius:6px;cursor:pointer">
            ➕
        </button>
    </form>"""

    return f"""
<h2>📡 Quellen-Verwaltung</h2>

<div style="background:#151525;border:1px solid #2a2a4a;border-radius:8px;padding:20px;margin-bottom:15px">
    <div style="color:#00d4ff;font-weight:bold;margin-bottom:15px;font-size:1.1em">
        🎬 YouTube Kanäle ({len(yt_channels)} aktiv)
    </div>
    <table>
        <tr>
            <th>Name</th><th>URL</th>
            <th style="text-align:center">30-Tage Mentions</th>
            <th>Letzter Beitrag</th><th>Aktion</th>
        </tr>
        {yt_rows}
    </table>
    <div style="color:#888;font-size:0.85em;margin-top:10px">Neuen Kanal hinzufügen:</div>
    {yt_add_form}
</div>

<div style="background:#151525;border:1px solid #2a2a4a;border-radius:8px;padding:20px;margin-bottom:15px">
    <div style="color:#00d4ff;font-weight:bold;margin-bottom:15px;font-size:1.1em">
        📰 RSS Feeds ({len(sources.get('rss_feeds',[]))} konfiguriert,
        {sum(1 for f in sources.get('rss_feeds',[]) if f.get('enabled'))} aktiv)
    </div>
    <table>
        <tr>
            <th>Name</th><th>URL</th><th style="text-align:center">Sprache</th>
            <th style="text-align:center">Gewicht</th><th>Aktionen</th>
        </tr>
        {rss_rows}
    </table>
    <div style="color:#888;font-size:0.85em;margin-top:10px">
        Neuen RSS Feed hinzufügen: (Name | URL | Sprache | Gewicht 0.5-3.0)
    </div>
    {rss_add_form}
</div>

<div style="background:#151525;border:1px solid #2a2a4a;border-radius:8px;padding:20px;margin-bottom:15px">
    <div style="color:#00d4ff;font-weight:bold;margin-bottom:15px;font-size:1.1em">
        🐦 Twitter/X Accounts ({len(sources.get('twitter_accounts',[]))} konfiguriert,
        {sum(1 for a in sources.get('twitter_accounts',[]) if a.get('enabled'))} aktiv)
    </div>
    <div style="font-size:0.8em;color:#888;margin-bottom:10px">
        ⚠️ Benötigt twscrape: <code style="background:#0a0a1a;color:#00e676;padding:2px 6px;border-radius:3px">
        pip3 install twscrape --break-system-packages</code>
    </div>
    <table>
        <tr>
            <th>Handle</th><th>Name</th><th>Kategorie</th>
            <th style="text-align:center">Gewicht</th><th>Aktionen</th>
        </tr>
        {tw_rows}
    </table>
    <div style="color:#888;font-size:0.85em;margin-top:10px">
        Neuen Twitter/X Account hinzufügen: (Handle | Name | Kategorie | Gewicht)
    </div>
    {tw_add_form}
</div>

<div style="background:#151525;border:1px dashed #2a2a4a;border-radius:8px;padding:15px;margin-bottom:20px;font-size:0.85em;color:#888">
    💡 <b style="color:#ffd740">Gewicht-Erklärung:</b>
    1.0 = Standard | &gt;1.0 = stärker gewichtet | &lt;1.0 = schwächer gewichtet<br>
    Empfehlung: Institutionelle Quellen (Fed, Goldman) 1.5-2.0 | 
    Privatpersonen 0.8-1.2 | News-Agenturen 1.3-1.5
</div>"""


def build_html(data):
    s   = data["stats"]
    cfg = data["cfg"]

    # Qualitäts-Metriken HTML
    eval_data = data.get("eval_metrics", [])
    if eval_data:
        latest = eval_data[0]
        wr7  = latest.get("win_rate_7d", 0)
        pf7  = latest.get("profit_factor_7d", 0)
        wr_c = "color:#00e676" if wr7 >= 0.5 else "color:#ffd740" if wr7 >= 0.35 else "color:#ff5252"
        signal_metrics_html = f"""
        <div style="font-size:0.9em;line-height:2">
            Neue Unternehmen: <b>{latest.get('new_companies',0)}</b><br>
            Bestätigungen: <b style="color:#00e676">{latest.get('confirmed',0)}</b> |
            Widersprüche: <b style="color:#ff5252">{latest.get('contradicted',0)}</b><br>
            Ø Conviction: <b>{latest.get('avg_conviction',0):.0%}</b><br>
            Signale gekauft: <b>{latest.get('signals_bought',0)}</b>
        </div>"""
        portfolio_metrics_html = f"""
        <div style="font-size:0.9em;line-height:2">
            Win Rate (7d): <b style="{wr_c}">{wr7:.0%}</b><br>
            Win Rate (30d): <b>{latest.get('win_rate_30d',0):.0%}</b><br>
            Profit Factor (7d): <b>{pf7:.2f}</b><br>
            Sortino (30d): <b>{latest.get('sortino_30d',0):.2f}</b> |
            Calmar: <b>{latest.get('calmar_30d',0):.2f}</b><br>
            Max DD (30d): <b style="color:#ff5252">{latest.get('max_drawdown_30d',0):.1f}%</b> |
            Ø R-Mult: <b>{latest.get('avg_r_multiple',0):.2f}R</b><br>
            Exposure: <b style="color:#00e676">LONG {latest.get('exposure_long_pct',0):.0f}%</b> /
            <b style="color:#ff5252">SHORT {latest.get('exposure_short_pct',0):.0f}%</b><br>
            Ø Haltedauer: <b>{latest.get('avg_holding_days',0):.1f} Tage</b><br>
            SL/TP/Tech Exits: <b>{latest.get('exit_sl_pct',0):.0%}</b> /
            <b>{latest.get('exit_tp_pct',0):.0%}</b> /
            <b>{latest.get('exit_tech_pct',0):.0%}</b>
        </div>"""
    else:
        signal_metrics_html = "<div style='color:#555'>Noch keine Daten – läuft täglich 05:00</div>"
        portfolio_metrics_html = "<div style='color:#555'>Noch keine Daten</div>"

    # Source Quality Rows
    source_quality_rows = ""
    for sq in data.get("source_quality", []):
        wr  = sq.get("win_rate_30d", 0)
        qsc = sq.get("quality_score", 0)
        wrc = "color:#00e676" if wr >= 0.6 else "color:#ffd740" if wr >= 0.4 else "color:#ff5252"
        qc  = "color:#00e676" if qsc >= 0.7 else "color:#ffd740" if qsc >= 0.4 else "color:#ff5252"
        source_quality_rows += f"""<tr>
            <td><b>{html.escape(str(sq.get('channel','')))}</b></td>
            <td style="text-align:center">{sq.get('mentions_30d',0)}</td>
            <td style="text-align:center">{sq.get('bought_30d',0)}</td>
            <td style="text-align:center;{wrc}">{wr:.0%}</td>
            <td style="text-align:center">{sq.get('avg_pnl_30d',0):+.2f}€</td>
            <td style="text-align:center;{qc};font-weight:bold">{qsc:.2f}</td>
        </tr>"""
    if not source_quality_rows:
        source_quality_rows = '<tr><td colspan="6" style="text-align:center;color:#555;padding:20px">Noch keine Daten – läuft täglich 05:00</td></tr>'

    # Regime HTML
    regime = data.get("regime", {})
    if regime:
        reg = regime.get("regime", "unknown")
        rc  = "color:#00e676" if reg=="bull" else "color:#ff5252" if reg=="bear" else "color:#ffd740"
        regime_html = """
        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:15px;font-size:0.9em">
            <div><div style="color:#888;font-size:0.75em">REGIME</div>
                <div style="{rc};font-size:1.4em;font-weight:bold">{reg.upper()}</div></div>
            <div><div style="color:#888;font-size:0.75em">SPY 20d</div>
                <div style="font-weight:bold">{regime.get('spy_return',0):.1%}</div></div>
            <div><div style="color:#888;font-size:0.75em">DAX 20d</div>
                <div style="font-weight:bold">{regime.get('dax_return',0):.1%}</div></div>
            <div><div style="color:#888;font-size:0.75em">Datum</div>
                <div>{regime.get('date','–')}</div></div>
        </div>
        <div style="margin-top:12px;font-size:0.85em;color:#888">
            Nächste Woche →
            Bull: <b style="color:#00e676">{regime.get('bull_prob',0):.0%}</b> |
            Bear: <b style="color:#ff5252">{regime.get('bear_prob',0):.0%}</b> |
            Sideways: <b style="color:#ffd740">{regime.get('sideways_prob',0):.0%}</b>
        </div>"""
    else:
        regime_html = "<div style='color:#555'>Noch keine Daten – läuft täglich 02:00</div>"

    # Sector Blacklist HTML
    sector_blacklist = cfg.get("sector_blacklist", {})
    if sector_blacklist:
        bl_rows = ""
        for sector, entry in sector_blacklist.items():
            bl_rows += f"""<tr>
                <td style="font-weight:bold;color:#ff5252">🚫 {sector}</td>
                <td>{html.escape(str(entry.get('reason', '–')))}</td>
                <td style="color:#ffd740">{'✅ Probation' if entry.get('probation_done', False) else '⏳ Cooldown'}</td>
            </tr>"""
        sector_blacklist_html = f"""<table style="font-size:0.85em">
            <tr><th>Sektor</th><th>Grund</th><th>Status</th></tr>
            {bl_rows}
        </table>"""
    else:
        sector_blacklist_html = "<div style='color:#555'>Keine Sektoren geblockt ✅</div>"

    # Benchmark + Equity-Kurve HTML (Phase 5.4)
    bm = data.get("benchmark", {})
    equity_curve = data.get("equity_curve", [])
    if bm:
        port_ret = bm.get("portfolio_return_ytd", 0) or 0
        spy_ret  = bm.get("spy_return_ytd", 0) or 0
        dax_ret  = bm.get("dax_return_ytd", 0) or 0
        alpha_s  = bm.get("alpha_spy", 0) or 0
        alpha_d  = bm.get("alpha_dax", 0) or 0
        prc      = "color:#00e676" if port_ret >= 0 else "color:#ff5252"
        asc      = "color:#00e676" if alpha_s >= 0 else "color:#ff5252"
        adc      = "color:#00e676" if alpha_d >= 0 else "color:#ff5252"
        benchmark_html = f"""
        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:20px;margin-bottom:20px">
            <div style="background:#111;padding:15px;border-radius:8px;text-align:center">
                <div style="color:#888;font-size:0.75em;margin-bottom:5px">PORTFOLIO YTD</div>
                <div style="{prc};font-size:1.8em;font-weight:bold">{port_ret:+.1f}%</div>
            </div>
            <div style="background:#111;padding:15px;border-radius:8px;text-align:center">
                <div style="color:#888;font-size:0.75em;margin-bottom:5px">ALPHA vs SPY</div>
                <div style="{asc};font-size:1.8em;font-weight:bold">{alpha_s:+.1f}%</div>
                <div style="color:#555;font-size:0.75em">SPY: {spy_ret:+.1f}%</div>
            </div>
            <div style="background:#111;padding:15px;border-radius:8px;text-align:center">
                <div style="color:#888;font-size:0.75em;margin-bottom:5px">ALPHA vs DAX</div>
                <div style="{adc};font-size:1.8em;font-weight:bold">{alpha_d:+.1f}%</div>
                <div style="color:#555;font-size:0.75em">DAX: {dax_ret:+.1f}%</div>
            </div>
        </div>"""
    else:
        benchmark_html = "<div style='color:#555;padding:20px'>Benchmark-Daten noch nicht verfügbar – läuft täglich 02:00</div>"

    # Equity-Kurve Chart (SVG-basiert, kein externer JS)
    if equity_curve and len(equity_curve) >= 2:
        chart_dates = [(r.get("date") or "")[-5:] for r in equity_curve]  # MM-DD
        port_vals   = [r.get("portfolio_return_ytd") or 0 for r in equity_curve]
        spy_vals    = [r.get("spy_return_ytd") or 0 for r in equity_curve]
        dax_vals    = [r.get("dax_return_ytd") or 0 for r in equity_curve]
        all_vals    = port_vals + spy_vals + dax_vals
        min_v, max_v = min(all_vals), max(all_vals)
        range_v = max(max_v - min_v, 1)
        # Normalize to SVG coords (800x180)
        W, H = 800, 180
        def to_x(i): return int(i / max(len(port_vals)-1, 1) * W)
        def to_y(v): return int((1 - (v - min_v) / range_v) * H)
        def polyline(vals, col):
            pts = " ".join(f"{to_x(i)},{to_y(v)}" for i, v in enumerate(vals))
            return f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2"/>'
        equity_svg = f"""<svg viewBox="0 0 {W} {H+30}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;background:#111;border-radius:8px;padding:10px">
            <line x1="0" y1="{to_y(0)}" x2="{W}" y2="{to_y(0)}" stroke="#333" stroke-width="1" stroke-dasharray="4"/>
            {polyline(port_vals,"#00e676")}{polyline(spy_vals,"#448aff")}{polyline(dax_vals,"#ffd740")}
            <text x="5" y="{H+22}" fill="#00e676" font-size="10">— Portfolio</text>
            <text x="100" y="{H+22}" fill="#448aff" font-size="10">— SPY</text>
            <text x="160" y="{H+22}" fill="#ffd740" font-size="10">— DAX</text>
            <text x="{W-50}" y="{H+22}" fill="#555" font-size="9">{chart_dates[-1] if chart_dates else ''}</text>
        </svg>"""
        equity_chart_html = f'<div style="margin-top:15px">{equity_svg}</div>'
    else:
        equity_chart_html = "<div style='color:#555;font-size:0.85em;padding:10px'>Equity-Kurve: noch zu wenig Datenpunkte (täglich aufgebaut)</div>"

    import yfinance as yf

    # Offene Positionen
    open_rows = ""
    for p in data["open_pos"]:
        dl = '<span style="color:#00e676">LONG</span>' if p["direction"]=="LONG" else '<span style="color:#ff5252">SHORT</span>'
        cur = pnl_e = pnl_p = "–"
        pc = "color:#888"
        try:
            t = yf.Ticker(p['ticker'])
            cp = t.fast_info['last_price']
            if cp and p['entry_price']:
                pct = (cp - p['entry_price']) / p['entry_price']
                if p['direction'] == 'SHORT': pct = -pct
                eur = pct * p['position_size']
                pc  = "color:#00e676" if eur >= 0 else "color:#ff5252"
                cur = f"{cp:.2f}"; pnl_e = f"{eur:+.2f}€"; pnl_p = f"{pct*100:+.1f}%"
        except Exception: pass
        open_rows += f"""<tr>
            <td>{html.escape(str(p['name']))}</td><td>{html.escape(str(p['ticker']))}</td><td>{dl}</td>
            <td>{p['entry_price']:.2f}</td>
            <td style="font-weight:bold">{cur}</td>
            <td style="{pc};font-weight:bold">{pnl_e}</td>
            <td style="{pc};font-weight:bold">{pnl_p}</td>
            <td style="color:#ff5252">{p['stop_loss']:.2f}</td>
            <td style="color:#00e676">{p['take_profit']:.2f}</td>
            <td>{p['position_size']:.0f}€</td>
            <td>{p['entry_date'][:10]}</td>
            <td style="font-size:0.8em;color:#888">{html.escape(str(p.get('source_channel','')))}</td>
        </tr>"""
    if not open_rows:
        open_rows = '<tr><td colspan="12" style="text-align:center;color:#555;padding:20px">Keine offenen Positionen</td></tr>'

    # Abgeschlossene Trades
    closed_rows = ""
    for p in data["closed"]:
        c = "color:#00e676" if (p.get("pnl_eur") or 0)>0 else "color:#ff5252"
        reason_map = {"SL_HIT":"🛑 SL", "TARGET_HIT":"🎯 TP", "TECH_BROKEN":"⚡ Tech", "MANUAL":"✋"}
        reason = reason_map.get(p.get("exit_reason",""), p.get("exit_reason",""))
        closed_rows += f"<tr><td>{html.escape(str(p['name']))}</td><td>{html.escape(str(p['ticker']))}</td><td>{html.escape(str(p['direction']))}</td><td>{p['entry_price']:.2f}</td><td>{p.get('exit_price',0):.2f}</td><td style='{c}'>{p.get('pnl_eur',0):+.2f}€</td><td style='{c}'>{p.get('pnl_pct',0):+.1f}%</td><td>{reason}</td><td>{(p.get('exit_date') or '')[:10]}</td></tr>"
    if not closed_rows:
        closed_rows = '<tr><td colspan="9" style="text-align:center;color:#555;padding:20px">Noch keine abgeschlossenen Trades</td></tr>'

    # Watchlist – als JSON für Client-Side-Rendering im JS
    wl_data = []
    for w in data["watchlist"]:
        chs = []
        try:
            chs = json.loads(w.get("channels") or "[]")
            chs = list(dict.fromkeys(chs))  # uniq, behält Reihenfolge
        except (json.JSONDecodeError, TypeError):
            chs = []
        # Bevorzuge canonical_name aus companies (LEFT JOIN), sonst watchlist.name
        display_name   = w.get("company_name")  or w.get("name") or ""
        display_sector = w.get("company_sector") or w.get("sector") or "Other"
        wl_data.append({
            "name":          display_name,
            "ticker":        w.get("ticker") or "?",
            "sector":        display_sector,
            "mention_count": w.get("mention_count") or 0,
            "bullish":       w.get("bullish_count") or 0,
            "bearish":       w.get("bearish_count") or 0,
            "neutral":       w.get("neutral_count") or 0,
            "conviction":    w.get("conviction_score") or 0,
            "conviction_aged": w.get("conviction_score_aged") or 0,
            "tech_score":    w.get("tech_score"),
            "tech_direction": w.get("tech_direction") or "",
            "channels":      chs,
            "first_seen":    w.get("first_seen") or "",
            "last_seen":     w.get("last_seen") or "",
            "status":        w.get("status") or "watching",
        })
    wl_json = json.dumps(wl_data, ensure_ascii=False)
    # #2: Verhindert </script>-Breakout und HTML-Injection aus dem JSON-Blob,
    # der in einen <script>-Block interpoliert wird.
    wl_json = (wl_json.replace("<", "\\u003c")
                      .replace(">", "\\u003e")
                      .replace("&", "\\u0026"))
    wl_count_total    = len(wl_data)
    wl_count_watching = sum(1 for w in wl_data if w["status"] == "watching")
    wl_count_bought   = sum(1 for w in wl_data if w["status"] == "bought")
    wl_count_dropped  = sum(1 for w in wl_data if w["status"] == "dropped")


    # Cron
    cron_rows = ""
    current_group = None
    for j in data["cron_jobs"]:
        group = j.get("group", "⏰ Sonstige")
        if group != current_group:
            current_group = group
            cron_rows += f"<tr style='background:#1e1e38'><td colspan='6' style='color:#00d4ff;font-weight:bold;padding:8px 10px;font-size:0.8em;letter-spacing:1px'>{group}</td></tr>"
        sc = "color:#00e676" if j['last_status']=="OK" else "color:#ff5252" if j['last_status']=="Fehler" else "color:#ffd740"
        cron_rows += f"<tr><td style='font-weight:bold'>{j['time']}</td><td>{j['days']}</td><td style='font-family:monospace;font-size:0.85em'>{j['script']}</td><td>{j['desc']}</td><td style='font-size:0.8em;color:#888'>{j['last_run']}</td><td style='{sc};font-weight:bold'>{j['last_status']}</td></tr>"

    # Logs
    log_rows = ""
    for line in data["log_lines"]:
        style = "color:#00e676;font-weight:bold" if "===" in line else "color:#2196f3;font-weight:bold" if "---" in line else ""
        log_rows += f'<tr><td style="font-family:monospace;padding:5px 10px;font-size:0.82em;{style}">{html.escape(line)}</td></tr>'
    thematic_log_rows = ""
    for line in data.get("thematic_log_lines", []):
        if "DONE" in line or "✅" in line:
            style = "color:#00e676;font-weight:bold"
        elif "ERROR" in line or "✗" in line or "Fehler" in line:
            style = "color:#ff5252;font-weight:bold"
        elif "===" in line or "---" in line or "START" in line:
            style = "color:#ffd740;font-weight:bold"
        elif "⚠" in line:
            style = "color:#ff9800"
        else:
            style = ""
        thematic_log_rows += f'<tr><td style="font-family:monospace;padding:5px 10px;font-size:0.82em;{style}">{html.escape(line)}</td></tr>'

    rc = "color:#00e676" if s["total_return"]>=0 else "color:#ff5252"

    # Sources Section
    sources_html = build_sources_section(data)

    return f"""<!DOCTYPE html>
<html lang="de"><head>
<meta charset="UTF-8"><meta http-equiv="refresh" content="900">
<title>Hermes Trading Dashboard</title>
<style>
    :root {{ --bg:#0a0a12; --card:#151525; --border:#2a2a4a; --accent:#00d4ff; --text:#e0e0e0; }}
    *{{ box-sizing:border-box; margin:0; padding:0; }}
    body{{ font-family:'Segoe UI',sans-serif; background:var(--bg); color:var(--text); padding:20px; line-height:1.4; }}
    h1{{ color:var(--accent); margin-bottom:20px; font-size:1.6em; }}
    h2{{ color:var(--accent); margin:25px 0 12px; font-size:0.9em; text-transform:uppercase;
         letter-spacing:1px; border-left:3px solid var(--accent); padding-left:10px; }}
    .top-container{{ display:grid; grid-template-columns:1fr 420px; gap:20px; margin-bottom:20px; }}
    .stats-grid{{ display:grid; grid-template-columns:repeat(auto-fit,minmax(130px,1fr)); gap:10px; }}
    .card{{ background:var(--card); border:1px solid var(--border); border-radius:8px; padding:12px; }}
    .card .label{{ font-size:0.65em; color:#888; text-transform:uppercase; font-weight:bold; }}
    .card .value{{ font-size:1.2em; font-weight:bold; margin-top:4px; }}
    .strategy-grid{{ display:grid; grid-template-columns:repeat(4,1fr); gap:15px; margin-bottom:20px; }}
    .strat-card{{ background:var(--card); border:1px solid var(--border); border-radius:8px; padding:15px; }}
    .strat-card h3{{ font-size:0.75em; color:var(--accent); margin-bottom:10px; text-transform:uppercase; }}
    .strat-item{{ display:flex; justify-content:space-between; font-size:0.85em; margin-bottom:5px;
                  border-bottom:1px solid #222; padding-bottom:2px; }}
    .strat-item span:last-child{{ font-weight:bold; color:#ffd740; }}
    table{{ width:100%; border-collapse:collapse; background:var(--card); border-radius:8px;
            overflow:hidden; margin-bottom:20px; border:1px solid var(--border); }}
    th{{ background:#1e1e38; padding:10px; text-align:left; font-size:0.7em; color:#888; text-transform:uppercase; }}
    td{{ padding:9px 10px; border-bottom:1px solid var(--border); font-size:0.85em; }}
    tr:last-child td{{ border-bottom:none; }}
    tr:hover{{ background:#1a1a2e; }}
    .tab-nav{{ display:flex; gap:5px; margin-bottom:20px; border-bottom:1px solid var(--border); padding-bottom:0; }}
    .tab-btn{{ padding:10px 20px; background:transparent; border:none; color:#888;
               cursor:pointer; font-size:0.9em; border-bottom:2px solid transparent;
               transition:all 0.2s; }}
    .tab-btn.active{{ color:var(--accent); border-bottom-color:var(--accent); }}
    .tab-btn:hover{{ color:var(--text); }}
    .tab-content{{ display:none; }}
    .tab-content.active{{ display:block; }}
    .footer{{ color:#444; font-size:0.7em; text-align:center; margin-top:30px; }}
    code{{ background:#000; color:#00e676; padding:2px 5px; border-radius:3px; font-family:monospace; }}
    input[type=text], input[type=number], select{{
        outline:none; font-family:'Segoe UI',sans-serif;
    }}
    input[type=text]:focus, input[type=number]:focus{{
        border-color:var(--accent) !important;
    }}
    .msg-box{{ background:#00d4ff11; border:1px solid #00d4ff44; border-radius:8px;
               padding:10px 15px; margin-bottom:15px; color:#00d4ff; font-size:0.9em; }}
</style></head><body>

<h1>📊 Hermes Trading Terminal</h1>

<!-- Stats -->
<div class="top-container">
    <div class="stats-grid">
        <div class="card"><div class="label">Portfolio</div>
            <div class="value" style="color:var(--accent)">{s['total_value']}€</div></div>
        <div class="card"><div class="label">Return</div>
            <div class="value" style="{rc}">{s['total_return']:+.1f}%</div></div>
        <div class="card"><div class="label">P&L Gesamt</div>
            <div class="value" style="{rc}">{s['total_pnl']:+.2f}€</div></div>
        <div class="card"><div class="label">Win Rate</div>
            <div class="value">{s['win_rate']}%</div></div>
        <div class="card"><div class="label">Cash</div>
            <div class="value">{s['cash']}€</div></div>
        <div class="card"><div class="label">Trades</div>
            <div class="value">{s['total_trades']}</div></div>
    </div>
    <div class="strat-card">
        <h3>⚙️ Aktive Strategie-Parameter</h3>
        <div class="strat-item"><span>Max Positionen</span><span>{cfg.get("max_positions",8)}</span></div>
        <div class="strat-item"><span>Stop-Loss</span><span>{cfg.get('atr_sl_multiplier',1.5)}x ATR</span></div>
        <div class="strat-item"><span>Take-Profit</span><span>{cfg.get('atr_tp_multiplier',3.0)}x ATR</span></div>
        <div class="strat-item"><span>Min. Konfidenz</span><span>{int(cfg.get('min_confidence',0.65)*100)}%</span></div>
        <div class="strat-item"><span>High Conv. Size</span><span>20% | 15% | 10%</span></div>
        <div class="strat-item"><span>Exit-Check</span><span>10:00 + 15:30</span></div>
        <div class="strat-item"><span>Startkapital</span><span>{cfg.get("starting_capital",10000):.0f}€</span></div>
    </div>
</div>

<!-- Tabs -->
<div class="tab-nav">
    <button class="tab-btn active" onclick="showTab('portfolio')">📂 Portfolio</button>
    <button class="tab-btn" onclick="showTab('watchlist')">📋 Watchlist ({len(data['watchlist'])})</button>
    <button class="tab-btn" onclick="showTab('sources')">📡 Quellen</button>
    <button class="tab-btn" onclick="showTab('quality')">📊 Qualität</button>
    <button class="tab-btn" onclick="showTab('cron')">⏰ Cron & Logs</button>
    <button class="tab-btn" onclick="showTab('thematic')" style="color:#ffd740">🎓 Thematic</button>
    <button class="tab-btn" onclick="showTab('exits')" style="color:#ff9800">🚪 Exits</button>
</div>

<!-- Tab: Portfolio -->
<div id="tab-portfolio" class="tab-content active">
    <h2>📂 Aktive Positionen ({len(data['open_pos'])}/{cfg.get('max_positions',8)})</h2>
    <table>
        <tr><th>Unternehmen</th><th>Ticker</th><th>Typ</th><th>Entry</th>
        <th>Aktuell</th><th>P&L €</th><th>P&L %</th>
        <th>SL</th><th>TP</th><th>Größe</th><th>Datum</th><th>Quelle</th></tr>
        {open_rows}
    </table>
    <h2>✅ Abgeschlossene Trades (letzte 20)</h2>
    <table>
        <tr><th>Unternehmen</th><th>Ticker</th><th>Typ</th><th>Entry</th>
        <th>Exit</th><th>P&L €</th><th>P&L %</th><th>Grund</th><th>Datum</th></tr>
        {closed_rows}
    </table>
</div>

<!-- Tab: Watchlist -->
<div id="tab-watchlist" class="tab-content">
    <h2>📋 Watchlist <span style="color:#888;font-size:0.7em">({wl_count_total} gesamt)</span></h2>
    
    <!-- Filter Buttons -->
    <div style="margin-bottom:15px;display:flex;gap:8px;flex-wrap:wrap;align-items:center">
        <span style="color:#888;font-size:0.85em">Status:</span>
        <button class="wl-filter active" data-status="watching" onclick="wlSetFilter('watching')">
            Beobachtet ({wl_count_watching})
        </button>
        <button class="wl-filter" data-status="bought" onclick="wlSetFilter('bought')">
            Gekauft ({wl_count_bought})
        </button>
        <button class="wl-filter" data-status="dropped" onclick="wlSetFilter('dropped')">
            Verworfen ({wl_count_dropped})
        </button>
        <button class="wl-filter" data-status="all" onclick="wlSetFilter('all')">
            Alle ({wl_count_total})
        </button>
        <input type="text" id="wl-search" placeholder="🔍 Suche (Name/Ticker/Sektor)" 
               style="margin-left:auto;padding:6px 10px;background:#1a1a2e;border:1px solid #2a2a4a;color:#fff;border-radius:4px;min-width:240px"
               oninput="wlRender()">
    </div>
    
    <!-- Tabelle -->
    <table id="wl-table">
        <thead>
            <tr>
                <th class="wl-sort" data-sort="name">Unternehmen ▾</th>
                <th class="wl-sort" data-sort="ticker">Ticker</th>
                <th class="wl-sort" data-sort="sector">Sektor</th>
                <th class="wl-sort" data-sort="mention_count" style="text-align:center">Mentions</th>
                <th class="wl-sort" data-sort="bullish" style="text-align:center">Bull</th>
                <th class="wl-sort" data-sort="bearish" style="text-align:center">Bear</th>
                <th class="wl-sort" data-sort="conviction" style="text-align:center">Conviction</th>
                <th class="wl-sort" data-sort="conviction_aged" style="text-align:center">Conv. (aged)</th>
                <th class="wl-sort" data-sort="tech_score" style="text-align:center">Tech</th>
                <th class="wl-sort" data-sort="tech_direction" style="text-align:center">Richtung</th>
                <th>Kanäle</th>
                <th class="wl-sort" data-sort="first_seen" style="text-align:center">Zuerst</th>
                <th class="wl-sort" data-sort="last_seen" style="text-align:center">Zuletzt</th>
            </tr>
        </thead>
        <tbody id="wl-tbody"></tbody>
    </table>
    
    <!-- Pagination -->
    <div id="wl-pagination" style="margin-top:15px;display:flex;gap:8px;align-items:center;color:#888;font-size:0.9em">
        <span id="wl-info"></span>
        <span style="margin-left:auto"></span>
        <button onclick="wlPagePrev()" id="wl-prev">◀ Zurück</button>
        <span id="wl-page-info"></span>
        <button onclick="wlPageNext()" id="wl-next">Weiter ▶</button>
    </div>
</div>

<style>
.wl-filter {{
    background: #1a1a2e; border: 1px solid #2a2a4a; color: #aaa;
    padding: 6px 12px; border-radius: 4px; cursor: pointer; font-size: 0.85em;
}}
.wl-filter:hover {{ background: #252540; color: #fff; }}
.wl-filter.active {{ background: #00d4ff; color: #000; border-color: #00d4ff; font-weight: bold; }}
.wl-sort {{ cursor: pointer; user-select: none; }}
.wl-sort:hover {{ background: #1e1e38; }}
.wl-sort.sort-asc::after {{ content: " ▲"; color: #00d4ff; }}
.wl-sort.sort-desc::after {{ content: " ▼"; color: #00d4ff; }}
#wl-prev, #wl-next {{
    background: #1a1a2e; border: 1px solid #2a2a4a; color: #fff;
    padding: 6px 12px; border-radius: 4px; cursor: pointer;
}}
#wl-prev:disabled, #wl-next:disabled {{ opacity: 0.4; cursor: not-allowed; }}
.wl-channels-wrap {{ position: relative; display: inline-block; }}
.wl-channels-tip {{
    visibility: hidden; position: absolute; z-index: 10; left: 0; top: 100%;
    background: #0a0a14; border: 1px solid #2a2a4a; padding: 8px; border-radius: 4px;
    min-width: 200px; font-size: 0.85em; color: #fff; box-shadow: 0 4px 12px rgba(0,0,0,0.5);
}}
.wl-channels-wrap:hover .wl-channels-tip {{ visibility: visible; }}
</style>

<script>
const WL_DATA = {wl_json};
let wlFilter = "watching";
let wlSortKey = "conviction";
let wlSortDir = "desc";
let wlPage = 1;
const WL_PAGE_SIZE = 50;

function wlSetFilter(status) {{
    wlFilter = status;
    wlPage = 1;
    document.querySelectorAll(".wl-filter").forEach(b => b.classList.toggle("active", b.dataset.status === status));
    wlRender();
}}

document.querySelectorAll(".wl-sort").forEach(th => {{
    th.addEventListener("click", () => {{
        const key = th.dataset.sort;
        if (wlSortKey === key) {{
            wlSortDir = wlSortDir === "asc" ? "desc" : "asc";
        }} else {{
            wlSortKey = key;
            wlSortDir = ["name","ticker","sector","first_seen","last_seen","tech_direction"].includes(key) ? "asc" : "desc";
        }}
        wlPage = 1;
        wlRender();
    }});
}});

function wlPagePrev() {{ if (wlPage > 1) {{ wlPage--; wlRender(); }} }}
function wlPageNext() {{ wlPage++; wlRender(); }}

function wlFiltered() {{
    const q = (document.getElementById("wl-search").value || "").toLowerCase().trim();
    return WL_DATA.filter(w => {{
        if (wlFilter !== "all" && w.status !== wlFilter) return false;
        if (q) {{
            const hay = (w.name + " " + w.ticker + " " + w.sector).toLowerCase();
            if (!hay.includes(q)) return false;
        }}
        return true;
    }});
}}

function wlSorted(rows) {{
    const k = wlSortKey, dir = wlSortDir === "asc" ? 1 : -1;
    return rows.slice().sort((a, b) => {{
        let va = a[k], vb = b[k];
        if (va == null) va = (typeof vb === "number") ? -Infinity : "";
        if (vb == null) vb = (typeof va === "number") ? -Infinity : "";
        if (typeof va === "number" && typeof vb === "number") return (va - vb) * dir;
        return String(va).localeCompare(String(vb)) * dir;
    }});
}}

function wlRender() {{
    document.querySelectorAll(".wl-sort").forEach(th => {{
        th.classList.remove("sort-asc", "sort-desc");
        if (th.dataset.sort === wlSortKey) th.classList.add("sort-" + wlSortDir);
    }});
    const filtered = wlFiltered();
    const sorted = wlSorted(filtered);
    const total = sorted.length;
    const maxPage = Math.max(1, Math.ceil(total / WL_PAGE_SIZE));
    if (wlPage > maxPage) wlPage = maxPage;
    const start = (wlPage - 1) * WL_PAGE_SIZE;
    const slice = sorted.slice(start, start + WL_PAGE_SIZE);

    const tbody = document.getElementById("wl-tbody");
    // #2: innerHTML-Escaping für DB/LLM-stämmige Felder (Name/Ticker/Sektor/Kanäle).
    const esc = s => String(s == null ? "" : s)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
    tbody.innerHTML = slice.map(w => {{
        const conv = w.conviction || 0;
        const cc = conv >= 0.6 ? "#00e676" : conv >= 0.4 ? "#ffd740" : "#ff5252";
        const tech = w.tech_score != null ? w.tech_score.toFixed(2) : "–";
        const dc = w.tech_direction === "LONG" ? "#00e676" : w.tech_direction === "SHORT" ? "#ff5252" : "#888";
        const first3 = w.channels.slice(0, 3).map(esc).join(", ");
        const rest = w.channels.slice(3);
        const tip = w.channels.length > 0
            ? `<div class="wl-channels-tip">${{w.channels.map(esc).join("<br>")}}</div>` : "";
        const more = rest.length > 0 ? ` <span style="color:#00d4ff">+${{rest.length}}</span>` : "";
        const status_icon = w.status === "bought" ? "🛒 " : w.status === "dropped" ? "✗ " : "";
        return `<tr>
            <td>${{status_icon}}${{esc(w.name)}}</td>
            <td>${{esc(w.ticker)}}</td>
            <td>${{esc(w.sector)}}</td>
            <td style="text-align:center">${{w.mention_count}}</td>
            <td style="color:#00e676;text-align:center">${{w.bullish}}↑</td>
            <td style="color:#ff5252;text-align:center">${{w.bearish}}↓</td>
            <td style="color:${{cc}};font-weight:bold;text-align:center">${{(conv*100).toFixed(0)}}%</td>
            <td style="text-align:center">${{w.conviction_aged > 0 ? (w.conviction_aged*100).toFixed(0)+'%' : '–'}}</td>
            <td style="text-align:center">${{tech}}</td>
            <td style="color:${{dc}};text-align:center">${{w.tech_direction || "–"}}</td>
            <td style="font-size:0.8em"><span class="wl-channels-wrap">${{first3}}${{more}}${{tip}}</span></td>
            <td style="font-size:0.8em;text-align:center">${{esc(w.first_seen)}}</td>
            <td style="font-size:0.8em;text-align:center">${{w.last_seen}}</td>
        </tr>`;
    }}).join("") || `<tr><td colspan="13" style="text-align:center;color:#555;padding:20px">Keine Treffer</td></tr>`;

    document.getElementById("wl-info").textContent = total === 0
        ? "Keine Eintraege" : `${{start + 1}}–${{Math.min(start + WL_PAGE_SIZE, total)}} von ${{total}}`;
    document.getElementById("wl-page-info").textContent = `Seite ${{wlPage}} / ${{maxPage}}`;
    document.getElementById("wl-prev").disabled = wlPage <= 1;
    document.getElementById("wl-next").disabled = wlPage >= maxPage;
}}

wlRender();
</script>

<!-- Tab: Quellen -->
<div id="tab-sources" class="tab-content">
    {sources_html}
</div>

<!-- Tab: Qualität -->
<div id="tab-quality" class="tab-content">
    <h2>📊 Qualitäts-Metriken</h2>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:15px;margin-bottom:20px">
        <div style="background:#151525;border:1px solid #2a2a4a;border-radius:8px;padding:15px">
            <div style="color:#00d4ff;font-weight:bold;margin-bottom:10px">📡 Signal-Pipeline (letzte 7 Tage)</div>
            {signal_metrics_html}
        </div>
        <div style="background:#151525;border:1px solid #2a2a4a;border-radius:8px;padding:15px">
            <div style="color:#00d4ff;font-weight:bold;margin-bottom:10px">💼 Portfolio-Performance</div>
            {portfolio_metrics_html}
        </div>
    </div>
    <h2>🔍 Source-Qualität (30 Tage)</h2>
    <table>
        <tr><th>Quelle</th><th style="text-align:center">Mentions</th>
        <th style="text-align:center">Gekauft</th><th style="text-align:center">Win Rate</th>
        <th style="text-align:center">Ø P&L</th><th style="text-align:center">Quality Score</th></tr>
        {source_quality_rows}
    </table>
    <h2>🌍 Markt-Regime</h2>
    <div style="background:#151525;border:1px solid #2a2a4a;border-radius:8px;padding:15px">
        {regime_html}
    </div>
    <h2>🚫 Geblockte Sektoren</h2>
    <div style="background:#151525;border:1px solid #2a2a4a;border-radius:8px;padding:15px">
        {sector_blacklist_html}
    </div>
    <h2>📈 Benchmark-Vergleich (YTD)</h2>
    <div style="background:#151525;border:1px solid #2a2a4a;border-radius:8px;padding:15px">
        {benchmark_html}
        {equity_chart_html}
    </div>
</div>

<!-- Tab: Cron & Logs -->
<div id="tab-cron" class="tab-content">
    <h2>⏰ Automatisierung</h2>
    <table>
        <tr><th>Zeit</th><th>Tage</th><th>Script</th>
        <th>Beschreibung</th><th>Letzter Run</th><th>Status</th></tr>
        {cron_rows}
    </table>
    <h2>📜 System-Logs — Klassischer Bot (letzte 50 Einträge)</h2>
    <table style="background:#05050a;">{log_rows}</table>
    <h2 style="margin-top:30px">🎯 Thematic Bot Logs (letzte 100 Einträge)</h2>
    <table style="background:#05050a;">{thematic_log_rows}</table>
</div>

<!-- Tab: Thematic -->
<div id="tab-thematic" class="tab-content">
    {build_thematic_section()}
</div>

<!-- Tab: Exits -->
<div id="tab-exits" class="tab-content">
    {build_exits_section(data)}
</div>

<div class="footer">Auto-Refresh alle 60s | {datetime.now().strftime('%d.%m.%Y %H:%M:%S')} | Hermes Trading v4.1</div>

<script>
function showTab(name) {{
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    var el = document.getElementById('tab-' + name);
    if (el) el.classList.add('active');
    if (event && event.target) event.target.classList.add('active');
    history.replaceState(null, '', '?tab=' + name);
}}
// Tab aus URL laden
var urlTab = new URLSearchParams(window.location.search).get('tab');
if (urlTab) {{
    var btn = document.querySelector('[onclick="showTab(\\'' + urlTab.replace(/'/g, "\\'") + '\\')"]');
    if (btn) btn.click();
}}
</script>
</body></html>"""


def build_exits_section(data):
    """🚪 Exit Management — Stairway to Heaven Step-Out-Visualisierung"""
    import yfinance as yf
    from config import DB_PATH, db_connect

    positions = data["open_pos"]
    if not positions:
        return '<div style="color:#555;padding:40px;text-align:center">Keine offenen Positionen – kein Exit-Management nötig ✅</div>'

    # Stairway-Standard-Levels (x ATR): wie viel % der Position verkaufen
    stairway_levels = [
        (1.0, 0.25, "TP1"),
        (2.0, 0.25, "TP2"),
        (3.0, 0.50, "TP3"),
    ]

    positions_html = ""
    summary_rows = []

    for idx, pos in enumerate(positions):
        ticker = pos["ticker"]
        direction = pos["direction"]
        entry = pos["entry_price"]
        sl = pos["stop_loss"]
        tp = pos["take_profit"]
        size = pos["position_size"]
        atr_entry = pos["atr_at_entry"] or 0

        # Aktuellen Preis holen
        current_price = None
        try:
            t = yf.Ticker(ticker)
            current_price = t.fast_info['last_price']
        except Exception:
            current_price = None

        if not current_price:
            # Fallback: entry nehmen
            current_price = entry

        # ATR bestimmen
        atr = atr_entry if atr_entry > 0 else (abs(tp - entry) / 3.0 if tp and entry else 1.0)

        if direction == "LONG":
            pnl_atr = (current_price - entry) / atr if atr > 0 else 0
            pnl_pct = ((current_price - entry) / entry * 100) if entry else 0
        else:
            pnl_atr = (entry - current_price) / atr if atr > 0 else 0
            pnl_pct = ((entry - current_price) / entry * 100) if entry else 0

        # Trailing-Stand
        trailing_sl = pos.get("trailing_sl") or sl
        highest = pos.get("highest_price") or current_price
        lowest = pos.get("lowest_price") or current_price

        # Stairway-levels berechnen
        # Für LONG: steps bei entry + atr_lvl * atr
        # Für SHORT: steps bei entry - atr_lvl * atr
        steps = []
        for atr_lvl, pct, label in stairway_levels:
            if direction == "LONG":
                step_price = entry + atr_lvl * atr
            else:
                step_price = entry - atr_lvl * atr

            hit = (direction == "LONG" and current_price >= step_price) or \
                  (direction == "SHORT" and current_price <= step_price)
            steps.append({
                "atr_lvl": atr_lvl,
                "pct": pct,
                "label": label,
                "price": round(step_price, 2),
                "hit": hit,
                "active": not hit,
            })

        # SVG Stairway (200x160)
        W, H = 200, 160
        # Normalisierter Bereich: min = min(entry, sl, current, trailing) - padding
        # max = max(entry, tp, current, trailing) + padding
        prices = [entry, sl, tp, current_price, trailing_sl]
        for s in steps:
            prices.append(s["price"])
        min_p = min(prices) - atr * 0.5
        max_p = max(prices) + atr * 0.5
        if max_p - min_p < 0.01:
            max_p = min_p + 1
        rng = max_p - min_p

        def to_y(price):
            # price oben ist größer → y wird kleiner
            return int(H - (price - min_p) / rng * (H - 20) - 10)

        def to_x(step_idx):
            return 30 + step_idx * (W - 60) // max(len(steps), 1)

        # SVG-Build
        svg_parts = []
        # Hintergrund
        svg_parts.append(f'<rect x="0" y="0" width="{W}" height="{H}" fill="#0d0d1a" rx="6"/>')

        # Horizontale ATR-Gitterlinien
        for atr_lvl in [0, 1, 2, 3]:
            if direction == "LONG":
                p = entry + atr_lvl * atr
            else:
                p = entry - atr_lvl * atr
            if min_p <= p <= max_p:
                y = to_y(p)
                dash = "3,3" if atr_lvl > 0 else ""
                svg_parts.append(
                    f'<line x1="5" y1="{y}" x2="{W-5}" y2="{y}" '
                    f'stroke="#1a1a2e" stroke-width="1" stroke-dasharray="{dash}"/>'
                )
                if atr_lvl > 0:
                    svg_parts.append(
                        f'<text x="{W-4}" y="{y-2}" fill="#333" font-size="7" '
                        f'text-anchor="end">{atr_lvl}×</text>'
                    )

        # Stairway-Treppe (Polygon)
        # Steps: entry → step1 → step2 → step3 → TP (horizontal)
        stair_x = [30]
        stair_y = [to_y(entry)]
        prev_y = to_y(entry)
        for i, s in enumerate(steps):
            x = to_x(i)
            y = to_y(s["price"])
            # vertical rauf
            stair_x.append(x)
            stair_y.append(prev_y)
            # horizontal rüber
            stair_x.append(x)
            stair_y.append(y)
            prev_y = y

        # TP als final step
        tp_x = W - 30
        tp_y = to_y(tp)
        stair_x.append(tp_x)
        stair_y.append(prev_y)
        stair_x.append(tp_x)
        stair_y.append(tp_y)

        # Stairway-Linie (grau)
        pts = " ".join(f"{stair_x[i]},{stair_y[i]}" for i in range(len(stair_x)))
        svg_parts.append(
            f'<polyline points="{pts}" fill="none" stroke="#333" stroke-width="1.5" '
            f'stroke-dasharray="4,3"/>'
        )

        # Aktuelle Position (dot)
        cy = to_y(current_price)
        clr = "#00e676" if pnl_pct >= 0 else "#ff5252"
        svg_parts.append(
            f'<circle cx="30" cy="{cy}" r="5" fill="{clr}" stroke="#fff" stroke-width="1.5"/>'
        )
        svg_parts.append(
            f'<text x="8" y="{cy+3}" fill="{clr}" font-size="8" font-weight="bold">●</text>'
        )

        # Trailing SL (Dreieck)
        ts_y = to_y(trailing_sl)
        svg_parts.append(
            f'<polygon points="22,{ts_y-4} 28,{ts_y+4} 16,{ts_y+4}" '
            f'fill="#ff9800" opacity="0.8"/>'
        )

        # Step-Markierungen (erreicht = grün, aktiv = orange)
        for i, s in enumerate(steps):
            x = to_x(i)
            y = to_y(s["price"])
            sc = "#00e676" if s["hit"] else "#ff9800"
            label = "✓" if s["hit"] else f'{int(s["pct"]*100)}%'
            svg_parts.append(
                f'<circle cx="{x}" cy="{y}" r="4" fill="{sc}" stroke="#fff" stroke-width="1"/>'
            )
            svg_parts.append(
                f'<text x="{x}" y="{y-7}" fill="{sc}" font-size="7" '
                f'text-anchor="middle">{label}</text>'
            )

        # SL (rot Dreieck nach unten)
        sl_y = to_y(sl)
        if direction == "LONG":
            # SL unterhalb
            svg_parts.append(
                f'<polygon points="22,{sl_y+4} 28,{sl_y-4} 16,{sl_y-4}" '
                f'fill="#ff5252" opacity="0.8"/>'
            )
        else:
            svg_parts.append(
                f'<polygon points="22,{sl_y-4} 28,{sl_y+4} 16,{sl_y+4}" '
                f'fill="#ff5252" opacity="0.8"/>'
            )

        # TP (grün Diamond)
        tp_y = to_y(tp)
        svg_parts.append(
            f'<polygon points="30,{tp_y-5} 35,{tp_y} 30,{tp_y+5} 25,{tp_y}" '
            f'fill="#00e676" opacity="0.6"/>'
        )

        # Entry-Marker
        ey = to_y(entry)
        svg_parts.append(
            f'<line x1="25" y1="{ey}" x2="35" y2="{ey}" stroke="#448aff" '
            f'stroke-width="2" opacity="0.5"/>'
        )

        svg = f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;border-radius:6px">{chr(10).join(svg_parts)}</svg>'

        # Summary-Table
        stp_pct = sum(s["pct"] for s in steps if s["hit"])
        next_step = next((s for s in steps if s["active"]), None)
        trail_status = "🔒 Trailing" if trailing_sl != sl else "⏳ Fix"
        if direction == "LONG" and trailing_sl > sl:
            trail_status = "🔒 Trailing"
        elif direction == "SHORT" and trailing_sl < sl:
            trail_status = "🔒 Trailing"
        else:
            trail_status = "⏳ Fix"

        partial_exit_done = pos.get("partial_exit_done", 0) or 0
        partial_pct = int(partial_exit_done * 100) if partial_exit_done < 1 else partial_exit_done

        positions_html += f"""
        <div style="background:#151525;border:1px solid #2a2a4a;border-radius:8px;padding:15px;margin-bottom:15px">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
                <div>
                    <span style="font-size:1.1em;font-weight:bold">{html.escape(pos['name'])}</span>
                    <span style="color:#888;font-size:0.85em"> ({ticker})</span>
                    <span style="color:{'#00e676' if direction=='LONG' else '#ff5252'};font-size:0.85em;margin-left:8px">{direction}</span>
                </div>
                <div style="text-align:right">
                    <span style="color:{'#00e676' if pnl_pct>=0 else '#ff5252'};font-weight:bold;font-size:1.1em">{pnl_pct:+.1f}%</span>
                    <span style="color:#888;font-size:0.8em;margin-left:8px">+{pnl_atr:.1f}x ATR</span>
                </div>
            </div>
            <div style="display:grid;grid-template-columns:220px 1fr;gap:15px">
                <div style="background:#0a0a14;border-radius:6px;padding:5px">{svg}</div>
                <div>
                    <table style="font-size:0.82em;margin-bottom:8px">
                        <tr><td style="color:#888;padding:3px 8px">Entry</td>
                            <td style="font-weight:bold">{entry:.2f}</td>
                            <td style="color:#888;padding:3px 8px">SL</td>
                            <td style="color:#ff5252">{sl:.2f}</td>
                            <td style="color:#888;padding:3px 8px">TP</td>
                            <td style="color:#00e676">{tp:.2f}</td></tr>
                        <tr><td style="color:#888;padding:3px 8px">Aktuell</td>
                            <td style="font-weight:bold;color:{clr}">{current_price:.2f}</td>
                            <td style="color:#888;padding:3px 8px">Trailing</td>
                            <td style="color:#ff9800">{trailing_sl:.2f}</td>
                            <td style="color:#888;padding:3px 8px">ATR</td>
                            <td>{atr:.2f}</td></tr>
                        <tr><td style="color:#888;padding:3px 8px">Größe</td>
                            <td>{size:.0f}€</td>
                            <td style="color:#888;padding:3px 8px">Trail</td>
                            <td>{trail_status}</td>
                            <td style="color:#888;padding:3px 8px">Step-out</td>
                            <td style="color:#ff9800">{int(stp_pct*100)}% done</td></tr>
                    </table>
                    <div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap">
                        {''.join(
                            f'<span style="background:#{'00e67622' if s['hit'] else 'ff980022'};'
                            f'border:1px solid #{'00e676' if s['hit'] else 'ff9800'};'
                            f'color:#{'00e676' if s['hit'] else 'ff9800'};'
                            f'padding:2px 8px;border-radius:4px;font-size:0.75em">'
                            f'{s["label"]}: {int(s["pct"]*100)}% @ {s["price"]:.2f} '
                            f'{"✅" if s["hit"] else "⏳"}'
                            f'</span>'
                            for s in steps
                        )}
                    </div>
                </div>
            </div>
        </div>"""

        summary_rows.append({
            "name": pos["name"],
            "ticker": ticker,
            "direction": direction,
            "pnl_pct": pnl_pct,
            "pnl_atr": pnl_atr,
            "trail_status": trail_status,
            "steps_done": f"{int(stp_pct*100)}%",
            "next_step": next_step["label"] if next_step else "✅ Alle",
        })

    # Summary-Tabelle
    sum_rows = ""
    for r in summary_rows:
        dc = "#00e676" if r["direction"] == "LONG" else "#ff5252"
        pc = "#00e676" if r["pnl_pct"] >= 0 else "#ff5252"
        sum_rows += f"""<tr>
            <td><b>{html.escape(r['name'])}</b></td>
            <td>{r['ticker']}</td>
            <td style="color:{dc}">{r['direction']}</td>
            <td style="color:{pc}">{r['pnl_pct']:+.1f}%</td>
            <td>{r['pnl_atr']:+.1f}x</td>
            <td style="color:#ff9800">{r['trail_status']}</td>
            <td style="color:#ff9800">{r['steps_done']}</td>
            <td>{r['next_step']}</td>
        </tr>"""

    return f"""
    <h2>🚪 Exit Management — Stairway to Heaven</h2>
    <p style="color:#888;font-size:0.85em;margin-bottom:15px">
        Automatischer Step-Out-Plan: Verkaufe Positionen in Tranchen bei steigenden ATR-Levels.
        Standard: 25% @ 1× ATR, 25% @ 2× ATR, 50% @ 3× ATR.
    </p>
    <h2 style="font-size:0.85em">📊 Übersicht ({len(positions)} Positionen)</h2>
    <table style="margin-bottom:20px">
        <tr><th>Position</th><th>Ticker</th><th>Typ</th><th>P&L</th>
        <th>ATR-P&L</th><th>Trail</th><th>Step-out</th><th>Nächster Step</th></tr>
        {sum_rows}
    </table>
    <h2 style="font-size:0.85em">📈 Stairway-Detail</h2>
    {positions_html}
    <div style="background:#151525;border:1px solid #2a2a4a;border-radius:8px;padding:12px;margin-top:10px;font-size:0.8em">
        <div style="color:#888;margin-bottom:5px"><b>Legende:</b></div>
        <div style="display:flex;gap:20px;flex-wrap:wrap">
            <span>● <span style="color:#00e676">Grün</span> = Aktueller Preis (im Plus)</span>
            <span>● <span style="color:#ff5252">Rot</span> = Aktueller Preis (im Minus)</span>
            <span>🔻 <span style="color:#ff5252">Dreieck</span> = Stop-Loss</span>
            <span>🔺 <span style="color:#ff9800">Dreieck</span> = Trailing Stop</span>
            <span>◆ <span style="color:#00e676">Diamant</span> = Take-Profit</span>
            <span>— <span style="color:#448aff">Blau</span> = Entry-Preis</span>
            <span>✅ <span style="color:#00e676">Grün</span> = Step erreicht</span>
            <span>⏳ <span style="color:#ff9800">Orange</span> = Step aktiv</span>
        </div>
    </div>
    """


def build_thematic_section():
    try:
        from dashboard_thematic import get_thematic_data, build_thematic_html
        data = get_thematic_data()
        return build_thematic_html(data)
    except Exception as e:
        return f'<div style="color:#ff5252;padding:20px">Thematic-Dashboard nicht verfügbar: {e}</div>'


# ─── HTTP Handler ─────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            page = build_html(get_data())
            # #1: Wenn ein DASHBOARD_TOKEN gesetzt ist, in jedes POST-Formular ein
            # verstecktes _token-Feld einfügen, damit die Dashboard-Buttons (same-
            # origin) weiter funktionieren. Eine fremde Website kann die Seite wegen
            # Same-Origin-Policy nicht auslesen → blinde CSRF-POSTs schlagen fehl.
            token = os.environ.get("DASHBOARD_TOKEN", "")
            if token:
                tok_field = f'<input type="hidden" name="_token" value="{html.escape(token)}">'
                page = re.sub(r'(<form\b[^>]*\bmethod="POST"[^>]*>)',
                              r'\1' + tok_field, page, flags=re.IGNORECASE)
            content = page.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type","text/html; charset=utf-8")
            self.send_header("Content-Length", len(content))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode())

    def do_POST(self):
        length  = int(self.headers.get("Content-Length", 0))
        body    = self.rfile.read(length).decode("utf-8")
        params  = {k: v[0] for k, v in parse_qs(body).items()}
        path    = urlparse(self.path).path
        success = False
        msg     = ""

        # #1: Zugriffskontrolle für Mutationen (POST). Konsistente Regeln:
        #   1) DASHBOARD_TOKEN gesetzt  → Token ist Pflicht (Header X-Dashboard-Token
        #      oder Formfeld _token). Schützt gegen CSRF/Drive-by aus dem Browser
        #      eines LAN-Geräts (eine fremde Website kennt den Token nicht).
        #   2) Kein Token + Bind non-local (0.0.0.0) → Mutationen GESPERRT
        #      (offenes LAN-Dashboard ohne jede Prüfung wäre der RCE/CSRF-Vektor).
        #   3) Kein Token + Bind 127.0.0.1 → erlaubt (nur lokal erreichbar).
        required = os.environ.get("DASHBOARD_TOKEN", "")
        bind_local = os.environ.get("DASHBOARD_BIND", "127.0.0.1") == "127.0.0.1"
        if required:
            supplied = self.headers.get("X-Dashboard-Token") or params.get("_token", "")
            if supplied != required:
                self.send_response(403)
                self.end_headers()
                self.wfile.write(b"forbidden: invalid or missing token")
                return
        elif not bind_local:
            self.send_response(403)
            self.end_headers()
            self.wfile.write(
                "Mutationen gesperrt: Dashboard ist per DASHBOARD_BIND im Netz "
                "erreichbar, aber kein DASHBOARD_TOKEN gesetzt. Bitte Token setzen."
                .encode("utf-8")
            )
            return

        try:
            sources = load_sources()

            # ── YouTube ───────────────────────────────────────────────────
            if path == "/sources/yt/add":
                name = params.get("name","").strip()
                url  = params.get("url","").strip()
                if name and url:
                    if add_yt_channel(name, url):
                        success = True; msg = f"YouTube-Kanal '{name}' hinzugefügt"

            elif path == "/sources/yt/remove":
                name = params.get("name","").strip()
                if name and remove_yt_channel(name):
                    success = True; msg = f"YouTube-Kanal '{name}' entfernt"

            # ── RSS ───────────────────────────────────────────────────────
            elif path == "/sources/rss/add":
                feed = {
                    "name":     params.get("name","").strip(),
                    "url":      params.get("url","").strip(),
                    "language": params.get("language","de"),
                    "weight":   float(params.get("weight", 1.0)),
                    "enabled":  True
                }
                if feed["name"] and feed["url"]:
                    sources["rss_feeds"].append(feed)
                    save_sources(sources)
                    success = True; msg = f"RSS Feed '{feed['name']}' hinzugefügt"

            elif path == "/sources/rss/remove":
                idx = int(params.get("idx", -1))
                if 0 <= idx < len(sources["rss_feeds"]):
                    removed = sources["rss_feeds"].pop(idx)
                    save_sources(sources)
                    success = True; msg = f"RSS Feed '{removed['name']}' entfernt"

            elif path in ("/sources/rss/enable", "/sources/rss/disable"):
                idx = int(params.get("idx", -1))
                if 0 <= idx < len(sources["rss_feeds"]):
                    sources["rss_feeds"][idx]["enabled"] = (path.endswith("enable"))
                    save_sources(sources)
                    success = True
                    name = sources["rss_feeds"][idx]["name"]
                    msg  = f"RSS Feed '{name}' {'aktiviert' if path.endswith('enable') else 'deaktiviert'}"

            elif path == "/sources/rss/weight":
                idx = int(params.get("idx", -1))
                w   = float(params.get("weight", 1.0))
                if 0 <= idx < len(sources["rss_feeds"]):
                    sources["rss_feeds"][idx]["weight"] = round(w, 1)
                    save_sources(sources)
                    success = True; msg = "Gewicht aktualisiert"

            # ── Twitter ───────────────────────────────────────────────────
            elif path == "/sources/twitter/add":
                acc = {
                    "handle":   params.get("handle","").strip().lstrip("@"),
                    "name":     params.get("name","").strip(),
                    "category": params.get("category","investor"),
                    "weight":   float(params.get("weight", 1.0)),
                    "enabled":  True
                }
                if acc["handle"] and acc["name"]:
                    sources["twitter_accounts"].append(acc)
                    save_sources(sources)
                    success = True; msg = f"@{acc['handle']} hinzugefügt"

            elif path == "/sources/twitter/remove":
                idx = int(params.get("idx", -1))
                if 0 <= idx < len(sources["twitter_accounts"]):
                    removed = sources["twitter_accounts"].pop(idx)
                    save_sources(sources)
                    success = True; msg = f"@{removed['handle']} entfernt"

            elif path in ("/sources/twitter/enable", "/sources/twitter/disable"):
                idx = int(params.get("idx", -1))
                if 0 <= idx < len(sources["twitter_accounts"]):
                    sources["twitter_accounts"][idx]["enabled"] = (path.endswith("enable"))
                    save_sources(sources)
                    success = True
                    handle = sources["twitter_accounts"][idx]["handle"]
                    msg = f"@{handle} {'aktiviert' if path.endswith('enable') else 'deaktiviert'}"

            elif path == "/sources/twitter/weight":
                idx = int(params.get("idx", -1))
                w   = float(params.get("weight", 1.0))
                if 0 <= idx < len(sources["twitter_accounts"]):
                    sources["twitter_accounts"][idx]["weight"] = round(w, 1)
                    save_sources(sources)
                    success = True; msg = "Gewicht aktualisiert"

        except Exception as e:
            msg = f"Fehler: {e}"

        # ── Thematic Routes ─────────────────────────────────────────
        try:
            if path == "/thematic/config/save":
                from dashboard_thematic import load_thematic_config, save_thematic_config
                cfg = load_thematic_config()
                for key, val in params.items():
                    if key.startswith("llm_"):
                        cfg.setdefault("llm_models", {})[key[4:]] = val
                    elif key.startswith("thresh_"):
                        cfg.setdefault("thresholds", {})[key[4:]] = float(val)
                save_thematic_config(cfg)
                msg = "LLM-Konfiguration gespeichert"; success = True

            elif path == "/thematic/merge/decide":
                queue_id = int(params.get("queue_id", 0))
                decision = params.get("decision", "")
                if queue_id > 0 and decision:
                    con = db_connect()
                    if decision == "merge":
                        from dashboard_thematic import db_connect
                        con2 = db_connect()
                        row = con2.execute(
                            "SELECT * FROM theme_merge_queue WHERE id = ?", (queue_id,)
                        ).fetchone()
                        if row:
                            con2.execute(
                                "UPDATE theme_merge_queue SET status='merged', decided_at=datetime('now'), decided_by='human' WHERE id=?",
                                (queue_id,)
                            )
                            con2.commit()
                        con2.close()
                    else:
                        from dashboard_thematic import db_connect
                        con2 = db_connect()
                        con2.execute(
                            "UPDATE theme_merge_queue SET status='kept_separate', decided_at=datetime('now'), decided_by='human' WHERE id=?",
                            (queue_id,)
                        )
                        con2.commit()
                        con2.close()
                    msg = f"Merge-Entscheidung: {decision}"; success = True
        except Exception as e:
            msg = f"Thematic-Fehler: {e}"

        # Redirect zurück mit Tab
        redirect_url = "/?tab=sources"
        if msg:
            import urllib.parse
            redirect_url += f"&msg={urllib.parse.quote(msg)}"
        self.send_response(303)
        self.send_header("Location", redirect_url)
        self.end_headers()

    def log_message(self, *args): pass


if __name__ == "__main__":
    port = 8081
    # #1: Standardmäßig NUR localhost. Für LAN-Zugriff bewusst
    # DASHBOARD_BIND=0.0.0.0 setzen – dann sollte DASHBOARD_TOKEN gesetzt sein.
    bind = os.environ.get("DASHBOARD_BIND", "127.0.0.1")
    if bind != "127.0.0.1" and not os.environ.get("DASHBOARD_TOKEN"):
        print("⚠ WARNUNG: Dashboard bindet auf", bind,
              "ohne DASHBOARD_TOKEN – Mutationen (POST) sind gesperrt.", flush=True)
    print(f"🌐 Dashboard läuft auf http://{bind}:{port}")
    HTTPServer((bind, port), Handler).serve_forever()
