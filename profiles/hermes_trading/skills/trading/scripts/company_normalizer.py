"""
company_normalizer.py – Zentrale Firmenname-Normalisierung (Shared-Modul)

Konsolidiert die zuvor doppelte Implementierung aus:
  - watchlist_manager.py   (122 Aliases)
  - watchlist_dedup.py     (161 Aliases)

Die beiden Dicts wurden vereinigt (203 Keys, 4 Konflikte manuell gelöst).

Importieren mit:
    from company_normalizer import normalize_company_name, NORMALIZE_ALIASES
    from company_normalizer import LEGAL_SUFFIX_RE, BRACKET_NOTE_RE
"""
import re

# ── Alias-Tabelle ─────────────────────────────────────────────────────────────
# Vereinigung aus watchlist_manager.py + watchlist_dedup.py.
# Konflikte gelöst:
#   - advanced micro devices → 'Advanced Micro Devices' (Firmenname, nicht Ticker)
#   - mara holdings / marathon digital holdings → 'MARA Holdings' (aktueller Name)

NORMALIZE_ALIASES = {
    # ── LLM-Tippfehler ────────────────────────────────────────────────────────
    "palantier":           "Palantir",
    "palanteer":           "Palantir",
    "reinmetall":          "Rheinmetall",
    "reimmetall":          "Rheinmetall",
    "corweef":             "CoreWeave",
    "core weave":          "CoreWeave",
    "nebiuz":              "Nebius",
    "enhropic":            "Anthropic",
    "entropic":            "Anthropic",
    "anropic":             "Anthropic",
    "tüssenkrup":          "ThyssenKrupp",
    "tüssengrup":          "ThyssenKrupp",
    "morgen stanley":      "Morgan Stanley",
    "rocketlab":           "Rocket Lab",
    "soundhoundai":        "SoundHound AI",
    "soundhound":          "SoundHound AI",
    "solar edge":          "SolarEdge",
    "johnson und johnson": "Johnson & Johnson",
    "albe male":           "Alphabet",
    "poo gold":            "Poo Gold",
    "service now":         "ServiceNow",
    "marvel":              "Marvell",
    "d w v quantum":       "D-Wave Quantum",
    "zalandos e":          "Zalando",
    "zaland se":           "Zalando",
    "standard chartered pl": "Standard Chartered",
    # ── Firmenname-Varianten ──────────────────────────────────────────────────
    "3i group plc":                            "3i Group",
    "8x8, inc.":                               "8x8",
    "abn amro bank n.v.":                      "ABN AMRO Bank",
    "adidas ag":                               "Adidas",
    "adobe inc.":                              "Adobe",
    "advanced micro devices":                  "Advanced Micro Devices",
    "agco corporation":                        "AGCO",
    "agilysys inc.":                           "Agilysys",
    "agnico eagle mines":                      "Agnico Eagle Mines",
    "alibaba group":                           "Alibaba",
    "allied gold corporation":                 "Allied Gold",
    "alphabet inc.":                           "Alphabet",
    "alphabet inc. (google)":                  "Alphabet",
    "altria group, inc.":                      "Altria",
    "amazon.com":                              "Amazon",
    "amazon.com inc.":                         "Amazon",
    "amd":                                     "AMD",
    "amer sports inc.":                        "Amer Sports",
    "american tower corporation":              "American Tower",
    "american water works":                    "American Water Works",
    "americas gold and silver corporation":    "Americas Gold and Silver",
    "apple inc.":                              "Apple",
    "arm holdings plc":                        "ARM",
    "asml holding":                            "ASML",
    "astrazeneca plc":                         "AstraZeneca",
    "atlas copco ab":                          "Atlas Copco",
    "bae systems plc":                         "BAE Systems",
    "basf se":                                 "BASF",
    "bayer ag":                                "Bayer",
    "bechtle ag":                              "Bechtle",
    "berkshire hathaway inc.":                 "Berkshire Hathaway",
    "booking holdings":                        "Booking Holdings",
    "booking":                                 "Booking Holdings",   # nach Holdings-Strip
    "by company":                              "BYD",
    "cerebras systems":                        "Cerebras",
    "cerebras systems inc.":                   "Cerebras",
    "cisco":                                   "Cisco",
    "cisco systems":                           "Cisco",
    "coca-cola co.":                           "Coca-Cola",
    "commerzbank ag":                          "Commerzbank",
    "costco wholesale":                        "Costco",
    "costco wholesale corporation":            "Costco",
    "cts eventim ag & co. kgaa":               "CTS Eventim",
    "d-wave quantum inc.":                     "D-Wave Quantum",
    "d-wave systems":                          "D-Wave Quantum",
    "d-wave systems inc.":                     "D-Wave Quantum",
    "deckers brands":                          "Deckers Outdoor",
    "delivery hero se":                        "Delivery Hero",
    "delta airlines":                          "Delta Air Lines",
    "deutsche bank ag":                        "Deutsche Bank",
    "domino's pizza":                          "Dominos Pizza",
    "dws group gmbh & co. kgaa":               "DWS",
    "e.l.f. beauty":                           "e.l.f.",
    "essity ab":                               "Essity",
    "exxon mobil":                             "Exxon",
    "fiserv, inc.":                            "Fiserv, Inc.",
    "fiserv, inc. (fisv)":                     "Fiserv, Inc.",
    "ge aerospace":                            "GE Aerospace",
    "gemini space station inc.":               "Gemini Space",
    "goldman sachs group":                     "Goldman Sachs",
    "googl":                                   "Alphabet",
    "gsk plc":                                 "GSK",
    "hannover rück":                           "Hannover Rück",
    "henkel ag & co. kgaa":                    "Henkel",
    "hilton worldwide holdings inc.":          "Hilton Worldwide Holdings",
    "hims & hers health":                      "Hims & Hers",
    "hochtief ag":                             "Hochtief",
    "hubspot, inc.":                           "HubSpot",
    "hyundai motor company":                   "Hyundai Motor",
    "ibm":                                     "IBM",
    "infineon technologies":                   "Infineon",
    "infineon technologies ag":                "Infineon",
    "innoviz technologies":                    "Innoviz",
    "intc":                                    "Intel",
    "intel corporation":                       "Intel",
    "intuit inc.":                             "Intuit",
    "intuitive surgical":                      "Intuitive Surgical",
    "itaú":                                    "Itaú Unibanco",
    "jabil inc.":                              "Jabil",
    "john deere":                              "Deere & Company",
    "johnson & johnson (jnj)":                 "Johnson & Johnson",
    "jp morgan":                               "JPMorgan",
    "jp morgan chase":                         "JPMorgan",
    "jpmorgan chase":                          "JPMorgan",
    "kingsoft corporation":                    "Kingsoft",
    "kws saat se & co. kgaa":                  "KWS SAAT",
    "linde plc":                               "Linde",
    "lvmh moet hennessy louis vuitton":        "LVMH",
    "lvmh moët hennessy louis vuitton":        "LVMH",
    "macy's":                                  "Macy",
    "mara holdings":                           "MARA Holdings",
    "mara":                                    "MARA Holdings",      # nach Holdings-Strip
    "marathon digital holdings":               "MARA Holdings",
    "marathon digital holdings inc.":          "MARA Holdings",
    "marathon digital":                        "MARA Holdings",  # nach Holdings-Strip
    "marvell technology":                      "Marvell",
    "marvell technology, inc.":                "Marvell",
    "mastercard inc.":                         "Mastercard",
    "mcdonald's corporation":                  "McDonald's",
    "mercado libre":                           "MercadoLibre",
    "mercedes-benz group":                     "Mercedes-Benz",
    "merck kgaa":                              "Merck",
    "meta":                                    "Meta",
    "meta platforms":                          "Meta",
    "meta platforms inc.":                     "Meta",
    "meta platforms, inc.":                    "Meta",
    "micron technology":                       "Micron",
    "microsoft corporation":                   "Microsoft",
    "microstrategy incorporated":              "MicroStrategy",
    "msft":                                    "Microsoft",
    "mtu":                                     "MTU Aero Engines",
    "munich re":                               "Münchner Rück",
    "münchener rück":                          "Münchner Rück",
    "n holdings":                              "Nu Holdings",
    "netflix inc.":                            "Netflix",
    "nextracker inc.":                         "Nextracker",
    "nibe industrier ab":                      "Nibe Industrier",
    "novo nordisk a/s":                        "Novo Nordisk",
    "nu holdings":                             "Nu Holdings",
    "nu":                                      "Nu Holdings",        # nach Holdings-Strip
    "nubank":                                  "NuBank",
    "nvidia":                                  "NVIDIA",
    "nvidia corp.":                            "NVIDIA",
    "nvidia corporation":                      "NVIDIA",
    "nxp semiconductor":                       "NXP Semiconductors",
    "on holding":                              "On",
    "ottobock se & co. kgaa":                  "Ottobock",
    "palantir technologies":                   "Palantir",
    "palo alto networks":                      "Palo Alto",
    "paypal holdings":                         "PayPal",
    "pepsico inc.":                            "PepsiCo",
    "qualcomm incorporated":                   "Qualcomm",
    "reddit inc.":                             "Reddit, Inc.",
    "reddit, inc.":                            "Reddit, Inc.",
    "renk group ag":                           "Renk Group",
    "rheinmetall ag":                          "Rheinmetall",
    "royal caribbean cruises ltd.":            "Royal Caribbean",
    "rwe ag":                                  "RWE",
    "salesforce inc.":                         "Salesforce",
    "samsung electronics":                     "Samsung",
    "scalable capital":                        "Scalable Capital",
    "schneider electric se":                   "Schneider Electric",
    "semiconductor manufacturing international corporation": "SMIC",
    "siemens ag":                              "Siemens",
    "siemens aktiengesellschaft":              "Siemens",
    "siltronic ag":                            "Siltronic",
    "sk hynix inc.":                           "SK Hynix",
    "sma solar technology ag":                 "SMA Solar Technology",
    "snowflake inc.":                          "Snowflake",
    "softbank group":                          "SoftBank",
    "softbank group corp.":                    "SoftBank",
    "standard chartered plc":                  "Standard Chartered",
    "strategy":                                "Strategy",
    "stroer se & co. kgaa":                    "Ströer",
    "taiwan semiconductor":                    "TSMC",
    "taiwan semiconductor manufacturing company":          "TSMC",
    "taiwan semiconductor manufacturing company limited":  "TSMC",
    "taiwan semiconductor manufacturing":                  "TSMC",  # nach Company-Strip
    "take two interactive":                    "Take-Two Interactive",
    "take two interactive software":           "Take-Two Interactive",
    "take-two interactive software":           "Take-Two Interactive",
    "team, inc.":                              "Team",
    "telefonica sa":                           "Telefónica",
    "the trade desk":                          "Trade Desk",
    "thyssenkrupp ag":                         "ThyssenKrupp",
    "uber technologies":                       "Uber",
    "under armour inc.":                       "Under Armour",
    "uniper se":                               "Uniper",
    "united health":                           "UnitedHealth",
    "united rentals":                          "United Rentals",
    "upstart holdings, inc. (upst)":           "Upstart",
    "vestas wind systems a/s":                 "Vestas",
    "vibra energia s.a.":                      "Vibra Energia",
    "viking holdings ltd":                     "Viking Holdings",
    "viking":                                  "Viking Holdings",    # nach Holdings-Strip
    "vinci sa":                                "Vinci",
    "visa inc.":                               "Visa",
    "vodafone group plc":                      "Vodafone",
    "volvo ab":                                "Volvo",
    "walmart inc.":                            "Walmart",
    "watches of switzerland group plc":        "Watches of Switzerland",
    "weir group plc":                          "Weir Group",
    "wells fargo & company":                   "Wells Fargo",
}


