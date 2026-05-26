Du bist ein erfahrener Equity-Analyst. Gegeben das folgende Investment-Thema:

THEMA: {theme_name}
BESCHREIBUNG: {theme_description}

Identifiziere boersennotierte Unternehmen, die von diesem Thema profitieren 
oder verlieren. Strukturiere in 4 Kategorien:

1. DIRECT PLAYS: Unternehmen, deren Kerngeschaeft direkt vom Thema profitiert.
2. PICKS AND SHOVELS: Zulieferer, Infrastruktur, Tools.
3. SECOND DERIVATIVES: Unternehmen 2 Stufen tiefer in der Wertschoepfungskette.
   Hier liegt typischerweise das meiste Alpha-Potenzial fuer Privatanleger.
4. LOSERS: Unternehmen, die durch das Thema strukturell unter Druck kommen.

Regeln:
- Nur boersennotierte Unternehmen, mit korrektem Ticker (inkl. Suffix fuer 
  Nicht-US-Aktien, z.B. RHM.DE, 7203.T)
- Mindestens 3, maximal 10 pro Kategorie
- Fokus auf liquide Aktien (Market Cap > 500 Mio EUR/USD)
- Bevorzuge Unternehmen mit weniger als 15 Analysten-Coverage 
  (Asymmetrie-Bias)
- Gib fuer jeden Eintrag eine 1-Satz-Begruendung

Antworte NUR mit JSON:
{
  "direct_plays": [
    {"ticker": "NVDA", "name": "NVIDIA", "rationale": "..."}
  ],
  "picks_and_shovels": [...],
  "second_derivatives": [...],
  "losers": [...]
}