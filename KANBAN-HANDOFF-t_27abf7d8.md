# Kanban Handoff — t_27abf7d8 (OpenRouter live-sync)

**Task ID:** t_27abf7d8
**Title:** OpenRouter live-sync (auto-fetch /api/v1/models → pricing merge)
**Assignee:** builder
**Status (filesystem-verified):** SHIPPED + VERIFIED
**Status (kanban DB):** stuck in `running` because the kanban DB is corrupt (every kanban_* tool errors)
**Date:** 2026-06-22

This file is the durable record of the work, in case the kanban DB stays broken.

## What was built

| Layer | File | Status |
|---|---|---|
| New | `app/openrouter.py` | 313 lines — fetcher + normalizer + cache writer/reader |
| New | `config/openrouter.json` | 336 models, 147KB, 57 providers, 27 free models preserved |
| New | `tests/test_openrouter.py` | 19 tests — normalizer, fetcher, cache writer, cache reader |
| Mod | `app/pricing.py` | added `load_pricing_files(*paths, missing_ok=False)` + `PricingLoader.replace_models()` |
| Mod | `app/main.py` | added `POST /admin/openrouter/refresh` + lifespan + `OPENROUTER_REFRESH_SECONDS` env var |
| Mod | `config/pricing.json` | `_meta` bumped to schema_version 1.1 with `openrouter_cache` field |
| Mod | `tests/test_pricing.py` | +6 multi-file merge tests |
| Mod | `tests/test_api.py` | +5 endpoint tests (refresh works, refresh 503 on network failure, lifespan skips when refresh=0, etc.) |
| Mod | `README.md` | documented the new endpoint + env var |
| Mod | `STATUS.md` | marked this task SHIPPED + synced with t_5fffc65f and t_2b8b6b30 status |

## What was verified (this run, 2026-06-22)

1. **pytest: 64/64 pass** — full suite. No regressions.
2. **Live API spot-check** — fetched `https://openrouter.ai/api/v1/models` (339 live) and compared 3 cached entries to OpenRouter's published prices, all match to 4 decimal places:
   - `openrouter/openai/gpt-4o`: cache $2.5/$10 vs live $2.5000/$10.0000 ✓
   - `openrouter/anthropic/claude-sonnet-4`: cache $3.0/$15 vs live $3.0000/$15.0000 ✓
   - `openrouter/google/gemini-2.5-pro`: cache $1.25/$10 vs live $1.2500/$10.0000 ✓
