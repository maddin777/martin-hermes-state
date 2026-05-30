# Cron-Ausführung 29.05.2026 – Lessons Learned

**Zentrale Erkenntnisse aus dieser Session:**
- Browser-Tools (`browser_navigate` + `browser_snapshot`) lieferten bei allen primären Quellen (tagesschau.de, spiegel.de, faz.net, welt.de, handelsblatt.com) extrem lange, redundante Snapshots (oft 800–2500+ Zeilen) mit Navigation, Consent-Bannern, Werbung, Livestream-Playern und Footer-Elementen. Dies führte zu Truncation und machte schnelle Extraktion relevanter Top-Meldungen praktisch unmöglich.
- Der robuste Fallback `curl -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" <URL> | grep -oE '<h[1-4][^>]*>.*?</h[1-4]>'` wurde mehrfach angewendet und bestätigte sich als schnell und zuverlässig für das Erkennen von Headlines und Newstickern. Er sollte zukünftig als Standard-First-Attempt nach fehlgeschlagenem Browser-Versuch etabliert werden.
- Wassertemperatur-Quellen (`wassertemperatur.org`, `seatemperature.org`, `wetter.com`, DWD) lieferten erneut keine verwertbaren aktuellen Werte (leere oder fehlende Ergebnisse). Die „keine aktuellen Messwerte verfügbar“-Formulierung wurde erfolgreich im „Ruhiger Morgen“-Briefing verwendet.
- Die finale Ausgabe entsprach exakt den Vorgaben: komplett auf Deutsch, nüchtern-sachlich, „Ruhiger Morgen“-Format mit kurzer Begründung, Quellenauflistung, direktem Übergang zum Wassertemperatur-Abschnitt, keine Tool-Spuren, keine Meta-Kommentare. Das Briefing wurde als einzige finale Antwort geliefert.
- Die Skill-Beschreibung war bereits sehr robust (Pitfalls-Sektion deckte Browser-Probleme und ruhige Tage gut ab). Die Referenzsammlung wurde um den aktuellen Tag erweitert.

**Nächste Verbesserungen für die Skill:**
- Ergänzung einer dedizierten `scripts/extract_headlines.py` oder eines zuverlässigeren curl-Parsing-Befehls (z. B. mit pup oder xmllint) im references-Verzeichnis.
- Erweiterung der Wassertemperatur-Fallback-Liste um weitere stabile Quellen (z. B. lokale Hafenämter Lübeck/Warnemünde, DWD-Seiten, sh-mv.de).
- Explizite Priorisierung von `curl + grep` als primärer Methode bei Cron-Jobs, da Browser-Stack in dieser Umgebung zu schwerfällig ist.

Diese Datei dient als Referenz für zukünftige Patches der Haupt-SKILL.md. Sie dokumentiert erfolgreiche Anwendung des „Ruhiger Morgen“-Formats bei sehr ruhiger Nachrichtenlage im Fokusgebiet (Nordost-Deutschland, Skandinavien, Polen, internationale Konflikte).