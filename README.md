# Token Cost Calculator API

Backend for the AI token-cost calculator website. Estimates the cost of an
inference task from a model and a usage profile. Pricing lives in JSON config
files so non-engineers can update prices without touching code.

The API loads **hand-curated vendor pricing** (`config/pricing.json`) merged
with **live OpenRouter pricing** (`config/openrouter.json`, auto-generated
from `https://openrouter.ai/api/v1/models`). On startup and on a background
interval, OpenRouter is re-fetched to keep the cache current.

## Quick start

```bash
# Install deps (already on this image: fastapi, uvicorn, pydantic, pytest, httpx)
pip install -r requirements.txt

# Run the API (lifespan does a best-effort initial OpenRouter refresh)
uvicorn app.main:app --host 0.0.0.0 --port 8000
# Open http://localhost:8000/docs for the auto-generated Swagger UI
```

Override pricing sources with the `PRICING_CONFIG` env var (single-file mode,
backward compatible) or pass multiple paths programmatically to `create_app`.

## Endpoints

| Method | Path                          | Purpose                                                 |
|--------|-------------------------------|---------------------------------------------------------|
| GET    | `/`                           | API metadata + endpoint list                            |
| GET    | `/health`                     | Liveness probe                                          |
| GET    | `/models`                     | List all models (hand-curated + OpenRouter)             |
| GET    | `/models/{model_id}`          | One model's pricing (`model_id` may contain `/`)         |
| POST   | `/calculate`                  | Cost estimate for one model + one request               |
| POST   | `/calculate/compare`          | Same request against multiple models                    |
| POST   | `/calculate/local`            | Self-hosted (Ollama) cost: GPU + power -> $/token       |
| GET    | `/local/gpus`                 | List known GPU profiles                                 |
| GET    | `/local/models`               | List known local (Ollama) model profiles                |
| POST   | `/admin/reload`               | Re-read both pricing files from disk (no network)       |
| POST   | `/admin/openrouter/refresh`   | Fetch live OpenRouter prices + rewrite cache + reload   |

OpenRouter models are namespaced with the `openrouter/` prefix, so the model
`anthropic/claude-3.5-sonnet` in OpenRouter's catalog becomes
`openrouter/anthropic/claude-3.5-sonnet` here (no collision with hand-curated
entries). Already-prefixed OpenRouter-native models like `openrouter/free` or
`openrouter/auto` stay as-is.

## Request shape for `/calculate`

```json
{
  "model_id": "openai/gpt-4o",
  "input_tokens": 5000,
  "output_tokens": 2000,
  "cached_input_tokens": 0,
  "reasoning_tokens": 0,
  "tool_call_count": 0,
  "image_input_count": 0,
  "num_runs": 1,
  "task_size": "medium",
  "reasoning_level": "low",
  "agentic": false,
  "system_prompt_tokens": 0,
  "task_type": "chat"
}
```

You can pass `task_size` ("tiny"|"small"|"medium"|"large"|"huge") instead of
explicit token counts; the calculator uses preset defaults for the size.

### Field guide

| Field                 | What it does                                              |
|-----------------------|-----------------------------------------------------------|
| `input_tokens`        | Tokens in the prompt. Used to compute input cost.         |
| `output_tokens`       | Tokens the model generates. Used for output cost.         |
| `cached_input_tokens` | Subset of input_tokens eligible for the cached rate.      |
| `reasoning_tokens`    | Reasoning tokens (o1, o3, R1, Gemini 2.5 thinking, etc.). Ignored if model doesn't support reasoning. |
| `tool_call_count`     | Number of tool calls in the run. Added at `tool_call_cost` per model. With `agentic=true` and no override, auto-filled to 5. |
| `image_input_count`   | Number of image inputs. Added at `image_input_cost_per_image` per model. |
| `num_runs`            | Multiplier on the per-run cost. Defaults to 1.            |
| `task_size`           | Preset for token counts when you don't want to specify them. |
| `reasoning_level`     | "low"/"medium"/"high"/"extreme". Multiplies output tokens (more reasoning = more tokens). |
| `agentic`             | `false` (default) or `true`. When `true`, the calculator auto-applies a 2,000-token system prompt (billed as input), 5 tool calls, and a 1.4× retry multiplier on top of the per-run cost. Replaces the old `task_type: "agentic"` slot — see `task_type` for backwards-compat notes. |
| `system_prompt_tokens`| Override the agentic system-prompt overhead (default `0` = auto-fill `2000` when `agentic=true`). Ignored when `agentic=false`. |
| `task_type`           | "chat"/"coding"/"writing"/"research". Inflates per-run cost to account for retries (e.g. `coding` 1.1×). The `"agentic"` value is **deprecated** as of v2.7 — use the `agentic` flag instead. Legacy callers that still send `task_type: "agentic"` keep getting the 1.4× multiplier without the tool-call / sys-prompt overhead. |

