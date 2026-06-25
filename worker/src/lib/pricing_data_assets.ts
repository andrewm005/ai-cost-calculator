/**
 * Baked-in copy of config/pricing.json (13 hand-curated models).
 *
 * The Cloudflare Workers runtime has no fs module, so we embed the
 * hand-curated pricing as a TypeScript object literal. This serves as the
 * baseline pricing before the first cron-triggered OpenRouter refresh writes
 * to KV.
 *
 * If you edit config/pricing.json, regenerate this file by running:
 *     node scripts/bake_pricing_assets.mjs
 *
 * (Source-of-truth: config/pricing.json. Worker bundle: this file.)
 */

export const PRICING_BLOB = {
  "_meta": {
    "schema_version": "1.1",
    "currency": "USD",
    "notes": "All prices in USD per 1,000,000 tokens. Hand-curated models reflect current OpenRouter public list pricing; verified daily. OpenRouter models are loaded separately from config/openrouter.json (auto-managed via live /api/v1/models sync).",
    "last_updated": "2026-06-22",
    "openrouter_cache": "config/openrouter.json",
    "how_to_update": "Edit this file. The API reloads it on each request. No code changes needed for price updates. To refresh OpenRouter: POST /admin/openrouter/refresh.",
    "last_verified": "2026-06-23",
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
      "notes": "OpenRouter public list price (auto-refreshed daily)",
      "last_verified": "2026-06-23",
      "verification_source": "openrouter"
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
      "notes": "OpenRouter public list price (auto-refreshed daily)",
      "last_verified": "2026-06-23",
      "verification_source": "openrouter"
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
      "notes": "OpenRouter $2/$8 — lower than OpenAI list $10/$40; OR may route to a cheaper variant. Refreshed daily.",
      "last_verified": "2026-06-23",
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
      "notes": "OpenRouter public list price (auto-refreshed daily)",
      "last_verified": "2026-06-23",
      "verification_source": "openrouter"
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
      "notes": "OpenRouter public list price (auto-refreshed daily)",
      "last_verified": "2026-06-23",
      "verification_source": "openrouter"
    },
    "anthropic/claude-haiku-4": {
      "provider": "anthropic",
      "display_name": "Anthropic: Claude Haiku 4.5",
      "input_per_1m": 1,
      "output_per_1m": 5,
      "cached_input_per_1m": 0.09999999999999999,
      "context_window": 200000,
      "supports_reasoning": false,
      "reasoning_per_1m": null,
      "tool_call_cost": 0,
      "image_input_cost_per_image": 0.00024,
      "notes": "OpenRouter $1/$5 — maps to Claude Haiku 4.5 (current generation). Auto-refreshed daily.",
      "last_verified": "2026-06-23",
      "verification_source": "openrouter"
    },
    "google/gemini-2.5-pro": {
      "provider": "google",
      "display_name": "Google: Gemini 2.5 Pro",
      "input_per_1m": 1.25,
      "output_per_1m": 10,
      "cached_input_per_1m": 0.125,
      "context_window": 1048576,
      "supports_reasoning": true,
      "reasoning_per_1m": 10,
      "tool_call_cost": 0,
      "image_input_cost_per_image": 0.00000125,
      "notes": "OpenRouter public list price (auto-refreshed daily)",
      "last_verified": "2026-06-23",
      "verification_source": "openrouter"
    },
    "google/gemini-2.5-flash": {
      "provider": "google",
      "display_name": "Google: Gemini 2.5 Flash",
      "input_per_1m": 0.3,
      "output_per_1m": 2.5,
      "cached_input_per_1m": 0.03,
      "context_window": 1048576,
      "supports_reasoning": true,
      "reasoning_per_1m": 2.5,
      "tool_call_cost": 0,
      "image_input_cost_per_image": 3e-7,
      "notes": "OpenRouter public list price (auto-refreshed daily)",
      "last_verified": "2026-06-23",
      "verification_source": "openrouter"
    },
    "deepseek/deepseek-chat": {
      "provider": "deepseek",
      "display_name": "DeepSeek: DeepSeek V3",
      "input_per_1m": 0.20020000000000002,
      "output_per_1m": 0.8000999999999999,
      "cached_input_per_1m": 0.07,
      "context_window": 131072,
      "supports_reasoning": false,
      "reasoning_per_1m": null,
      "tool_call_cost": 0,
      "image_input_cost_per_image": 0,
      "notes": "OpenRouter $0.20/$0.80 — DeepSeek V3 (latest). Auto-refreshed daily.",
      "last_verified": "2026-06-23",
      "verification_source": "openrouter"
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
      "notes": "OpenRouter $0.70/$2.50 — R1 list. Auto-refreshed daily.",
      "last_verified": "2026-06-23",
      "verification_source": "openrouter"
    },
    "mistral/mistral-large": {
      "provider": "mistralai",
      "display_name": "Mistral Large",
      "input_per_1m": 2,
      "output_per_1m": 6,
      "cached_input_per_1m": 0.19999999999999998,
      "context_window": 128000,
      "supports_reasoning": false,
      "reasoning_per_1m": null,
      "tool_call_cost": 0,
      "image_input_cost_per_image": 0,
      "notes": "OpenRouter public list price (auto-refreshed daily)",
      "last_verified": "2026-06-23",
      "verification_source": "openrouter"
    },
    "mistral/mistral-small": {
      "provider": "mistralai",
      "display_name": "Mistral: Mistral Small 4",
      "input_per_1m": 0.15,
      "output_per_1m": 0.6,
      "cached_input_per_1m": 0.015,
      "context_window": 262144,
      "supports_reasoning": true,
      "reasoning_per_1m": null,
      "tool_call_cost": 0,
      "image_input_cost_per_image": 0,
      "notes": "OpenRouter $0.15/$0.60 — Mistral Small 4 (current). Auto-refreshed daily.",
      "last_verified": "2026-06-23",
      "verification_source": "openrouter"
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
      "notes": "Price is dynamic — OpenRouter auto-router picks a different model per request. Reference rate shown; real cost depends on chosen upstream.",
      "last_verified": "2026-06-23",
      "verification_source": "openrouter"
    }
  }
} as const;
