/**
 * Node entry — port of app/main.py:create_app() + the lifespan refresh loop.
 *
 * Resolves paths (defaults to ../config + ../data), builds the PricingLoader,
 * Calculator, and Hono app, starts the Node server, and sets up the
 * OpenRouter refresh interval (default 6h, env: OPENROUTER_REFRESH_SECONDS,
 * 0 disables).
 *
 * For the Cloudflare Workers runtime, see ./index.ts. That entry reads
 * pricing from KV instead of disk and uses a cron trigger instead of
 * setInterval.
 */
import { serve } from '@hono/node-server';
import { resolve } from 'node:path';
import { env } from 'node:process';
import { existsSync } from 'node:fs';

import { createApp } from './lib/app.js';
import type { AppState } from './state.js';
import {
  PricingLoader,
  loadPricingFromDisk,
  loadPricingFromKV,
  type ModelPricing,
  type KVNamespaceLike,
} from './lib/pricing.js';
import { Calculator } from './lib/calculator.js';
import {
  loadGpuProfiles,
  loadModelProfiles,
} from './lib/local_cost.js';
import { refreshToDisk, refreshToKV } from './lib/openrouter.js';

const REPO_ROOT = resolve(import.meta.dirname, '..', '..');

const DEFAULT_PRICING_PATH = env.PRICING_CONFIG ?? resolve(REPO_ROOT, 'config', 'pricing.json');
const DEFAULT_OPENROUTER_PATH = resolve(REPO_ROOT, 'config', 'openrouter.json');
const DEFAULT_REFRESH_SECONDS = 21600;
const DEFAULT_GPU_PROFILES_PATH = resolve(REPO_ROOT, 'data', 'local_gpu_profiles.json');
const DEFAULT_MODEL_PROFILES_PATH = resolve(REPO_ROOT, 'data', 'local_model_profiles.json');
const DEFAULT_PORT = 8002;

const PRICING_PATHS = [
  env.PRICING_CONFIG ?? DEFAULT_PRICING_PATH,
  env.OPENROUTER_CACHE ?? DEFAULT_OPENROUTER_PATH,
];

const OPENROUTER_CACHE_PATH = env.OPENROUTER_CACHE ?? DEFAULT_OPENROUTER_PATH;

const REFRESH_SECONDS = (() => {
  const raw = env.OPENROUTER_REFRESH_SECONDS ?? String(DEFAULT_REFRESH_SECONDS);
  const n = Number(raw);
  return Number.isFinite(n) ? n : DEFAULT_REFRESH_SECONDS;
})();

const PORT = Number(env.PORT ?? DEFAULT_PORT);
const AUTO_REFRESH_ON_STARTUP = env.AUTO_REFRESH_ON_STARTUP === '1';

// ---------------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------------

function rebuildCalculator(loader: PricingLoader, calculator: Calculator): void {
  const models = loader.listModels();
  for (const m of models) calculator.addModel(m);
}

function buildState(): AppState {
  const merged = loadPricingFromDisk(PRICING_PATHS, true);
  // Use the first existing path as the loader's primary file (for reload()).
  let primary: string | null = null;
  for (const p of PRICING_PATHS) {
    if (existsSync(p)) {
      primary = p;
      break;
    }
  }
  if (primary === null) {
    // No files exist at all — create an empty loader on the first path.
    primary = PRICING_PATHS[0]!;
  }
  const loader = new PricingLoader(primary);
  loader.replaceModels(merged);

  const calculator = new Calculator();
  rebuildCalculator(loader, calculator);

  const gpuProfiles = loadGpuProfiles(DEFAULT_GPU_PROFILES_PATH);
  const modelProfiles = loadModelProfiles(DEFAULT_MODEL_PROFILES_PATH);

  const reloadPricing = (): number => {
    const m = loadPricingFromDisk(PRICING_PATHS, true);
    loader.replaceModels(m);
    rebuildCalculator(loader, calculator);
    return Object.keys(m).length;
  };

  const openrouterModelCount = (): number =>
    loader.listModelIds().filter((id) => id.startsWith('openrouter/')).length;

  const refreshOpenrouter = async (): Promise<number> => {
    const count = await refreshToDisk(OPENROUTER_CACHE_PATH);
    const merged2 = loadPricingFromDisk(PRICING_PATHS, true);
    loader.replaceModels(merged2);
    rebuildCalculator(loader, calculator);
    return count;
  };

  return {
    loader,
    calculator,
    pricingPaths: PRICING_PATHS,
    openrouterCachePath: OPENROUTER_CACHE_PATH,
    refreshSeconds: REFRESH_SECONDS,
    gpuProfiles,
    modelProfiles,
    reloadPricing,
    refreshOpenrouter,
    openrouterModelCount,
  };
}

async function main() {
  const state = buildState();

  // Best-effort initial refresh (mirrors FastAPI lifespan auto_refresh_on_startup)
  if (AUTO_REFRESH_ON_STARTUP) {
    try {
      const count = await state.refreshOpenrouter();
      if (count > 0) {
        console.log(`Initial OpenRouter refresh: ${count} models`);
      }
    } catch (e) {
      console.warn(`Initial OpenRouter refresh failed (keeping stale cache): ${(e as Error).message}`);
    }
  }

  const app = createApp(state);

  serve(
    {
      fetch: app.fetch,
      port: PORT,
      hostname: '0.0.0.0',
    },
    (info) => {
      console.log(`Token Cost Calculator (TS) listening on http://0.0.0.0:${info.port}`);
      console.log(`  models_loaded: ${state.loader.listModelIds().length}`);
      console.log(`  openrouter_models: ${state.openrouterModelCount()}`);
      console.log(`  local_gpus: ${Object.keys(state.gpuProfiles).length}`);
      console.log(`  local_models: ${Object.keys(state.modelProfiles).length}`);
      console.log(`  refresh_seconds: ${state.refreshSeconds}`);
    },
  );

  // Background refresh — setInterval instead of asyncio.create_task.
  if (state.refreshSeconds > 0) {
    const interval = setInterval(async () => {
      try {
        const count = await state.refreshOpenrouter();
        console.log(`Background OpenRouter refresh: ${count} models`);
      } catch (e) {
        console.warn(`Background OpenRouter refresh failed: ${(e as Error).message}`);
      }
    }, state.refreshSeconds * 1000);
    interval.unref?.();
  }
}

main().catch((e) => {
  console.error('Fatal:', e);
  process.exit(1);
});
