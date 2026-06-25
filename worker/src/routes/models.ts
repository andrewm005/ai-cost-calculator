/**
 * GET /models and GET /models/{model_id} — port of app/main.py:330-362.
 *
 * The :path suffix is critical: model IDs contain slashes (e.g.
 * openrouter/anthropic/claude-3.5-sonnet), so we capture the full path.
 */
import type { Context } from 'hono';
import { HTTPException } from 'hono/http-exception';
import type { AppState } from '../state.js';
import type { ModelPricing } from '../lib/pricing.js';

function toModelOut(m: ModelPricing) {
  return {
    model_id: m.model_id,
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

export function listModelsRoute(state: AppState) {
  return (c: Context) => {
    return c.json({ models: state.loader.listModels().map(toModelOut) });
  };
}

export function getModelRoute(state: AppState) {
  return (c: Context) => {
    // Hono 4 wildcards: `*` captures the rest of the path. Strip the leading
    // "/models/" prefix that the route mount adds.
    const raw = c.req.path;
    const modelId = raw.startsWith('/models/') ? raw.slice('/models/'.length) : raw;
    if (!modelId) {
      throw new HTTPException(404, { message: 'model_id is required' });
    }
    try {
      const m = state.loader.getModel(modelId);
      return c.json(toModelOut(m));
    } catch (e) {
      throw new HTTPException(404, { message: (e as Error).message });
    }
  };
}
