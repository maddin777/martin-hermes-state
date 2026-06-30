"""
Dashboard Thematic — Erweiterung des bestehenden Dashboards.
Neue Tabs: Briefing, Theme Watchlist, Themes, Thesis Health,
Prediction Markets, Merge Queue, Drawdown, Tax, LLM Config.
Nutzt Jinja2 fuer Templates + Tailwind CSS + Alpine.js (CDN).
"""
import json
import os
import sqlite3
import re
from datetime import date, datetime

DB_PATH = os.path.join(
    os.path.dirname(__file__), "data", "trading.db"
)
THEMATIC_DIR = os.path.join(os.path.dirname(__file__), "thematic")
CONFIG_PATH = os.path.join(THEMATIC_DIR, "config", "thematic_config.json")
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates", "thematic")

DB_PATH_ABS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "trading.db"
)


def db_connect():
    con = sqlite3.connect(DB_PATH_ABS)
    con.row_factory = sqlite3.Row
    return con


def load_thematic_config():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def save_thematic_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


# ─── Data Queries ─────────────────────────────────────────────────────────

def get_thematic_data():
    """Sammelt alle Daten fuer die Thematic-Tabs."""
    con = db_connect()
    cfg = load_thematic_config()

    today = date.today().isoformat()

    # Briefing
    briefing = con.execute(
        "SELECT * FROM briefings ORDER BY date DESC LIMIT 1"
    ).fetchone()

    # Themes
    themes = [dict(t) for t in con.execute("""
        SELECT t.*, COUNT(b.id) as beneficiary_count
        FROM theme_definitions t
        LEFT JOIN theme_beneficiaries b ON t.id = b.theme_id AND b.status != 'archived'
        GROUP BY t.id
        ORDER BY t.last_seen DESC
        LIMIT 20
    """).fetchall()]

    # Active Beneficiaries (Watchlist)
    beneficiaries = [dict(b) for b in con.execute("""
        SELECT b.*, t.name as theme_name, t.momentum as theme_momentum
        FROM theme_beneficiaries b
        JOIN theme_definitions t ON b.theme_id = t.id
        WHERE b.status IN ('candidate', 'watching', 'in_position')
        ORDER BY t.last_seen DESC, b.llm_confidence_count DESC
        LIMIT 50
    """).fetchall()]

    # Ergaenze Factor Scores + Setup Zones
    for b in beneficiaries:
        fs = con.execute(
            "SELECT composite_score FROM factor_scores WHERE ticker = ? ORDER BY date DESC LIMIT 1",
            (b["ticker"],)
        ).fetchone()
        b["composite_score"] = fs["composite_score"] if fs else None

        sz = con.execute(
            "SELECT setup_type, strength FROM setup_zones WHERE ticker = ? AND date = ?",
            (b["ticker"], today)
        ).fetchall()
        b["setups"] = [dict(s) for s in sz] if sz else []

    # Thesis Health
    thesis_health = [dict(t) for t in con.execute("""
        SELECT tsl.*, p.name as position_name
        FROM thesis_status_log tsl
        LEFT JOIN positions p ON tsl.position_id = p.id
        WHERE tsl.id IN (
            SELECT MAX(id) FROM thesis_status_log
            GROUP BY ticker
        )
        ORDER BY tsl.check_date DESC, tsl.ticker
    """).fetchall()]

    # Prediction Markets
    pm_markets = [dict(m) for m in con.execute("""
        SELECT * FROM prediction_markets
        WHERE status = 'active'
        ORDER BY total_volume_usd DESC
        LIMIT 30
    """).fetchall()]

    # Merge Queue
    merge_queue = [dict(m) for m in con.execute("""
        SELECT mq.*, td.name as existing_theme_name
        FROM theme_merge_queue mq
        LEFT JOIN theme_definitions td ON mq.candidate_existing_id = td.id
        WHERE mq.status = 'pending'
        ORDER BY mq.created_at DESC
    """).fetchall()]

    # Drawdown
    drawdowns = [dict(d) for d in con.execute("""
        SELECT * FROM drawdown_log ORDER BY date DESC LIMIT 20
    """).fetchall()]

    system_state = {}
    for row in con.execute("SELECT key, value FROM system_state"):
        system_state[row["key"]] = row["value"]

    # Tax
    tax = None
    tax_row = con.execute(
        "SELECT * FROM tax_year_tracking WHERE year = ?", (date.today().year,)
    ).fetchone()
    if tax_row:
        tax = dict(tax_row)

    # Historische Briefings
    briefing_dates = [dict(b) for b in con.execute(
        "SELECT id, date, red_alerts_count, yellow_alerts_count FROM briefings ORDER BY date DESC LIMIT 30"
    ).fetchall()]

    con.close()

    return {
        "cfg": cfg,
        "today": today,
        "briefing": dict(briefing) if briefing else None,
        "briefing_dates": briefing_dates,
        "themes": themes,
        "beneficiaries": beneficiaries,
        "thesis_health": thesis_health,
        "pm_markets": pm_markets,
        "merge_queue": merge_queue,
        "drawdowns": drawdowns,
        "system_state": system_state,
        "tax": tax,
    }


