/**
 * POST /calculate and POST /calculate/compare — port of app/main.py:364-383.
 */
import type { Context } from 'hono';
import { HTTPException } from 'hono/http-exception';
import type { AppState } from '../state.js';
import { CalculateRequest, CompareRequest } from '../lib/schema.js';
import type { CalculationRequest, CalculationResult } from '../lib/calculator.js';

function toCalcReq(
  modelId: string,
  r: Record<string, unknown>,
): CalculationRequest {
  return {
    model_id: modelId,
    input_tokens: r.input_tokens == null ? null : Number(r.input_tokens),
    output_tokens: r.output_tokens == null ? null : Number(r.output_tokens),
    cached_input_tokens: r.cached_input_tokens == null ? 0 : Number(r.cached_input_tokens),
    reasoning_tokens: r.reasoning_tokens == null ? 0 : Number(r.reasoning_tokens),
    tool_call_count: r.tool_call_count == null ? 0 : Number(r.tool_call_count),
    image_input_count: r.image_input_count == null ? 0 : Number(r.image_input_count),
    num_runs: r.num_runs == null ? 1 : Number(r.num_runs),
    task_size: (r.task_size as string | undefined) ?? null,
    reasoning_level: (r.reasoning_level as string | undefined) ?? 'low',
    agentic: r.agentic == null ? false : Boolean(r.agentic),
    system_prompt_tokens: r.system_prompt_tokens == null ? 0 : Number(r.system_prompt_tokens),
    task_type: (r.task_type as string | undefined) ?? 'chat',
  };
}

function toResultOut(r: CalculationResult) {
  return {
    model_id: r.model_id,
    display_name: r.display_name,
    input_cost: r.input_cost,
    output_cost: r.output_cost,
    reasoning_cost: r.reasoning_cost,
    tool_cost: r.tool_cost,
    image_cost: r.image_cost,
    cost_per_run: r.cost_per_run,
    total_cost: r.total_cost,
    num_runs: r.num_runs,
    tokens_used: {
      input_tokens: r.tokens_used.input_tokens,
      output_tokens: r.tokens_used.output_tokens,
      reasoning_tokens: r.tokens_used.reasoning_tokens,
      cached_input_tokens: r.tokens_used.cached_input_tokens,
    },
    explanation: r.explanation,
    assumptions: r.assumptions,
  };
}

export function calculateRoute(state: AppState) {
  return async (c: Context) => {
    const body = await c.req.json().catch(() => ({}));
    const parsed = CalculateRequest.safeParse(body);
    if (!parsed.success) {
      throw new HTTPException(400, { message: JSON.stringify(parsed.error.issues) });
    }
    const req = parsed.data as unknown as Record<string, unknown>;
    try {
      const result = state.calculator.calculate(toCalcReq(String(req.model_id), req));
      return c.json(toResultOut(result));
    } catch (e) {
      throw new HTTPException(404, { message: (e as Error).message });
    }
  };
}

export function compareRoute(state: AppState) {
  return async (c: Context) => {
    const body = await c.req.json().catch(() => ({}));
    const parsed = CompareRequest.safeParse(body);
    if (!parsed.success) {
      throw new HTTPException(400, { message: JSON.stringify(parsed.error.issues) });
    }
    const req = parsed.data as unknown as Record<string, unknown>;
    const modelIds = req.model_ids as string[];
    const results: unknown[] = [];
    for (const mid of modelIds) {
      try {
        const r = state.calculator.calculate(toCalcReq(mid, req));
        results.push(toResultOut(r));
      } catch (e) {
        throw new HTTPException(404, { message: (e as Error).message });
      }
    }
    return c.json({ results });
  };
}
