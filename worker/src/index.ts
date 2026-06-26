/**
 * Cloudflare Workers entry — runs on the Workers runtime (V8 isolates).
 *
 * Storage: Workers KV (namespace `PRICING`, key `cache`). The cron-triggered
 * handler in `src/scheduled.ts` fetches OpenRouter and writes the cache;
 * this entry reads from KV on each request with a short in-memory TTL.
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
import { refreshToKV } from './lib/openrouter.js';
import {
  loadGpuProfilesFromObject,
  loadModelProfilesFromObject,
} from './lib/local_cost.js';
import {
  GPU_PROFILES_RAW,
  MODEL_PROFILES_RAW,
} from './lib/local_data_assets.js';
import { PRICING_BLOB } from './lib/pricing_data_assets.js';
import { OPENROUTER_BLOB } from './lib/openrouter_data_assets.js';
import { getCached, setCached, invalidateCache } from './cache.js';

export interface Env {
  PRICING: KVNamespaceLike;
  PRICING_KEY?: string;
  OPENROUTER_CACHE_PATH?: string;
}

async function buildStateFromKV(env: Env): Promise<AppState> {
  const key = env.PRICING_KEY ?? 'cache';

  const baked = loadPricingFromObject(PRICING_BLOB);
  const openrouterBaked = loadPricingFromObject(OPENROUTER_BLOB);
  const live = await loadPricingFromKV(env.PRICING, key);

  const merged = {
    ...baked,
    ...openrouterBaked,
    ...live,
  };

  const loader = new PricingLoader();
  loader.replaceModels(merged);

  const calculator = new Calculator();
  for (const m of loader.listModels()) {
    calculator.addModel(m);
  }

  const gpuProfiles = loadGpuProfilesFromObject(GPU_PROFILES_RAW);
  const modelProfiles = loadModelProfilesFromObject(MODEL_PROFILES_RAW);

const reloadPricing = (): number => Object.keys(merged).length;

const refreshOpenrouter = async (): Promise<number> => {
  const count = await refreshToKV(env.PRICING, env.PRICING_KEY ?? 'cache');
  invalidateCache();
  return count;
};

const openrouterModelCount = (): number =>
  loader.listModelIds().filter((id) => id.startsWith('openrouter/')).length;
  
  return {
    loader,
    calculator,
    pricingPaths: [],
    openrouterCachePath: 'kv',
    refreshSeconds: 0,
    gpuProfiles,
    modelProfiles,
    reloadPricing,
    refreshOpenrouter,
    openrouterModelCount,
};
}

const outer = new Hono<{ Bindings: Env }>();

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
  let cached = getCached();

  if (cached === null) {
    const state = await buildStateFromKV(c.env);
    const app = createApp(state);
    setCached(app);
    cached = { app, cachedAt: Date.now() };
  }

  return cached.app.fetch(c.req.raw, c.env, c.executionCtx);
});

export default outer;

export { scheduled } from './scheduled.js';
