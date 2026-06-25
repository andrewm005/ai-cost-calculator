/**
 * Local (self-hosted) AI inference cost calculator — port of app/local_cost.py.
 *
 * Cost formula:
 *
 *   cost_per_token = ((gpu_rental_per_hour + power_per_hour) / 3600)
 *                    / (tokens_per_second * utilization)
 *
 * Per AGENTS.md decision #2, local Ollama is NOT merged with cloud Ollama —
 * the latter would only land as a normal worker/config/pricing.json entry with
 * provider="ollama" if/when Ollama publishes public prices.
 */

import { readFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';

// ---------------------------------------------------------------------------
// Data classes (structurally equivalent to Python @dataclass(frozen=True))
// ---------------------------------------------------------------------------

export interface GpuProfile {
  gpu_id: string;
  display_name: string;
  tdp_watts: number;
  vram_gb: number;
  default_tokens_per_second: number;
  notes: string;
}

export interface ModelProfile {
  model_id: string;
  display_name: string;
  parameters_b: number;
  default_tokens_per_second: number;
  tokens_per_second_by_gpu: Record<string, number>;
  notes: string;
}

export interface LocalCostBreakdown {
  cost_per_token_usd: number;
  cost_per_million_tokens_usd: number;
  cost_per_second_usd: number;
  cost_per_hour_usd: number;
  components: Record<string, number>;
  effective_tokens_per_second: number;
  explanation: string;
  assumptions: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Parsers (raw object → typed profiles — shared by disk + bundled loaders)
// ---------------------------------------------------------------------------

/** Parse a {gpu_id: {display_name, tdp_watts, ...}} raw object into GpuProfile[]. */
export function parseGpuProfilesFromRaw(raw: Record<string, unknown>): Record<string, GpuProfile> {
  const out: Record<string, GpuProfile> = {};
  for (const [gid, g] of Object.entries(raw)) {
    if (!g || typeof g !== 'object') continue;
    const obj = g as Record<string, unknown>;
    if (!('tdp_watts' in obj) || !('default_tokens_per_second' in obj)) continue;
    const tdpWatts = Number(obj.tdp_watts);
    const defaultTps = Number(obj.default_tokens_per_second);
    if (!Number.isFinite(tdpWatts) || !Number.isFinite(defaultTps)) continue;
    if (tdpWatts < 0 || defaultTps < 0) continue;
    out[gid] = {
      gpu_id: gid,
      display_name: String(obj.display_name ?? gid),
      tdp_watts: tdpWatts,
      vram_gb: Number(obj.vram_gb ?? 0.0),
      default_tokens_per_second: defaultTps,
      notes: String(obj.notes ?? ''),
    };
  }
  return out;
}

/** Parse a {model_id: {display_name, parameters_b, tokens_per_second_by_gpu, ...}} raw object. */
export function parseModelProfilesFromRaw(raw: Record<string, unknown>): Record<string, ModelProfile> {
  const out: Record<string, ModelProfile> = {};
  for (const [mid, m] of Object.entries(raw)) {
    if (!m || typeof m !== 'object') continue;
    const obj = m as Record<string, unknown>;
    const tpsByGpuRaw = (obj.tokens_per_second_by_gpu as Record<string, unknown> | null) ?? {};
    const tpsByGpu: Record<string, number> = {};
    if (typeof tpsByGpuRaw === 'object' && tpsByGpuRaw !== null) {
      for (const [gpuId, val] of Object.entries(tpsByGpuRaw)) {
        const n = Number(val);
        if (Number.isFinite(n) && n >= 0) tpsByGpu[gpuId] = n;
      }
    }
    out[mid] = {
      model_id: mid,
      display_name: String(obj.display_name ?? mid),
      parameters_b: Number(obj.parameters_b ?? 0.0),
      default_tokens_per_second: Number(obj.default_tokens_per_second ?? 0.0),
      tokens_per_second_by_gpu: tpsByGpu,
      notes: String(obj.notes ?? ''),
    };
  }
  return out;
}

// ---------------------------------------------------------------------------
// Loaders — disk (Node) + bundled (Workers)
// ---------------------------------------------------------------------------

/** Node-only: read a pricing JSON file from disk and parse the gpus object. */
export function loadGpuProfiles(path: string): Record<string, GpuProfile> {
  const abs = resolve(path);
  if (!existsSync(abs)) return {};
  let payload: { gpus?: Record<string, unknown> };
  try {
    payload = JSON.parse(readFileSync(abs, 'utf-8'));
  } catch {
    return {};
  }
  if (!payload || typeof payload !== 'object') return {};
  return parseGpuProfilesFromRaw(payload.gpus ?? {});
}

/** Node-only: read a model profiles JSON file from disk and parse the models object. */
export function loadModelProfiles(path: string): Record<string, ModelProfile> {
  const abs = resolve(path);
  if (!existsSync(abs)) return {};
  let payload: { models?: Record<string, unknown> };
  try {
    payload = JSON.parse(readFileSync(abs, 'utf-8'));
  } catch {
    return {};
  }
  if (!payload || typeof payload !== 'object') return {};
  return parseModelProfilesFromRaw(payload.models ?? {});
}

/** Workers-compatible: parse pre-loaded raw objects (e.g. from local_data_assets.ts). */
export function loadGpuProfilesFromObject(raw: Record<string, unknown>): Record<string, GpuProfile> {
  return parseGpuProfilesFromRaw(raw);
}

/** Workers-compatible: parse pre-loaded raw objects. */
export function loadModelProfilesFromObject(raw: Record<string, unknown>): Record<string, ModelProfile> {
  return parseModelProfilesFromRaw(raw);
}

// ---------------------------------------------------------------------------
// Lookups
// ---------------------------------------------------------------------------

export function resolveGpu(
  gpuId: string,
  profiles: Record<string, GpuProfile>,
): GpuProfile | null {
  if (gpuId in profiles) return profiles[gpuId]!;
  const lower = gpuId.toLowerCase().trim();
  for (const prof of Object.values(profiles)) {
    if (prof.display_name.toLowerCase() === lower) return prof;
  }
  return null;
}

export function resolveTokensPerSecond(
  model: ModelProfile,
  gpuId: string,
  override: number | null = null,
  gpuProfiles: Record<string, GpuProfile> | null = null,
): number {
  if (override != null && override > 0) return override;
  if (gpuId in model.tokens_per_second_by_gpu) {
    return model.tokens_per_second_by_gpu[gpuId]!;
  }
  if (gpuProfiles && gpuId in gpuProfiles) {
    const gpu = gpuProfiles[gpuId]!;
    // Reference baseline: 135 tok/s on RTX 4090-class hardware (8B model).
    const ref = 135.0;
    if (gpu.default_tokens_per_second > 0) {
      return (model.default_tokens_per_second * gpu.default_tokens_per_second) / ref;
    }
  }
  return model.default_tokens_per_second;
}

// ---------------------------------------------------------------------------
// Pure cost math
// ---------------------------------------------------------------------------

export function localCostPerToken(
  tokensPerSecond: number,
  tdpWatts = 0.0,
  gpuCostPerHour = 0.0,
  powerCostPerKwh = 0.0,
  utilization = 1.0,
): LocalCostBreakdown {
  if (tokensPerSecond <= 0) {
    throw new Error(`tokens_per_second must be > 0, got ${tokensPerSecond}`);
  }
  if (!(utilization > 0 && utilization <= 1.0)) {
    throw new Error(`utilization must be in (0, 1], got ${utilization}`);
  }
  if (gpuCostPerHour < 0 || powerCostPerKwh < 0 || tdpWatts < 0) {
    throw new Error('cost inputs must be non-negative');
  }

  // Per-second cost
  const rentalPerSecond = gpuCostPerHour / 3600.0;
  const powerPerHour = (tdpWatts / 1000.0) * powerCostPerKwh;
  const powerPerSecond = powerPerHour / 3600.0;
  const costPerSecond = rentalPerSecond + powerPerSecond;
  const costPerHour = costPerSecond * 3600.0;

  // Effective throughput after duty cycle adjustment
  const effectiveTps = tokensPerSecond * utilization;

  // Per-token
  const costPerToken = costPerSecond / effectiveTps;
  const costPerMillion = costPerToken * 1_000_000.0;

  const components: Record<string, number> = {};
  if (rentalPerSecond > 0) components.gpu_rental = rentalPerSecond / effectiveTps;
  if (powerPerSecond > 0) components.power = powerPerSecond / effectiveTps;
  if (Object.keys(components).length === 0) components.none = 0.0;

  // Explanation
  const parts: string[] = [];
  parts.push(`Cost rate: $${costPerSecond.toFixed(6)}/sec = $${costPerHour.toFixed(4)}/hr.`);
  if (rentalPerSecond > 0) {
    parts.push(`GPU rental $${gpuCostPerHour.toFixed(4)}/hr ÷ 3600 = $${rentalPerSecond.toFixed(6)}/sec.`);
  }
  if (powerPerSecond > 0) {
    parts.push(
      `Power: ${tdpWatts.toFixed(0)}W × $${powerCostPerKwh.toFixed(4)}/kWh ÷ 3600 = $${powerPerSecond.toFixed(6)}/sec.`,
    );
  }
  parts.push(
    `Effective throughput: ${tokensPerSecond.toFixed(1)} tok/s × utilization ${utilization.toFixed(2)} ` +
    `= ${effectiveTps.toFixed(1)} tok/s.`,
  );
  parts.push(
    `Per-token: $${costPerSecond.toFixed(6)}/sec ÷ ${effectiveTps.toFixed(1)} tok/s = ` +
    `$${costPerToken.toFixed(10)}/token ($${costPerMillion.toFixed(4)}/1M tokens).`,
  );
  if (utilization < 1.0) {
    parts.push(
      `Note: utilization=${utilization.toFixed(2)} — fixed costs amortized over ` +
      `${effectiveTps.toFixed(1)} tok/s instead of ${tokensPerSecond.toFixed(1)} tok/s.`,
    );
  }

  const assumptions: Record<string, unknown> = {
    tokens_per_second_input: tokensPerSecond,
    utilization,
    gpu_cost_per_hour: gpuCostPerHour,
    power_cost_per_kwh: powerCostPerKwh,
    tdp_watts: tdpWatts,
  };

  return {
    cost_per_token_usd: costPerToken,
    cost_per_million_tokens_usd: costPerMillion,
    cost_per_second_usd: costPerSecond,
    cost_per_hour_usd: costPerHour,
    components,
    effective_tokens_per_second: effectiveTps,
    explanation: parts.join(' '),
    assumptions,
  };
}
