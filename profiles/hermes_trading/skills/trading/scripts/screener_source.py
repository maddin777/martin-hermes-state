#!/usr/bin/env python3
"""
screener_source.py — Deterministische Screener-Quelle für Hermes Trading
========================================================================

Zusätzliche Kandidaten-Quelle PARALLEL zum YouTube Signal Extractor.
Läuft als Pipeline-Schritt VOR watchlist_manager und schreibt Treffer als
Mentions einer eigenen Quelle (channel='screener') in watchlist_mentions.
Dadurch fließen die Kandidaten durch die bestehende Conviction-Berechnung,
das Tech-Scoring und den Signal Manager — wie jede andere Quelle.

Ansatz "best für dieses Setup" = Momentum + Trendstruktur + Katalysator,
gehärtet durch:
  • QUALITY-GATE  – verhindert Momentum-auf-Junk (Hauptursache für Long-Blowups)
  • REGIME/VOL-OVERLAY – nutzt das bestehende Regime (regime_history / macro_signal.json):
        bear/High-VIX → weniger & strengere Longs, mehr Shorts (Momentum-Crash-Schutz)

Wiederverwendet aus dem bestehenden Code (DRY):
  utils.get_technical_score      – Momentum/Trend (EMA-Stack, RSI, MACD, ADX, Volumen)
  utils.prefetch_prices          – Batch-Download in den TTL-Cache
  utils.get_price_data_cached    – OHLCV für 52W-/Relative-Stärke-Berechnung
  config.db_connect              – zentrale DB-Connection
  company_validator-Konventionen – Registrierung in companies / company_aliases

Aufruf:
    python3 screener_source.py            # schreibt Mentions in die DB
    python3 screener_source.py --dry-run  # nur anzeigen, nichts schreiben
"""
import sys
import os
import json
from datetime import datetime

# ── Pfad-Setup wie in den anderen Pipeline-Schritten ───────────────────────────
_TRADING_ROOT = "/root/.hermes/profiles/hermes_trading/skills/trading"
_SCRIPTS_DIR  = os.path.join(_TRADING_ROOT, "scripts")
for _p in (_TRADING_ROOT, _SCRIPTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)
try:
    import env_loader  # noqa: F401  (Side-Effect: lädt .env)
except Exception:
    pass

import yfinance as yf

# yfinance-eigene ERROR-Logs (transiente "possibly delisted"-Aussetzer) dämpfen,
# damit nicht-fatale Skips keine Cron-Mails auslösen. Betrifft nur diesen
# Subprozess — jeder Pipeline-Schritt läuft separat.
import logging as _logging
_logging.getLogger("yfinance").setLevel(_logging.CRITICAL)

from config import db_connect, MACRO_SIGNAL_PATH
from utils import (get_logger, prefetch_prices, get_price_data_cached,
                   get_technical_score)

log = get_logger("screener_source")

# ════════════════════════════════════════════════════════════════════════════
# CONFIG  (kann bei Bedarf nach config.py ausgelagert werden)
# ════════════════════════════════════════════════════════════════════════════
SCREENER_CHANNEL       = "screener"   # muss = source_registry.display_name sein
BENCHMARK              = "SPY"
REL_STRENGTH_LOOKBACK  = 63           # ~3 Handelsmonate
MAX_PCT_FROM_EXTREME   = 15.0         # Long: ≤15% unter 52W-Hoch / Short: ≤15% über 52W-Tief

# Short-Seite QmJ-konform: bevorzugt schwache Fundamentals, meidet Qualitätsnamen
SHORT_MIN_PCT_ABOVE_LOW = 5.0   # kein Short direkt am 52W-Tief (Squeeze/Boden-Fishing vermeiden)
SHORT_MAX_QUALITY_BONUS = 1.0   # Quality-Goodness darüber → zu hochwertig zum Shorten → skip
MAX_UNIVERSE           = 250          # Cap für nächtliche yfinance-Last
PREFETCH_CHUNK         = 50

# Handelbare Börsen (Ticker-Suffix). "" = US (NYSE/NASDAQ, keine Endung).
# Filtert Index-/Fonds-/Asia-Ticker aus der companies-Tabelle (z.B. 000016.SZ = SSE-50-Index).
# Nur auf DE+US einengen: ALLOWED_SUFFIXES = {"", "DE"}
ALLOWED_SUFFIXES = {
    "",                                              # US
    "DE",                                            # XETRA
    "SW",                                            # SIX (CH)
    "PA", "AS", "BR", "LS", "MI", "MC",              # Euronext / Borsa Italiana / Madrid
    "HE", "ST", "CO", "VI", "IR",                    # Nordics / Wien / Dublin
    "L",                                             # London
}

