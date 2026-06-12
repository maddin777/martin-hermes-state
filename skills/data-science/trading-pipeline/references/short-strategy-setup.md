# Short Strategy Setup (11.06.2026)

## Problem

Das System hatte 43 LONG- vs. 1 SHORT-Trade. Shorts waren strukturell unsichtbar, obwohl:
- `calculate_conviction_bear()` existierte und `conviction_score_bear` korrekt berechnet wurde
- `tech_direction='SHORT'` war in der Watchlist vorhanden (11 Kandidaten)
- Signal-Manager hatte SHORT-Logik (`allow_short`, `min_confidence_short`, separate Query)

**Drei unsichtbare Blockaden:**

1. **Tech-Scores nur für Bull-Kandidaten** — `watchlist_manager.py` (Zeile 572) updatete `tech_score`/`tech_direction` nur für Top 20 nach `conviction_score` (bullish). Short-Kandidaten mit hohem `conviction_score_bear` aber niedrigem `conviction_score` bekamen nie yfinance-Daten → `tech_score IS NOT NULL` scheiterte → nie in Short-Query.

2. **`min_mentions` = 2 für Shorts** — `signal_manager.py` (Zeile 680) nutzte `cfg.get("min_mentions", 2)` für die Short-Query. Bearish Mentions sind seltener als bullish → kaum Shorts erreichten 2 Mentions.

3. **Keine Short-Quellen** — RSS-Feeds (Seeking Alpha, Bloomberg, etc.) waren bullish. Keine bearish/konträren Quellen.

## Implementierte Änderungen

### 1. config/sources.json — 3 neue RSS-Feeds

```json
{"name": "ZeroHedge", "url": "https://www.zerohedge.com/rss.xml", "weight": 1.5},
{"name": "MishTalk", "url": "https://mimikater.net/feed/", "weight": 1.2},
{"name": "HighShortInterest", "url": "https://highshortinterest.com/rss/", "weight": 1.8}
```

ZeroHedge = konträr/bearish Makro. MishTalk = makro-kritisch. HighShortInterest = Short-Interest-Daten (höchstes Gewicht 1.8).

### 2. watchlist_manager.py — Dualer Tech-Score-Pfad

Vorher: Nur Top 20 nach `conviction_score` (bullish).
Nachher: Top 20 nach `conviction_score` PLUS Top 20 nach `conviction_score_bear`, dedupliziert.

```python
candidates_long = con.execute("""
    SELECT * FROM watchlist WHERE status='watching'
    AND conviction_score >= ? AND mention_count >= ? AND ticker IS NOT NULL
    ORDER BY conviction_score DESC LIMIT 20
""", (MIN_CONVICTION * 0.5, 1)).fetchall()

candidates_short = con.execute("""
    SELECT * FROM watchlist WHERE status='watching'
    AND conviction_score_bear >= ? AND mention_count >= 1 AND ticker IS NOT NULL
    ORDER BY conviction_score_bear DESC LIMIT 20
""", (MIN_CONVICTION * 0.5,)).fetchall()

top_candidates = candidates_long + [
    c for c in candidates_short
    if c["ticker"] not in {x["ticker"] for x in candidates_long}
]
```

Print zeigt `🔻` für Short-Kandidaten und `ShortConv:` im Log.

### 3. data/strategy_config.json — Short-Parameter

```json
"min_confidence_short": 0.5,
"min_mentions_short": 1
```

`min_confidence_short` von 0.65 auf 0.5 gesenkt (= niedrigere Hürde für Short-Entries).  
Neuer Key `min_mentions_short: 1` (statt 2 für LONG).

### 4. signal_manager.py — Separater Mention-Parameter für Shorts

```python
cfg.get("min_confidence_short", 0.5),
cfg.get("min_mentions_short", 1)  # vorher: cfg.get("min_mentions", 2)
```

## Post-Fix Status

**Sofort qualifizierte Kandidaten (vor Pipeline-Neulauf):**
- Berkshire Hathaway (BRK-B): bear_conviction=0.643, 12 Mentions, tech_direction=SHORT
- Walmart (WMT): bear_conviction=0.514, 5 Mentions, tech_direction=SHORT

**Regime-Kontext:** SIDEWAYS (82.5%) + macro=neutral → SHORT erlaubt, max 3 Short-Slots.

**Nächster Pipeline-Lauf:** 04:00 UTC — Signal-Manager evaluiert Shorts automatisch.

## get_technical_score() Direction-Logik

In `utils.py` `get_technical_score()`:

```python
direction = "LONG" if score >= 2 else "SHORT" if score <= -2 else "NEUTRAL"
```

Scale: -10 bis +10. Score setzt sich aus 7 Indikatoren zusammen:

| Indikator | Bullish | Bearish | Max Impact |
|-----------|---------|---------|------------|
| EMA Stack (20>50>200) | +1 | -1 | ±1 |
| RSI | +2 (ideal) | -2 (überkauft/überverkauft) | ±2 |
| MACD Histogram | +2 (steigend positiv) | -2 (fallend negativ) | ±2 |
| Preis vs EMA50 | +1 (>5% drüber) | -1 (>5% drunter) | ±1 |
| Volumen | +1.5 (stark erhöht) | 0 | +1.5 |
| Weekly Trend | +1 | -1 | ±1 |
| ADX | +1 (>25) | -0.5 (<15) | ±1 |

**Asymmetrie:** Short-Seite ist schwerer zu erreichen weil (a) die Quellen bullish sind und (b) Short-Kandidaten niedrige Mention-Counts haben → conviction_score_bear bleibt niedrig.

## Backtesting

Backtester (`backtester.py`) unterstützt SHORT bereits:
```python
elif direction == "SHORT":
    # simuliert als Knockout-Zertifikat 1x Hebel
```