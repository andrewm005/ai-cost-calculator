/**
 * App state — shared between route handlers.
 *
 * This is the TypeScript equivalent of the `state` dict in app/main.py.
 */

import type { PricingLoader } from './lib/pricing.js';
import type { Calculator } from './lib/calculator.js';
import type { GpuProfile, ModelProfile } from './lib/local_cost.js';

export interface AppState {
  loader: PricingLoader;
  calculator: Calculator;
  pricingPaths: string[];
  openrouterCachePath: string | null;
  refreshSeconds: number;
  // ISO timestamp of when the price cache was last successfully refreshed.
  // null if the worker has only the baked-in baseline and the KV/cache has
  // never been populated. Used by the meta endpoint so the UI can show
  // "OpenRouter prices as of <date>" and the user can spot stale data.
  cacheLastSyncedAt: string | null;
  gpuProfiles: Record<string, GpuProfile>;
  modelProfiles: Record<string, ModelProfile>;
  reloadPricing: () => number;
  refreshOpenrouter: () => Promise<number>;
  openrouterModelCount: () => number;
}