## Response shape

```json
{
  "model_id": "openai/gpt-4o",
  "display_name": "OpenAI GPT-4o",
  "input_cost": 0.0125,
  "output_cost": 0.02,
  "reasoning_cost": 0.0,
  "tool_cost": 0.0,
  "image_cost": 0.0,
  "cost_per_run": 0.0325,
  "total_cost": 0.0325,
  "num_runs": 1,
  "tokens_used": {
    "input_tokens": 5000,
    "output_tokens": 2000,
    "reasoning_tokens": 0,
    "cached_input_tokens": 0
  },
  "explanation": "Model: OpenAI GPT-4o (openai/gpt-4o). Per-run cost: $0.0325. ...",
  "assumptions": {
    "task_type_multiplier": 1.0,
    "reasoning_level_multiplier": 1.0
  }
}
```

## Updating pricing

### Hand-curated models (`config/pricing.json`)

Edit `config/pricing.json`. All prices are USD per 1,000,000 tokens. Then
either restart the server or hit `POST /admin/reload` to pick up the new
prices without a restart (also re-reads the OpenRouter cache).

To add a new model, append an entry under `models`:

```json
"acme/new-model": {
  "provider": "acme",
  "display_name": "Acme New Model",
  "input_per_1m": 0.50,
  "output_per_1m": 1.50,
  "cached_input_per_1m": 0.10,
  "context_window": 128000,
  "supports_reasoning": false,
  "reasoning_per_1m": null,
  "tool_call_cost": 0.0,
  "image_input_cost_per_image": 0.0,
  "notes": "PLACEHOLDER PRICING"
}
```

### OpenRouter live sync (`config/openrouter.json`)

The cache is auto-generated from `https://openrouter.ai/api/v1/models` —
**do not hand-edit**. The schema matches `pricing.json` so the loader
treats both files uniformly.

To force a refresh:

- `curl -X POST http://localhost:8000/admin/openrouter/refresh` — immediate,
  returns 503 on network failure (stale cache stays in use).
- Or set `OPENROUTER_REFRESH_SECONDS` (default `21600` = 6 hours) to control
  the background scheduler cadence. Set to `0` to disable the background loop.

A committed seed of `config/openrouter.json` ships with the repo so first-boot
works without network access.

### Notes on the live sync

- **Negative pricing values** in OpenRouter (e.g. `openrouter/auto` with
  `prompt: "-1"`) are skipped — they're sentinels for "dynamic / route at
  request time", not real prices. Such models stay out of the cache.
- **Free models** (`prompt == "0"` and `completion == "0"`) are kept and
  annotated `(free via OpenRouter)` in their notes.
- **Namespacing**: every OpenRouter model id is prefixed with `openrouter/`
  unless it already starts with `openrouter/`. This prevents collisions with
  hand-curated entries and makes the source of a model obvious from its id.
- **Hand-curated entries win** on collision (e.g. `openrouter/auto` stays
  the placeholder from `pricing.json` because OpenRouter's live data for it
  is the "-1" sentinel and is filtered out).

**All current hand-curated prices are PLACEHOLDER values.** Verify against
vendor pricing pages before quoting estimates to anyone.

## How the calculation works

For one run:

```
input_cost   = (uncached_input  * input_per_1m
              + cached_input    * cached_input_per_1m) / 1_000_000
output_cost  = output_tokens * output_per_1m / 1_000_000
reasoning_cost = reasoning_tokens * reasoning_per_1m / 1_000_000   (if supported)
tool_cost    = effective_tool_call_count * tool_call_cost
image_cost   = image_input_count * image_input_cost_per_image

per_run_base = sum of the above
per_run      = per_run_base * type_multiplier       (chat=1.0, coding=1.1, agentic=True=1.4, ...)
total        = per_run * num_runs
```

`reasoning_level` inflates `output_tokens` before pricing
(low=1.0x, medium=1.2x, high=1.5x, extreme=2.5x) because models emit more
tokens when reasoning harder.

