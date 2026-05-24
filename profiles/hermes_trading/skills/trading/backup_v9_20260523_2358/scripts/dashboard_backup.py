"""Trading Dashboard - Modernisiertes Layout"""
import sqlite3, json, os, subprocess, html
from collections import deque
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

DB_PATH     = "/root/.hermes/profiles/hermes_trading/skills/trading/data/trading.db"
CONFIG_PATH = "/root/.hermes/profiles/hermes_trading/skills/trading/data/strategy_config.json"
LOG_PATH    = "/root/.hermes/profiles/hermes_trading/skills/trading/data/cron.log"

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {"starting_capital":10000,"total_trades":0,"winning_trades":0,
            "atr_sl_multiplier":1.5,"atr_tp_multiplier":3.0,"min_confidence":0.65,
            "max_positions":4}

def get_last_run(script_name):
    import re
    last_done_ts  = None
    last_start_ts = None
    last_status   = "–"
    try:
        if not os.path.exists(LOG_PATH): return None, "kein Log"
        with open(LOG_PATH, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        for line in lines:
            line = line.strip()
            if script_name not in line: continue
            m = re.search(r"===\s+(.+?)\s+===", line)
            ts = m.group(1).strip() if m else None
            if "DONE" in line and ts:
                last_done_ts = ts
                last_status  = "OK"
            elif "START" in line and ts:
                last_start_ts = ts
            elif "---" in line and ts:
                last_done_ts = ts
                last_status  = "OK"
        if last_start_ts and not last_done_ts:
            last_status = "Fehler"
            return last_start_ts, last_status
        return last_done_ts, last_status
    except:
        return None, "Fehler"

def get_cron_jobs():
    descriptions = {
        "yt_channel_monitor":  "YouTube Kanäle scannen (11 Kanäle)",
        "signal_extractor":    "KI-Analyse Transkripte (Gemini)",
        "watchlist_manager":   "Watchlist + Conviction Score",
        "technical_validator": "Technische Analyse (EMA/RSI/MACD)",
        "signal_manager":      "Signale + Portfolio Management",
        "strategy_optimizer":  "Selbstverbesserung Grid Search",
        "fundamental_data":    "FRED Makro + SEC Insider + PCR",
        "social_scanner":      "RSS Feeds + Twitter/X Scan",
        "export_watchlist":    "Watchlist Export Obsidian",
        "active_exit_check":   "Tech-Check + Profit-Sicherung",
        "db_backup":           "Datenbank Backup Obsidian",
    }
    try:
        output = subprocess.run(["crontab","-l"], capture_output=True, text=True).stdout
        jobs = []
        for line in output.splitlines():
            line = line.strip()
            if not line or line.startswith("#"): continue
            if not any(k in line for k in ["yt_channel","signal_","technical_validator","watchlist_manager","strategy_optimizer","trading_db","fundamental_data","social_scanner","export_watchlist","active_exit_check"]):
                continue
            parts = line.split()
            if len(parts) < 6: continue
            
            minute, hour, dow = parts[0], parts[1], parts[4]
            script_path = next((p for p in parts if ".py" in p), "")
            script_name = script_path.split("/")[-1].replace(".py","")
            desc = descriptions.get(script_name, script_name)
            dow_str = "Mo-Fr" if dow == "1-5" else dow
            
            # Zeit für die Anzeige formatieren
            time_display = f"{hour.zfill(2)}:{minute.zfill(2)}" if minute.isdigit() and hour.isdigit() else f"{hour}:{minute}"
            
            # Hilfsvariable für die Sortierung (immer HH:MM)
            sort_time = f"{hour.zfill(2)}:{minute.zfill(2)}" if hour.isdigit() else "99:99"

            if "check_only" in line:
                time_display = f"{hour}:00 (h)"
                desc = "SL/TP prüfen"
                
            mode = " [full]" if "full" in parts else " [check]" if "check_only" in parts else ""
            last_ts, last_status = get_last_run(script_name)
            
            jobs.append({
                "time": time_display, 
                "sort_key": sort_time, # Neues Feld für die Sortierung
                "days": dow_str, 
                "script": script_name+mode, 
                "desc": desc, 
                "last_run": last_ts or "–", 
                "last_status": last_status
            })
        
        # Sortierung nach der sort_time (Uhrzeit aufsteigend)
        jobs.sort(key=lambda x: x["sort_key"])
        
        return jobs
    except:
        return []

def get_log_lines():
    try:
        lines = deque(maxlen=50)
        with open(LOG_PATH, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip(): lines.append(line.rstrip('\n'))
        return list(lines)
    except: return ["Log nicht verfügbar"]

def get_data():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cfg = load_config()
    portfolio = con.execute("SELECT * FROM portfolio WHERE id=1").fetchone()
    open_pos  = con.execute("SELECT * FROM positions WHERE status='open' ORDER BY entry_date DESC").fetchall()
    closed    = con.execute("SELECT * FROM positions WHERE status='closed' ORDER BY exit_date DESC LIMIT 20").fetchall()
    total_pnl = sum(p["pnl_eur"] or 0 for p in con.execute("SELECT pnl_eur FROM positions WHERE status='closed'").fetchall())
    win_rate  = (cfg["winning_trades"]/cfg["total_trades"]*100 if cfg["total_trades"]>0 else 0)
    cash      = portfolio["cash"] if portfolio else cfg["starting_capital"]
    
    open_val = sum(p["position_size"] or 0 for p in con.execute("SELECT position_size FROM positions WHERE status='open'").fetchall())
    open_pnl = sum(p["pnl_eur"] or 0 for p in con.execute("SELECT pnl_eur FROM positions WHERE status='open'").fetchall())
    
    total_value = cash + open_val + open_pnl
    total_return = (total_value - cfg["starting_capital"]) / cfg["starting_capital"] * 100
    
    try:
        watchlist = [dict(w) for w in con.execute("SELECT * FROM watchlist WHERE status='watching' ORDER BY conviction_score DESC LIMIT 30").fetchall()]
    except: watchlist = []
    con.close()

    return {
        "watchlist": watchlist, "open_pos": [dict(p) for p in open_pos], "closed": [dict(p) for p in closed],
        "cfg": cfg, "cron_jobs": get_cron_jobs(), "log_lines": get_log_lines(),
        "stats": {
            "total_pnl": round(total_pnl, 2), "win_rate": round(win_rate, 1), "total_trades": cfg["total_trades"],
            "total_return": round(total_return, 2), "total_value": round(total_value, 2), "cash": round(cash, 2), "start_cap": cfg["starting_capital"]
        }
    }

def build_html(data):
    s = data["stats"]
    cfg = data["cfg"]
    
    import yfinance as yf

    open_rows = ""
    for p in data["open_pos"]:
        direction_label = '<span style="color:#00e676">LONG</span>' if p["direction"]=="LONG" else '<span style="color:#ff5252">SHORT</span>'
        
        # Standardwerte falls Abfrage fehlschlägt
        current_str = "–"
        pnl_eur_str = "–"
        pnl_pct_str = "–"
        pnl_color = "color:#888"

        try:
            # Live-Preis abrufen
            t = yf.Ticker(p['ticker'])
            # fast_info ist sehr schnell und stabil
            current_price = t.fast_info['last_price']
            
            if current_price and p['entry_price']:
                raw_pnl_pct = (current_price - p['entry_price']) / p['entry_price']
                if p['direction'] == 'SHORT':
                    raw_pnl_pct = -raw_pnl_pct
                
                raw_pnl_eur = raw_pnl_pct * p['position_size']
                
                pnl_color = "color:#00e676" if raw_pnl_eur >= 0 else "color:#ff5252"
                current_str = f"{current_price:.2f}"
                pnl_eur_str = f"{raw_pnl_eur:+.2f}€"
                pnl_pct_str = f"{raw_pnl_pct*100:+.1f}%"
        except Exception as e:
            # Falls yfinance mal hakt, bleibt es bei "–"
            pass

        open_rows += f"""<tr>
            <td>{p['name']}</td>
            <td>{p['ticker']}</td>
            <td>{direction_label}</td>
            <td>{p['entry_price']:.2f}</td>
            <td style="font-weight:bold">{current_str}</td>
            <td style="{pnl_color};font-weight:bold">{pnl_eur_str}</td>
            <td style="{pnl_color};font-weight:bold">{pnl_pct_str}</td>
            <td style="color:#ff5252">{p['stop_loss']:.2f}</td>
            <td style="color:#00e676">{p['take_profit']:.2f}</td>
            <td>{p['position_size']:.0f}€</td>
            <td>{p['entry_date'][:10]}</td>
            <td style="font-size:0.8em;color:#888">{p.get('source_channel','')}</td>
        </tr>"""
    
    closed_rows = ""
    for p in data["closed"]:
        c = "color:#00e676" if (p.get("pnl_eur") or 0)>0 else "color:#ff5252"
        closed_rows += f"<tr><td>{p['name']}</td><td>{p['ticker']}</td><td>{p['direction']}</td><td>{p['entry_price']:.2f}</td><td>{p.get('exit_price',0):.2f}</td><td style='{c}'>{p.get('pnl_eur',0):+.2f}€</td><td style='{c}'>{p.get('pnl_pct',0):+.1f}%</td><td>{p.get('exit_reason','')}</td><td>{(p.get('exit_date') or '')[:10]}</td></tr>"

    cron_rows = ""
    for j in data["cron_jobs"]:
        sc = "color:#00e676" if j['last_status']=="OK" else "color:#ff5252"
        cron_rows += f"<tr><td>{j['time']}</td><td>{j['days']}</td><td>{j['script']}</td><td>{j['desc']}</td><td style='font-size:0.8em'>{j['last_run']}</td><td style='{sc};font-weight:bold'>{j['last_status']}</td></tr>"

    log_rows = ""
    for line in data["log_lines"]:
        style = "color:#00e676;font-weight:bold" if "===" in line else "color:#2196f3" if "---" in line else ""
        log_rows += f'<tr><td style="font-family:monospace;padding:8px 10px;{style}">{html.escape(line)}</td></tr>'

    rc = "color:#00e676" if s["total_return"]>=0 else "color:#ff5252"

    return f"""<!DOCTYPE html>
<html lang="de"><head>
<meta charset="UTF-8"><meta http-equiv="refresh" content="60">
<title>Hermes Trading Dashboard</title>
<style>
    :root {{ --bg: #0a0a12; --card: #151525; --border: #2a2a4a; --accent: #00d4ff; --text: #e0e0e0; }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); padding: 20px; line-height: 1.4; }}
    h1 {{ color: var(--accent); margin-bottom: 20px; font-size: 1.6em; }}
    h2 {{ color: var(--accent); margin: 25px 0 12px; font-size: 0.9em; text-transform: uppercase; letter-spacing: 1px; border-left: 3px solid var(--accent); padding-left: 10px; }}
    
    .top-container {{ display: grid; grid-template-columns: 1fr 380px; gap: 20px; margin-bottom: 20px; }}
    .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; }}
    .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 12px; }}
    .card .label {{ font-size: 0.65em; color: #888; text-transform: uppercase; font-weight: bold; }}
    .card .value {{ font-size: 1.2em; font-weight: bold; margin-top: 4px; }}
    
    .quick-source {{ background: rgba(0, 212, 255, 0.05); border: 1px dashed var(--accent); border-radius: 8px; padding: 15px; font-size: 0.85em; }}
    .quick-source b {{ color: var(--accent); }}
    code {{ background: #000; color: #00e676; padding: 2px 5px; border-radius: 3px; font-family: monospace; display: inline-block; margin-top: 4px; }}

    .strategy-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin-bottom: 20px; }}
    .strat-card {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 15px; }}
    .strat-card h3 {{ font-size: 0.75em; color: var(--accent); margin-bottom: 10px; text-transform: uppercase; }}
    .strat-item {{ display: flex; justify-content: space-between; font-size: 0.85em; margin-bottom: 5px; border-bottom: 1px solid #222; padding-bottom: 2px; }}
    .strat-item span:last-child {{ font-weight: bold; color: #ffd740; }}

    table {{ width: 100%; border-collapse: collapse; background: var(--card); border-radius: 8px; overflow: hidden; margin-bottom: 20px; border: 1px solid var(--border); }}
    th {{ background: #1e1e38; padding: 10px; text-align: left; font-size: 0.7em; color: #888; text-transform: uppercase; }}
    td {{ padding: 10px; border-bottom: 1px solid var(--border); font-size: 0.85em; }}
    .footer {{ color: #444; font-size: 0.7em; text-align: center; margin-top: 30px; }}
</style></head><body>

<h1>📊 Hermes Trading Terminal</h1>

<div class="top-container">
    <div class="stats-grid">
        <div class="card"><div class="label">Portfolio</div><div class="value" style="color:var(--accent)">{s['total_value']}€</div></div>
        <div class="card"><div class="label">Return</div><div class="value" style="{rc}">{s['total_return']:+.1f}%</div></div>
        <div class="card"><div class="label">P&L Gesamt</div><div class="value">{s['total_pnl']}€</div></div>
        <div class="card"><div class="label">Win Rate</div><div class="value">{s['win_rate']}%</div></div>
        <div class="card"><div class="label">Cash</div><div class="value">{s['cash']}€</div></div>
        <div class="card"><div class="label">Trades</div><div class="value">{s['total_trades']}</div></div>
    </div>
    <div class="quick-source">
        <b>➕ Quellen hinzufügen</b><br>
        🎬 YouTube-Kanal (Konsole): <code>/trading-add-channel URL "Name"</code><br>
        📰 RSS / 🐦 Twitter: <code>skills/trading/config/sources.json</code>
    </div>
</div>

<h2>📂 Aktive Positionen ({len(data['open_pos'])}/{cfg.get('max_positions',4)})</h2>
<table>
    <tr><th>Unternehmen</th><th>Ticker</th><th>Typ</th><th>Entry</th><th>Aktuell</th><th>P&L €</th><th>P&L %</th><th>SL</th><th>TP</th><th>Größe</th><th>Datum</th><th>Quelle</th></tr>
    {open_rows}
</table>

<h2>📋 Strategie & Konfiguration</h2>
<div class="strategy-grid">
    <div class="strat-card">
        <h3>⚙️ Risk & Size</h3>
        <div class="strat-item"><span>High Conv. (80%)</span><span>20% Portf.</span></div>
        <div class="strat-item"><span>Normal (60%)</span><span>15% Portf.</span></div>
        <div class="strat-item"><span>Max Positions</span><span>{cfg.get("max_positions",8)}</span></div>
    </div>
    <div class="strat-card">
        <h3>🚪 Exit Parameter</h3>
        <div class="strat-item"><span>Stop-Loss</span><span>{cfg.get('atr_sl_multiplier',1.5)}x ATR</span></div>
        <div class="strat-item"><span>Take-Profit</span><span>{cfg.get('atr_tp_multiplier',3.0)}x ATR</span></div>
        <div class="strat-item"><span>Min. Confid.</span><span>{int(cfg.get('min_confidence',0.65)*100)}%</span></div>
    </div>
    <div class="strat-card">
        <h3>📡 Scanner Status</h3>
        <div class="strat-item"><span>YouTube</span><span>11 Kanäle</span></div>
        <div class="strat-item"><span>News</span><span>RSS & X/Twitter</span></div>
        <div class="strat-item"><span>Insider</span><span>SEC Form 4</span></div>
    </div>
    <div class="strat-card">
        <h3>🛠 System</h3>
        <div class="strat-item"><span>Kapital</span><span>{cfg.get("starting_capital",10000):.0f}€</span></div>
        <div class="strat-item"><span>Check-Interval</span><span>15:30 / 10:00</span></div>
        <div class="strat-item"><span>Version</span><span>Hermes v3.2</span></div>
    </div>
</div>

<h2>⏰ Automatisierung (Cron)</h2>
<table>
    <tr><th>Zeit</th><th>Tage</th><th>Script</th><th>Beschreibung</th><th>Letzter Run</th><th>Status</th></tr>
    {cron_rows}
</table>

<h2>📜 System-Logs</h2>
<table style="background:#05050a;">{log_rows}</table>

<div class="footer">Auto-Refresh alle 60s | {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}</div>
</body></html>"""

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            content = build_html(get_data()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type","text/html; charset=utf-8")
            self.send_header("Content-Length",len(content))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode())
    def log_message(self, *args): pass

if __name__ == "__main__":
    port = 8081
    print(f"🌐 Dashboard läuft auf http://0.0.0.0:{port}")
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