# ─── HTML Builders (im BaseHTTPRequestHandler-Stil) ───────────────────────

def build_thematic_tabs_html(data):
    """Baut HTML fuer alle Thematic-Tabs."""
    parts = []
    parts.append(build_llm_config_tab(data))
    parts.append(build_briefing_tab(data))
    parts.append(build_watchlist_tab(data))
    parts.append(build_themes_tab(data))
    parts.append(build_thesis_health_tab(data))
    parts.append(build_pm_tab(data))
    parts.append(build_merge_queue_tab(data))
    parts.append(build_drawdown_tab(data))
    parts.append(build_tax_tab(data))
    return "\n".join(parts)


def build_llm_config_tab(data):
    cfg = data["cfg"]
    models = cfg.get("llm_models", {})
    thresholds = cfg.get("thresholds", {})

    rows = ""
    for key, val in models.items():
        rows += f"""
        <tr>
            <td style="font-weight:bold;color:#ffd740">{key}</td>
            <td>
                <input type="text" name="llm_{key}" value="{val}"
                    style="width:100%;background:#0a0a1a;border:1px solid #2a2a4a;color:#e0e0e0;padding:6px 10px;border-radius:4px">
            </td>
        </tr>"""

    threshold_rows = ""
    for key, val in thresholds.items():
        threshold_rows += f"""
        <tr>
            <td style="font-size:0.85em;color:#888">{key}</td>
            <td>
                <input type="text" name="thresh_{key}" value="{val}"
                    style="width:100px;background:#0a0a1a;border:1px solid #2a2a4a;color:#ffd740;padding:4px 8px;border-radius:4px;text-align:center">
            </td>
        </tr>"""

    return f"""
    <div id="tab-thematic-config" class="tab-content">
        <h2>⚙️ LLM Konfiguration</h2>
        <div style="background:#151525;border:1px solid #2a2a4a;border-radius:8px;padding:20px;margin-bottom:15px">
            <div style="color:#00d4ff;font-weight:bold;margin-bottom:15px">🧠 LLM-Modelle (OpenRouter / Grok Lite)</div>
            <p style="color:#888;font-size:0.85em;margin-bottom:15px">
                Alle Modelle sind konfigurierbar. Budget-Tipp: Gemini 2.0 Flash ist guenstig (ca. 0,10 USD/M input).
                Grok Lite laeuft ueber GROK_LITE_API_KEY. OpenRouter-Modelle koennen jedes verfuegbare Modell sein.
            </p>
            <form method="POST" action="/thematic/config/save">
                <table><tr><th>Aufgabe</th><th>Modell (OpenRouter-ID oder grok-lite)</th></tr>
                {rows}
                </table>
                <button type="submit" style="margin-top:15px;background:#00d4ff22;border:1px solid #00d4ff;color:#00d4ff;padding:8px 20px;border-radius:6px;cursor:pointer">
                    💾 LLM-Konfiguration speichern
                </button>
            </form>
        </div>
        <div style="background:#151525;border:1px solid #2a2a4a;border-radius:8px;padding:20px">
            <div style="color:#00d4ff;font-weight:bold;margin-bottom:15px">📏 Thresholds</div>
            <form method="POST" action="/thematic/config/save">
                <table>{threshold_rows}</table>
                <button type="submit" style="margin-top:15px;background:#00d4ff22;border:1px solid #00d4ff;color:#00d4ff;padding:8px 20px;border-radius:6px;cursor:pointer">
                    💾 Thresholds speichern
                </button>
            </form>
        </div>
    </div>"""


