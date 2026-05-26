Du bewertest, ob eine Investment-These noch intakt ist.

POSITION: {ticker} ({company_name})
URSPRUENGLICHE THESE: {thesis_text}
THEMA: {theme_name} — {theme_description}
ENTRY-DATUM: {entry_date}

NEWS DER LETZTEN 24H:
{news_snippets_with_urls}

RELEVANTE PREDICTION MARKETS:
{prediction_markets_with_prices_and_deltas}
Format:
- Polymarket "Will Israel-Iran ceasefire hold through 2026?": 
  Current 0.34, 7d ago 0.18 (+89% relative) → STRENGTHENING ceasefire scenario
- Polymarket "Fed rate cut by July?": 
  Current 0.62, 7d ago 0.71 (-13% relative) → WEAKENING dovish expectations

Beantworte strukturiert:
1. Ist die Kernannahme der These noch gueltig? (ja/nein/teilweise)
2. Gibt es neue Fakten, die der These direkt widersprechen?
3. Wie passen die PM-Bewegungen zur These?
4. Hat sich die Markt-Narrative zum Thema verschoben?
5. Gesamtbewertung: INTACT | WEAKENING | BROKEN
6. Confidence (0-1)

Sei konservativ mit BROKEN — markiere es nur bei klaren faktischen 
Widerlegungen oder massiven PM-Bewegungen (>30% relativ in 7d gegen die These).
WEAKENING ist die typische Vorwarnstufe.

Antworte NUR mit JSON:
{
  "core_assumption_valid": "yes|no|partial",
  "contradicting_facts": "..." or null,
  "pm_signal_assessment": "supporting|neutral|contradicting|not_applicable",
  "narrative_shift": "..." or null,
  "verdict": "INTACT|WEAKENING|BROKEN",
  "confidence": 0.85,
  "rationale": "2-3 Saetze",
  "triggering_urls": ["url1", "url2"],
  "triggering_pm_markets": ["market_id_1"]
}