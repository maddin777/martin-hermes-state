# Cron-Ausführung 26.05.2026 – Lessons Learned

**Zentrale Erkenntnisse aus dieser Session:**
- Browser-Tools (browser_navigate + snapshot) liefern bei News-Portalen oft sehr lange, redundante Snapshots mit Navigationselementen, Consent-Bannern und Videos. Dies führt zu hohen Token-Verbrauch und erschwert schnelles Parsen. 
- Empfohlene Fallback-Strategie (stark bewährt): Bei leeren/unbrauchbaren Snapshots oder 403 sofort auf `curl -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"` mit anschließender `grep`/`head` oder dediziertem Parsing-Skript umschalten.
- Wassertemperatur-Quellen (seatemperature.org, wetter.com, DWD) waren zum Zeitpunkt der Abfrage nicht erreichbar oder lieferten 404. Zukünftig breitere Fallback-Liste (z. B. https://www.wassertemperatur.org/, lokale Hafenämter MV) und explizite Fehlerbehandlung ("keine aktuellen Messwerte verfügbar") im Briefing einbauen.
- Die finale Ausgabe entsprach exakt dem gewünschten Telegram-Format (Gruppierung, Trennlinien, nüchterner Ton, Wassertemperatur-Abschnitt bei ruhiger Lage). Keine Meta-Informationen oder Tool-Spuren enthalten – gut.
- Die Skill-Beschreibung war bereits sehr nah am tatsächlichen Cron-Workflow; kleine Präzisierungen (max. 5 Nachrichten statt 3, explizites Einbeziehen lokaler Ereignisse/ internationaler Konflikte, detaillierter User-Agent, erweiterte Pitfalls) wurden direkt eingepflegt.

**Nächste Verbesserungen für Skill:**
- Ergänzung robusterer Wassertemperatur-Scraping-Logik (mehr Fallback-URLs).
- Optional: Kleines Python-Skript in `scripts/extract_news_headlines.py` für zuverlässigeres Parsing von curl-Ausgaben.

Diese Referenz sollte bei zukünftigen Patches der Haupt-SKILL.md berücksichtigt werden.