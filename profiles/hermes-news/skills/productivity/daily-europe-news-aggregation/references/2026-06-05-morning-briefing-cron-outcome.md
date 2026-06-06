# Cron-Ausführung 05.06.2026 – Lessons Learned (hermes-news profile)

**Zentrale Erkenntnisse aus dieser Session:**
- Die initiale Recherche mit browser_navigate auf tagesschau.de, spiegel.de, faz.net, ndr.de, welt.de und handelsblatt.com lieferte stark truncated Snapshots (oft >1000 Zeilen mit Navigation, Consent-Bannern und JS-Elementen). Dennoch konnten die dominierenden Themen (Selenskyj-Friedensangebot an Putin, US-Kongress-Position zur Ukraine/NATO, SpaceX-Index-Frage, Boeing-Entwicklung, MV-Landtagsdebatte um Tankrabatt/Energie) klar identifiziert und über mehrere Quellen cross-gecheckt werden.
- Regionale Relevanz für Mecklenburg-Vorpommern, Schleswig-Holstein, Hamburg, Skandinavien und Polen war gering; nur eine Landtagsdebatte in MV und Unwetter in Norddeutschland qualifizierten sich. Dies führte zu einer knappen Gruppierung mit 3 Themen und einer ehrlichen Einleitung statt „Ruhiger Morgen“.
- Wetter- und Wassertemperatur-Recherche (wttr.in, wetter.com, wassertemperatur.org) funktionierte zuverlässig über curl/wttr.in (12–17 °C, bewölkt) und lieferte konkrete Ostsee-Werte (16 °C in Warnemünde/Lübeck-Trave). Die Anweisung „nie 'keine Messung verfügbar'“ wurde eingehalten.
- Das aktualisierte Briefing-Format (max 5 unique Themen, strikte 4-Teile-Struktur pro Thema, Gruppierung, 1-Satz-Einleitung bei ruhiger Lage, konkrete Wetter/Wasser-Abschnitte, nüchtern-sachlich, keine Tool-Spuren/Meta) wurde vollständig umgesetzt. Die Ausgabe war kompakt, hochqualitativ und lieferte maximalen Informationsgehalt ohne Spekulationen oder vage Formulierungen.
- Die Skill-Beschreibung hat sich bewährt, insbesondere die Priorisierung von browser-first + sofortigem curl-Fallback, die 24h-Fenster-Regel und die strikte Output-Disziplin für Cron-Jobs. Neue Referenzdatei hinzugefügt.

**Nächste Verbesserungen für die Skill:**
- Ergänzung stabilerer Extraktionsmuster für lange/truncated Snapshots (z. B. Kombination aus browser_snapshot(full=false) + gezieltem browser_console oder terminal-curl + pup).
- Erweiterung der Wetter/Wasser-Quellen-Liste um DWD-API oder lokale Hafen-Seiten für Schweriner See (falls wttr.in unzureichend).
- Explizite Anweisung, vor jeder Meldung oder „wenig Neues“-Aussage die Tools (browser_navigate auf Top-Quellen + regionale Suchen) intensiv zu nutzen – dies wurde in dieser Session erfolgreich umgesetzt.
- Sicherstellen, dass bei ruhiger regionaler Lage immer eine kurze, ehrliche Einleitung („Die Berichterstattung wird von … dominiert“) verwendet wird.

Diese Datei dient als konkrete Referenz für zukünftige Cron-Läufe im hermes-news-Profil. Sie bestätigt die Robustheit des Workflows auch bei moderater Nachrichtenlage und unterstreicht die Notwendigkeit intensiver Tool-Nutzung vor jeder Formulierung.