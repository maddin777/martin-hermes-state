Klassifiziere folgenden Polymarket-Markt:

QUESTION: {question}
CATEGORY: {category}
RESOLUTION DATE: {resolution_date}

AKTIVE THEMES IM SYSTEM:
{list_of_active_theme_names_and_descriptions}

Beantworte:
1. Welche Aktien-Tickers waeren betroffen, falls der Markt zu YES resolved?
   (Long-Beneficiaries)
2. Welche Tickers waeren negativ betroffen?
3. Zu welchem der aktiven Themes passt dieser Markt am besten? 
   (Theme-ID oder "none")
4. Staerke der Verknuepfung: strong | moderate | weak | none

Antworte NUR mit JSON:
{
  "related_tickers_positive": ["RHM.DE", "LMT"],
  "related_tickers_negative": ["BABA"],
  "related_theme_ids": [42],
  "connection_strength": "strong",
  "rationale": "1-2 Saetze"
}