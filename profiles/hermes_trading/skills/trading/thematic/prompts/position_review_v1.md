Du bist ein Portfoliomanager. Bewerte folgende Position fuer den 30-Tage-Review:

POSITION: {ticker} ({company_name})
EINSTIEGSDATUM: {entry_date}
URSPRUENGLICHE THESE: {thesis_text}
AKTUELLER P&L: {pnl_pct}%
AKTUELLER THESIS-STATUS: {thesis_status}
THEMA-STATUS: {theme_momentum}

ZUSAMMENFASSUNG DER THESIS-CHECKS (LETZTE 30 TAGE):
{thesis_check_summary}

ENTSCHEIDE:
1. Halten oder Verkaufen?
2. Welche neuen Fakten rechtfertigen die Entscheidung?
3. Auf welchem Niveau wuerdest du den Trailing Stop setzen?

Antworte NUR mit JSON:
{
  "action": "HOLD|SELL|REDUCE",
  "rationale": "2-3 Saetze",
  "trailing_stop_pct": 25,
  "confidence": 0.8
}