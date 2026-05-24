# LLM Stock Selection — Konkretes Beispiel fuer "Weiterdenken"

Session vom 2026-05-11: Martin fand ein X-Profil (@aifinancelabs) das $150M+ mit
Grok/ChatGPT/DeepSeek/Claude verwaltet. Statt den Artikel nur ins Wiki einsortieren
wurde die Intention des Autors weitergedacht und in konkrete Handlung uebersetzt.

## 1. Rohmaterial

X-Profil: https://x.com/aifinancelabs
Bio: "$150M+ invested alongside Grok, Chat, DeepSeek & Claude on @joinautopilot"
Platform: marketplace.joinautopilot.com — kopiert Portfolios von Politikern/Tradern via LLMs

GPT Portfolio von Dr. Lopez Lira: +58.1%, $36.8M AUM
AI World War III Portfolio: +147.3%, $113.8M AUM

## 2. Intention verstanden

Der Autor zeigt wie LLMs als Portfolio-Manager eingesetzt werden.
Kernidee: Multi-Modell-Ensemble (gleicher Prompt an mehrere LLMs → Schnittmenge = Trade).
Prompt Engineering > Fine-Tuning. Kein Whitepaper, keine offene Dokumentation.

## 3. Weiterdenken / Uebersetzung auf Martins Setup

Martins Trading-Profil (hermes_trading) hat bereits:
- signal_extractor.py (KI via OpenRouter/Gemini)
- technical_validator.py (via yfinance)
- signal_manager.py (Portfolio + SL/TP)

Was fehlt fuer Multi-LLM-Ensemble:
- Gleichen Prompt an mehrere Modelle senden (Grok, Claude, DeepSeek)
- Schnittmenge der Empfehlungen als Signal nutzen
- Vergleich der Begrundungen

## 4. Ablage

Wiki-Seite: /root/obsidian-vault/wiki/concepts/LLM Stock Selection.md
Verknuepft im: wiki/trading-index.md
Naechster Schritt: Vorschlag umgesetzt per vault-insights-daily Cron
