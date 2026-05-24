# Hermes Browser Automation Setup

Setup for local Chromium-based browser automation within Hermes.

## Background

Hermes browser tools (`browser_navigate`, `browser_click`, etc.) need a backend:
- **Browserbase** (cloud, needs `BROWSERBASE_API_KEY`)
- **Camofox** (cloud, needs API key)
- **Local Chromium via Playwright** (free, no API key)

With `browser.engine: auto` (default), Hermes tries Browserbase/Camofox first, then falls back to local Chromium.

## Install Local Chromium

```bash
# cd to hermes source (playwright-core lives in its node_modules)
cd ~/.hermes/hermes-agent

# Install chromium browser (~400MB)
npx playwright install chromium

# Verify
node -e "const {chromium}=require('playwright-core'); (async()=>{const b=await chromium.launch({headless:true}); console.log('OK:', await b.version()); await b.close();})();"
# Expected: "OK: 147.0.7727.15" (or similar)
```

## Verify Files

```bash
# Playwright browsers cache
ls ~/.cache/ms-playwright/
# Expected: chromium-<build_id>  chromium_headless_shell-<build_id>  ffmpeg-<build_id>

# Chromium binary
find ~/.cache/ms-playwright -name "chrome" -type f
# Expected: .../chrome-linux64/chrome
```

## Config

`browser.engine: auto` in config.yaml picks up local Chromium automatically when cloud backends are unconfigured. No manual config changes needed.

## When to Choose Which

| Backend | Use Case |
|---------|----------|
| Local Chromium | Dev, testing, one-off scrapes |
| Browserbase | Production, anti-bot evasion, proxies |
| Camofox | Persisted browser sessions across restarts |

## Pitfalls

- **Proxmox LXC containers**: Docker overlayfs doesn't work in unprivileged LXCs, so self-hosting Firecrawl or running browser-in-Docker won't work. Local Chromium via Playwright is the reliable path.
- **Disk space**: Chromium is ~400MB. `ffmpeg` for video recording adds ~100MB.