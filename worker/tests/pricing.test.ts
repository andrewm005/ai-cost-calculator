/**
 * Pricing loader tests — mirror tests/test_pricing.py.
 */
import { describe, test, expect, beforeEach } from 'vitest';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { PricingLoader, loadPricingFiles, type ModelPricing } from '../src/lib/pricing.js';

function writePricingFile(path: string, models: Record<string, Record<string, unknown>>): string {
  const payload = { _meta: { schema_version: '1.0', currency: 'USD' }, models };
  writeFileSync(path, JSON.stringify(payload));
  return path;
}

function modelDict(modelId: string, overrides: Record<string, unknown> = {}): Record<string, unknown> {
  const base = {
    provider: 'test',
    display_name: modelId,
    input_per_1m: 1.0,
    output_per_1m: 2.0,
    cached_input_per_1m: 0.0,
    context_window: 100_000,
    supports_reasoning: false,
    reasoning_per_1m: null,
    tool_call_cost: 0.0,
    image_input_cost_per_image: 0.0,
    notes: '',
  };
  return { ...base, ...overrides };
}

describe('PricingLoader', () => {
  let dir: string;
  let pricingPath: string;

  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), 'pricing-'));
    pricingPath = writePricingFile(join(dir, 'pricing.json'), {
      'test/foo': { ...modelDict('Test Foo', { input_per_1m: 1.0, output_per_1m: 2.0, cached_input_per_1m: 0.5, context_window: 100_000, image_input_cost_per_image: 0.001, notes: 'fixture' }) },
      'test/bar': { ...modelDict('Test Bar (reasoning)', { input_per_1m: 3.0, output_per_1m: 9.0, cached_input_per_1m: 1.5, context_window: 200_000, supports_reasoning: true, reasoning_per_1m: 9.0, image_input_cost_per_image: 0.0, notes: 'fixture' }) },
    });
  });

  test('returns models from config', () => {
    const loader = new PricingLoader(pricingPath);
    expect(loader.listModelIds().sort()).toEqual(['test/bar', 'test/foo']);
  });

  test('get_model returns a ModelPricing with parsed numeric fields', () => {
    const loader = new PricingLoader(pricingPath);
    const m = loader.getModel('test/foo');
    expect(m.model_id).toBe('test/foo');
    expect(m.provider).toBe('test');
    expect(m.display_name).toBe('Test Foo');
    expect(m.input_per_1m).toBe(1.0);
    expect(m.output_per_1m).toBe(2.0);
    expect(m.cached_input_per_1m).toBe(0.5);
    expect(m.context_window).toBe(100_000);
    expect(m.supports_reasoning).toBe(false);
    expect(m.reasoning_per_1m).toBe(null);
    expect(m.image_input_cost_per_image).toBe(0.001);
  });

  test('get unknown model throws with available ids in message', () => {
    const loader = new PricingLoader(pricingPath);
    expect(() => loader.getModel('test/does-not-exist')).toThrow(/test\/foo/);
  });

  test('reload picks up file changes', () => {
    const loader = new PricingLoader(pricingPath);
    expect(loader.getModel('test/foo').input_per_1m).toBe(1.0);
    const raw = JSON.parse(require('node:fs').readFileSync(pricingPath, 'utf-8'));
    raw.models['test/foo'].input_per_1m = 99.0;
    writeFileSync(pricingPath, JSON.stringify(raw));
    loader.reload();
    expect(loader.getModel('test/foo').input_per_1m).toBe(99.0);
  });

  test('missing file throws', () => {
    expect(() => new PricingLoader(join(dir, 'nope.json'))).toThrow();
  });
});

describe('loadPricingFiles multi-file merge', () => {
  let dir: string;
  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), 'pricing-merge-'));
  });

  test('merges multiple files (disjoint)', () => {
    const f1 = writePricingFile(join(dir, 'a.json'), {
      'test/a1': modelDict('Test A1', { input_per_1m: 1.0 }),
      'test/a2': modelDict('Test A2', { input_per_1m: 2.0 }),
    });
    const f2 = writePricingFile(join(dir, 'b.json'), {
      'test/b1': modelDict('Test B1', { input_per_1m: 10.0 }),
    });
    const merged = loadPricingFiles([f1, f2]);
    expect(Object.keys(merged).sort()).toEqual(['test/a1', 'test/a2', 'test/b1']);
    expect(merged['test/b1']!.input_per_1m).toBe(10.0);
  });

  test('later file overrides earlier on collision', () => {
    const f1 = writePricingFile(join(dir, 'hand.json'), {
      'openrouter/auto': modelDict('OpenRouter Auto (placeholder)', { input_per_1m: 99.0 }),
    });
    const f2 = writePricingFile(join(dir, 'live.json'), {
      'openrouter/auto': modelDict('OpenRouter Auto (live)', { input_per_1m: 0.5 }),
    });
    const merged = loadPricingFiles([f1, f2]);
    expect(Object.keys(merged)).toEqual(['openrouter/auto']);
    expect(merged['openrouter/auto']!.input_per_1m).toBe(0.5);
    expect(merged['openrouter/auto']!.display_name).toContain('live');
  });

  test('missing files raise by default', () => {
    const f1 = writePricingFile(join(dir, 'real.json'), { 'test/x': modelDict('Test X') });
    expect(() => loadPricingFiles([f1, join(dir, 'nope.json')])).toThrow();
  });

  test('missing_ok=true skips silently', () => {
    const f1 = writePricingFile(join(dir, 'real.json'), { 'test/x': modelDict('Test X') });
    const merged = loadPricingFiles([f1, join(dir, 'nope.json')], true);
    expect(Object.keys(merged)).toEqual(['test/x']);
  });

  test('all missing with missing_ok returns empty', () => {
    const merged = loadPricingFiles(
      [join(dir, 'a.json'), join(dir, 'b.json')],
      true,
    );
    expect(merged).toEqual({});
  });

  test('skips invalid entries', () => {
    const bad = {
      _meta: {},
      models: {
        good: modelDict('Good'),
        missing_input: { provider: 'test', output_per_1m: 1.0 },
        wrong_type: { ...modelDict('WrongType'), input_per_1m: 'not-a-number' },
      },
    };
    const p = join(dir, 'mixed.json');
    writeFileSync(p, JSON.stringify(bad));
    const merged = loadPricingFiles([p]);
    expect('good' in merged).toBe(true);
    expect('missing_input' in merged).toBe(false);
    expect('wrong_type' in merged).toBe(false);
  });
});