def build_briefing_tab(data):
    briefing = data.get("briefing")
    dates = data.get("briefing_dates", [])

    if not briefing:
        content = "<div style='color:#555;padding:40px;text-align:center'>Noch kein Briefing generiert — laeuft taeglich 07:00</div>"
    else:
        content = f"""
        <div style="background:#0d0d1a;border:1px solid #2a2a4a;border-radius:8px;padding:25px;font-family:monospace;font-size:0.9em;line-height:1.7;max-height:70vh;overflow-y:auto">
            <div style="color:#00d4ff;font-weight:bold;margin-bottom:10px">📋 Briefing vom {briefing['date']}</div>
            <div style="white-space:pre-wrap">{briefing['content_md']}</div>
        </div>"""

    date_options = ""
    for d in dates:
        alerts = f"🔴{d['red_alerts_count']} 🟡{d['yellow_alerts_count']}"
        selected = "selected" if d["id"] == (briefing.get("id") if briefing else None) else ""
        date_options += f'<option value="{d["id"]}" {selected}>{d["date"]} ({alerts})</option>'

    return f"""
    <div id="tab-thematic-briefing" class="tab-content">
        <h2>📋 Heutiges Briefing</h2>
        <div style="display:flex;gap:10px;align-items:center;margin-bottom:15px">
            <form method="GET" action="/thematic/briefing" style="display:flex;gap:10px">
                <select name="id" style="background:#0a0a1a;border:1px solid #2a2a4a;color:#e0e0e0;padding:8px;border-radius:6px">
                    {date_options}
                </select>
                <button type="submit" style="background:#00d4ff22;border:1px solid #00d4ff;color:#00d4ff;padding:8px 16px;border-radius:6px;cursor:pointer">
                    📅 Laden
                </button>
            </form>
        </div>
        {content}
    </div>"""


def build_watchlist_tab(data):
    bens = data.get("beneficiaries", [])
    rows = ""
    for b in bens:
        ticker = b["ticker"]
        composite = b.get("composite_score")
        comp_str = f"{composite:.0f}" if composite is not None else "–"
        cc = "color:#00e676" if composite and composite >= 70 else \
             "color:#ffd740" if composite and composite >= 50 else "color:#888"

        setups = b.get("setups", [])
        timing = "READY" if any(s["setup_type"] != "OVERBOUGHT_WARNING" and s["strength"] > 0 for s in setups) else \
                 "OVERBOUGHT" if any(s["setup_type"] == "OVERBOUGHT_WARNING" for s in setups) else "NEUTRAL"
        tc = "color:#00e676" if timing == "READY" else \
             "color:#ff5252" if timing == "OVERBOUGHT" else "color:#ffd740"

        conf = b.get("llm_confidence_count", 0)
        conf_str = f"{conf}/3"

        rows += f"""
        <tr>
            <td><b>{ticker}</b></td>
            <td>{b.get('company_name', '–')}</td>
            <td style="font-size:0.85em">{b.get('theme_name', '–')[:30]}</td>
            <td>{b.get('play_type', '–')}</td>
            <td style="{cc};font-weight:bold;text-align:center">{comp_str}</td>
            <td style="{tc};font-weight:bold;text-align:center">{timing}</td>
            <td style="text-align:center">{conf_str}</td>
            <td style="font-size:0.8em">{b.get('added_date', '–')}</td>
        </tr>"""

    if not rows:
        rows = '<tr><td colspan="8" style="text-align:center;color:#555;padding:20px">Keine Beneficiaries</td></tr>'

    return f"""
    <div id="tab-thematic-watchlist" class="tab-content">
        <h2>🎯 Theme Watchlist ({len(bens)} Kandidaten)</h2>
        <table>
            <tr><th>Ticker</th><th>Name</th><th>Theme</th><th>Play Type</th>
            <th style="text-align:center">Composite</th>
            <th style="text-align:center">Timing</th>
            <th style="text-align:center">LLM-Konsens</th>
            <th>Hinzugefuegt</th></tr>
            {rows}
        </table>
    </div>"""