# Statisches Liquiditäts-Universum (DE + US). Wird mit aktiven companies-Tickern
# vereinigt. Download-Fehler (z.B. falsches Suffix) werden still übersprungen.
DAX40 = [
    "ADS.DE","AIR.DE","ALV.DE","BAS.DE","BAYN.DE","BEI.DE","BMW.DE","BNR.DE",
    "CBK.DE","CON.DE","1COV.DE","DB1.DE","DBK.DE","DHL.DE","DTE.DE","DTG.DE",
    "EOAN.DE","FME.DE","FRE.DE","HEI.DE","HEN3.DE","HNR1.DE","IFX.DE","MBG.DE",
    "MRK.DE","MTX.DE","MUV2.DE","P911.DE","PAH3.DE","QIA.DE","RHM.DE","RWE.DE",
    "SAP.DE","SHL.DE","SIE.DE","SRT3.DE","SY1.DE","VNA.DE","VOW3.DE","ZAL.DE",
]
MDAX = [
    "AFX.DE","AT1.DE","BC8.DE","COK.DE","EVK.DE","FRA.DE","G24.DE","GXI.DE",
    "HFG.DE","HLE.DE","KGX.DE","LEG.DE","LHA.DE","NDA.DE","PUM.DE","RAA.DE",
    "SDF.DE","TEG.DE","TKA.DE","WCH.DE",
]
SP100 = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","GOOG","TSLA","BRK-B","AVGO",
    "JPM","LLY","V","UNH","XOM","MA","JNJ","PG","HD","COST","MRK","ABBV","CVX",
    "ADBE","PEP","KO","WMT","BAC","CRM","NFLX","AMD","ORCL","ACN","MCD","CSCO",
    "ABT","TMO","LIN","INTC","DIS","WFC","VZ","QCOM","INTU","TXN","IBM","AMGN",
    "CAT","GE","NOW","PM","NKE","UNP","HON","SPGI","GS","BKNG","COP","AXP",
    "NEE","RTX","LOW","T","BLK","ELV","DE","BA","MS","SBUX","MDT","GILD","LMT",
    "ADP","MDLZ","CB","C","MMC","PLD","BMY","TJX","SO","REGN","PGR","SCHW",
    "MO","BSX","CME","ZTS","USB","CI","DUK","FI","MU","PYPL","UBER","PANW",
]


