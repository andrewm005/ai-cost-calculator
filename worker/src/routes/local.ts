/**
 * /calculate/local + /local/gpus + /local/models — port of app/main.py:385-517.
 */
import type { Context } from 'hono';
import { HTTPException } from 'hono/http-exception';
import type { AppState } from '../state.js';
import { LocalCostRequest } from '../lib/schema.js';
import { TASK_SIZE_PRESETS, REASONING_MULTIPLIERS, TASK_TYPE_MULTIPLIERS } from '../lib/calculator.js';
import { resolveGpu, resolveTokensPerSecond, localCostPerToken } from '../lib/local_cost.js';

export function calculateLocalRoute(state: AppState) {
  return async (c: Context) => {
    const body = await c.req.json().catch(() => ({}));
    const parsed = LocalCostRequest.safeParse(body);
    if (!parsed.success) {
      throw new HTTPException(400, { message: JSON.stringify(parsed.error.issues) });
    }
    const req = parsed.data as unknown as Record<string, unknown>;
    const modelId = String(req.model_id);
    const gpuId = String(req.gpu_id);
    const tps = req.tokens_per_second == null ? null : Number(req.tokens_per_second);
    const gpuCost = Number(req.gpu_cost_per_hour ?? 0);
    const pwrCost = Number(req.power_cost_per_kwh ?? 0);
    const tdp = req.gpu_tdp_watts == null ? null : Number(req.gpu_tdp_watts);
    const util = Number(req.utilization ?? 1.0);
    const inT = req.input_tokens == null ? null : Number(req.input_tokens);
    const outT = req.output_tokens == null ? null : Number(req.output_tokens);
    const taskSize = (req.task_size as string | undefined) ?? null;
    const reasoningLevel = (req.reasoning_level as string | undefined) ?? 'low';
    const taskType = (req.task_type as string | undefined) ?? 'chat';
    const numRuns = Number(req.num_runs ?? 1);

    const gpus = state.gpuProfiles;
    const models = state.modelProfiles;

    if (Object.keys(gpus).length === 0 || Object.keys(models).length === 0) {
      throw new HTTPException(503, {
        message: 'Local-cost profiles are not loaded (missing data/local_*.json?)',
      });
    }

    const gpu = resolveGpu(gpuId, gpus);
    if (!gpu) {
      const avail = Object.keys(gpus).sort().join(', ');
      throw new HTTPException(404, {
        message: `Unknown GPU '${gpuId}'. Available (canonical ids): ${avail}`,
      });
    }
    if (!(modelId in models)) {
      const avail = Object.keys(models).sort().join(', ');
      throw new HTTPException(404, {
        message: `Unknown local model '${modelId}'. Available: ${avail}`,
      });
    }
    const model = models[modelId]!;

    const tokensPerSecond = resolveTokensPerSecond(
      model,
      gpu.gpu_id,
      tps,
      gpus,
    );

    const tdpWatts = tdp ?? gpu.tdp_watts;
    const breakdown = localCostPerToken(
      tokensPerSecond,
      tdpWatts,
      gpuCost,
      pwrCost,
      util,
    );

    // Apply task-size / reasoning / task-type so per-task total matches /calculate
    let effIn: number;
    let effOut: number;
    if (taskSize && taskSize in TASK_SIZE_PRESETS) {
      const [presetIn, presetOut] = TASK_SIZE_PRESETS[taskSize]!;
      effIn = inT ?? presetIn;
      effOut = outT ?? presetOut;
    } else {
      effIn = inT ?? 0;
      effOut = outT ?? 0;
    }
    const outMult = REASONING_MULTIPLIERS[reasoningLevel] ?? 1.0;
    effOut = Math.trunc(effOut * outMult);
    const totalTokens = effIn + effOut;
    const typeMult = TASK_TYPE_MULTIPLIERS[taskType] ?? 1.0;
    const costPerRun = breakdown.cost_per_token_usd * totalTokens * typeMult;
    const totalCost = costPerRun * numRuns;

    return c.json({
      model_id: model.model_id,
      gpu_id: gpu.gpu_id,
      gpu_display_name: gpu.display_name,
      model_display_name: model.display_name,
      tokens_per_second: tokensPerSecond,
      effective_tokens_per_second: breakdown.effective_tokens_per_second,
      cost_per_token_usd: breakdown.cost_per_token_usd,
      cost_per_million_tokens_usd: breakdown.cost_per_million_tokens_usd,
      cost_per_hour_usd: breakdown.cost_per_hour_usd,
      total_tokens: totalTokens,
      cost_per_run: costPerRun,
      total_cost: totalCost,
      num_runs: numRuns,
      tokens_used: {
        input_tokens: effIn,
        output_tokens: effOut,
        reasoning_tokens: 0,
        cached_input_tokens: 0,
      },
      breakdown: {
        gpu_rental: breakdown.components.gpu_rental ?? null,
        power: breakdown.components.power ?? null,
      },
      explanation: breakdown.explanation,
      assumptions: {
        ...breakdown.assumptions,
        task_type_multiplier: typeMult,
        reasoning_level_multiplier: outMult,
        tokens_per_second_source: tps != null
          ? 'override'
          : gpu.gpu_id in model.tokens_per_second_by_gpu
            ? 'profile'
            : 'fallback',
      },
    });
  };
}

export function listGpusRoute(state: AppState) {
  return (c: Context) => {
    const sorted = Object.values(state.gpuProfiles).sort((a, b) =>
      a.gpu_id.localeCompare(b.gpu_id),
    );
    return c.json({
      gpus: sorted.map((g) => ({
        gpu_id: g.gpu_id,
        display_name: g.display_name,
        tdp_watts: g.tdp_watts,
        vram_gb: g.vram_gb,
        default_tokens_per_second: g.default_tokens_per_second,
        notes: g.notes,
      })),
    });
  };
}

export function listLocalModelsRoute(state: AppState) {
  return (c: Context) => {
    const sorted = Object.values(state.modelProfiles).sort((a, b) =>
      a.model_id.localeCompare(b.model_id),
    );
    return c.json({
      models: sorted.map((m) => ({
        model_id: m.model_id,
        display_name: m.display_name,
        parameters_b: m.parameters_b,
        default_tokens_per_second: m.default_tokens_per_second,
        supported_gpus: Object.keys(m.tokens_per_second_by_gpu).sort(),
        notes: m.notes,
      })),
    });
  };
}