def build_themes_tab(data):
    themes = data.get("themes", [])
    rows = ""
    for t in themes:
        pm = t.get("pm_confirmation_status") or "no_data"
        pm_emoji = "🎯" if pm == "supporting" else "⚡" if pm == "mixed" else "—"
        rows += f"""
        <tr>
            <td><b>{t['name'][:40]}</b></td>
            <td>{t.get('category', '–')}</td>
            <td>{t.get('first_detected', '–')}</td>
            <td style="text-align:center">{t.get('beneficiary_count', 0)}</td>
            <td style="text-align:center">{t.get('momentum', '–')}</td>
            <td style="text-align:center">{pm_emoji}</td>
            <td style="text-align:center">{t.get('underreported_score', 0):.1f}</td>
        </tr>"""

    if not rows:
        rows = '<tr><td colspan="7" style="text-align:center;color:#555;padding:20px">Keine aktiven Themen</td></tr>'

    return f"""
    <div id="tab-thematic-themes" class="tab-content">
        <h2>🌐 Themes ({len(themes)} aktiv)</h2>
        <table>
            <tr><th>Name</th><th>Kategorie</th><th>Erkannt</th>
            <th style="text-align:center">Beneficiaries</th>
            <th style="text-align:center">Momentum</th>
            <th style="text-align:center">PM</th>
            <th style="text-align:center">Underreported</th></tr>
            {rows}
        </table>
    </div>"""


def build_thesis_health_tab(data):
    health = data.get("thesis_health", [])
    rows = ""
    for h in health[:30]:
        sc = "color:#00e676" if h["status"] == "INTACT" else \
             "color:#ffd740" if h["status"] == "WEAKENING" else "color:#ff5252"
        rows += f"""
        <tr>
            <td>{h.get('position_name', '–')}</td>
            <td><b>{h['ticker']}</b></td>
            <td style="{sc};font-weight:bold">{h['status']}</td>
            <td style="text-align:center">{h['confidence']:.0%}</td>
            <td style="font-size:0.85em">{h.get('check_date', '–')}</td>
            <td style="font-size:0.8em;max-width:300px;overflow:hidden">{h.get('rationale', '–')[:120]}</td>
        </tr>"""

    if not rows:
        rows = '<tr><td colspan="6" style="text-align:center;color:#555;padding:20px">Keine Thesis-Checks</td></tr>'

    return f"""
    <div id="tab-thematic-thesis" class="tab-content">
        <h2>🩺 Position Thesis Health</h2>
        <table>
            <tr><th>Position</th><th>Ticker</th><th>Status</th>
            <th style="text-align:center">Confidence</th><th>Datum</th><th>Rationale</th></tr>
            {rows}
        </table>
    </div>"""


def build_pm_tab(data):
    pm_markets = data.get("pm_markets", [])
    rows = ""
    for m in pm_markets[:20]:
        d7 = m.get("delta_7d") or 0
        dc = "color:#00e676" if d7 > 0 else "color:#ff5252"
        rows += f"""
        <tr>
            <td style="max-width:350px;overflow:hidden;font-size:0.85em">{m.get('question', '–')[:100]}</td>
            <td>{m.get('category', '–')}</td>
            <td style="text-align:center;font-weight:bold">{m.get('current_yes_price', 0):.2f}</td>
            <td style="{dc};text-align:center;font-weight:bold">{d7:+.3f}</td>
            <td style="text-align:center">${m.get('volume_24h_usd', 0):,.0f}</td>
        </tr>"""

    if not rows:
        rows = '<tr><td colspan="5" style="text-align:center;color:#555;padding:20px">Keine PM-Daten</td></tr>'

    return f"""
    <div id="tab-thematic-pm" class="tab-content">
        <h2>📊 Prediction Markets</h2>
        <table>
            <tr><th>Market</th><th>Kategorie</th>
            <th style="text-align:center">Yes-Preis</th>
            <th style="text-align:center">Delta 7d</th>
            <th style="text-align:center">Vol 24h</th></tr>
            {rows}
        </table>
    </div>"""