### Agentic overhead (v2.7)

When `agentic: true` is sent, the calculator bundles three pieces of agentic
overhead into the cost instead of forcing the caller to specify each one:

1. **System-prompt overhead** — `effective_system_prompt_tokens` (default 2,000)
   are added to `input_tokens` and bill at the model's input rate. Override
   with `system_prompt_tokens: N` (non-zero). Ignored when `agentic: false`.
2. **Tool-call overhead** — `effective_tool_call_count` defaults to 5 when
   `agentic: true` and the caller didn't pass `tool_call_count`. Otherwise
   the caller's value is used verbatim (including when `agentic: false`).
3. **Retry multiplier** — `per_run` is multiplied by 1.4× to account for the
   extra back-and-forth an agent loop typically incurs. This 1.4× replaces
   the legacy `task_type: "agentic"` slot (deprecated v2.7); when `agentic`
   is true the multiplier is 1.4× regardless of `task_type`.

The response's `assumptions` block surfaces the effective values so the
frontend can show the user exactly what was applied:

```json
"assumptions": {
  "task_type_multiplier": 1.4,
  "reasoning_level_multiplier": 1.0,
  "agentic": true,
  "agentic_tool_call_count_effective": 5,
  "agentic_system_prompt_tokens_effective": 2000,
  "agentic_multiplier_applied": 1.4
}
```

## Configuration reference

| Env var                       | Default       | What it does                                |
|-------------------------------|---------------|---------------------------------------------|
| `PRICING_CONFIG`              | `config/pricing.json` | Single-file mode override (legacy).   |
| `OPENROUTER_REFRESH_SECONDS`  | `21600` (6h)  | Background refresh interval; `0` disables.  |

## Tests

```bash
python -m pytest tests/ -v
```

102 tests cover the pricing loader (single + multi-file merge), the calculator,
the HTTP API (incl. OpenRouter refresh endpoint, failure modes, the
placeholder replacement behavior, and the local-cost endpoint), the
OpenRouter normalizer, and the local-cost math + profile loaders.

## Local (self-hosted) cost — Ollama on your own GPU

