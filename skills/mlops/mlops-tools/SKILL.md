---
name: mlops-tools
description: "MLOps: HF models, llama.cpp, vLLM, lm-eval, W&B."
version: 1.1.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [mlops, huggingface, llama-cpp, vllm, evaluation, wandb, inference]
    related_skills: [axolotl, unsloth, fine-tuning-with-trl, dspy, outlines]
trigger:
  - "Download/upload HuggingFace models"
  - "Local LLM inference"
  - "LLM serving"
  - "Evaluate LLMs"
  - "ML experiment tracking"
---

# MLOps Tools

Class-level skill for the operational side of ML: get model weights, run them, serve them,
measure them, log the results. Training/fine-tuning lives in `axolotl`, `unsloth`,
`fine-tuning-with-trl`; structured generation in `outlines`; prompt programs in `dspy`.

## When to Use

- Pulling, converting, or uploading model weights (HuggingFace Hub)
- Running a GGUF locally, or standing up an OpenAI-compatible server (llama.cpp, vLLM)
- Benchmarking a model (lm-eval) or logging experiments (W&B)
- "Which engine should I use on this GPU?" / "the server OOMs"

## Engine choice (decide first)

| Situation | Use |
|-----------|-----|
| One user, one model, CPU or small VRAM, quantized GGUF | **llama.cpp** (`llama-server`) |
| Many concurrent requests, GPU with headroom, HF-format weights | **vLLM** (`vllm serve`) |
| Need the same model on several sizes/quant levels | llama.cpp + GGUF variants of one repo |
| Training, not inference | see the fine-tuning skills |

Rule: pick the engine before downloading weights. GGUF for llama.cpp, safetensors for vLLM —
downloading the wrong format wastes hours.

## HuggingFace Hub

```bash
pip install -U "huggingface_hub[hf_transfer]"
hf auth login                                   # token from hf.co/settings/tokens
hf download <org>/<repo> --local-dir ./models/<name>
hf download <org>/<repo> <file.gguf> --local-dir ./models/<name>
hf upload <org>/<repo> <local-path> <path-in-repo>
```

- `HF_HUB_ENABLE_HF_TRANSFER=1` speeds up large downloads; it needs the `hf_transfer` extra.
- Always pin a revision for anything you will evaluate later (`--revision <sha>`); "main" moves.
- Gated repos 403 without an accepted license on the model page — accept it in the browser first, then retry with the token.
- `huggingface-cli` is the legacy name of `hf`; if only the old binary exists, the same subcommands apply.

## llama.cpp (local GGUF)

```bash
llama-server -m ./models/<name>/<file>.gguf \
  -ngl 99 -c 8192 --host 0.0.0.0 --port 8080 --jinja
```

- `-ngl` = layers offloaded to GPU; `99` = all. If VRAM is tight, lower it before lowering context.
- `-c` is total context across slots; `--parallel N` splits it — `-c 8192 --parallel 4` gives ~2k per request.
- `--jinja` enables the model's own chat template; without it, tool-calling prompts break.
- Exposes OpenAI-compatible `/v1/chat/completions` on the given port.
- Q4_K_M is the default quality/size trade-off; below Q4 quality degrades noticeably on reasoning tasks.
- OOM at load = context too large or `-ngl` too high; OOM mid-generation = KV cache growth, reduce `-c`.

## vLLM (throughput serving)

```bash
vllm serve <org>/<repo> --max-model-len 8192 \
  --gpu-memory-utilization 0.90 --tensor-parallel-size 1 --port 8000
```

- OpenAI-compatible at `http://localhost:8000/v1`.
- `--gpu-memory-utilization` above ~0.92 usually crashes at startup; leave headroom.
- `--tensor-parallel-size` must divide the attention-head count — a non-divisor fails at init, not at request time.
- Long `--max-model-len` at startup reserves KV cache up front; if it won't start, that is the knob.
- `--quantization awq|gptq|fp8` only when the checkpoint is already quantized in that format.

## Evaluation (lm-eval-harness)

```bash
lm_eval --model hf --model_args pretrained=<repo>,revision=<sha> \
  --tasks mmlu,gsm8k --batch_size auto --output_path results/<run>.json
```

- Compare only numbers produced by the same harness version, task config, and few-shot count. Cross-paper comparisons are noise.
- `--limit N` for smoke tests, never for reported numbers.
- Record model revision, quantization, and prompt format next to every score — quantized and chat-templated runs are not comparable to base-model runs.
- `--batch_size auto` on OOM: set a fixed smaller batch and `--device cuda:0`.

## Experiment tracking (W&B)

```bash
wandb login                 # or WANDB_API_KEY in env
WANDB_MODE=offline python train.py   # no network / no account
wandb sync <run-dir>        # upload later
```

```python
import wandb
run = wandb.init(project="<project>", config={"model": ..., "lr": ...})
wandb.log({"loss": loss, "step": step})
wandb.finish()
```

- Log the config you actually ran (model revision, data hash), not the intended one.
- `wandb.finish()` in a `finally` block — crashed runs otherwise stay "running" forever.
- Offline runs keep everything locally; `wandb sync` uploads them later.

## Cross-cutting rules

- Pin revisions/hashes for anything you will compare or ship.
- Report throughput with the prompt shape you measured (tok/s on a 4k prompt ≠ on a 200-token prompt).
- Keep model artifacts out of git; use a models dir plus a manifest of repo+revision.