def build_merge_queue_tab(data):
    queue = data.get("merge_queue", [])
    rows = ""
    for m in queue:
        try:
            new_data = json.loads(m.get("new_theme_data", "{}"))
            new_name = new_data.get("name", "?")
        except json.JSONDecodeError:
            new_name = "?"

        rows += f"""
        <tr>
            <td><b>{new_name}</b></td>
            <td>{m.get('existing_theme_name', '?')}</td>
            <td style="text-align:center;font-weight:bold;color:#ffd740">{m.get('similarity_score', 0):.3f}</td>
            <td style="font-size:0.8em">{m.get('created_at', '–')[:10]}</td>
            <td>
                <form method="POST" action="/thematic/merge/decide" style="display:inline">
                    <input type="hidden" name="queue_id" value="{m['id']}">
                    <input type="hidden" name="decision" value="merge">
                    <button type="submit" style="background:#00d4ff22;border:1px solid #00d4ff;color:#00d4ff;padding:3px 10px;border-radius:4px;cursor:pointer;font-size:0.8em">Merge</button>
                </form>
                <form method="POST" action="/thematic/merge/decide" style="display:inline;margin-left:5px">
                    <input type="hidden" name="queue_id" value="{m['id']}">
                    <input type="hidden" name="decision" value="separate">
                    <button type="submit" style="background:#ff525222;border:1px solid #ff5252;color:#ff5252;padding:3px 10px;border-radius:4px;cursor:pointer;font-size:0.8em">Separate</button>
                </form>
            </td>
        </tr>"""

    if not rows:
        rows = '<tr><td colspan="5" style="text-align:center;color:#555;padding:20px">Keine pending Reviews</td></tr>'

    return f"""
    <div id="tab-thematic-merge" class="tab-content">
        <h2>🔀 Theme Merge Queue ({len(queue)} pending)</h2>
        <table>
            <tr><th>Neues Theme</th><th>Bestehendes Theme</th>
            <th style="text-align:center">Similarity</th><th>Datum</th><th>Aktion</th></tr>
            {rows}
        </table>
    </div>"""


def build_drawdown_tab(data):
    dds = data.get("drawdowns", [])
    state = data.get("system_state", {})

    is_paused = state.get("system_paused") == "true"
    pause_since = state.get("pause_timestamp", "?")
    eligible = state.get("reactivation_eligible_at", "?")

    rows = ""
    for d in dds[:15]:
        tc = "color:#00e676" if d.get("drawdown_pct", 0) > -5 else \
             "color:#ffd740" if d.get("drawdown_pct", 0) > -10 else "color:#ff5252"
        rows += f"""
        <tr>
            <td>{d.get('date', '–')}</td>
            <td style="text-align:right">{d.get('portfolio_value', 0):,.2f}€</td>
            <td style="text-align:right">{d.get('all_time_high', 0):,.2f}€</td>
            <td style="{tc};text-align:right;font-weight:bold">{d.get('drawdown_pct', 0):.2f}%</td>
            <td style="font-weight:bold">{d.get('trigger_level', 'none').upper()}</td>
        </tr>"""

    pause_html = ""
    if is_paused:
        pause_html = f"""
        <div style="background:#ff525211;border:2px solid #ff5252;border-radius:8px;padding:20px;margin-bottom:15px">
            <div style="color:#ff5252;font-size:1.2em;font-weight:bold;margin-bottom:10px">🛑 SYSTEM PAUSIERT</div>
            <p>Pausiert seit: {pause_since}</p>
            <p>Reaktivierung moeglich ab: {eligible}</p>
        </div>"""

    return f"""
    <div id="tab-thematic-drawdown" class="tab-content">
        <h2>📉 Portfolio Drawdown</h2>
        {pause_html}
        <table>
            <tr><th>Datum</th><th style="text-align:right">Portfolio</th>
            <th style="text-align:right">ATH</th><th style="text-align:right">Drawdown</th><th>Trigger</th></tr>
            {rows}
        </table>
    </div>"""


