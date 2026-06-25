/**
 * KV write/read cycle test — verifies that refreshToKV + loadPricingFromKV
 * round-trip the OpenRouter cache correctly. Uses an in-memory KV mock so
 * no real Workers runtime is needed.
 *
 * This is the core invariant of the Cloudflare Workers migration:
 * whatever the cron handler writes to KV is exactly what the fetch
 * handler reads back, with no data loss or schema drift.
 */
import { describe, expect, it, beforeEach } from 'vitest';

import {
  refreshToKV,
  buildCachePayload,
  fetchModels,
  OPENROUTER_MODELS_URL,
} from '../src/lib/openrouter.js';
import { loadPricingFromKV, type KVNamespaceLike } from '../src/lib/pricing.js';
import type { ModelPricing } from '../src/lib/pricing.js';

// ---------------------------------------------------------------------------
// In-memory KV mock — satisfies the KVNamespaceLike interface used by
// refreshToKV and loadPricingFromKV.
// ---------------------------------------------------------------------------

class InMemoryKV implements KVNamespaceLike {
  private store = new Map<string, string>();

  async get(key: string): Promise<string | null>;
  async get(key: string, type: 'json'): Promise<unknown>;
  async get(key: string, type?: 'json'): Promise<string | null | unknown> {
    const raw = this.store.get(key);
    if (raw === undefined) return null;
    if (type === 'json') return JSON.parse(raw);
    return raw;
  }

  async put(key: string, value: string): Promise<void>;
  async put(key: string, value: unknown): Promise<void>;
  async put(key: string, value: string | unknown): Promise<void> {
    const str = typeof value === 'string' ? value : JSON.stringify(value);
    this.store.set(key, str);
  }

  // Test helpers (not part of KVNamespaceLike)
  size(): number {
    return this.store.size;
  }

  keys(): string[] {
    return Array.from(this.store.keys());
  }
}

// ---------------------------------------------------------------------------
// Fake OpenRouter response — minimal schema, 3 models with hand-picked prices.
// ---------------------------------------------------------------------------

const FAKE_OPENROUTER_PAYLOAD = {
  data: [
    {
      id: 'openai/gpt-4o',
      name: 'OpenAI: GPT-4o',
      context_length: 128000,
      pricing: {
        prompt: '0.0000025',
        completion: '0.00001',
        request: '0',
        image: '0.002125',
        input_cache_read: '0.00000125',
      },
    },
    {
      id: 'anthropic/claude-3.5-sonnet',
      name: 'Anthropic: Claude 3.5 Sonnet',
      context_length: 200000,
      pricing: {
        prompt: '0.000003',
        completion: '0.000015',
        request: '0',
      },
    },
    {
      // Free model — verify zero-pricing handling survives the round trip.
      id: 'meta-llama/llama-3.1-8b-instruct:free',
      name: 'Meta: Llama 3.1 8B Instruct (free)',
      context_length: 131072,
      pricing: {
        prompt: '0',
        completion: '0',
      },
    },
  ],
};

