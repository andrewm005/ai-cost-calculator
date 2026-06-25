# Show HN — AI Cost Calculator (copy-paste ready)

> Replace `aicostcalculator.net` with your actual domain (e.g. aicostcalculator.com) before posting.

**Title:** Show HN: AI Cost Calculator – Free AI Cost Calculator (349 OpenRouter Models, Live)

**URL:** https://aicostcalculator.net/

**Body:**

I built a free AI cost calculator that pulls live pricing from all 349 models
on OpenRouter and lets you estimate costs for any workload. No signup, no
tracking, no API keys. Everything runs client-side.

The interesting bits:

- **Live pricing**: pulls from OpenRouter's /api/v1/models every 6 hours. The
  numbers always match what you'd actually pay.
- **One page per model**: /models/openai-gpt-4o, /models/anthropic-claude-sonnet-4,
  etc. — 349 static pages optimized for "[model name] pricing" searches.
- **Side-by-side comparison**: pick up to 5 models, see cost deltas across
  workload sizes (chat / RAG / coding / agentic / long-context).
- **Local LLM cost**: GPU + power + tokens-per-second → cost-per-million,
  for when you're deciding "should I self-host Llama 70B or pay for
  DeepSeek?". This is the part nobody else has.
- **43 project presets**: LangChain agent, RAG pipeline, full Next.js app,
  etc. Each preset has realistic token + iteration defaults sourced from
  SWE-bench, Cursor telemetry, and Devin case studies.
- **Workflow multipliers**: Single chat vs Coding assistant vs Agentic vs
  Multi-agent — adds 2k–12k sys prompt tokens + 5–20 tool calls + 1.2–1.6×
  retry to the cost calc. Matches what real agent loops actually cost.

Stack: FastAPI backend (Python), vanilla JS frontend, no frameworks. The
whole thing fits in one repo. ~600 lines of backend math, 1500 lines of
frontend.

Happy to talk through:
- The model page generation strategy (one static HTML per model)
- The OpenRouter sync loop + how I handle the 6h refresh
- How I source "typical_iterations" defaults (real research, not vibes)
- The local cost calculator math (GPU TDP × tokens/sec)

What I want feedback on:
- Is the workflow type dropdown (chat/coding/RAG/agentic/multi-agent) the
  right level of granularity?
- Am I missing any obvious cost categories?
- Pricing blind spots — anything where my numbers don't match reality?

GitHub: https://github.com/[YOUR_GH_USERNAME]/tokentally

---

**Posting notes:**
- Best time: Tuesday or Wednesday, 9-11am EST (peak HN dev engagement)
- Reply to EVERY comment within 1 hour for the first 6 hours
- If a comment asks "how does this differ from X?" don't trash competitors —
  answer with a feature comparison
- Be ready for "why .com not .ai?" or "you misspelled a model" type nitpicks
  — polite + fast replies win

---

# Hacker News reply template (if asked about competitors)

If someone asks "how is this different from AIPricing.guru / Helicone / Portkey?":

> Different scope: AIPricing.guru shows static tables that go stale.
> Helicone/Portkey are paid observability platforms ($79-799/mo) — they're
> about logging your actual API spend. AI Cost Calculator is a free estimator for
> what you'd pay *before* you spend it. Different problem.
>
> OpenRouter integration is the wedge — I'm the only calculator that pulls
> their full 349-model catalog live. Others show a hand-curated subset.
>
> Local cost calculator is also unique — there's no other tool that does
> GPU + power + tokens/sec math for self-hosted models.
