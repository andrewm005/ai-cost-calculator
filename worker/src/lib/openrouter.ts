/**
 * OpenRouter live sync — port of app/openrouter.py.
 *
 * Pulls OpenRouter's public /api/v1/models endpoint, normalizes each entry
 * into our ModelPricing schema, and writes the result to a local JSON cache.
 * Fetcher failures must NOT crash the app — caller decides what to do.
 *
 * Namespacing: all incoming model ids are prefixed with `openrouter/` UNLESS
 * they already start with `openrouter/`. Prevents collisions with the
 * hand-curated vendor models in config/pricing.json.
 */

import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';
import { dirname } from 'node:path';
import type { ModelPricing, KVNamespaceLike } from './pricing.js';

export const OPENROUTER_MODELS_URL = 'https://openrouter.ai/api/v1/models';
export const DEFAULT_TIMEOUT = 30_000; // ms

// ---------- helpers ----------

function safeFloat(value: unknown, default_ = 0.0): number {
  if (value == null) return default_;
  const n = Number(value);
  return Number.isFinite(n) ? n : default_;
}

function namespacedModelId(rawId: string): string {
  if (rawId.startsWith('openrouter/')) return rawId;
  return `openrouter/${rawId}`;
}

function deriveProvider(namespacedId: string): string {
  if (namespacedId.startsWith('openrouter/')) {
    const rest = namespacedId.slice('openrouter/'.length);
    if (rest.includes('/')) return rest.split('/', 1)[0]!;
    return 'openrouter';
  }
  const parts = namespacedId.split('/', 1);
  return parts[0] ?? 'unknown';
}

function pickDisplayName(raw: Record<string, unknown>, namespacedId: string): string {
  const name = raw.name;
  if (typeof name === 'string' && name.trim()) return name.trim();
  const slug = raw.canonical_slug;
  if (typeof slug === 'string' && slug.trim()) return slug.trim();
  return namespacedId;
}

function supportsReasoning(raw: Record<string, unknown>): boolean {
  const reasoning = (raw.reasoning as Record<string, unknown> | null) ?? null;
  if (reasoning && typeof reasoning === 'object') {
    const efforts = reasoning.supported_efforts as unknown[] | undefined;
    if (Array.isArray(efforts) && efforts.length > 0) return true;
    if (reasoning.mandatory === true) return true;
  }
  const haystack = `${String(raw.id ?? '')} ${String(raw.name ?? '')}`.toLowerCase();
  return haystack.includes('thinking') || haystack.includes('reasoning');
}

// ---------- normalize() ----------

export function normalize(raw: Record<string, unknown>): ModelPricing | null {
  const rawId = raw.id;
  const pricing = (raw.pricing as Record<string, unknown> | null) ?? null;
  if (typeof rawId !== 'string' || !rawId) return null;
  if (!pricing || typeof pricing !== 'object') return null;
  if (!('prompt' in pricing) || !('completion' in pricing)) return null;

  const namespacedId = namespacedModelId(rawId);
  const promptPerToken = safeFloat(pricing.prompt);
  const completionPerToken = safeFloat(pricing.completion);

  // Negative pricing = OpenRouter's "dynamic" sentinel (e.g. openrouter/auto).
  if (promptPerToken < 0 || completionPerToken < 0) return null;

  const isFree = pricing.prompt === '0' && pricing.completion === '0';

  const inputPer1m = promptPerToken * 1_000_000;
  const outputPer1m = completionPerToken * 1_000_000;

  // Cached input: prefer input_cache_read, fall back to input_cache_write.
  const cacheRate = pricing.input_cache_read ?? pricing.input_cache_write;
  const cachedInputPer1m = cacheRate ? safeFloat(cacheRate) * 1_000_000 : 0.0;

  // Tool call cost: only set if non-zero
  const requestVal = pricing.request;
  const toolCallCost = requestVal && safeFloat(requestVal) > 0
    ? safeFloat(requestVal)
    : 0.0;

  // Image input: $/image, no 1M conv.
  const imageVal = pricing.image;
  const imageInputCostPerImage = imageVal ? safeFloat(imageVal) : 0.0;

  const notesParts: string[] = ['OpenRouter live sync'];
  if (isFree) notesParts.push('(free via OpenRouter)');

  return {
    model_id: namespacedId,
    provider: deriveProvider(namespacedId),
    display_name: pickDisplayName(raw, namespacedId),
    input_per_1m: inputPer1m,
    output_per_1m: outputPer1m,
    cached_input_per_1m: cachedInputPer1m,
    context_window: Math.trunc(safeFloat(raw.context_length, 0)),
    supports_reasoning: supportsReasoning(raw),
    reasoning_per_1m: null, // OpenRouter doesn't expose a separate rate
    tool_call_cost: toolCallCost,
    image_input_cost_per_image: imageInputCostPerImage,
    notes: notesParts.join('; '),
  };
}

