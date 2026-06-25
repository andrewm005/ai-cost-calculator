# Token Cost Calculator — TypeScript Worker (Hono)

TypeScript port of the FastAPI backend in `../app/`. Runs in **two modes**:

1. **Local dev (Node runtime)** — `npm run dev` starts a Node server on port
   8002 with pricing loaded from `../config/pricing.json` and the
   OpenRouter cache from `../config/openrouter.json`. The setInterval
   refresh loop mirrors the Python FastAPI lifespan.

2. **Production (Cloudflare Workers runtime)** — `npx wrangler deploy`
   ships the same Hono app to Cloudflare's edge with pricing cached in
   Workers KV (namespace `PRICING`, key `cache`) and refreshed every
   6 hours via a cron trigger. No home box dependency. No port. No
   process to babysit.

Both runtimes share the same calculator math, the same API surface, and
the same JSON schemas — only the storage + scheduling differ.

## Why two runtimes?

The operator wanted a TypeScript copy of the backend so they can switch
between FastAPI on Python (production-stable, runs on the home box) and
Hono on the Cloudflare edge (zero-ops, free tier, sub-millisecond cold
starts). The same code runs on both via Hono's runtime-agnostic design.

## Layout

```
worker/
├── src/
│   ├── index.ts             # Workers entry (default export + scheduled)
│   ├── server.ts            # Node entry (hono/node-server + setInterval)
│   ├── cache.ts             # Per-isolate inner-app cache (shared fetch/scheduled)
│   ├── scheduled.ts         # Cron handler — fetches OR, writes KV
│   ├── state.ts             # AppState type
│   ├── routes/
│   │   ├── meta.ts          # GET /
│   │   ├── health.ts        # GET /health
│   │   ├── models.ts        # GET /models, GET /models/:id
│   │   ├── calculate.ts     # POST /calculate, POST /calculate/compare
│   │   ├── local.ts         # POST /calculate/local, GET /local/gpus, GET /local/models
│   │   └── admin.ts         # POST /admin/reload, POST /admin/openrouter/refresh
│   └── lib/
│       ├── app.ts           # Pure Hono factory (createApp(state) → Hono)
│       ├── pricing.ts       # Disk + KV loaders, PricingLoader class
│       ├── calculator.ts    # The math — MUST match app/calculator.py exactly
│       ├── openrouter.ts    # Live sync from /api/v1/models → disk OR KV
│       ├── local_cost.ts    # Ollama GPU + power cost
│       ├── schema.ts        # Zod request/response schemas
│       ├── local_data_assets.ts        # Baked GPU + Ollama model profiles
│       └── pricing_data_assets.ts      # Baked hand-curated pricing (13 models)
├── tests/                   # vitest — mirrors ../tests/ pytest
│   ├── calculator.test.ts
│   ├── pricing.test.ts
│   ├── openrouter.test.ts
│   ├── local_cost.test.ts
│   └── kv_cycle.test.ts     # NEW — KV write/read cycle invariant
├── wrangler.toml            # NEW — Cloudflare Workers config (KV + cron)
├── package.json
├── tsconfig.json
├── vitest.config.ts
└── README.md (this file)
```

## Run — local dev (Node)

```bash
cd worker
npm install
npm test                # vitest run — 64 tests must stay green
npm run dev             # start on port 8002
npm run build           # strict TypeScript compile check
```

The dev server reads pricing from `../config/pricing.json` and
`../config/openrouter.json` by default. Override with env vars
`PRICING_CONFIG` and `OPENROUTER_CACHE` (relative to the repo root).

## Run — Cloudflare Workers (production)

### Prerequisites

- A Cloudflare account (free tier is fine — Workers free includes
  100K requests/day, 100K KV reads/day, 1K KV writes/day).