`POST /calculate/local` estimates the cost of running an Ollama model on
your own hardware. The cost is a function of GPU rental/hosting rate,
power consumption, and measured throughput — **not** vendor token pricing
(per AGENTS.md operator-locked decision #2: local Ollama ≠ cloud Ollama).

### Cost formula

```
cost_per_token = ( (gpu_cost_per_hour / 3600)
                 + (tdp_watts / 1000) * power_cost_per_kwh / 3600 )
                 / (tokens_per_second * utilization)
```

Either `gpu_cost_per_hour` or `power_cost_per_kwh` can be zero. Set both
to zero for a "free at the meter" estimate (useful for hobby rigs where
the electricity delta is negligible).

### Request shape

```json
{
  "model_id": "llama3.3:70b",
  "gpu_id": "nvidia-h100-80gb",
  "tokens_per_second": null,        // override (else: profile lookup, then fallback)
  "gpu_cost_per_hour": 3.0,         // cloud rental or amortized hardware cost
  "power_cost_per_kwh": 0.0,        // local electricity
  "gpu_tdp_watts": null,            // override (else: GPU profile default)
  "utilization": 1.0,               // duty cycle in (0, 1]
  "task_size": "medium",            // tiny|small|medium|large|huge (uses presets)
  "task_type": "chat",              // applies the same multiplier as /calculate
  "num_runs": 1
}
```

`gpu_id` accepts the canonical id (`nvidia-rtx-4090`) OR the display name
(`NVIDIA RTX 4090`, case-insensitive). The endpoint returns the canonical
id in the response so the frontend can pin it for the next call.

`model_id` is an Ollama tag from `data/local_model_profiles.json` (e.g.
`llama3.1:8b`, `llama3.3:70b`, `qwen2.5:32b`, `mistral:7b`).

### Response shape

```json
{
  "model_id": "llama3.3:70b",
  "gpu_id": "nvidia-h100-80gb",
  "gpu_display_name": "NVIDIA H100 80GB",
  "model_display_name": "Llama 3.3 70B",
  "tokens_per_second": 110.0,
  "effective_tokens_per_second": 110.0,
  "cost_per_token_usd": 7.5757575757e-06,
  "cost_per_million_tokens_usd": 7.5758,
  "cost_per_hour_usd": 3.0,
  "total_tokens": 7000,
  "cost_per_run": 0.05303,
  "total_cost": 0.05303,
  "num_runs": 1,
  "tokens_used": {
    "input_tokens": 5000, "output_tokens": 2000,
    "reasoning_tokens": 0, "cached_input_tokens": 0
  },
  "breakdown": {
    "gpu_rental": 7.5757575757e-06,
    "power": null
  },
  "explanation": "Cost rate: $0.000833/sec = $3.0000/hr. GPU rental $3.0000/hr ÷ 3600 = $0.000833/sec. ...",
  "assumptions": {
    "tokens_per_second_input": 110.0,
    "utilization": 1.0,
    "gpu_cost_per_hour": 3.0,
    "power_cost_per_kwh": 0.0,
    "tdp_watts": 700.0,
    "task_type_multiplier": 1.0,
    "reasoning_level_multiplier": 1.0,
    "tokens_per_second_source": "profile"
  }
}
```

### How throughput is resolved

`tokens_per_second` is filled in this order (first match wins):

1. **Override** in the request body.
2. **Direct profile hit** — `data/local_model_profiles.json` entry for
   `(model, gpu_id)`. Most combinations of the bundled 10 models × 13
   GPUs are covered.
3. **GPU-default proxy** — if the model has no entry for this GPU but
   the GPU has a `default_tokens_per_second`, scale the model's
   `default_tokens_per_second` by the GPU's default vs. a 135 tok/s
   reference. This is a heuristic — operators who care about accuracy
   should pass an explicit `tokens_per_second`.
4. **Model default** — `model.default_tokens_per_second` as a last resort.

The response's `assumptions.tokens_per_second_source` records which
path was used (`override`, `profile`, or `fallback`).

### Data files

- `data/local_gpu_profiles.json` — 13 GPU classes (RTX 4090/4080/3090,
  RTX 4060 Ti, A100, H100, L40S, RTX 3060, MI300X, M2 Ultra, M3 Max,
  M4 Max, CPU fallback). Each has `tdp_watts`, `vram_gb`, and a
  reference `default_tokens_per_second` for an 8B-class model.
- `data/local_model_profiles.json` — 10 Ollama models (Llama 3.1/3.2/3.3
  family, Mistral 7B, Gemma 2 27B, Phi-3 14B, Qwen 2.5 32B, DeepSeek R1
  8B, CodeLlama 34B, Ministral 3 14B). Each has per-GPU
  `tokens_per_second_by_gpu`.

**All throughput and power figures are PLACEHOLDER values** compiled
from GigaGPU, Mustafa.net, Ollama TPS Live, and NVIDIA NIM benchmarks
(cited in `findings.md` §5). Verify against current vendor benchmarks
before quoting estimates to anyone. Edit the JSON files and call
`POST /admin/reload` to pick up changes without restarting.

### A note on the formula

The cost formula above is exact arithmetic. The example in `findings.md`
§5 stated that RTX 4090 @ $1.80/hr, 135 tok/s yields **$0.50 / 1M tokens**
— the correct number from the same inputs is **$3.70 / 1M tokens**
($1.80 ÷ 3600 ÷ 135 = $3.7e-6/token = $3.70/1M). The endpoint
implements the correct math; the research file's example arithmetic was
off by ~7× and should be re-verified before any vendor quote.

## Project layout

```
.
├── app/
│   ├── main.py        # FastAPI app + lifespan + endpoints
│   ├── calculator.py  # Pure calc logic + presets
│   ├── pricing.py     # JSON pricing loader (single + multi-file merge)
│   ├── openrouter.py  # OpenRouter fetcher + normalizer + cache writer
│   ├── local_cost.py  # Self-hosted (Ollama) cost: GPU + power -> $/token
│   └── models.py      # Pydantic request/response schemas
├── config/
│   ├── pricing.json       # Hand-curated 13 vendor models (PLACEHOLDER)
│   └── openrouter.json    # Auto-generated OpenRouter cache (~336 models)
├── data/
│   ├── local_gpu_profiles.json    # 13 GPU classes (TDP + reference tok/s)
│   └── local_model_profiles.json  # 10 Ollama models with per-GPU tok/s
├── tests/
│   ├── test_pricing.py
│   ├── test_calculator.py
│   ├── test_openrouter.py
│   ├── test_api.py
│   └── test_local_cost.py
├── requirements.txt
└── README.md
```