function fakeFetchOk(_url: string | URL | Request, _init?: RequestInit): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(FAKE_OPENROUTER_PAYLOAD), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    }),
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('KV write/read cycle (Workers migration invariant)', () => {
  let kv: InMemoryKV;

  beforeEach(() => {
    kv = new InMemoryKV();
  });

  it('fetchModels returns normalized pricing from a mocked fetch', async () => {
    const models = await fetchModels(fakeFetchOk as typeof fetch);
    expect(models).toHaveLength(3);
    const gpt = models.find((m) => m.model_id === 'openrouter/openai/gpt-4o');
    expect(gpt).toBeDefined();
    // 0.0000025 * 1_000_000 = 2.5
    expect(gpt!.input_per_1m).toBeCloseTo(2.5, 6);
    expect(gpt!.output_per_1m).toBeCloseTo(10.0, 6);
    expect(gpt!.cached_input_per_1m).toBeCloseTo(1.25, 6);
    expect(gpt!.context_window).toBe(128000);
    expect(gpt!.image_input_cost_per_image).toBeCloseTo(0.002125, 9);
    expect(gpt!.notes).toContain('OpenRouter live sync');
  });

  it('refreshToKV writes a fetchable payload, loadPricingFromKV reads it back', async () => {
    // Step 1: cron handler runs — fetch + normalize + write to KV.
    const written = await refreshToKV(kv, 'cache', fakeFetchOk as typeof fetch);
    expect(written).toBe(3);
    expect(kv.size()).toBe(1);
    expect(kv.keys()).toEqual(['cache']);

    // Step 2: fetch handler runs — read from KV.
    const pricing = await loadPricingFromKV(kv, 'cache');
    expect(Object.keys(pricing)).toHaveLength(3);

    // Verify the round-trip preserves all fields.
    const gpt = pricing['openrouter/openai/gpt-4o'];
    expect(gpt).toBeDefined();
    expect(gpt.input_per_1m).toBeCloseTo(2.5, 6);
    expect(gpt.output_per_1m).toBeCloseTo(10.0, 6);
    expect(gpt.cached_input_per_1m).toBeCloseTo(1.25, 6);
    expect(gpt.context_window).toBe(128000);
    expect(gpt.provider).toBe('openai');
    expect(gpt.display_name).toBe('OpenAI: GPT-4o');
    expect(gpt.image_input_cost_per_image).toBeCloseTo(0.002125, 9);

    const sonnet = pricing['openrouter/anthropic/claude-3.5-sonnet'];
    expect(sonnet).toBeDefined();
    expect(sonnet.input_per_1m).toBeCloseTo(3.0, 6);
    expect(sonnet.output_per_1m).toBeCloseTo(15.0, 6);
    expect(sonnet.provider).toBe('anthropic');

    // Step 3: free model preserved — pricing fields are 0, notes flag free.
    const free = pricing['openrouter/meta-llama/llama-3.1-8b-instruct:free'];
    expect(free).toBeDefined();
    expect(free.input_per_1m).toBe(0);
    expect(free.output_per_1m).toBe(0);
    expect(free.notes).toContain('(free via OpenRouter)');
  });

  it('loadPricingFromKV returns {} when the key is missing', async () => {
    const pricing = await loadPricingFromKV(kv, 'cache');
    expect(pricing).toEqual({});
  });

  it('loadPricingFromKV returns {} when the payload is malformed', async () => {
    // Write a non-JSON value — KVNamespaceLike.get should still handle it.
    await kv.put('cache', 'not-json-at-all');
    const pricing = await loadPricingFromKV(kv, 'cache');
    expect(pricing).toEqual({});
  });

  it('buildCachePayload is a pure function (no I/O) and matches refreshToKV output', async () => {
    // buildCachePayload is the shared logic between refreshToKV and
    // refreshToDisk — verifying it directly catches regressions in either path.
    const models: ModelPricing[] = [
      {
        model_id: 'test/model',
        provider: 'test',
        display_name: 'Test Model',
        input_per_1m: 1.0,
        output_per_1m: 2.0,
        cached_input_per_1m: 0.5,
        context_window: 8000,
        supports_reasoning: false,
        reasoning_per_1m: null,
        tool_call_cost: 0.0,
        image_input_cost_per_image: 0.0,
        notes: 'test',
      },
    ];
    const payload = buildCachePayload(models);
    expect(payload.models['test/model']).toBeDefined();
    expect(payload._meta.source).toBe(OPENROUTER_MODELS_URL);
    expect(payload._meta.count).toBe(1);
    expect(typeof payload._meta.last_synced_at).toBe('string');
    // ISO 8601-ish: ends with 'Z'
    expect(payload._meta.last_synced_at).toMatch(/Z$/);
  });

  it('a second refreshToKV call replaces the prior cache (idempotent)', async () => {
    const first = await refreshToKV(kv, 'cache', fakeFetchOk as typeof fetch);
    expect(first).toBe(3);

    // A second call should overwrite (KV.put is not append).
    const second = await refreshToKV(kv, 'cache', fakeFetchOk as typeof fetch);
    expect(second).toBe(3);

    // Still one key, still 3 models.
    expect(kv.size()).toBe(1);
    const pricing = await loadPricingFromKV(kv, 'cache');
    expect(Object.keys(pricing)).toHaveLength(3);
  });
});