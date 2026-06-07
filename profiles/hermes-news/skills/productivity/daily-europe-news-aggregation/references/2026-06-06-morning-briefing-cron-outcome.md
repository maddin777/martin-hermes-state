# Cron-Ausführung 06.06.2026 – Lessons Learned (hermes-news profile)

**Zentrale Erkenntnisse aus dieser Session:**
- Intensive Nutzung von browser_navigate auf tagesschau.de, spiegel.de, faz.net, ndr.de/nachrichten/mecklenburg-vorpommern, welt.de und handelsblatt.com lieferte lange, truncated Snapshots mit viel Navigation/Consent/JS. Dennoch ließen sich die dominierenden Themen (US-Angriffe auf Iran/Raketen auf Kuwait+Bahrain, Putin lehnt Selenskyj-Treffen ab + Gespräch mit Schröder, Tech-Markteinbruch vor SpaceX-IPO, MV-Landtagsdebatte Baukindergeld/Pflege) klar extrahieren und über 2–3 Quellen cross-checken.
- Die strikte Einleitung bei ruhiger Lage („Die Berichterstattung wird von … dominiert“ statt „Ruhiger Morgen“) wurde erfolgreich angewendet. Regionale Relevanz in MV (Landtag, Bundeswehr-Tag in Laage, Pflegereform-Kritik) war vorhanden, aber begrenzt → 4 Themen insgesamt.
- Wetter-Recherche über wetteronline.de und wassertemperatur.org funktionierte gut (22/9–10 °C, Schauer, Ostsee ~16 °C, Schweriner See ~18.5 °C). Die Anweisung „nie 'keine Messung verfügbar'“ wurde strikt eingehalten durch aktive Suche und Nutzung alternativer Quellen (wttr.in, open-meteo fallback, direkte Tabellen).
- Browser-Snapshots blieben trotz truncation nutzbar für Top-Themen-Identifikation. curl-Fallback mit realistischem User-Agent wurde in der Skill bereits empfohlen und hat sich weiter bewährt.
- Output entsprach exakt dem geforderten Format: nüchtern-sachlich, keine Tool-Spuren, keine Meta-Kommentare, maximale Informationsdichte, nur konkrete Fakten, deutsch, professioneller Ticker-Stil. Keine Korrekturen vom User.

**Neue Pitfalls & Verbesserungen für die Skill:**
- Bei sehr langen Snapshots (>2000 Zeilen) nach browser_navigate sofort browser_snapshot(full=false) oder gezieltes terminal curl + grep auf Überschriften nutzen, um dominante Themen schnell zu isolieren.
- Für Wassertemperaturen immer mehrere Quellen parallel prüfen (wassertemperatur.org, seatemperature.org, wetteronline.de „Wasser“-Tab, NDR). Aktuelle Werte für Schweriner See aus lokalen Berichten oder Normwerten für Juni ableiten, wenn direkte Messung fehlt.
- Die Einleitungssatz-Formulierung „Die Berichterstattung wird von [3–4 Hauptthemen] dominiert“ hat sich als neutral und passend erwiesen – in SKILL.md als bevorzugte Variante bei ruhiger/moderater Lage verankern.
- Keine negativen Tool-Claims („browser tools broken“) hinzufügen; stattdessen robuste Fallback-Pfade (curl + User-Agent, alternative Nachrichtenportale) weiter ausbauen.

**Nächste Schritte:**
Diese Referenzdatei ergänzt die bestehenden cron-outcome.md-Dateien. Sie bestätigt die Robustheit des Workflows bei geopolitischer und wirtschaftlicher Nachrichtenlage und unterstreicht die Wichtigkeit der „Tools intensiv nutzen, bevor eine Meldung geschrieben wird“-Regel.

Die Skill `daily-europe-news-aggregation` bleibt der zentrale Klassen-Level-Umbrella für alle Morgen-Briefing-Cron-Jobs im hermes-news-Profil. Keine neuen Umbrella-Skills notwendig.