# ── Regex-Konstanten ──────────────────────────────────────────────────────────

LEGAL_SUFFIX_RE = re.compile(
    r"(?:\s*[,/]\s*)?"
    r"(?:"
    r"AG(?:\s+&?\s*Co\.?\s*(?:KGaA|KG|OHG))?"
    r"|SE|GmbH(?:\s*&\s*Co\.?\s*(?:KG|KGaA|OHG))?"
    r"|PLC|plc|Inc\.|Inc|Corporation|Corp\.?|Corp"
    r"|Ltd\.?|Limited|LLC|LLP|LP|NV|N\.V\.|SA|S\.A\.|AB|OY"
    r"|S\.p\.A\.|Sp\.? z\.?o\.?o\.?|JSC|PJSC|OJSC"
    r"|Holdings?|Group|Co\.|Company"
    r"|Class\s+[ABCDE]|Common\s+Stock"
    r")(?:\.|\s)*$",
    re.IGNORECASE
)

BRACKET_NOTE_RE = re.compile(
    r"\s*\((?:nicht\s+börsennotiert|Marke\s+von[^)]*|privat[^)]*|Teil\s+von[^)]*)\)\s*$",
    re.IGNORECASE
)


# ── Normalisierungsfunktion ───────────────────────────────────────────────────

