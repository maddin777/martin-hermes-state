# Cron-Ausführung 27.05.2026 – Lessons Learned

**Zentrale Erkenntnisse:**
- Browser-Tools (`browser_navigate` + `snapshot`) lieferten bei tagesschau.de, spiegel.de, faz.net, welt.de und handelsblatt.com extrem lange Snapshots (oft 800–2400+ Zeilen) mit Navigation, Consent-Bannern, Livestream-Playern und redundanten Elementen. Dies führte zu Truncation und erschwerte schnelle Extraktion relevanter Headlines.
- Empfohlener robuster Fallback (bewährt in dieser Session): Bei unbrauchbaren Snapshots sofort auf `curl -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"` umschalten und mit `grep -oE '<h[1-4][^>]*>.*?</h[1-4]>'` nach Überschriften suchen. Dies lieferte schnell nutzbare Newsticker- und Top-Themen-Listen.
- Wassertemperaturen: Quellen wie wetter.com und seatemperature.org lieferten keine oder leere Ergebnisse. `wassertemperatur.org/ostsee/` gab plausible Werte (13–15 °C für Ostsee, ~15–17 °C Schweriner See als Schätzung). Zukünftig diese Domain priorisieren oder explizit saisonale Schätzung + Hinweis auf fehlende aktuelle Messwerte verwenden.
- „Ruhiger Morgen“-Format wurde erfolgreich angewendet: Kurze Begründung mit Quellenauflistung, nüchterner Ton, direkter Übergang zum Wassertemperatur-Abschnitt. Finale Antwort enthielt ausschließlich das Briefing – keine Tool-Spuren.
- Die Skill-Beschreibung war bereits gut vorbereitet; die Pitfalls-Sektion wurde um den curl+grep-Fallback und die vierte ruhige Tag-Referenz erweitert.

**Nächste Verbesserungen:**
- Ergänzung weiterer stabiler Wassertemperatur-URLs in der Skill (z. B. dwd.de, lokale Hafenbehörden).
- Optional: Kleines Python-Parsing-Skript in `scripts/extract_headlines.py` für zuverlässigere curl-Auswertung.

Diese Referenz sollte bei zukünftigen Patches berücksichtigt werden. Neue Datei: references/2026-05-27-cron-outcome.md