/**
 * Pricing loader — port of app/pricing.py.
 *
 * Multi-file merge: load_pricing_files(...paths) reads multiple JSON files in
 * order and returns a single {model_id: ModelPricing} dict. Later files
 * override earlier ones on collision (so config/openrouter.json loaded after
 * config/pricing.json replaces any placeholder OpenRouter entries with live
 * data).
 *
 * Two storage backends:
 *   - **Disk** (Node dev): reads JSON files via `fs.readFileSync`.
 *   - **Workers KV** (production): reads the merged pricing blob from a single
 *     KV key (`cache`), populated by the cron-triggered OpenRouter refresh.
 *
 * Both backends return the same `{model_id: ModelPricing}` shape.
 */

import { readFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ModelPricing {
  model_id: string;
  provider: string;
  display_name: string;
  input_per_1m: number;            // USD per 1,000,000 input tokens
  output_per_1m: number;           // USD per 1,000,000 output tokens
  cached_input_per_1m: number;     // USD per 1,000,000 cached input tokens
  context_window: number;          // Max input+output tokens
  supports_reasoning: boolean;
  reasoning_per_1m: number | null; // USD per 1,000,000 reasoning tokens
  tool_call_cost: number;          // Flat USD per tool call
  image_input_cost_per_image: number;
  notes: string;
}

/**
 * Minimal Workers KV interface — we only need .get() and .put().
 * Mirrors Cloudflare's `KVNamespace` so the same code runs in Workers
 * and in tests with an in-memory mock. Locally we never construct one,
 * so importing @cloudflare/workers-types is NOT required.
 */
export interface KVNamespaceLike {
  get(key: string, type: 'json'): Promise<unknown>;
  get(key: string): Promise<string | null>;
  put(key: string, value: string, options?: { expirationTtl?: number }): Promise<void>;
  put(key: string, value: unknown, options?: { expirationTtl?: number }): Promise<void>;
}

// ---------------------------------------------------------------------------
// Parser (shared between disk + KV)
// ---------------------------------------------------------------------------

/** Parse the "models" dict from a pricing file/blob into ModelPricing objects. */
function parseModels(modelsRaw: Record<string, unknown>): Record<string, ModelPricing> {
  const parsed: Record<string, ModelPricing> = {};
  for (const [modelId, m] of Object.entries(modelsRaw)) {
    if (!m || typeof m !== 'object') continue;
    const obj = m as Record<string, unknown>;
    // Required fields: provider, input_per_1m, output_per_1m.
    // Python raises KeyError on `m["input_per_1m"]`; we must do the same.
    if (obj.provider == null) continue;
    if (obj.input_per_1m == null) continue;
    if (obj.output_per_1m == null) continue;
    const inRate = Number(obj.input_per_1m);
    const outRate = Number(obj.output_per_1m);
    if (!Number.isFinite(inRate) || !Number.isFinite(outRate)) continue;
    try {
      parsed[modelId] = {
        model_id: modelId,
        provider: String(obj.provider),
        display_name: String(obj.display_name ?? modelId),
        input_per_1m: inRate,
        output_per_1m: outRate,
        cached_input_per_1m: Number(obj.cached_input_per_1m ?? 0.0),
        context_window: Math.trunc(Number(obj.context_window ?? 0)),
        supports_reasoning: Boolean(obj.supports_reasoning ?? false),
        reasoning_per_1m: obj.reasoning_per_1m == null
          ? null
          : Number(obj.reasoning_per_1m),
        tool_call_cost: Number(obj.tool_call_cost ?? 0.0),
        image_input_cost_per_image: Number(obj.image_input_cost_per_image ?? 0.0),
        notes: String(obj.notes ?? ''),
      };
    } catch {
      // skip malformed entry — never poison the whole loader
      continue;
    }
  }
  return parsed;
}

// ---------------------------------------------------------------------------
// Loader class
// ---------------------------------------------------------------------------

export class PricingLoader {
  private path: string | null;
  private models: Record<string, ModelPricing> = {};

  /**
   * @param path Optional file path. If provided, the file is read on
   *             construction. If omitted (Workers), the loader starts empty
   *             and the caller must `replaceModels()` or `setModels()`.
   */
  constructor(path: string | null = null) {
    this.path = path !== null ? resolve(path) : null;
    if (this.path !== null) this.reload();
  }

  /** Re-read the file from disk. Throws if no path was set. */
  reload(): void {
    if (this.path === null) {
      throw new Error('PricingLoader.reload(): no file path set (Workers loader)');
    }
    if (!existsSync(this.path)) {
      throw new Error(`Pricing config not found: ${this.path}`);
    }
    const raw = JSON.parse(readFileSync(this.path, 'utf-8')) as {
      models?: Record<string, unknown>;
    };
    this.models = parseModels(raw.models ?? {});
  }

  /** Swap in a pre-built model dict (used after merging multiple files or loading from KV). */
  replaceModels(models: Record<string, ModelPricing>): void {
    this.models = { ...models };
  }

  listModelIds(): string[] {
    return Object.keys(this.models);
  }

  listModels(): ModelPricing[] {
    return Object.values(this.models);
  }

  getModel(modelId: string): ModelPricing {
    if (!(modelId in this.models)) {
      const available = Object.keys(this.models).sort().join(', ');
      throw new Error(`Unknown model '${modelId}'. Available: ${available}`);
    }
    return this.models[modelId];
  }
}

// ---------------------------------------------------------------------------
// Multi-source merge: disk (Node dev)
// ---------------------------------------------------------------------------

/**
 * Read multiple pricing JSON files from disk and merge them.
 *
 * Later files override earlier ones on collision (matches Python
 * `load_pricing_files` semantics — `config/openrouter.json` loaded after
 * `config/pricing.json` replaces any placeholder OpenRouter entries).
 */
export function loadPricingFromDisk(
  paths: string[],
  missingOk = false,
): Record<string, ModelPricing> {
  const merged: Record<string, ModelPricing> = {};
  for (const p of paths) {
    const abs = resolve(p);
    if (!existsSync(abs)) {
      if (missingOk) continue;
      throw new Error(`Pricing config not found: ${abs}`);
    }
    const raw = JSON.parse(readFileSync(abs, 'utf-8')) as {
      models?: Record<string, unknown>;
    };
    const parsed = parseModels(raw.models ?? {});
    Object.assign(merged, parsed);
  }
  return merged;
}

/** Backwards-compat alias — older callers (Node entry) used this name. */
export const loadPricingFiles = loadPricingFromDisk;

// ---------------------------------------------------------------------------
// Single-source load: KV (Workers production)
// ---------------------------------------------------------------------------

/** Default KV key where the merged pricing blob lives. */
export const PRICING_KV_KEY = 'cache';

/**
 * Read the merged pricing blob from a Workers KV namespace.
 *
 * The blob is the same shape as `config/openrouter.json`:
 *   { _meta: {...}, models: { model_id: {...} } }
 *
 * Returns `{}` if the key is missing or the blob is malformed — the caller
 * should fall back to disk-loaded hand-curated entries.
 */
export async function loadPricingFromKV(
  kvNamespace: KVNamespaceLike,
  key: string = PRICING_KV_KEY,
): Promise<Record<string, ModelPricing>> {
  let raw: unknown;
  try {
    raw = await kvNamespace.get(key, 'json');
  } catch {
    return {};
  }
  if (!raw || typeof raw !== 'object') return {};
  const obj = raw as { models?: Record<string, unknown> };
  if (!obj.models || typeof obj.models !== 'object') return {};
  return parseModels(obj.models);
}

/**
 * Read hand-curated pricing (config/pricing.json) baked into the worker bundle
 * as a JS object literal. Used as the fallback before KV is populated by the
 * first scheduled refresh.
 *
 * `bundledPricing` is the parsed JSON object — typically imported from
 * `src/lib/pricing_data_assets.ts` or fetched from KV on cold start.
 */
export function loadPricingFromObject(
  raw: { models?: Record<string, unknown> } | null | undefined,
): Record<string, ModelPricing> {
  if (!raw || typeof raw !== 'object') return {};
  return parseModels(raw.models ?? {});
}