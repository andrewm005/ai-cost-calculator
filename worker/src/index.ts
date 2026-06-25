/**
 * Cloudflare Workers entry — runs on the Workers runtime (V8 isolates).
 *
 * Storage: Workers KV (namespace `PRICING`, key `cache`). The cron-triggered
 * handler in `src/scheduled.ts` fetches OpenRouter and writes the cache;
 * this entry reads from KV on each request (with a short in-memory TTL).
 *
 * Architecture:
 *   1. Per request → loadPricingFromKV(env.PRICING) → fallback to the baked
 *      hand-curated pricing (PRICING_BLOB) if KV is empty.
 *   2. Build AppState from the merged model dict + bundled GPU/model profiles
 *      (loaded from `local_data_assets.ts` at module load — no disk access).
 *   3. Delegate to the inner Hono app (built via `createApp(state)`).
 *
 * The inner Hono app is cached for KV_TTL_MS within an isolate (see
 * `src/cache.ts`) to amortize KV reads. The `scheduled` handler invalidates
 * the cache on each refresh.
 */

import { Hono } from 'hono';
import { cors } from 'hono/cors';
import type { AppState } from './state.js';
import { createApp } from './lib/app.js';
import {
  loadPricingFromKV,
  loadPricingFromObject,
  PricingLoader,
  type KVNamespaceLike,
} from './lib/pricing.js';
import { Calculator } from './lib/calculator.js';
import {
  loadGpuProfilesFromObject,
  loadModelProfilesFromObject,
} from './lib/local_cost.js';
import {
  GPU_PROFILES_RAW,
  MODEL_PROFILES_RAW,
} from './lib/local_data_assets.js';
import { PRICING_BLOB } from './lib/pricing_data_assets.js';
import { getCached, setCached } from './cache.js';

// ---------------------------------------------------------------------------
// Env bindings (the `Bindings` shape wired to wrangler.toml KV bindings)
// ---------------------------------------------------------------------------

export interface Env {
  /** Workers KV namespace binding — `wrangler kv:namespace create PRICING`. */
  PRICING: KVNamespaceLike;
  /** KV key holding the merged pricing blob. Default: 'cache'. */
  PRICING_KEY?: string;
}

// ---------------------------------------------------------------------------
// State builder — pure, takes KVNamespaceLike + bundled assets
// ---------------------------------------------------------------------------

/** Build a complete AppState from KV (with baked fallback) + bundled profiles. */
async function buildStateFromKV(env: Env): Promise<AppState> {
  const key = env.PRICING_KEY ?? 'cache';

  // 1. Try KV first; if empty, fall back to the baked hand-curated pricing.
const baked = loadPricingFromObject(PRICING_BLOB);
const live = await loadPricingFromKV(env.PRICING, key);

const merged = {
  ...baked,
  ...live,
};

  // 2. Empty-loader; we'll inject the merged dict.
  const loader = new PricingLoader();
  loader.replaceModels(merged);

  // 3. Calculator populated from the loader.
  const calculator = new Calculator();
  for (const m of loader.listModels()) calculator.addModel(m);

  // 4. GPU + model profiles come from the bundled assets (no disk access).
  const gpuProfiles = loadGpuProfilesFromObject(GPU_PROFILES_RAW);
  const modelProfiles = loadModelProfilesFromObject(MODEL_PROFILES_RAW);

  // 5. Workers runtime has no `setInterval` — `/admin/openrouter/refresh`
  //    and `/admin/reload` are no-ops in production (the cron handler is
  //    the only way to refresh). For Workers, the reload + refresh
  //    functions just return the current state without touching KV.
  //    The operator can still trigger a manual refresh via the dashboard
  //    ("Run scheduled task now") if needed.
  const reloadPricing = (): number => Object.keys(merged).length;
  refreshOpenrouter: async () => refreshToKV(env.PRICING, env.PRICING_KEY ?? 'cache'),
  const openrouterModelCount = (): number =>
    loader.listModelIds().filter((id) => id.startsWith('openrouter/')).length;

  return {
    loader,
    calculator,
    pricingPaths: [], // disk paths N/A in Workers
    openrouterCachePath: 'kv',
    refreshSeconds: 0,
    gpuProfiles,
    modelProfiles,
    reloadPricing,
    refreshOpenrouter,
    openrouterModelCount,
  };
}

// ---------------------------------------------------------------------------
// Outer Hono app (Workers fetch handler) — default export
// ---------------------------------------------------------------------------

const outer = new Hono<{ Bindings: Env }>();

// CORS for the static frontend (also mounted by the inner app, but the
// outer needs it for the OPTIONS preflight to work before delegation).
outer.use(
  '*',
  cors({
    origin: '*',
    allowMethods: ['GET', 'POST', 'OPTIONS'],
    allowHeaders: ['*'],
    credentials: false,
  }),
);

outer.use('*', async (c) => {
  // Cache the inner app (KV reads amortize across requests in the same isolate).
  let cached = getCached();
  if (cached === null) {
    const state = await buildStateFromKV(c.env);
    const app = createApp(state);
    setCached(app);
    cached = { app, cachedAt: Date.now() };
  }
  // Delegate to the cached inner Hono app. Pass c.env so any nested Hono
  // bindings resolve correctly (the inner routes don't use env, but this
  // keeps the contract consistent).
  return cached.app.fetch(c.req.raw, c.env, c.executionCtx);
});

export default outer;

// ---------------------------------------------------------------------------
// Scheduled handler (cron trigger) — also wired via wrangler.toml
// ---------------------------------------------------------------------------

export { scheduled } from './scheduled.js';
