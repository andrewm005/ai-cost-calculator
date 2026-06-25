/**
 * Hono app factory — port of app/main.py create_app().
 *
 * Pure factory: takes the resolved state (pricing, calculator, GPU profiles,
 * model profiles) and returns a Hono app with all 11 endpoints mounted.
 *
 * Both the Workers entry (`src/index.ts`) and the Node dev entry
 * (`src/server.ts`) import this — they differ only in how they build state.
 */

import { Hono } from 'hono';
import { cors } from 'hono/cors';
import type { AppState } from '../state.js';
import { metaRoute } from '../routes/meta.js';
import { healthRoute } from '../routes/health.js';
import { listModelsRoute, getModelRoute } from '../routes/models.js';
import { calculateRoute, compareRoute } from '../routes/calculate.js';
import {
  calculateLocalRoute,
  listGpusRoute,
  listLocalModelsRoute,
} from '../routes/local.js';
import { reloadRoute, refreshOpenrouterRoute } from '../routes/admin.js';

export function createApp(state: AppState): Hono {
  const app = new Hono();

  // Top-level error logger — surface 500s so the smoke test can see them.
  app.onError((err, c) => {
    console.error('[hono error]', err);
    return c.json({ error: (err as Error).message }, 500);
  });

  app.notFound((c) => c.json({ error: 'not found', path: c.req.path }, 404));

  // CORS for the static frontend. Mirror Python's CORSMiddleware(allow_origins=['*']).
  app.use(
    '*',
    cors({
      origin: '*',
      allowMethods: ['GET', 'POST', 'OPTIONS'],
      allowHeaders: ['*'],
      credentials: false,
    }),
  );

  // Routes — order matches the Python app.
  app.get('/', metaRoute(state));
  app.get('/health', healthRoute(state));
  app.get('/models', listModelsRoute(state));
  app.get('/models/*', getModelRoute(state));
  app.post('/calculate', calculateRoute(state));
  app.post('/calculate/compare', compareRoute(state));
  app.post('/calculate/local', calculateLocalRoute(state));
  app.get('/local/gpus', listGpusRoute(state));
  app.get('/local/models', listLocalModelsRoute(state));
  app.post('/admin/reload', reloadRoute(state));
  app.post('/admin/openrouter/refresh', refreshOpenrouterRoute(state));

  return app;
}