def normalize_company_name(name: str) -> str:
    """Normalisiert Unternehmensnamen für Duplikat-Vergleiche.

    Schritte:
      1. Strip Klammer-Notizen: '(nicht börsennotiert)', '(Marke von ...)'
      2. Strip Legal-Suffixe: AG, Inc., Corporation, Ltd, PLC, SE, GmbH & Co. KGaA …
      3. Strip 'The '-Präfix
      4. Alias-Resolution via NORMALIZE_ALIASES
      5. Whitespace normalisieren
    """
    n = name.strip()
    # Klammer-Notizen entfernen
    n = BRACKET_NOTE_RE.sub("", n)
    n = re.sub(r"\s*\([^)]*[?][^)]*\)\s*$", " ", n)
    # Legal-Suffixe entfernen (iterativ für verschachtelte Formen)
    prev = None
    while prev != n:
        prev = n
        n = LEGAL_SUFFIX_RE.sub("", n).strip()
    # 'The '-Präfix entfernen
    n = re.sub(r"^The\s+", "", n)
    # Whitespace normalisieren
    n = re.sub(r"\s+", " ", n).strip()
    # Alias-Lookup (case-insensitive Key)
    lower = n.lower()
    if lower in NORMALIZE_ALIASES:
        return NORMALIZE_ALIASES[lower]
    return n
