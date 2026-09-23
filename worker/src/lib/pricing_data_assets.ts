/**
 * Baked-in copy of worker/config/pricing.json (13 hand-curated models).
 *
 * The Cloudflare Workers runtime has no fs module, so we embed the
 * hand-curated pricing as a TypeScript object literal. This serves as the
 * baseline pricing before the first cron-triggered OpenRouter refresh writes
 * to KV.
 *
 * If you edit worker/config/pricing.json, regenerate this file by running:
 *     node scripts/bake_pricing_assets.mjs
 *
 * (Source-of-truth: worker/config/pricing.json. Worker bundle: this file.)
 */

export const PRICING_BLOB = {
  "_meta": {
    "schema_version": "1.1",
    "currency": "USD",
    "notes": "All prices in USD per 1,000,000 tokens. Hand-curated overrides for ~13 models where OpenRouter's price matches the vendor's list price. Used as fallback when the OpenRouter cache lookup fails for a model id. OpenRouter cache is in worker/config/openrouter.json (synced from /api/v1/models).",
    "last_updated": "2026-09-23",
    "openrouter_cache": "worker/config/openrouter.json",
    "how_to_update": "Edit this file. The API reloads it on each request. To refresh the OpenRouter cache: python3 scripts/sync_openrouter.py",
    "verification_cadence": "spot-checked against OR live API on updates; OpenRouter cache auto-syncs every 6h in production via cron",
    "placeholder_models": 0
  },
  "models": {
    "openai/gpt-4o": {
      "provider": "openai",
      "display_name": "OpenAI: GPT-4o",
      "input_per_1m": 2.5,
      "output_per_1m": 10,
      "cached_input_per_1m": 1.25,
      "context_window": 128000,
      "supports_reasoning": false,
      "reasoning_per_1m": null,
      "tool_call_cost": 0,
      "image_input_cost_per_image": 0.002125,
      "notes": "Matches OR and OpenAI list price.",
      "last_verified": "2026-09-23",
      "verification_source": "openrouter+openai"
    },
    "openai/gpt-4o-mini": {
      "provider": "openai",
      "display_name": "OpenAI: GPT-4o-mini",
      "input_per_1m": 0.15,
      "output_per_1m": 0.6,
      "cached_input_per_1m": 0.075,
      "context_window": 128000,
      "supports_reasoning": false,
      "reasoning_per_1m": null,
      "tool_call_cost": 0,
      "image_input_cost_per_image": 0.000075,
      "notes": "Matches OR and OpenAI list price.",
      "last_verified": "2026-09-23",
      "verification_source": "openrouter+openai"
    },
    "openai/o3": {
      "provider": "openai",
      "display_name": "OpenAI: o3",
      "input_per_1m": 2,
      "output_per_1m": 8,
      "cached_input_per_1m": 0.5,
      "context_window": 200000,
      "supports_reasoning": true,
      "reasoning_per_1m": 40,
      "tool_call_cost": 0,
      "image_input_cost_per_image": 0,
      "notes": "OpenRouter $2/$8 — lower than OpenAI list $10/$40 because OR may route to a cheaper variant.",
      "last_verified": "2026-09-23",
      "verification_source": "openrouter"
    },
    "anthropic/claude-opus-4": {
      "provider": "anthropic",
      "display_name": "Anthropic: Claude Opus 4",
      "input_per_1m": 15,
      "output_per_1m": 75,
      "cached_input_per_1m": 1.5,
      "context_window": 200000,
      "supports_reasoning": true,
      "reasoning_per_1m": 75,
      "tool_call_cost": 0,
      "image_input_cost_per_image": 0.0048,
      "notes": "Matches OR and Anthropic list price.",
      "last_verified": "2026-09-23",
      "verification_source": "openrouter+anthropic"
    },
    "anthropic/claude-sonnet-4": {
      "provider": "anthropic",
      "display_name": "Anthropic: Claude Sonnet 4",
      "input_per_1m": 3,
      "output_per_1m": 15,
      "cached_input_per_1m": 0.3,
      "context_window": 1000000,
      "supports_reasoning": false,
      "reasoning_per_1m": null,
      "tool_call_cost": 0,
      "image_input_cost_per_image": 0.00096,
      "notes": "Matches OR and Anthropic list price.",
      "last_verified": "2026-09-23",
      "verification_source": "openrouter+anthropic"
    },
    "anthropic/claude-haiku-4.5": {
      "provider": "anthropic",
      "display_name": "Anthropic: Claude Haiku 4.5",
      "input_per_1m": 1,
      "output_per_1m": 5,
      "cached_input_per_1m": 0.1,
      "context_window": 200000,
      "supports_reasoning": false,
      "reasoning_per_1m": null,
      "tool_call_cost": 0,
      "image_input_cost_per_image": 0.00024,
      "notes": "Renamed from claude-haiku-4 on 2026-09-23 (vendor discontinued the -4 name; current generation is 4.5).",
      "last_verified": "2026-09-23",
      "verification_source": "openrouter+anthropic"
    },
    "google/gemini-2.5-pro": {
      "provider": "google",
      "display_name": "Google: Gemini 2.5 Pro",
      "input_per_1m": 1.25,
      "output_per_1m": 10,
      "cached_input_per_1m": 0.31,
      "context_window": 1048576,
      "supports_reasoning": true,
      "reasoning_per_1m": 10,
      "tool_call_cost": 0,
      "image_input_cost_per_image": 0.00000125,
      "notes": "Cached-input corrected on 2026-09-23 (was 0.125, vendor list is 0.31 for context <=200k).",
      "last_verified": "2026-09-23",
      "verification_source": "openrouter+google"
    },
    "google/gemini-2.5-flash": {
      "provider": "google",
      "display_name": "Google: Gemini 2.5 Flash",
      "input_per_1m": 0.3,
      "output_per_1m": 2.5,
      "cached_input_per_1m": 0.075,
      "context_window": 1048576,
      "supports_reasoning": true,
      "reasoning_per_1m": 2.5,
      "tool_call_cost": 0,
      "image_input_cost_per_image": 3e-7,
      "notes": "Cached-input corrected on 2026-09-23 (was 0.03, vendor list is 0.075).",
      "last_verified": "2026-09-23",
      "verification_source": "openrouter+google"
    },
    "deepseek/deepseek-chat": {
      "provider": "deepseek",
      "display_name": "DeepSeek: DeepSeek V3",
      "input_per_1m": 0.2,
      "output_per_1m": 0.8,
      "cached_input_per_1m": 0.07,
      "context_window": 131072,
      "supports_reasoning": false,
      "reasoning_per_1m": null,
      "tool_call_cost": 0,
      "image_input_cost_per_image": 0,
      "notes": "DeepSeek V3 list price. Float precision cleaned up on 2026-09-23 (was 0.20020000000000002).",
      "last_verified": "2026-09-23",
      "verification_source": "openrouter+deepseek"
    },
    "deepseek/deepseek-r1": {
      "provider": "deepseek",
      "display_name": "DeepSeek: R1",
      "input_per_1m": 0.7,
      "output_per_1m": 2.5,
      "cached_input_per_1m": 0.14,
      "context_window": 163840,
      "supports_reasoning": true,
      "reasoning_per_1m": 2.19,
      "tool_call_cost": 0,
      "image_input_cost_per_image": 0,
      "notes": "DeepSeek R1 list price.",
      "last_verified": "2026-09-23",
      "verification_source": "openrouter+deepseek"
    },
    "mistral/mistral-large-2407": {
      "provider": "mistralai",
      "display_name": "Mistral Large 2407",
      "input_per_1m": 2,
      "output_per_1m": 6,
      "cached_input_per_1m": 0.2,
      "context_window": 128000,
      "supports_reasoning": false,
      "reasoning_per_1m": null,
      "tool_call_cost": 0,
      "image_input_cost_per_image": 0,
      "notes": "Pinned to -2407 variant on 2026-09-23 (the bare 'mistral-large' id now routes to -2512 at $0.50/$1.50 which is a different product).",
      "last_verified": "2026-09-23",
      "verification_source": "openrouter+mistral"
    },
    "mistral/mistral-small-2603": {
      "provider": "mistralai",
      "display_name": "Mistral Small 2603",
      "input_per_1m": 0.15,
      "output_per_1m": 0.6,
      "cached_input_per_1m": 0.015,
      "context_window": 262144,
      "supports_reasoning": true,
      "reasoning_per_1m": null,
      "tool_call_cost": 0,
      "image_input_cost_per_image": 0,
      "notes": "Pinned to -2603 variant on 2026-09-23.",
      "last_verified": "2026-09-23",
      "verification_source": "openrouter+mistral"
    },
    "openrouter/auto": {
      "provider": "openrouter",
      "display_name": "OpenRouter Auto (router picks best)",
      "input_per_1m": 2,
      "output_per_1m": 8,
      "cached_input_per_1m": 0.5,
      "context_window": 200000,
      "supports_reasoning": false,
      "reasoning_per_1m": null,
      "tool_call_cost": 0,
      "image_input_cost_per_image": 0.001,
      "notes": "Price is dynamic, OR auto-router picks a different model per request. Reference rate shown; real cost depends on chosen upstream.",
      "last_verified": "2026-09-23",
      "verification_source": "openrouter"
    }
  }
} as const;
