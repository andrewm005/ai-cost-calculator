# Token Cost Calculator — Project Agent Guide

**Slug:** `token-calculator`   **Owner:** Andrew (Fleet Admiral)   **Seeded:** 2026-06-22

Backend for the AI token-cost calculator website. Estimates inference cost from
model + token usage. Pricing lives in `config/pricing.json` so non-engineers can
update prices without touching code. Now expanding to cover OpenRouter (live
sync from `/api/v1/models`) and Ollama (local-cost calculator + Cloud entries).

## Layout

```
token-calculator/
├── app/
│   ├── main.py        FastAPI app, route mounts, lifespan/refresh loop
│   ├── calculator.py  Pure calc logic + task_size/reasoning/task_type multipliers
│   ├── pricing.py     JSON pricing loader (single-file + multi-file merge)
│   ├── openrouter.py  NEW — OpenRouter fetcher + normalizer + cache writer
│   ├── local_cost.py  NEW — Ollama local-cost calculator (GPU + power + throughput)
│   └── models.py      Pydantic request/response schemas
├── config/
│   ├── pricing.json   Hand-curated models (PLACEHOLDER prices — verify before quoting)
│   └── openrouter.json  NEW — auto-generated cache of OpenRouter models
├── data/              NEW — local GPU + Ollama model throughput profiles
├── tests/             pytest — extend existing 33 tests + new coverage
├── requirements.txt   fastapi, uvicorn, pydantic, pytest, httpx (all on this image)
├── README.md
└── STATUS.md          current in-flight cards + known gotchas
```

## Stack

- **Backend:** Python 3.14 / FastAPI / Pydantic v2 / Uvicorn
- **HTTP client:** httpx (already in requirements.txt; OpenRouter fetcher reuses it)
- **Tests:** pytest + httpx TestClient
- **No DB.** Pricing is JSON files; loader re-reads on every request + on demand via `/admin/reload`
- **Refresh loop:** stdlib `asyncio.create_task` in a lifespan context manager; configurable via env var `OPENROUTER_REFRESH_SECONDS` (default 21600 = 6h, 0 = disable)
- **No external runtime deps beyond what's already pinned.** Don't add new packages without operator approval.

## Key files (the ones that matter)

- `app/main.py` — FastAPI app, route mounts, lifespan (background refresh loop)
- `app/pricing.py` — JSON loader; `load_pricing_files(*paths)` merges multi-file pricing
- `app/calculator.py` — pure calc; multipliers for reasoning_level + task_type
- `app/models.py` — Pydantic schemas (CalculateRequest, CompareRequest, ModelOut, …)
- `app/openrouter.py` (NEW) — fetches OpenRouter `/api/v1/models`, normalizes, caches
- `app/local_cost.py` (NEW) — `/calculate/local` endpoint: GPU + power + tokens/sec → $/token
- `config/pricing.json` — hand-curated 13 models, all flagged PLACEHOLDER
- `config/openrouter.json` (NEW) — auto-generated, do not hand-edit
- `data/local_gpu_profiles.json` (NEW) — GPU class → tokens/sec default + TDP
- `data/local_model_profiles.json` (NEW) — Ollama model tag → tokens/sec per GPU
- `tests/test_*.py` — pytest; covers loader, calculator, API, OpenRouter sync, local cost

## Common tasks

- **Dev server:** `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`
- **Run tests:** `python -m pytest tests/ -v`  (existing 33 must stay green; add new for new features)
- **Hit the API:** `curl -s localhost:8000/ | jq` (metadata); `curl -s localhost:8000/models | jq '.models | length'`
- **Calculate cost:** `curl -X POST localhost:8000/calculate -H 'Content-Type: application/json' -d '{"model_id":"openai/gpt-4o","task_size":"medium"}'`
- **Calculate local (Ollama):** `curl -X POST localhost:8000/calculate/local -H 'Content-Type: application/json' -d '{"model_id":"llama3.3:70b","task_size":"medium","gpu_model":"NVIDIA RTX 4090","gpu_cost_per_hour":0.50}'`
- **Reload pricing:** `curl -X POST localhost:8000/admin/reload`
- **Refresh OpenRouter (when implemented):** `curl -X POST localhost:8000/admin/openrouter/refresh`

## Operator-locked decisions (do not deviate without explicit approval)

1. **OpenRouter lives in `config/openrouter.json`, NOT in `config/pricing.json`.** The loader merges both; hand-curated 13 models stay hand-curated, OpenRouter models replace the stub `openrouter/auto` placeholder.
2. **Local Ollama ≠ cloud Ollama.** The `/calculate/local` endpoint is for self-hosted (GPU + power inputs); if Ollama publishes Cloud prices they go through normal pricing.json entries with `provider="ollama"`. Don't merge the two.
3. **All prices flagged PLACEHOLDER until verified against vendor docs.** README + STATUS call this out. Don't auto-quote estimates to anyone without a verification pass.
4. **Model IDs contain slashes** (`openai/gpt-4o`, `openrouter/anthropic/claude-3.5-sonnet`). The `GET /models/{model_id:path}` route uses `:path` so it captures the slash. Don't simplify back to `{model_id}` — that breaks the lookup.
5. **Calculator instances hold models in a dict.** `/admin/reload` rebuilds the set from the freshly-loaded config. After adding a model, call reload or restart.
6. **OpenRouter failures must not crash the app.** Log + keep stale cache + return 503 only from the manual refresh endpoint. The hand-curated 13 models must keep working with no network.
7. **Free OpenRouter models** (`pricing.prompt == "0" and pricing.completion == "0"`) → input/output per_1m = 0.0, notes include "(free via OpenRouter)". Don't drop them — they show the user what's available.

