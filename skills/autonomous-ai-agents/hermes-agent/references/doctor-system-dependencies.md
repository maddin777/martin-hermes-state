# Hermes Doctor: "system dependency not met" Guide

Each toolset in Hermes has an optional `check_fn` that gates its availability. When
`hermes doctor` shows `⚠ <toolset> (system dependency not met)`, the `check_fn`
returned `False` for the current environment.

This reference documents every toolset that can show this status, what its
`check_fn` actually checks, and what to do about it.

## How to trace a check_fn yourself

```bash
# 1. Find the toolset definition in toolsets.py
grep -A5 '"messaging":' ~/.hermes/hermes-agent/toolsets.py

# 2. Find the tool(s) in the toolset and their registry.register() call
# Each tool's check_fn is in the registry.register() at the bottom of tools/<name>.py
grep -A20 'registry.register(' ~/.hermes/hermes-agent/tools/send_message_tool.py | head -25

# 3. Read the check_fn
grep -A15 'def _check_send_message' ~/.hermes/hermes-agent/tools/send_message_tool.py

# 4. For env-var-gated toolsets: the check_fn just tests os.getenv("VAR")
# For runtime-gated toolsets: it tests a process or daemon
```

---

## Toolset-by-toolset breakdown

### messaging
- **Tool:** `send_message` (in `tools/send_message_tool.py`)
- **check_fn:** `_check_send_message()`
- **Logic (source):**
  1. If `HERMES_SESSION_PLATFORM` is set and not `"local"` → **True** (we're inside a gateway session, send_message can route through it)
  2. Otherwise → calls `is_gateway_running()` from `gateway/status.py`
  3. `is_gateway_running()` checks for a PID file at `{HERMES_HOME}/gateway.pid`
- **Resolve:** Start the gateway: `hermes gateway start` or `systemctl --user start hermes-gateway`
- **Expected?** Yes — the gateway runs as a daemon. CLI-only sessions don't start it by default.
- **Profile-isolated setup (Martin):** When using profile-based gateways (hermes-news, hermes_trading, etc.), the main profile's gateway is typically disabled. This message is **harmless** — each profile runs its own gateway with its own PID file. Disable the toolset: `hermes tools disable messaging`

### web
- **Tools:** `web_search`, `web_extract`
- **check_fn:** In each tool's registry.register, or in a combined toolset-level check
- **Logic:** Checks that at least one of `EXA_API_KEY`, `PARALLEL_API_KEY`, `TAVILY_API_KEY`, `FIRECRAWL_API_KEY` (or their URL equivalents) is set. The full list of env vars checked: `EXA_API_KEY`, `PARALLEL_API_KEY`, `TAVILY_API_KEY`, `FIRECRAWL_API_KEY`, `FIRECRAWL_API_URL`, `FIRECRAWL_GATEWAY_URL`, `TOOL_GATEWAY_DOMAIN`, `TOOL_GATEWAY_SCHEME`, `TOOL_GATEWAY_USER_TOKEN`
- **Resolve:** Obtain a key from any supported provider and set it in `~/.hermes/.env`. `hermes setup tools` walks through this interactively.
- **Expected?** Yes — web search requires a paid/registered API key.

### browser-cdp
- **Tools:** Browser automation tools
- **check_fn:** Checks `browser.cdp_url` in config.yaml or `BROWSERBASE_API_KEY` + `BROWSERBASE_PROJECT_ID` in `.env`
- **Resolve:** Set up Browserbase (cloud) or a local Chromium CDP URL
- **Expected?** Yes — requires either cloud or local browser infrastructure.

### computer_use
- **Tools:** `computer_use`
- **check_fn:** Checks for `cua-driver` binary (macOS only)
- **Resolve:** Install cua-driver (macOS) or ignore on Linux
- **Expected?** Yes, on Linux — computer use is macOS-only.

### discord / discord_admin
- **Tools:** Discord integration tools
- **check_fn:** `bool(os.getenv("DISCORD_BOT_TOKEN"))`
- **Resolve:** Set `DISCORD_BOT_TOKEN` in `.env`
- **Expected?** Yes — requires a Discord bot token.

### homeassistant
- **Tools:** `ha_list_entities`, `ha_get_state`, `ha_list_services`, `ha_call_service`
- **check_fn:** Checks for `HASS_TOKEN` or Home Assistant configuration
- **Resolve:** Set up Home Assistant integration
- **Expected?** Yes — Home Assistant is optional.

### image_gen
- **Tools:** Image generation tools
- **check_fn:** Checks for `FAL_KEY` or other image-gen provider keys
- **Resolve:** Set a FAL.ai key or other provider credential
- **Expected?** Yes — requires a paid API key.

### rl
- **Tools:** Reinforcement learning tools
- **check_fn:** Checks for `TINKER_API_KEY` and `WANDB_API_KEY`
- **Resolve:** Set both keys in `.env`
- **Expected?** Yes — RL training is an advanced feature.

### hermes-yuanbao
- **Tools:** Yuanbao (元宝) group tools
- **check_fn:** Checks for Yuanbao-specific configuration
- **Resolve:** Set up Yuanbao integration
- **Expected?** Yes — Yuanbao is specific to certain users/regions.

## Patterns

| Pattern | Examples | check_fn approach |
|---------|----------|-------------------|
| **Env var gate** | discord, rl, web | `bool(os.getenv("VAR"))` — tool available if key is set |
| **Runtime gate** | messaging | Checks PID file, process, or daemon status |
| **Platform gate** | computer_use | Checks for platform-specific binary |
| **Config gate** | browser-cdp | Checks config.yaml for specific keys |

## False positives in profile-based setups

When running multiple Hermes profiles with isolated gateways (Martin's setup),
the main profile's `hermes doctor` will show `messaging (system dependency not met)`
because the gateway daemon for the main profile isn't running. This is **expected**
and **harmless** — each profile runs its own gateway with its own PID file.

Fix: `hermes tools disable messaging` to stop the doctor warning.