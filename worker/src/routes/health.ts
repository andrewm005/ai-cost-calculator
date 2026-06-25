/**
 * GET /health — port of app/main.py:322-328.
 */
import type { Context } from 'hono';
import type { AppState } from '../state.js';

export function healthRoute(state: AppState) {
  return (c: Context) => {
    return c.json({
      status: 'ok',
      models_loaded: state.loader.listModelIds().length,
      openrouter_models: state.openrouterModelCount(),
    });
  };
}
