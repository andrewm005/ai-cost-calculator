/**
 * Cloudflare Pages Functions — auto-routes /api/* to the Hono worker.
 *
 * If the operator chooses Pages Functions instead of a standalone Worker,
 * Cloudflare Pages auto-routes any request under /api/ to this file. We
 * re-export the Hono app's fetch handler so all endpoints become
 * same-origin /api/calculate, /api/models, etc.
 *
 * NOTE: This file lives at the REPO ROOT (sibling to app/, worker/, frontend/),
 * NOT inside worker/. Pages Functions has its own discovery mechanism that
 * looks for `functions/<path>.ts` files anywhere in the repo root.
 *
 * Setup:
 *   1. Connect the repo to Cloudflare Pages (dashboard → Pages → Connect to Git).
 *   2. Set the build output directory to `frontend` (the static site).
 *   3. Add the PRICING KV namespace binding in
 *      Pages project → Settings → Functions → KV namespace bindings:
 *        Variable name: PRICING
 *        KV namespace: (select the namespace created via wrangler)
 *   4. Add a custom domain (e.g. aicostcalculator.net) under
 *      Pages project → Custom domains.
 *
 *   After this is wired up, the frontend's `window.TOKENTALLY_API` should
 *   default to '' (same origin), so it hits /api/* on the Pages domain
 *   without any cross-origin setup.
 */
import app from '../worker/src/index.js';

// Pages Functions expects a single `onRequest` (or `onRequestGet` /
// `onRequestPost` etc.) export. Hono's `app.fetch` matches the Workers
// fetch handler signature (Request → Promise<Response>), which is exactly
// what Pages Functions calls.
//
// We destructure-on-export to keep this file minimal — no custom wrapper.
export const onRequest = (context: {
  request: Request;
  env: Record<string, unknown>;
  // Pages also passes params, data, etc.; Hono's fetch only needs request + env.
  [key: string]: unknown;
}) => app.fetch(context.request, context.env as { PRICING: unknown });