## Do NOT touch (without explicit operator approval)

- `~/.hermes/` — fleet state, not this project
- Any other project under `Projects/` (LeadHound, llmstxt-validator, etc.)
- Live vendor pricing pages — the OpenRouter fetcher hits the public endpoint; don't scrape vendor websites
- Twingate / DNS / domain registration — operator-managed
- `config/pricing.json` hand-curated 13 entries — verify with vendor docs, don't silently change

## Critical gotcha: kanban_complete metadata gate (Audit Fix C)

The dispatcher's `_verify_status_md_updated` gate (in `hermes_cli/kanban_preamble.py` ~line 90) blocks any `kanban_complete` on a vault `Projects/<slug>/` task unless the metadata passes one of two checks:

1. `metadata["status_md_updated"] is True`, OR
2. Any path in `metadata["changed_files"]` realpath-matches `<workspace>/STATUS.md`

**The trap:** the `kanban_complete` tool's JSON schema for `metadata` has `additionalProperties: false` and lists only 6 allowed keys: `changed_files`, `decisions`, `artifacts`, `findings`, `additional_artifacts`, `metadata` (recursive). **`status_md_updated` is NOT in the allow-list.** Pydantic silently strips it at the tool boundary. The worker thinks it passed the flag; the dispatcher never sees it; the gate fires; the worker exits cleanly → `protocol_violation` → `lost` → after 2 of those the dispatcher gives up. Don't fall into this loop.

**The working escape hatch** is the auto-detect path:

```python
kanban_complete(
    summary="...",
    metadata={
        "changed_files": [
            "/home/vboxuser/vaults/star-command/Projects/token-calculator/STATUS.md",
        ],
        "decisions": [...],
        "findings": [...],
    },
)
```

The dispatcher walks `changed_files`, realpath-compares each entry to STATUS.md, and passes the gate when it matches. STATUS.md must exist on disk at that absolute path (the dispatcher verifies paths exist).

**Do NOT** rely on `metadata["status_md_updated"]` — it gets stripped. Use `changed_files` instead. If your deliverable lives OUTSIDE the project workspace (e.g. in `Concepts/`), STILL include the STATUS.md path in `changed_files` — the auto-detect is workspace-relative to STATUS.md, not your deliverable.

**When to set `status_md_updated: True` anyway** (defense in depth): if a future tool version makes the schema more permissive, both flags being present is harmless and the dispatcher short-circuits on the first check.

## Smoke check (right now)

```bash
cd /home/vboxuser/vaults/star-command/Projects/token-calculator
python -m pytest tests/ -v | tail -5   # 33+ tests, all green
uvicorn app.main:app --host 0.0.0.0 --port 8000 &
sleep 2
curl -s localhost:8000/health | jq      # {"status":"ok","models_loaded":13}
curl -s localhost:8000/models | jq '.models | length'   # 13
curl -X POST localhost:8000/calculate -H 'Content-Type: application/json' \
  -d '{"model_id":"openai/gpt-4o","task_size":"medium"}' | jq '.cost_per_run'   # > 0
kill %1
echo "OK: backend up + models loadable + calc returns nonzero cost"
```

## Before you start (fleet-wide pre-flight)

1. `hindsight_recall` on `token-calculator` and `OpenRouter pricing` for prior context
2. `session_search` for any prior work on this project
3. Read `STATUS.md` in this folder — it lists in-flight kanban cards, known gotchas, stale docs
4. Check `kanban_show <task_id>` first if you're a retry — prior attempts often have the answer in their comment thread
5. Operator shell quirk: `PORT=3015` is set in commander's env (Star Command). If you start uvicorn and want a different port, override with `uvicorn ... --port 8000` explicitly (don't rely on PORT env).
6. Workspace is `dir:` (shared persistent) — other workers may also edit these files. Run `git status` (well, there's no git here yet, but a sibling may be writing) before patching shared files. If a sibling task on this project is `running`, check its current diff before touching the same file.

## Frontend (t_d7afb25e, shipped 2026-06-22)

The static frontend lives at `frontend/` under the project root:

- `index.html` + `app.css` + `app.js` + `logo.svg` + `favicon.svg` + `README.md`
- Plain HTML/CSS/vanilla JS — no build step, no framework, no npm
- Backend wired via `window.TOKENTALLY_API` (default `http://10.10.10.205:8001`)
- Serve: `cd frontend && python3 -m http.server 3018 --bind 0.0.0.0` then open `http://10.10.10.205:3018/`
- Backend CORS is currently `*` so the page can `fetch()` directly; tighten to the page's real origin before public launch
- All math runs through the live API; the frontend does NOT do its own calculation