def build_tax_tab(data):
    tax = data.get("tax")
    if not tax:
        content = "<div style='color:#555;padding:40px;text-align:center'>Noch keine Steuerdaten</div>"
    else:
        net = tax.get("net_realized_eur", 0)
        nc = "color:#00e676" if net >= 0 else "color:#ff5252"
        content = f"""
        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:15px">
            <div style="background:#151525;border:1px solid #2a2a4a;border-radius:8px;padding:15px;text-align:center">
                <div style="color:#888;font-size:0.75em">Realisierte Gewinne</div>
                <div style="color:#00e676;font-size:1.4em;font-weight:bold">{tax.get('realized_gains_eur', 0):+,.2f}€</div>
            </div>
            <div style="background:#151525;border:1px solid #2a2a4a;border-radius:8px;padding:15px;text-align:center">
                <div style="color:#888;font-size:0.75em">Realisierte Verluste</div>
                <div style="color:#ff5252;font-size:1.4em;font-weight:bold">{tax.get('realized_losses_eur', 0):,.2f}€</div>
            </div>
            <div style="background:#151525;border:1px solid #2a2a4a;border-radius:8px;padding:15px;text-align:center">
                <div style="color:#888;font-size:0.75em">Netto</div>
                <div style="{nc};font-size:1.4em;font-weight:bold">{net:+,.2f}€</div>
            </div>
        </div>
        <div style="background:#151525;border:1px solid #2a2a4a;border-radius:8px;padding:15px;margin-top:15px">
            <div style="color:#00d4ff;font-weight:bold;margin-bottom:10px">Steuerschaetzung {tax.get('year', date.today().year)}</div>
            <p>Sparerpauschbetrag: {tax.get('sparerpauschbetrag_eur', 0):.2f}€</p>
            <p>Davon genutzt: {tax.get('sparerpauschbetrag_used', 0):.2f}€</p>
            <p style="font-weight:bold;color:#ffd740">Geschaetzte Steuerlast: {tax.get('estimated_tax_liability_eur', 0):.2f}€</p>
        </div>"""

    return f"""
    <div id="tab-thematic-tax" class="tab-content">
        <h2>💶 Tax Summary</h2>
        {content}
    </div>"""


def build_thematic_style():
    return """
    <style>
        .thematic-tab-nav { display:flex; gap:3px; margin-bottom:15px; border-bottom:1px solid var(--border); padding-bottom:0; flex-wrap:wrap; }
        .thematic-tab-btn { padding:8px 14px; background:transparent; border:none; color:#888;
                   cursor:pointer; font-size:0.82em; border-bottom:2px solid transparent;
                   transition:all 0.2s; white-space:nowrap; }
        .thematic-tab-btn.active { color:var(--accent); border-bottom-color:var(--accent); }
        .thematic-tab-btn:hover { color:var(--text); }
        .tab-content { display:none; }
        .tab-content.active { display:block; }
    </style>
    <script>
    function showThematicTab(name) {
        document.querySelectorAll('#thematic-tabs .tab-content').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('#thematic-tabs .thematic-tab-btn').forEach(b => b.classList.remove('active'));
        const el = document.getElementById('tab-thematic-' + name);
        if (el) el.classList.add('active');
        event.target.classList.add('active');
        history.replaceState(null, '', '?tab=thematic&sub=' + name);
    }
    </script>"""


def build_thematic_html(data):
    """Komplettes HTML fuer die Thematic-Sektion."""
    style = build_thematic_style()
    tabs = build_thematic_tabs_html(data)

    return f"""
    {style}
    <h1 style="margin-top:20px">🎓 Hermes Thematic Terminal</h1>
    <div id="thematic-tabs">
        <div class="thematic-tab-nav">
            <button class="thematic-tab-btn active" onclick="showThematicTab('briefing')">📋 Briefing</button>
            <button class="thematic-tab-btn" onclick="showThematicTab('watchlist')">🎯 Watchlist</button>
            <button class="thematic-tab-btn" onclick="showThematicTab('themes')">🌐 Themes</button>
            <button class="thematic-tab-btn" onclick="showThematicTab('thesis')">🩺 Thesis Health</button>
            <button class="thematic-tab-btn" onclick="showThematicTab('pm')">📊 PM</button>
            <button class="thematic-tab-btn" onclick="showThematicTab('merge')">🔀 Merge Queue</button>
            <button class="thematic-tab-btn" onclick="showThematicTab('drawdown')">📉 Drawdown</button>
            <button class="thematic-tab-btn" onclick="showThematicTab('tax')">💶 Tax</button>
            <button class="thematic-tab-btn" onclick="showThematicTab('config')">⚙️ LLM Config</button>
        </div>
        {tabs}
    </div>
    """