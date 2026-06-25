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
  gpuProfiles: Record<string, GpuProfile>;
  modelProfiles: Record<string, ModelProfile>;
  reloadPricing: () => number;
  refreshOpenrouter: () => Promise<number>;
  openrouterModelCount: () => number;
}
