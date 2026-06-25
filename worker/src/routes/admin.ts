/**
 * POST /admin/reload + POST /admin/openrouter/refresh — port of app/main.py:519-560.
 */
import type { Context } from 'hono';
import { HTTPException } from 'hono/http-exception';
import type { AppState } from '../state.js';

export function reloadRoute(state: AppState) {
  return (c: Context) => {
    const count = state.reloadPricing();
    return c.json({
      status: 'reloaded',
      models_loaded: count,
      openrouter_models: state.openrouterModelCount(),
    });
  };
}

export function refreshOpenrouterRoute(state: AppState) {
  return async (c: Context) => {
    if (!state.openrouterCachePath) {
      throw new HTTPException(503, {
        message: 'OpenRouter cache is not configured (no second pricing path)',
      });
    }
    try {
      const count = await state.refreshOpenrouter();
      return c.json({
        status: 'reloaded',
        models_loaded: state.loader.listModelIds().length,
        openrouter_models: count,
      });
    } catch (e) {
      throw new HTTPException(503, {
        message: `OpenRouter refresh failed: ${(e as Error).message}`,
      });
    }
  };
}
