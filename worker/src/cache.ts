/**
 * Per-isolate app cache — shared between the fetch handler (src/index.ts)
 * and the cron handler (src/scheduled.ts).
 *
 * The fetch handler caches the inner Hono app (built from a freshly-loaded
 * KV state) for KV_TTL_MS to amortize KV reads. The cron handler invalidates
 * the cache after every successful refresh so the next request sees the
 * freshest pricing immediately.
 *
 * Cloudflare Workers auto-routes requests to isolates; a hot worker
 * typically uses 1-2 isolates. The module-level `cached` variable is
 * per-isolate, which is exactly the granularity we want.
 */

import type { Hono } from 'hono';

interface CachedApp {
  app: Hono;
  cachedAt: number;
}

/** How long the cached app is reused before re-reading from KV. */
export const KV_TTL_MS = 60_000; // 1 minute

let cached: CachedApp | null = null;

/** Return the cached app if it's fresh, otherwise null. */
export function getCached(): CachedApp | null {
  if (cached === null) return null;
  if (Date.now() - cached.cachedAt > KV_TTL_MS) {
    cached = null;
    return null;
  }
  return cached;
}

/** Store a fresh inner Hono app in the cache. */
export function setCached(app: Hono): void {
  cached = { app, cachedAt: Date.now() };
}

/** Drop the cache. The next fetch will rebuild from KV. */
export function invalidateCache(): void {
  cached = null;
}