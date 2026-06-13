# Vault Curation — Durchlauf 11.06.2026

Kuratiert 13 neue Dateien in Clippings/hermes/Geldverdienen. Vollständiges Beispiel des Vault-Curation-Workflows.

## Scan-Ergebnis

- **13 neue Dateien** seit 10.06.2026
- **8 Duplikat-Paare** gefunden (alle verschiedene MD5 = unterschiedliche Versionen)

## Duplikat-Behandlung

| Paar | Typ | Aktion |
|------|-----|--------|
| `10 HERMES AGENT HACKS...` + `... 1.md` | ` 1`-Suffix | Jun 10 behalten, Jun 7 gelöscht, ` 1` entfernt |
| `How to make Claude time-travel...` + `... 1.md` | ` 1`-Suffix | Mai 31 behalten, Mai 26 gelöscht |
| `I Replaced My Entire Research Stack...` + `... 1.md` | ` 1`-Suffix | Mai 31 behalten, Mai 26 gelöscht |
| `How to Build an Obsidian Knowledge Vault...` + `... 1.md` | ` 1`-Suffix | ` 1` behalten (einzige mit Datum) |
| `How to Build a Hermes Agent...` + `... 1.md` | ` 1`-Suffix | Jun 10 behalten |
| `The exact system...` in Clippings/ + hermes/ | Cross-Dir | Unterschiedlich → beide behalten |
| `Gemeinnütziger Verein und Steuern.md` + `- Verein und Steuern.md` | Gleicher Inhalt | Hyphen-Version behalten |
| `Praxisbeispiel Verein.md` + `Verein - Praxisbeispiel.md` | Gleicher Inhalt | `Verein - Praxisbeispiel.md` behalten |

## Relevanz-Klassifikation

| 🔥 | Token-Optimierung (Codex 245M→28M) | Wiki-Seite |
| 🔥 | 17 Hermes Prompts | Wiki-Seite |
| 🔥 | MCP Trading Setup (TradingView+Binance) | Wiki-Seite |
| 🔥 | Claude 5 Tradingbot | In Trading.md eingearbeitet |
| 📌 | AutoThink/AutoBuild (gkisokay) | In agent.md eingearbeitet |
| 📌 | AgentForge Harness | In agent.md eingearbeitet |
| ⏹ | Important software | Nur Liste |
| ⏹ | N8N AI trending videos | Kurzclip |
| ⏹ | Faceless YouTube (beide) | Kein Fokus |
| ⏹ | hermes + xAI = money | X-API zu teuer |
| ⏹ | WTF Is a Loop | Bereits in agent.md verlinkt |

## Wiki-Änderungen (7)

3 neue Seiten:
- `wiki/concepts/Hermes Prompt Recipes.md`
- `wiki/concepts/Token Optimization.md`
- `wiki/concepts/MCP Trading Setup.md`

4 Extensions:
- `wiki/concepts/agent.md` → AutoThink/AutoBuild + AgentForge Abschnitte, Quellen-Links
- `wiki/concepts/Trading.md` → Multi-Asset Strategie (Mean Reversion, Momentum, ATR, Correlation Filter)
- `wiki/concepts/index.md` → Neue Seiten verlinkt
- Alle mit Source-Backlinks zu den Clippings

## Nützliche Kommandos

```bash
# MD5-Vergleich für Duplikat-Check
md5sum "datei1.md" "datei2.md"

# Dateien nach Änderungsdatum sortiert
find . -name "*.md" -newer reference-date-file -type f

# ` 1`-Suffixe finden
find . -name "* 1.md" -type f
```