3. **Live boot smoke** — uvicorn on port 18765 (use `python3 -m uvicorn`, the bare `uvicorn` binary isn't on PATH):
   - `GET /health` → `{"status":"ok","models_loaded":348,"openrouter_models":336}`
   - `GET /models` → 348 models total (12 hand-curated + 336 OR; `openrouter/auto` placeholder correctly replaced per AGENTS.md locked decision #1)
   - `POST /calculate openrouter/anthropic/claude-sonnet-4 medium` → cost_per_run=$0.0450 (matches $3/M × 5000 in + $15/M × 2000 out)
   - `POST /calculate openai/gpt-4o medium` → cost_per_run=$0.0325 (matches $2.5/M × 5000 + $10/M × 2000)
   - `POST /admin/openrouter/refresh` → live call succeeded, wrote 335 OR models (1 deprecated since our cache — expected real-world drift)
   - `POST /admin/reload` → works
4. **Cache schema sanity** — `_meta` has `count:336, last_synced_at:2026-06-22T14:38:53Z, source:https://openrouter.ai/api/v1/models`; 57 distinct providers; 27 free models preserved (per AGENTS.md locked decision #7); all 336 OR models have `notes: "OpenRouter live sync"`.

## Operator-locked decisions (confirmed upheld)

1. ✓ OpenRouter lives in `config/openrouter.json`, NOT merged into `pricing.json` (hand-curated 13 stay hand-curated; `openrouter/auto` placeholder is replaced when OR models load).
2. ✓ Local Ollama ≠ cloud Ollama — not in this task (handled by t_5fffc65f).
3. ✓ All prices flagged PLACEHOLDER until verified against vendor docs. (OR prices are pulled live; hand-curated 13 still flagged PLACEHOLDER in `config/pricing.json` `_meta.notes`.)
4. ✓ Model IDs contain slashes — `GET /models/{model_id:path}` uses `:path` (unchanged from t_2484dd6c).
5. ✓ Calculator instances hold models in a dict; `/admin/reload` rebuilds after config edits.
6. ✓ OpenRouter failures don't crash the app — log + keep stale cache + return 503 only from the manual refresh endpoint; hand-curated 13 must keep working with no network (test `test_refresh_endpoint_returns_503_on_network_failure` enforces this).
7. ✓ Free OR models preserved (27 in cache, 0 → 0 pricing).

## Why this handoff exists

The kanban DB at `~/.hermes/kanban.db` is corrupt. Every kanban_* tool (show, comment, complete, block) fails with:

```
fts5: error creating shadow table tasks_fts_data: table 'tasks_fts_data' already exists
```

The dispatcher auto-backs-up on detection (today's backups: `kanban.db.corrupt.600f520c650b1d3d.bak` at 14:45, `kanban.db.corrupted-2026-06-22-1447` at 14:47) but does not auto-restore. The integrity check (`PRAGMA integrity_check;`) returns `ok`, but `.tables` returns nothing on the live DB during my read attempts — the hermes dispatcher (PID 2071) is concurrently modifying the DB. Per the user profile ("shared infra / persistent state / operator shell = confirm per step"), I did NOT auto-restore or auto-swap any DB.

## What the operator needs to do

1. **Repair the kanban DB.** Try, in order:
   - `sqlite3 ~/.hermes/kanban.db .recover` (already tried — only produced 210 bytes; schema is more deeply broken than just FTS5)
   - Restore from the most recent intact backup. The `.corrupt.600f520c650b1d3d.bak` (14:45 today) had 15 tasks including ours with status `blocked`, but the page-level integrity check still fails (`database disk image is malformed (11)`). It would need a manual salvage.
   - If all backups are unrecoverable, rebuild from session history (the prior session's comments and the file evidence in this project ARE the source of truth).

2. **Manually mark t_27abf7d8 as done.** The work IS done — this file + the test suite + the live spot-check are evidence.

3. **Once unblocked, dispatch t_2b8b6b30 (verifier)** — the verifier card is gated on this task + t_5e6f95f8 (research, already done).

4. **Then dispatch t_5fffc65f (Ollama local-cost + Cloud entries)** — gated on this task. My changes to `app/main.py` were additive (new endpoint + lifespan + new file `openrouter.py`), so Ollama has a clean merge path.

## Files referenced

- `/home/vboxuser/vaults/star-command/Projects/token-calculator/app/openrouter.py`
- `/home/vboxuser/vaults/star-command/Projects/token-calculator/config/openrouter.json`
- `/home/vboxuser/vaults/star-command/Projects/token-calculator/tests/test_openrouter.py`
- `/home/vboxuser/vaults/star-command/Projects/token-calculator/app/pricing.py`
- `/home/vboxuser/vaults/star-command/Projects/token-calculator/app/main.py`
- `/home/vboxuser/vaults/star-command/Projects/token-calculator/config/pricing.json`
- `/home/vboxuser/vaults/star-command/Projects/token-calculator/README.md`
- `/home/vboxuser/vaults/star-command/Projects/token-calculator/STATUS.md`

## Counts at handoff time

- OpenRouter models in cache: 336 (latest live was 339; 3 added since 2026-06-22T14:38:53Z)
- Hand-curated models: 13 in `pricing.json`, 12 loaded after `openrouter/auto` placeholder is replaced by OR (so `models_loaded` = 348)
- pytest tests: 64 pass (33 original + 6 pricing merge + 19 openrouter + 6 API additions)
- Providers represented: 57 distinct providers in the OR cache
- Free models preserved: 27 in cache (0/0 pricing per AGENTS.md decision #7)

---

## Re-verification log (4th worker session, 2026-06-22T15:43Z)

This task was dispatched to a fresh worker session after a third prior session
ended in the same FTS5 blocker. State on disk re-verified intact:

- `app/openrouter.py` (313 lines), `config/openrouter.json` (4363 lines, 147KB),
  `tests/test_openrouter.py` (385 lines), `app/pricing.py` (141 lines),
  `app/main.py` (377 lines), `config/pricing.json` (180 lines),
  `tests/test_pricing.py` (193 lines), `tests/test_api.py` (422 lines) — all
  present, unmodified since the prior session's last write.
- pytest re-run via `python3 -m pytest tests/ -q`: **64 passed** (0.85s).
- No regressions.

### DB state observed this session

- `/home/vboxuser/.hermes/kanban.db` is 626,688 bytes (matches prior session
  reports). The operator has rebuilt the DB since the prior session — the
  schema is now populated:
  - `.tables` returns `kanban_notify_subs, lost_and_found, task_attachments,
    task_comments, task_events, task_links, task_runs, tasks,
    tasks_fts_config, tasks_fts_data, tasks_fts_docsize, tasks_fts_idx`.
  - `SELECT id, status, assignee FROM tasks WHERE id='t_27abf7d8'` →
    `t_27abf7d8|running|builder`.
  - `PRAGMA integrity_check` → `ok`.
  - `.recover` → 625,909 bytes (full recoverable content).
- But the dispatcher still hits the same FTS5 shadow-table collision on
  every `kanban_*` op. Diagnosis: the FTS5 init path tries to recreate
  `tasks_fts_data` on every operation and trips over the existing one.
- `kanban_complete` (with full structured metadata) → FTS5 error.
- `kanban_block` (with operator-actionable reason) → FTS5 error.
- All four prior workers hit the same wall (sessions 13:36, 15:03, 15:28,
  and this one at 15:43).

### Concrete operator fix path

The FTS5 shadow-table collision looks like the dispatcher's
`CREATE VIRTUAL TABLE tasks_fts USING fts5(...)` runs unconditionally on
every kanban op, but the table already exists from the prior init. One of
these should clear it (each is operator-grade — NOT a builder action):

1. **DROP the shadow table and let the dispatcher recreate it:**
   ```bash
   sqlite3 /home/vboxuser/.hermes/kanban.db \
     "DROP TABLE IF EXISTS tasks_fts_data; DROP TABLE IF EXISTS tasks_fts_idx; DROP TABLE IF EXISTS tasks_fts_config; DROP TABLE IF EXISTS tasks_fts_docsize; DROP TABLE IF EXISTS tasks_fts;"
   ```
   Then run any `kanban_*` op — the dispatcher will recreate FTS5 cleanly.

2. **Mark task done directly via SQL** (work IS verifiably done; this is
   the legitimate operator override for an infrastructure-blocked task):
   ```bash
   sqlite3 /home/vboxuser/.hermes/kanban.db \
     "UPDATE tasks SET status='done', result='OpenRouter live-sync shipped (64/64 pytest, 348 models loaded)', updated_at=$(date +%s) WHERE id='t_27abf7d8';"
   ```

3. **Restore from a clean backup.** `kanban.db.corrupt.600f520c650b1d3d.bak`
   (today 14:45, 790KB) had the most-recently-populated schema per prior
   session's analysis.

### Why I didn't take any of those paths

All three are operator-grade interventions on shared infrastructure
(kanban DB, hermes gateway). Per user doctrine ("shared infra /
persistent state / operator shell = confirm per step"), the worker does
not mutate the DB. Per the kanban-worker skill (corruption-handoff
recipe), I tried `kanban_complete` and `kanban_block` once each, then
stopped.

---

## Re-verification log (5th worker session, 2026-06-22 ~16:00Z)

Same dispatcher as 4th session. State on disk re-verified intact:

- pytest via `python3 -m pytest tests/ -q`: **64 passed** (0.88s, 1 deprecation warning).
  No regressions across 5 worker sessions.
- All files unmodified since 4th session's last write:
  - `app/openrouter.py` (313 lines, 12560 bytes)
  - `config/openrouter.json` (4363 lines, 146681 bytes)
  - `tests/test_openrouter.py` (385 lines, 13277 bytes)
  - `app/pricing.py` (141 lines, 5678 bytes)
  - `app/main.py` (377 lines, 14526 bytes)
  - `config/pricing.json` (180 lines, 6086 bytes)
  - `tests/test_pricing.py` (193 lines, 7329 bytes)
  - `tests/test_api.py` (422 lines, 14729 bytes)

### DB state observed this session (unchanged from 4th)

- `/home/vboxuser/.hermes/kanban.db` still 626,688 bytes, integrity ok,
  schema populated, t_27abf7d8 in `running` status assigned to `builder`.
- `kanban_complete` (with full structured metadata) → FTS5 error.
- `kanban_block` → FTS5 error.

### Operator action (still required, same as 4th session)

Any of the three paths in §"Concrete operator fix path" above will
unblock this card. The cleanest single command is the DROP-shadow-table
path — the dispatcher will recreate the FTS5 indexes on the next op and
subsequent `kanban_complete` will succeed against the live schema.

---

## Re-verification log (6th worker session, 2026-06-22 17:52Z)

Same dispatcher. State on disk re-verified intact:

- pytest via `python3 -m pytest tests/ -q`: **64 passed** (0.84s, 1 deprecation warning).
  No regressions across 6 worker sessions.
- All files unmodified since 5th session's last write (byte sizes match):
  - `app/openrouter.py` (313 lines, 12560 bytes)
  - `config/openrouter.json` (4363 lines, 146681 bytes)
  - `tests/test_openrouter.py` (385 lines, 13277 bytes)
  - `app/pricing.py` (141 lines, 5678 bytes)
  - `app/main.py` (377 lines, 14526 bytes)
  - `config/pricing.json` (180 lines, 6086 bytes)
  - `tests/test_pricing.py` (193 lines, 7329 bytes)
  - `tests/test_api.py` (422 lines, 14729 bytes)

### DB state observed this session — NEW CORRUPTION

The DB has REGRESSED since the 5th session (2 hours ago):

| Session        | DB size    | integrity_check | Notes                                   |
|----------------|------------|-----------------|-----------------------------------------|
| 4th (~15:43Z)  | 626,688 B  | ok              | FTS5 shadow-table collision on every op  |
| 5th (~16:00Z)  | 626,688 B  | ok              | same                                    |
| **6th (17:52Z)** | **630,784 B** | **FAIL**     | **btree page corruption**               |

`PRAGMA integrity_check` now returns:

```
*** in database main ***
Tree 6 page 6 cell 0: invalid page number 155
Tree 6 page 6 cell 14: 2nd reference to page 19
wrong # of entries in index idx_comments_task
```

This is **genuine btree page corruption**, not just FTS5 shadow-table
collision. The corruption appeared between the 5th session (~16:00Z)
and now (17:52Z), about 2 hours apart. No kanban ops were attempted in
between — this is a fresh on-disk corruption, possibly a fsync / WAL
issue with concurrent writes from the dispatcher process.

### Dispatcher has hardened its refusal behavior

The dispatcher's error message is now explicit and protective:

```
Refusing to open corrupt kanban DB at /home/vboxuser/.hermes/kanban.db:
integrity_check returned '<btree errors>'. Original preserved;
backup at /home/vboxuser/.hermes/kanban.db.corrupt.4482e6e5049dfcb6.bak.
```

Both `kanban_complete` and `kanban_block` returned this identical
message — the dispatcher now refuses to even ATTEMPT any op on a
corrupt DB. No partial state can land. This is the cleanest possible
failure mode and validates the durability-of-evidence path: the file
system IS the source of truth until the DB is repaired.

### Backup file inventory (2026-06-22 17:52Z)

```
kanban.db                              630784 B   17:52Z  (current — btree corrupt)
kanban.db-shm                           32768 B   17:55Z
kanban.db-wal                                0 B   17:55Z

kanban.db.corrupt.4482e6e5049dfcb6.bak  630784 B   17:52Z  ← fresh this session
kanban.db.corrupt.600f520c650b1d3d.bak  790528 B   14:45Z  (4th/5th session's "intact")
kanban.db.corrupted-2026-06-22-1447     790528 B   14:47Z  (later copy of same)
kanban.db.corrupt-2026-06-19-2004       446464 B   19:48Z  (older)
kanban.db.corrupt.30716fdbd4c36e9f.bak  438272 B   19:37Z  (older)
kanban.db.corrupt.54ad4aa9950253ed.bak  438272 B   19:36Z  (older)
kanban.db.corrupt.6785f58f21b4e5a1.bak  438272 B   19:41Z  (older)
kanban.db.corrupt.c1f712dc625dff2a.bak  446464 B   19:48Z  (older)
kanban.db.corrupt.cfc846297e7faa48.bak  438272 B   19:42Z  (older)
kanban.db.corrupted-2026-06-18         9797632 B   21:14Z  (oldest, biggest)
kanban.db.recovered                    3182592 B   Jun 18  (largest .recovered)
```

The 4th/5th session recommendation to "restore from
`kanban.db.corrupt.600f520c650b1d3d.bak`" was based on file size
heuristics. That backup is now itself suspect — the dispatcher hasn't
verified its integrity in 4 hours. The `.recovered` file (3.18MB, Jun 18)
is the largest recoverable candidate but predates this session's work
by 4 days; the schema there may not match the current task graph.

### Concrete operator fix path (revised)

The original §"Concrete operator fix path" three options still apply,
but with new context:

1. **Try the largest intact backup first** — `kanban.db.recovered`
   (3.18MB, Jun 18) is the most likely to have a recoverable schema.
   But it predates the current task graph, so a restore would lose
   ~4 days of task state. Re-dispatch any lost tasks from session
   history.
2. **DROP the FTS5 shadow tables and let the dispatcher recreate them.**
   This worked in theory on the 4th/5th session (where the DB was
   btree-intact) but the current DB has actual btree corruption, so
   it won't help unless the btree corruption is fixed first.
3. **Mark task done via direct SQL.** Work IS done — 64/64 tests pass,
   348 models loaded live, 4dp spot-check against OpenRouter. The
   legitimate operator override:
   ```bash
   sqlite3 /home/vboxuser/.hermes/kanban.db \
     "UPDATE tasks SET status='done', result='OpenRouter live-sync shipped (64/64 pytest, 348 models loaded)' WHERE id='t_27abf7d8';"
   ```
   But this requires the DB to be openable. If the dispatcher keeps
   refusing, the only path is to restore from a backup first.

### Why I didn't take any of those paths

All three are operator-grade interventions on shared infrastructure
(kanban DB, hermes gateway). Per user doctrine ("shared infra /
persistent state / operator shell = confirm per step"), the worker does
not mutate the DB. Per the kanban-worker skill (corruption-handoff
recipe), I tried `kanban_complete` and `kanban_block` once each, then
stopped.

### Next worker session will see the same wall

If the operator doesn't intervene, every subsequent kanban dispatch
onto this task will hit the same corruption. The durable evidence
chain (this file + the comment thread + the test suite + the on-disk
files) is the source of truth until the DB is repaired.
