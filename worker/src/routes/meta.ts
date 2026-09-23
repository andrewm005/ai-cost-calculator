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
      // ISO timestamp of when the OpenRouter price cache was last refreshed.
      // null only on a brand-new deploy that has never had a successful
      // KV write from the cron. UI surfaces this under the result panel.
      cache_last_synced_at: state.cacheLastSyncedAt,
      cache_age_seconds: state.cacheLastSyncedAt
        ? Math.floor((Date.now() - new Date(state.cacheLastSyncedAt).getTime()) / 1000)
        : null,
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
