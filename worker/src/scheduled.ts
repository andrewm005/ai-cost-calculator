/**
 * Cloudflare Workers — cron trigger handler.
 *
 * Fires every 6 hours via the schedule declared in `wrangler.toml`
 * (`[triggers] crons = ["0 * /6 * * *"]`). Fetches OpenRouter's public
 * `/api/v1/models` endpoint, normalizes the entries, and writes the result
 * to the `PRICING` KV namespace at the `cache` key.
 *
 * Mirrors the Python FastAPI lifespan refresh loop in `app/main.py`, with
 * one key difference: Workers have no `setInterval`, so the cron trigger is
 * the only refresh path. The `/admin/openrouter/refresh` endpoint in the
 * Worker entry is therefore a no-op (it returns an error explaining how to
 * trigger the cron manually via the Cloudflare dashboard).
 */

import { refreshToKV } from './lib/openrouter.js';
import { invalidateCache } from './cache.js';
import type { KVNamespaceLike } from './lib/pricing.js';

/** Cloudflare Env bindings (the same shape used by the fetch handler). */
export interface Env {
  /** Workers KV namespace binding — `wrangler kv:namespace create PRICING`. */
  PRICING: KVNamespaceLike;
  /** KV key holding the merged pricing blob. Default: 'cache'. */
  PRICING_KEY?: string;
}

/** Cron event payload — see Cloudflare docs. */
interface ScheduledEvent {
  /** ISO timestamp of when the trigger fired. */
  scheduledTime: number;
  /** Cron pattern that fired. */
  cron: string;
}

/** Workers ExecutionContext — passed to scheduled() for `ctx.waitUntil`. */
interface ExecutionContext {
  waitUntil(promise: Promise<unknown>): void;
  passThroughOnException(): void;
}

export async function scheduled(
  event: ScheduledEvent,
  env: Env,
  ctx: ExecutionContext,
): Promise<void> {
  // Schedule the refresh work so the cron invocation returns immediately
  // and the refresh runs in the background. The `ctx.waitUntil` lets the
  // Workers runtime keep the request alive until the work completes.
  const work = (async () => {
    try {
      const count = await refreshToKV(env.PRICING, env.PRICING_KEY ?? 'cache');
      invalidateCache(); // force the next request to re-read KV
      console.log(`[scheduled] OpenRouter refresh OK: ${count} models`);
    } catch (e) {
      // Per AGENTS.md decision #6: OpenRouter failures must NOT crash the app.
      // Log and keep the stale cache; the next cron tick will retry.
      console.warn(`[scheduled] OpenRouter refresh failed: ${(e as Error).message}`);
    }
  })();

  // waitUntil keeps the worker alive until the promise resolves.
  // If `ctx.waitUntil` is unavailable (e.g. some test environments), await directly.
  if (typeof ctx.waitUntil === 'function') {
    ctx.waitUntil(work);
  } else {
    await work;
  }
}