/**
 * OpenRouter normalizer + cache tests — mirror tests/test_openrouter.py.
 */
import { describe, test, expect } from 'vitest';
import { mkdtempSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { normalize, loadCache } from '../src/lib/openrouter.js';

describe('OpenRouter normalize()', () => {
  test('basic entry: maps fields and multiplies per-token to per-1m', () => {
    const raw = {
      id: 'anthropic/claude-3.5-sonnet',
      name: 'Claude 3.5 Sonnet',
      pricing: { prompt: '0.000003', completion: '0.000015' },
      context_length: 200000,
    };
    const m = normalize(raw);
    expect(m).not.toBeNull();
    expect(m!.model_id).toBe('openrouter/anthropic/claude-3.5-sonnet');
    expect(m!.provider).toBe('anthropic');
    expect(m!.display_name).toBe('Claude 3.5 Sonnet');
    expect(m!.input_per_1m).toBe(3.0);
    expect(m!.output_per_1m).toBe(15.0);
    expect(m!.context_window).toBe(200000);
  });

  test('namespaces only when not already prefixed', () => {
    const raw = {
      id: 'openrouter/free',
      pricing: { prompt: '0', completion: '0' },
    };
    const m = normalize(raw)!;
    expect(m.model_id).toBe('openrouter/free');
    expect(m.provider).toBe('openrouter');
    expect(m.input_per_1m).toBe(0);
    expect(m.output_per_1m).toBe(0);
    expect(m.notes).toContain('(free via OpenRouter)');
  });

  test('negative pricing (dynamic sentinel) returns null', () => {
    const raw = {
      id: 'openrouter/auto',
      pricing: { prompt: '-1', completion: '0.000001' },
    };
    expect(normalize(raw)).toBeNull();
  });

  test('detects reasoning via structured field', () => {
    const raw = {
      id: 'openai/o1',
      pricing: { prompt: '0.000015', completion: '0.00006' },
      reasoning: { supported_efforts: ['low', 'medium', 'high'] },
    };
    const m = normalize(raw)!;
    expect(m.supports_reasoning).toBe(true);
  });

  test('detects reasoning via keyword in id/name', () => {
    const raw = {
      id: 'custom/thinking-v1',
      name: 'Thinking Model',
      pricing: { prompt: '0.000001', completion: '0.000002' },
    };
    const m = normalize(raw)!;
    expect(m.supports_reasoning).toBe(true);
  });

  test('cached input uses input_cache_read', () => {
    const raw = {
      id: 'anthropic/claude-3.5-sonnet',
      pricing: {
        prompt: '0.000003',
        completion: '0.000015',
        input_cache_read: '0.0000003',
      },
    };
    const m = normalize(raw)!;
    expect(m.cached_input_per_1m).toBe(0.3);
  });

  test('image input cost is preserved (not multiplied by 1M)', () => {
    const raw = {
      id: 'gpt-4-vision',
      pricing: {
        prompt: '0.00001',
        completion: '0.00003',
        image: '0.001',
      },
    };
    const m = normalize(raw)!;
    expect(m.image_input_cost_per_image).toBe(0.001);
  });

  test('returns null when required fields missing', () => {
    expect(normalize({ id: 'x' })).toBeNull();
    expect(normalize({ id: 'x', pricing: {} })).toBeNull();
    expect(normalize({ id: 'x', pricing: { prompt: '0' } })).toBeNull();
  });
});

describe('OpenRouter loadCache()', () => {
  test('reads cache file and parses models', () => {
    const dir = mkdtempSync(join(tmpdir(), 'or-cache-'));
    const path = join(dir, 'cache.json');
    const payload = {
      _meta: { source: 'https://example.com', count: 2 },
      models: {
        'openrouter/test': {
          provider: 'test',
          display_name: 'Test',
          input_per_1m: 1.0,
          output_per_1m: 2.0,
          cached_input_per_1m: 0.0,
          context_window: 100000,
          supports_reasoning: false,
          reasoning_per_1m: null,
          tool_call_cost: 0.0,
          image_input_cost_per_image: 0.0,
          notes: '',
        },
      },
    };
    writeFileSync(path, JSON.stringify(payload));
    const out = loadCache(path);
    expect(out['openrouter/test']).toBeDefined();
    expect(out['openrouter/test']!.input_per_1m).toBe(1.0);
  });

  test('returns {} on missing file', () => {
    expect(loadCache('/tmp/definitely-does-not-exist.json')).toEqual({});
  });

  test('returns {} on malformed JSON', () => {
    const dir = mkdtempSync(join(tmpdir(), 'or-bad-'));
    const path = join(dir, 'bad.json');
    writeFileSync(path, 'not json {');
    expect(loadCache(path)).toEqual({});
  });
});

// Re-imported for the writeFileSync call
import { writeFileSync } from 'node:fs';
