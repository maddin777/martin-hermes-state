# Reddit Fallback — Produktiv-Beispiele

Fallback-Kette wenn Reddit direkt blockt (403).

## Beispiel 1: Thread "Hermes for Passive Income"

**URL:** `https://www.reddit.com/r/hermesagent/comments/1umnpmd/hermes_for_passive_income/`

**Exa Query:**
```
mcporter call 'exa.web_search_exa(query: "\"Hermes for Passive Income\" reddit", numResults: 5)'
```

**Was zurückkam:** Highlights aus dem Thread (Score 392, 91 Comments), Top-Kommentar über €2.700/Monat Hermes-Installationen.

**Alternative:** Query über die Post-ID:
```
mcporter call 'exa.web_search_exa(query: "1umnpmd hermes passive income", numResults: 5)'
```

## Beispiel 2: Suche über Subreddit + Topic

```
mcporter call 'exa.web_search_exa(query: "r/hermesagent lessons learned building controlled workflow", numResults: 5)'
```

Liefert Thread-Exzerpte auch ohne die exakte URL.

## Query-Template

```
mcporter call 'exa.web_search_exa(query: "site:reddit.com/r/SUBREDDIT KEYWORDS", numResults: 5)'
```

**Keywords-Bau:** Kombiniere Post-ID-Fragment + Titel-Kern + Subreddit-Name. Exa matched semantisch, nicht exakt — je spezifischer desto besser.