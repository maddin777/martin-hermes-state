# Lessons from 16.06.2026 morning briefing cron run

## Water temperature data — new reliable source found

**Open-Meteo Marine API** (working, free, no auth required):
```
curl -s "https://marine-api.open-meteo.com/v1/marine?latitude=54.17&longitude=12.08&daily=sea_surface_temperature_max&timezone=Europe/Berlin&forecast_days=1"
```
Returns JSON with `daily.sea_surface_temperature_max` in °C. Confirmed working for:
- Rostock/Warnemünde (54.17, 12.08) → 16.4 °C
- Wismar (53.89, 11.46) → 17.5 °C
- Travemünde/Lübeck (53.95, 10.87) → 16.9 °C

**Inland lakes (Schweriner See):** Open-Meteo marine API returns `null` for inland coordinates. Use `wassertemperatur.org` root page as fallback — it lists multiple lake temps in plain HTML. Schweriner See was 20 °C on 16.06.2026.

**Failed water temp sources (confirmed again this run):**
- seatemperature.org — renders temp via JS only, raw HTML has no usable data
- wassertemperatur-ostsee.de — returns only CSS/JS, no data in raw HTML
- DWD Kühlwassertemperatur page — 404 on the specific URL tried

## Weather data — Open-Meteo forecast API (confirmed reliable)
```
curl -s "https://api.open-meteo.com/v1/forecast?latitude=53.85&longitude=10.71&daily=temperature_2m_max,temperature_2m_min,weathercode,precipitation_sum,windspeed_10m_max&timezone=Europe/Berlin&forecast_days=1"
```
Weather code 3 = "Bedeckt" (overcast). Both Ratzeburg and Schwerin: code 3, no precipitation.

## Bot detection updates (newly confirmed blocked)
- wetteronline.de → 403 (CloudFront)
- finanzen.net → Access Denied
- wetter.de city pages → 404 (URL structure changed)
- Yahoo Finance → consent wall (EU cookie banner)
- Gazeta Wyborcza → SSL certificate error
- Ostsee-Zeitung → DataDome bot protection
- ZEIT online → SSL certificate error

## Research realities
- Tagesschau article URLs (e.g. /ausland/iran-usa-abkommen-100.html) return 404 — content has limited dwell time per Rundfunkstaatsvertrag. Always use the homepage or section pages.
- FAZ liveblog pages are reliable for real-time Iran/G7 updates.
- NZZ requires cookie consent but the Deutschland section is accessible.
- DR (Denmark) shows cookie wall but content is accessible behind it.
- SVT (Sweden) works without consent issues for headline extraction.

## Refined workflow for water temperatures
1. Try Open-Meteo marine API for sea locations (Warnemünde, Wismar, Travemünde)
2. For inland lakes (Schweriner See), try wassertemperatur.org root page
3. If both fail, note the last known value and flag it — never output "keine Messung verfügbar"