- `wrangler` CLI: `npm install` (it's a devDep) or `npx wrangler --version`.
- Auth: `npx wrangler login`.

### One-time setup

```bash
# 1. Create the KV namespace
npx wrangler kv:namespace create PRICING
# → Wrangler prints: { binding = "PRICING", id = "abc123..." }

# 2. Paste the ID into worker/wrangler.toml (replaces
#    REPLACE_WITH_KV_NAMESPACE_ID). Optionally create a preview namespace
#    for `wrangler dev`:
#      npx wrangler kv:namespace create PRICING --preview
#    Paste that ID into the `preview_id` field.

# 3. (Optional) Local Pages Functions test:
npx wrangler pages dev ../frontend --port 8788
# This boots the frontend static files AND a Pages Function host that
# picks up functions/api/[[path]].ts. Hits /api/calculate on :8788
# routes through the same code path as production.

# 4. Deploy:
npx wrangler deploy
# Or for Pages Functions: connect the repo via the dashboard
# (Pages → Connect to Git → build dir = frontend, no build command),
# then add the PRICING KV binding in
# Pages project → Settings → Functions → KV namespace bindings.

# 5. Add a custom domain:
# Pages project → Custom domains → aicostcalculator.net
```

### How the cron refresh works

`wrangler.toml` declares `[triggers] crons = ["0 */6 * * *"]`. Cloudflare's
runtime fires the `scheduled()` handler in `src/scheduled.ts` every 6
hours on the hour. The handler:

1. Calls `refreshToKV(env.PRICING, "cache")` — fetches OpenRouter's
   public `/api/v1/models`, normalizes each entry, and writes the cache
   blob to KV at key `cache`.
2. Calls `invalidateCache()` to drop the per-isolate cache so the next
   fetch handler call rebuilds state from KV.

Failures are logged but never crash — the stale cache is kept (per
AGENTS.md decision #6: "OpenRouter failures must not crash the app").

### Verify the deploy

```bash
# Health check
curl https://aicostcalculator.net/api/health

# Calculate cost
curl -X POST https://aicostcalculator.net/api/calculate \
  -H 'Content-Type: application/json' \
  -d '{"model_id":"openai/gpt-4o","task_size":"medium"}'
```

## API parity

Every endpoint, request body, and response shape matches the Python
service verbatim. The frontend (`../frontend/app.js`) can switch by
changing `window.TOKENTALLY_API`:

| Backend | `window.TOKENTALLY_API` | URL pattern |
|---------|-------------------------|-------------|
| Python FastAPI (home box) | `https://aicostcalculator.net` | `${API}/calculate` |
| Hono Node (local dev) | `https://aicostcalculator.net` | `${API}/calculate` |
| Cloudflare Workers (prod) | (empty — same origin) | `/api/calculate` |

The default in `frontend/app.js:5` is now empty string (`''`) so a
production deploy on a custom domain works without any frontend edits.

The `Calculator` is ported to keep math outputs byte-for-byte identical
to the Python version (down to 1e-9 precision in tests). See
`tests/calculator.test.ts` for the equivalence test suite and
`tests/parity_test.py` for the live cross-backend parity harness.

## Refresh loop

| Runtime | Mechanism | Default interval |
|---------|-----------|------------------|
| Python FastAPI | `asyncio.create_task` in lifespan | 6 h |
| Node (this) | `setInterval` in `server.ts` | 6 h |
| Workers (this) | Cron trigger fires `scheduled.ts` | 6 h |

`OPENROUTER_REFRESH_SECONDS=0` disables the Node scheduler. The
Workers cron is controlled via `wrangler.toml` (`[triggers] crons`).

## Bundled data assets

Two JSON files are baked into the worker bundle as TypeScript modules:

- `src/lib/pricing_data_assets.ts` — generated from `config/pricing.json`
  (the 13 hand-curated models). Regenerate with:
  ```
  node scripts/bake_pricing_assets.mjs
  ```

- `src/lib/local_data_assets.ts` — hand-maintained copy of
  `data/local_gpu_profiles.json` + `data/local_model_profiles.json`.
  Edit both the source JSON and the TS module in lockstep (or just the
  TS module and copy back).

These exist because the Workers runtime has no `fs` module — data has
to ship in the bundle. They're ~10 KB total, well under the 1 MB
worker bundle limit.