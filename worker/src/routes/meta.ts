/**
 * GET / — root metadata. Port of app/main.py:296-320.
 */
import type { Context } from 'hono';
import type { AppState } from '../state.js';

export function metaRoute(state: AppState) {
  return (c: Context) => {
    const total = state.loader.listModelIds().length;
    const orCount = state.openrouterModelCount();
    return c.json({
      name: 'Token Cost Calculator API',
      version: '1.2.0',
      models_loaded: total,
      openrouter_models: orCount,
      local_gpus: Object.keys(state.gpuProfiles).length,
      local_models: Object.keys(state.modelProfiles).length,
      refresh_seconds: state.refreshSeconds,
      endpoints: [
        'GET /health',
        'GET /models',
        'GET /models/{model_id}',
        'POST /calculate',
        'POST /calculate/compare',
        'POST /calculate/local',
        'GET /local/gpus',
        'GET /local/models',
        'POST /admin/reload',
        'POST /admin/openrouter/refresh',
      ],
    });
  };
}
