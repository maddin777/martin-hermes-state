# Assigning per-bot models (role-bot team)

Learned while setting up Martin's 5-bot roster (designer/coder/writer/researcher/reviewer) to run distinct LLMs.

## How to set a bot's model
There is **no `hermes model set <name>` subcommand** (that path is interactive-only). The model is the **first line of the profile's `config.yaml`**:
```
model: openai/gpt-5.6-luna
```
Patch that one line; leave the provider implicit (Hermes resolves it from the model id).

Verify with TWO steps — config alone is not proof:
1. `hermes profile list` → Model column shows the new id.
2. Real smoke call, because many config-level "ok" states hide a runtime failure:
   `hermes -p <name> chat -q "Antworte nur exakt: OK" -Q`
   Expect the literal `OK` back. A 404/error here means the model won't work in production.

## Role → model mapping (what worked)
- **researcher** = strong orchestration → `openai/gpt-5.6-luna`
- **coder** = code-specialist → `openai/gpt-5.6-sol`
- **writer** = long-form → `anthropic/claude-sonnet-5`
- **designer** = creative → `moonshotai/kimi-k2.6`
- **reviewer** = cheap-but-critical → `qwen/qwen3.8-27b` (you do NOT need a pricey model to spot holes — it caught 4 genuine factual/QA errors on a real report in testing)

## Pitfall 1 — `:batch`-suffix models are unusable for agent calls
OpenRouter model ids ending in `:batch` (e.g. `openai/gpt-5.6-sol:batch`, `anthropic/claude-sonnet-5:batch`) are **only reachable via the Batch API** (offline/async). Hermes calls models synchronously live, so a `:batch` model fails hard even though it exists in `/v1/models`:
```
HTTP 404: This model is only available through the Batch API.
Use the /api/beta/batches endpoint instead.
```
**Always use the non-`:batch` variant** (`openai/gpt-5.6-sol`), which is the same model core served in real-time. When anyone suggests a `:batch` model for a live agent, refuse and take the non-batch form.

## Pitfall 2 — OpenRouter account provider-allowlist blocks models, not the config
A model can 404 at runtime while existing in the catalog if the account's "Allowed providers" list excludes the providers that actually serve it:
```
HTTP 404: No allowed providers are available for the selected model.
Providers serving anthropic/claude-sonnet-5: anthropic, claude-on-aws, azure,
google-vertex, amazon-bedrock, but your account's allowed-providers setting
permits only: xai, meta, novita, nvidia, openai, xiaomi, ...
```
Fix is in the OpenRouter UI (Settings → Provider routing → Allowed providers), NOT in the profile config. Claude is only served via `anthropic` / `claude-on-aws` / `azure` / `google-vertex` / `amazon-bedrock` — add at least `anthropic, azure, google-vertex` for the writer bot. Re-test the smoke call after the user saves the UI change.

## Pitfall 3 — verify model existence before assigning
Always check the target model resolves on the provider before patching a config, to avoid setting a dead id:
```python
import urllib.request, json
key = '<OPENROUTER_API_KEY>'
req = urllib.request.Request('https://openrouter.ai/api/v1/models',
      headers={'Authorization': 'Bearer '+key})
ids = [m['id'] for m in json.load(urllib.request.urlopen(req))['data']]
print('openai/gpt-5.6-luna' in ids)  # also print fuzzy matches to spot :batch vs non-batch
```
