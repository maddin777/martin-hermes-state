# OTHER-Sektor Klassifikation für Private Companies

## Kontext

Das Trading-System weist **Asset-Typen** (TECH, STANDARD, DEFENSIVE) anhand des **Sektors** zu (siehe `config.py` → `SECTOR_TO_ASSET_TYPE`). Für börsennotierte Aktien liefert yfinance den Sektor. **Private Companies** haben keinen yfinance-Sektor → landen im `other_sector`-Catch-all → default auf STANDARD.

Das ist suboptimal: OpenAI (Technology) sollte TECH bekommen, Schwarz Gruppe (Consumer Defensive) sollte DEFENSIVE bekommen.

## Prinzip

1. **Branche ermitteln** (auch ohne yfinance): Was macht das Unternehmen?
2. **Standard-Branche zuordnen**: Technology, Financial Services, Industrials, Consumer Cyclical, Consumer Defensive, Healthcare, Energy etc.
3. **Davon Asset-Type ableiten**: über `SECTOR_TO_ASSET_TYPE` aus config.py

| Standard-Branche | Asset-Type | Begründung |
|-----------------|------------|------------|
| Technology | **TECH** | Höhere Vola, weitere Stops |
| Communication Services | **TECH** | Gleiches Vola-Profil |
| Financial Services | **STANDARD** | Normale Vola |
| Industrials | **STANDARD** | Normale Vola |
| Consumer Cyclical | **STANDARD** | Zyklisch aber nicht Tech-Vola |
| Consumer Defensive | **DEFENSIVE** | Geringe Vola, enge Stops |
| Healthcare | **DEFENSIVE** | Geringe Vola |
| Energy | **STANDARD** | Rohstoffabhängig, Mittelmaß |
| Utilities | **DEFENSIVE** | Geringe Vola |

## Bekannte Private Companies — Klassifikation

Stand Juni 2026, aus manuellem OTHER-Sektor-Review.

### Technology → TECH

| Unternehmen | Begründung |
|-------------|------------|
| OpenAI | KI-Research, Software |
| Anthropic | KI-Research, Software |
| Figma | Design-SaaS, Kollaboration |
| Depop | Social-Commerce-Plattform |
| ISI (Istituto Seraphicus Informationis) | Software/IT-Dienstleistung |
| Helsing | KI-basierte Defense-Software |
| Epic Games | Spiele-Engine (Unreal), Game-Dev |

### Financial Services → STANDARD

| Unternehmen | Begründung |
|-------------|------------|
| Bitpanda | Krypto-Broker/Exchange |
| Check24 | Vergleichsportal (Versicherung, Finanzen) |
| Citadel | Hedgefonds, Market-Making |
| Hauck & Aufhäuser | Privatbank (wenn nicht in Gruppe) |
| Icahn Enterprises | Investment-Holding (Carl Icahn) |
| Mackenzie Financial | Vermögensverwaltung (Canada) |
| Scalable Capital | Neo-Broker, Vermögensverwaltung |
| Banque FR | Französische Bank / Finanzinstitut |

### Industrials → STANDARD

| Unternehmen | Begründung |
|-------------|------------|
| SpaceX | Raumfahrt, Raketenbau |
| Robert Bosch | Automotive-Zulieferer, Industrie |
| Innio | Energieerzeugung (Gasmotoren, Jennbacher) |
| KNDS (KMW+Nexter) | Rüstung, Panzerbau |

### Consumer Cyclical → STANDARD

| Unternehmen | Begründung |
|-------------|------------|
| Audemars Piguet | Luxusuhren (discretionary spending) |
| Everlane | Mode-E-Commerce (Direct-to-Consumer) |
| New Balance | Sportschuhe, Bekleidung |
| Shein | Fast-Fashion E-Commerce |

### Consumer Defensive → DEFENSIVE

| Unternehmen | Begründung |
|-------------|------------|
| Schwarz Gruppe | Lidl, Kaufland — Supermarkt (nicht-zyklisch) |

## Umsetzung

Die Klassifikation sollte in `config.py` als **separate Map** liegen, nicht im `SECTOR_TO_ASSET_TYPE`-Dict (das auf yfinance-Sektoren basiert). Vorschlag:

```python
# Private Company Sector Mapping (manuell gepflegt)
# Wird verwendet wenn yfinance keinen Sektor liefert (z.B. OTHER)
PRIVATE_COMPANY_SECTORS = {
    "OPENAI": "Technology",
    "ANTHROPIC": "Technology",
    "FIGMA": "Technology",
    "HELSING": "Technology",
    "DEPOP": "Technology",
    "ISI": "Technology",
    "BITPANDA": "Financial Services",
    "CHECK24": "Financial Services",
    "CITADEL": "Financial Services",
    "HAUCK": "Financial Services",
    "ICAHN": "Financial Services",
    "MACKENZIE": "Financial Services",
    "SCALABLE": "Financial Services",
    "BANQUE": "Financial Services",
    "SPACEX": "Industrials",
    "BOSCH": "Industrials",
    "INNIO": "Industrials",
    "KNDS": "Industrials",
    "AUDEMARS": "Consumer Cyclical",
    "EVERLANE": "Consumer Cyclical",
    "NEW BALANCE": "Consumer Cyclical",
    "SHEIN": "Consumer Cyclical",
    "SCHWARZ GRUPPE": "Consumer Defensive",
}

def get_private_company_sector(ticker_or_name: str) -> str | None:
    """Look up sector for known private companies by name or ticker."""
    lookup = ticker_or_name.upper().strip()
    for key, sector in PRIVATE_COMPANY_SECTORS.items():
        if key in lookup or lookup in key:
            return sector
    return None
```

## Verknüpfung in der Pipeline

In der `get_asset_type()`-Funktion (config.py) sollte der Fallback für den `other_sector` so erweitert werden:

```python
# Aktuell: sector = "OTHER" → "STANDARD"
# Besser: sector = "OTHER" → prüfe PRIVATE_COMPANY_SECTORS → sonst "STANDARD"

sector = row.get("sector", "OTHER")
if sector == "OTHER":
    sector = get_private_company_sector(row.get("ticker", "")) 
    if not sector:
        sector = get_private_company_sector(row.get("name", ""))
    if not sector:
        sector = "OTHER"  # bleibt STANDARD
```

## Grenzen

- **Nicht vollständig:** Nur die zum Zeitpunkt der Erstellung bekannten Companies erfasst. Neue private Unternehmen (z.B. xAI, Mistral, Glean) müssen ergänzt werden.
- **Namenserkennung:** Die substring-Match-Logik ist rudimentär. Bei Konflikten (z.B. "ISI" trifft auch auf andere Firmen zu) prüfen.
- **Kein yfinance-Fallback möglich:** Private Companies haben keinen yfinance-Eintrag → die sector-Spalte bleibt "OTHER". Der Lookup muss immer manuell gepflegt werden oder via alias-Tabelle in der DB.