// ---------- HTTP fetch ----------

export interface FetchResult {
  ok: boolean;
  models: ModelPricing[];
  error?: string;
}

export async function fetchModels(
  fetcher: typeof fetch = fetch,
): Promise<ModelPricing[]> {
  const response = await fetcher(OPENROUTER_MODELS_URL, {
    signal: AbortSignal.timeout(DEFAULT_TIMEOUT),
  });
  if (!response.ok) {
    throw new Error(`OpenRouter HTTP ${response.status}`);
  }
  const payload = (await response.json()) as { data?: unknown };
  const rawModels = Array.isArray(payload.data) ? payload.data : [];
  const out: ModelPricing[] = [];
  for (const raw of rawModels) {
    if (!raw || typeof raw !== 'object') continue;
    const m = normalize(raw as Record<string, unknown>);
    if (m) out.push(m);
  }
  return out;
}

// ---------- refresh_to_kv() (Workers cron path) ----------

/**
 * Fetch OpenRouter models and write the normalized cache to a Workers KV
 * namespace. Returns the number of models written.
 *
 * Shape written: `{ _meta: {...}, models: { model_id: {...} } }` — same as
 * `config/openrouter.json` on disk, so `loadPricingFromKV` reads it back
 * with no transformation.
 */
export async function refreshToKV(
  kvNamespace: KVNamespaceLike,
  key: string = 'cache',
  fetcher: typeof fetch = fetch,
): Promise<number> {
  const models = await fetchModels(fetcher);
  const payload = buildCachePayload(models);
  await kvNamespace.put(key, JSON.stringify(payload));
  return Object.keys(payload.models).length;
}

/**
 * Build the cache payload that refreshToKV / refreshToDisk both write.
 * Pure function so tests can call it without mocking fetch or fs.
 */
export function buildCachePayload(models: ModelPricing[]): {
  _meta: { source: string; last_synced_at: string; count: number };
  models: Record<string, Record<string, unknown>>;
} {
  const byId: Record<string, Record<string, unknown>> = {};
  for (const m of models) {
    byId[m.model_id] = {
      provider: m.provider,
      display_name: m.display_name,
      input_per_1m: m.input_per_1m,
      output_per_1m: m.output_per_1m,
      cached_input_per_1m: m.cached_input_per_1m,
      context_window: m.context_window,
      supports_reasoning: m.supports_reasoning,
      reasoning_per_1m: m.reasoning_per_1m,
      tool_call_cost: m.tool_call_cost,
      image_input_cost_per_image: m.image_input_cost_per_image,
      notes: m.notes,
    };
  }
  return {
    _meta: {
      source: OPENROUTER_MODELS_URL,
      last_synced_at: new Date().toISOString().replace(/\.\d{3}Z$/, 'Z'),
      count: Object.keys(byId).length,
    },
    models: byId,
  };
}

// ---------- refresh_to_disk() (Node dev path) ----------

/** Node-only: fetch OpenRouter and write the cache JSON to a local file. */
export async function refreshToDisk(
  cachePath: string,
  fetcher: typeof fetch = fetch,
): Promise<number> {
  const models = await fetchModels(fetcher);
  const payload = buildCachePayload(models);
  mkdirSync(dirname(cachePath), { recursive: true });
  writeFileSync(cachePath, JSON.stringify(payload, null, 2));
  return Object.keys(payload.models).length;
}

// ---------- load_cache() ----------

export function loadCache(cachePath: string): Record<string, ModelPricing> {
  if (!existsSync(cachePath)) return {};
  let raw: string;
  try {
    raw = readFileSync(cachePath, 'utf-8');
  } catch {
    return {};
  }
  let payload: { models?: Record<string, unknown> };
  try {
    payload = JSON.parse(raw);
  } catch {
    return {};
  }
  if (!payload || typeof payload !== 'object') return {};
  const modelsRaw = payload.models ?? {};
  if (typeof modelsRaw !== 'object' || modelsRaw === null) return {};

  const out: Record<string, ModelPricing> = {};
  for (const [modelId, m] of Object.entries(modelsRaw)) {
    if (!m || typeof m !== 'object') continue;
    try {
      const obj = m as Record<string, unknown>;
      out[modelId] = {
        model_id: modelId,
        provider: String(obj.provider ?? 'unknown'),
        display_name: String(obj.display_name ?? modelId),
        input_per_1m: Number(obj.input_per_1m ?? 0.0),
        output_per_1m: Number(obj.output_per_1m ?? 0.0),
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
      continue;
    }
  }
  return out;
}
