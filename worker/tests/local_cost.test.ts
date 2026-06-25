/**
 * Local-cost tests — mirror tests/test_local_cost.py.
 */
import { describe, test, expect } from 'vitest';
import {
  resolveGpu,
  resolveTokensPerSecond,
  localCostPerToken,
  type GpuProfile,
  type ModelProfile,
} from '../src/lib/local_cost.js';

const gpu4090: GpuProfile = {
  gpu_id: 'nvidia-rtx-4090',
  display_name: 'NVIDIA RTX 4090',
  tdp_watts: 450,
  vram_gb: 24,
  default_tokens_per_second: 135,
  notes: '',
};

const modelLlama: ModelProfile = {
  model_id: 'llama3.3:70b',
  display_name: 'Llama 3.3 70B',
  parameters_b: 70,
  default_tokens_per_second: 25,
  tokens_per_second_by_gpu: { 'nvidia-rtx-4090': 25 },
  notes: '',
};

describe('localCostPerToken', () => {
  test('throws on tokens_per_second <= 0', () => {
    expect(() => localCostPerToken(0)).toThrow();
    expect(() => localCostPerToken(-1)).toThrow();
  });

  test('throws on utilization outside (0, 1]', () => {
    expect(() => localCostPerToken(10, 0, 0, 0, 0)).toThrow();
    expect(() => localCostPerToken(10, 0, 0, 0, 1.5)).toThrow();
  });

  test('throws on negative inputs', () => {
    expect(() => localCostPerToken(10, -1)).toThrow();
    expect(() => localCostPerToken(10, 0, -1)).toThrow();
    expect(() => localCostPerToken(10, 0, 0, -1)).toThrow();
  });

  test('free at the meter: $0 cost', () => {
    const r = localCostPerToken(100, 0, 0, 0, 1.0);
    expect(r.cost_per_token_usd).toBe(0);
    expect(r.cost_per_million_tokens_usd).toBe(0);
    expect(r.cost_per_hour_usd).toBe(0);
  });

  test('gpu rental only: $0.50/hr, 100 tok/s, util=1.0', () => {
    const r = localCostPerToken(100, 0, 0.5, 0, 1.0);
    // rental_per_second = 0.5 / 3600 ≈ 1.3889e-4
    // cost_per_token = 1.3889e-4 / 100 ≈ 1.3889e-6
    const expected = (0.5 / 3600) / 100;
    expect(r.cost_per_token_usd).toBeCloseTo(expected, 9);
    expect(r.cost_per_million_tokens_usd).toBeCloseTo(expected * 1_000_000, 4);
  });

  test('utilization < 1.0 increases per-token cost', () => {
    const r1 = localCostPerToken(100, 0, 0.5, 0, 1.0);
    const r05 = localCostPerToken(100, 0, 0.5, 0, 0.5);
    expect(r05.cost_per_token_usd).toBeCloseTo(r1.cost_per_token_usd * 2, 9);
  });
});

describe('resolveGpu', () => {
  test('resolves by canonical id', () => {
    const profiles = { [gpu4090.gpu_id]: gpu4090 };
    expect(resolveGpu('nvidia-rtx-4090', profiles)).toBe(gpu4090);
  });

  test('resolves by display name (case-insensitive)', () => {
    const profiles = { [gpu4090.gpu_id]: gpu4090 };
    expect(resolveGpu('NVIDIA RTX 4090', profiles)).toBe(gpu4090);
    expect(resolveGpu('nvidia rtx 4090', profiles)).toBe(gpu4090);
  });

  test('returns null for unknown', () => {
    expect(resolveGpu('nope', { [gpu4090.gpu_id]: gpu4090 })).toBeNull();
  });
});

describe('resolveTokensPerSecond', () => {
  test('override wins', () => {
    expect(
      resolveTokensPerSecond(modelLlama, 'nvidia-rtx-4090', 50, { [gpu4090.gpu_id]: gpu4090 }),
    ).toBe(50);
  });

  test('profile direct hit when no override', () => {
    expect(
      resolveTokensPerSecond(modelLlama, 'nvidia-rtx-4090', null, { [gpu4090.gpu_id]: gpu4090 }),
    ).toBe(25);
  });

  test('falls back to model default when GPU not in profile', () => {
    const otherGpu: GpuProfile = { ...gpu4090, gpu_id: 'amd-rx-7900', default_tokens_per_second: 100 };
    const m: ModelProfile = { ...modelLlama, tokens_per_second_by_gpu: {} };
    expect(resolveTokensPerSecond(m, 'amd-rx-7900', null, { 'amd-rx-7900': otherGpu })).toBe(25 * 100 / 135);
  });

  test('last resort: model default when no GPU profile either', () => {
    const m: ModelProfile = { ...modelLlama, tokens_per_second_by_gpu: {} };
    expect(resolveTokensPerSecond(m, 'nvidia-rtx-4090', null, null)).toBe(25);
  });
});
