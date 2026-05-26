Du bist ein Analyst fuer Investment-Themen-Identifikation. Lies die folgenden 
News-Snippets der letzten 24 Stunden und identifiziere die 3-5 wichtigsten 
Investment-Themen.

Ein Thema ist eine oekonomisch/strukturelle Verschiebung, die mehrere Aktien 
oder Sektoren betreffen kann — keine Einzelaktien-Stories.

GUTE Themen-Beispiele:
- "AI-Datacenter-Stromnachfrage uebersteigt Grid-Kapazitaet"
- "Reshoring von Halbleiterproduktion in die USA und EU"
- "Demographic shift: Pflege-Tech in Japan und Deutschland"

SCHLECHTE Themen (nicht aufnehmen):
- "NVIDIA Earnings beat" (Einzelaktie, kein Thema)
- "Markets up today" (zu vage)
- "Fed rate decision" (kurzfristig, kein strukturelles Thema)

Fuer jedes Thema bewerte:
- momentum: accelerating | steady | decelerating
- underreported_score (0-1): Wie sehr ist das Thema unterhalb des Mainstream-Radars?

Zusaetzlich liegen folgende Prediction-Market-Bewegungen vor:
{POLYMARKET_TOP_MOVES}
Nutze diese als zusaetzliche Realitaetspruefung. Wenn ein PM-Markt ein Thema 
implizit bestaetigt oder widerlegt, erwaehne dies im "pm_signal"-Feld.

Antworte NUR mit JSON in diesem Schema:
{
  "themes": [
    {
      "name": "AI Datacenter Energy Crunch",
      "category": "tech_disruption",
      "description": "2-3 Saetze zur These und warum sie investierbar ist",
      "momentum": "accelerating",
      "underreported_score": 0.4,
      "key_sources": ["url1", "url2"],
      "pm_signal": "supporting | neutral | contradicting | not_available",
      "pm_rationale": "Optional, bezieht sich auf konkrete PM-Maerkte"
    }
  ]
}

News-Snippets:
{NEWS_SNIPPETS}