# ════════════════════════════════════════════════════════════════════════════
# Reine Logik-Helfer (deterministisch, ohne Netzwerk → unit-testbar)
# ════════════════════════════════════════════════════════════════════════════
def regime_params(regime: str, vix, overlay) -> dict:
    """
    Leitet aus dem bestehenden Regime die Screener-Emissions-Parameter ab.
    max_long/max_short = wie viele Kandidaten pro Nacht emittiert werden
    (Portfolio-Limits selbst setzt weiterhin der signal_manager).
    long_conf/short_conf = Tech-Confidence-Schwellen (get_technical_score).
    """
    r = (str(regime) if regime is not None else "neutral").lower()
    p = {"max_long": 8, "max_short": 4, "long_conf": 0.65, "short_conf": 0.35}
    if r == "bull":
        p.update(max_long=10, max_short=2, long_conf=0.62, short_conf=0.32)
    elif r == "bear":
        p.update(max_long=3,  max_short=8, long_conf=0.72, short_conf=0.40)
    elif r == "sideways":
        p.update(max_long=5,  max_short=5, long_conf=0.68, short_conf=0.35)

    # Vol-Overlay: Momentum-Crashes passieren in High-Vol-Phasen → Longs drosseln.
    # overlay kann je nach DB ein String ('bearish') ODER ein numerischer Score sein
    # → nur den String-Fall als Trigger werten, VIX deckt den Vol-Teil ohnehin ab.
    try:
        vix_val = float(vix) if vix is not None else None
    except (TypeError, ValueError):
        vix_val = None
    overlay_bearish = isinstance(overlay, str) and "bear" in overlay.lower()
    if (vix_val is not None and vix_val > 25) or overlay_bearish:
        p["max_long"] = max(1, p["max_long"] // 2)
        p["long_conf"] = min(0.80, p["long_conf"] + 0.05)
    if vix_val is not None and vix_val > 30:
        p["max_long"] = max(1, p["max_long"] // 2)
        p["long_conf"] = 0.80
    return p


def quality_check(info: dict):
    """
    QmJ-lite Quality-Gate aus yfinance .info.
    Returns (label, bonus):
        'junk'    – unprofitabel UND schrumpfend (oder hoch verschuldet + Verlust) → Long skippen
        'ok'      – Quality vorhanden, bonus 0..1.5 fließt in den Long-Score
        'unknown' – keine Fundamentaldaten (z.B. dünn gecoverte DE-Titel) → kein Penalty
    """
    if not info:
        return "unknown", 0.0
    pm  = info.get("profitMargins")
    rev = info.get("revenueGrowth")
    d2e = info.get("debtToEquity")      # yfinance: in Prozent (158.9 = 1.59x)
    roe = info.get("returnOnEquity")

    if pm is not None and rev is not None and pm < 0 and rev < 0:
        return "junk", 0.0
    if d2e is not None and pm is not None and d2e > 300 and pm < 0:
        return "junk", 0.0

    if pm is None and roe is None and rev is None:
        return "unknown", 0.0

    bonus = 0.0
    if roe is not None and roe > 0.12: bonus += 0.5
    if pm  is not None and pm  > 0.08: bonus += 0.5
    if d2e is not None and d2e < 100:  bonus += 0.3
    if rev is not None and rev > 0.05: bonus += 0.3
    return "ok", round(min(bonus, 1.5), 2)


def map_strength(direction: str, conf: float, metrics: dict,
                 qbonus: float = 0.0, quality: str = None):
    """
    Bildet einen Composite-Score und mappt ihn auf strong/moderate/weak
    (= die strength-Spalte, die watchlist_manager gewichtet:
    strong=1.0, moderate=0.6, weak=0.3).
    """
    rel_c = min(abs(metrics["rel"]) / 10.0, 1.0)
    if direction == "long":
        tech_c = max(0.0, (conf - 0.5) * 4)                       # conf .75 → 1.0
        prox   = max(0.0, (MAX_PCT_FROM_EXTREME - metrics["pct_below_high"]) / MAX_PCT_FROM_EXTREME)
        composite = tech_c + rel_c + prox + qbonus
    else:
        tech_c = max(0.0, (0.5 - conf) * 4)                       # conf .25 → 1.0
        prox   = max(0.0, (MAX_PCT_FROM_EXTREME - metrics["pct_above_low"]) / MAX_PCT_FROM_EXTREME)
        # QmJ Short-Quality: Junk bestätigt den Short, hohe Quality wird bestraft
        if quality == "junk":
            quality_adj = 0.8                       # schwache Fundamentals = guter Short
        elif quality == "ok":
            quality_adj = -0.5 * qbonus             # qbonus = Goodness (0..1.5) → Malus
        else:                                       # unknown → neutral
            quality_adj = 0.0
        composite = tech_c + rel_c + prox + quality_adj

    if   composite >= 2.5: strength = "strong"
    elif composite >= 1.5: strength = "moderate"
    else:                  strength = "weak"
    return strength, round(composite, 2)


def setup_metrics(df, bench_ret: float, lookback: int = REL_STRENGTH_LOOKBACK):
    """52W-Distanz + relative Stärke vs. Benchmark aus einem OHLCV-DataFrame."""
    if df is None or df.empty:
        return None
    close = df["Close"].iloc[:, 0] if df["Close"].ndim > 1 else df["Close"]
    close = close.dropna()
    if len(close) < 200 or len(close) <= lookback:
        return None
    last   = float(close.iloc[-1])
    high52 = float(close.tail(252).max())
    low52  = float(close.tail(252).min())
    ret    = (last / float(close.iloc[-lookback]) - 1.0) * 100.0
    return {
        "last": last,
        "pct_below_high": (high52 - last) / high52 * 100.0 if high52 else 999.0,
        "pct_above_low":  (last - low52) / low52 * 100.0 if low52 else 999.0,
        "rel": ret - bench_ret,
    }


# ════════════════════════════════════════════════════════════════════════════
# Netzwerk-/DB-Helfer
# ════════════════════════════════════════════════════════════════════════════
def _current_regime():
    """Liest das aktuelle Regime aus regime_history (primär) bzw. macro_signal.json."""
    try:
        con = db_connect()
        row = con.execute(
            "SELECT * FROM regime_history ORDER BY date DESC LIMIT 1"
        ).fetchone()
        con.close()
        if row:
            cols = row.keys()
            return (row["regime"],
                    row["vix"] if "vix" in cols else None,
                    row["macro_overlay"] if "macro_overlay" in cols else None)
    except Exception as e:
        log.warning("regime_history nicht lesbar (%s)", e)
    try:
        with open(MACRO_SIGNAL_PATH) as f:
            m = json.load(f)
        return m.get("regime", "neutral"), m.get("vix"), m.get("macro_overlay")
    except Exception:
        return "neutral", None, None


def _benchmark_return(lookback: int) -> float:
    try:
        b = yf.download(BENCHMARK, period="6mo", interval="1d",
                        progress=False, auto_adjust=True)
        close = b["Close"].iloc[:, 0] if b["Close"].ndim > 1 else b["Close"]
        close = close.dropna()
        if len(close) > lookback:
            return float((close.iloc[-1] / close.iloc[-lookback] - 1.0) * 100.0)
    except Exception as e:
        log.warning("Benchmark-Return fehlgeschlagen (%s) → 0", e)
    return 0.0


def _fetch_info(ticker: str) -> dict:
    try:
        return yf.Ticker(ticker).info or {}
    except Exception:
        return {}


def _is_tradeable(ticker: str) -> bool:
    """Nur Aktien auf handelbaren Börsen. Filtert numerische Asia-/Index-/Fonds-Ticker."""
    t = (ticker or "").strip().upper()
    if not t:
        return False
    base = t.split(".")[0]
    if base.isdigit():                      # 000016.SZ, 1810.HK, 005930.KS ...
        return False
    suffix = t.split(".")[-1] if "." in t else ""
    return suffix in ALLOWED_SUFFIXES


def _build_universe() -> list:
    tickers = list(DAX40) + list(MDAX) + list(SP100)
    try:
        con = db_connect()
        rows = con.execute(
            "SELECT ticker FROM companies "
            "WHERE status='active' AND ticker IS NOT NULL "
            "AND (quote_type IS NULL OR quote_type='EQUITY')"
        ).fetchall()
        con.close()
        tickers += [r["ticker"] for r in rows]
    except Exception as e:
        log.warning("companies-Universum nicht lesbar (%s)", e)
    seen, uni = set(), []
    for t in tickers:
        t = (t or "").strip()
        if t and t.upper() not in seen and _is_tradeable(t):
            seen.add(t.upper())
            uni.append(t)
    return uni[:MAX_UNIVERSE]


def _register_source(con):
    con.execute("""
        INSERT OR IGNORE INTO source_registry
            (source_type, source_key, display_name, language, region,
             category, status, weight, enabled, added_by, discovery_reason)
        VALUES ('screener','screener',?, 'en','global','technical',
                'active',1.0,1,'system','deterministic technical+quality screen')
    """, (SCREENER_CHANNEL,))


def _register_company(con, ticker: str, info: dict) -> str:
    """Registriert Ticker idempotent in companies + company_aliases (wie company_validator)."""
    name = info.get("longName") or info.get("shortName") or ticker
    con.execute("""
        INSERT OR IGNORE INTO companies
            (ticker, canonical_name, quote_type, sector, industry,
             country, currency, isin, status, source, last_validated_at)
        VALUES (?,?,?,?,?,?,?,NULL,'active','screener',datetime('now'))
    """, (ticker, name, info.get("quoteType"), info.get("sector"),
          info.get("industry"), info.get("country"), info.get("currency")))
    for alias in {name.lower().strip(), ticker.lower().strip()}:
        if alias:
            con.execute(
                "INSERT OR IGNORE INTO company_aliases (alias, ticker) VALUES (?,?)",
                (alias, ticker))
    return name


# ════════════════════════════════════════════════════════════════════════════
# Hauptablauf
# ════════════════════════════════════════════════════════════════════════════
def _make_cand(ticker, direction, strength, composite, conf, mt, quality, info):
    extreme = (f"{mt['pct_below_high']:.0f}% unter 52W-Hoch" if direction == "long"
               else f"{mt['pct_above_low']:.0f}% über 52W-Tief")
    reason = (f"Tech {direction.upper()} conf={conf:.2f}; {extreme}; "
              f"rel {mt['rel']:+.0f} vs {BENCHMARK}; Quality={quality}")
    return {
        "ticker": ticker, "direction": direction, "strength": strength,
        "composite": composite, "reason": reason, "info": info,
    }


def main(dry_run: bool = False):
    today = datetime.now().strftime("%Y-%m-%d")
    regime, vix, overlay = _current_regime()
    p = regime_params(regime, vix, overlay)
    print(f"📡 Screener Source | Regime={regime} VIX={vix} Overlay={overlay} "
          f"→ max_long={p['max_long']} max_short={p['max_short']} "
          f"long_conf={p['long_conf']:.2f} short_conf={p['short_conf']:.2f}", flush=True)
    log.info("Screener Start | regime=%s vix=%s overlay=%s params=%s",
             regime, vix, overlay, p)

    universe = _build_universe()
    print(f"  Universum: {len(universe)} Ticker", flush=True)

    for i in range(0, len(universe), PREFETCH_CHUNK):
        prefetch_prices(universe[i:i + PREFETCH_CHUNK])

    bench_ret = _benchmark_return(REL_STRENGTH_LOOKBACK)
    print(f"  Benchmark ({BENCHMARK}) {REL_STRENGTH_LOOKBACK}d-Return: {bench_ret:+.1f}%", flush=True)

    longs, shorts = [], []
    for tkr in universe:
        try:
            tech = get_technical_score(tkr)
        except Exception:
            tech = None
        if not tech:
            continue
        _, _, df = get_price_data_cached(tkr)
        mt = setup_metrics(df, bench_ret)
        if not mt:
            continue

        direction = tech["direction"]
        conf      = tech["confidence"]

        if (direction == "LONG" and conf >= p["long_conf"]
                and mt["pct_below_high"] <= MAX_PCT_FROM_EXTREME and mt["rel"] >= 0):
            info = _fetch_info(tkr)
            quality, qbonus = quality_check(info)
            if quality == "junk":
                continue
            strength, composite = map_strength("long", conf, mt, qbonus, quality)
            longs.append(_make_cand(tkr, "long", strength, composite, conf, mt, quality, info))

        elif (direction == "SHORT" and conf <= p["short_conf"]
                and SHORT_MIN_PCT_ABOVE_LOW <= mt["pct_above_low"] <= MAX_PCT_FROM_EXTREME
                and mt["rel"] <= 0):
            info = _fetch_info(tkr)
            quality, qbonus = quality_check(info)
            # QmJ: Qualitätsnamen nicht shorten (genau das, was die Long-Seite kauft)
            if quality == "ok" and qbonus >= SHORT_MAX_QUALITY_BONUS:
                continue
            strength, composite = map_strength("short", conf, mt, qbonus, quality)
            shorts.append(_make_cand(tkr, "short", strength, composite, conf, mt, quality, info))

    longs.sort(key=lambda c: c["composite"], reverse=True)
    shorts.sort(key=lambda c: c["composite"], reverse=True)
    selected = longs[:p["max_long"]] + shorts[:p["max_short"]]
    print(f"  Treffer: {len(longs)} long / {len(shorts)} short "
          f"→ {len(selected)} emittiert (Regime-Cap)", flush=True)

    if dry_run:
        for c in selected:
            print(f"  {c['direction'].upper():5} {c['ticker']:9} {c['strength']:8} "
                  f"comp={c['composite']:.2f}  {c['reason']}", flush=True)
        print("  (dry-run: nichts in die DB geschrieben)", flush=True)
        return

    con = db_connect()
    try:
        _register_source(con)
        written = 0
        for c in selected:
            name = _register_company(con, c["ticker"], c["info"])
            con.execute("""
                INSERT OR IGNORE INTO watchlist_mentions
                    (name, channel, video_id, video_title, sentiment, strength, reason, mention_date)
                VALUES (?,?,?,?,?,?,?,?)
            """, (name, SCREENER_CHANNEL, f"screener:{c['ticker']}:{today}",
                  "Technical+Quality Screen",
                  "bullish" if c["direction"] == "long" else "bearish",
                  c["strength"], c["reason"][:500], today))
            if con.execute("SELECT changes()").fetchone()[0] > 0:
                written += 1
        con.commit()
        print(f"  ✓ {written} Screener-Mentions geschrieben "
              f"(Channel='{SCREENER_CHANNEL}')", flush=True)
    finally:
        con.close()
    print("✅ Screener Source abgeschlossen", flush=True)


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
