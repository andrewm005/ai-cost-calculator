# Reddit posts (copy-paste ready)

> Replace `aicostcalculator.net` with your actual domain.

---

## 1. r/LocalLLaMA (https://reddit.com/r/LocalLLaMA)

**Title:** I built a cost calculator that compares self-hosted Ollama vs cloud APIs honestly (GPU + power + tokens/sec)

**Body:**

I kept getting confused by LLM cost comparisons — most calculators only
show cloud API pricing and ignore what self-hosted actually costs you.

So I built AI Cost Calculator (aicostcalculator.net) which has a `/calculate/local`
endpoint that takes:
- GPU model (H100, A100, RTX 4090, M2 Ultra, etc.)
- Tokens/sec throughput for your chosen model on that GPU
- $/hour GPU rental (spot instance pricing)
- Tokens/month you plan to serve

And returns:
- Cost per million tokens (self-hosted)
- Break-even point vs same model on OpenRouter
- Total monthly cost
- Power cost (if you tell it your kWh rate)

Example numbers from my own calculator:
- Llama 3.3 70B on 2× RTX 4090 (spot @ $0.50/hr each) → ~$3.70/1M tokens
  self-hosted
- Same model via OpenRouter → $0.88/1M input, $0.88/1M output
- Break-even: ~3M tokens/day before self-hosting wins on cost alone
  (excluding your time)

For DeepSeek V3 (the cheap one): cloud is $0.14/$0.28 per 1M. You'd
need to run an H100 cluster to beat that — not worth it for most people.

The calculator is free, no signup, and the GPU profiles are from the
Ollama benchmark suite + community-reported numbers. Happy to add your
GPU if you have benchmark data.

What's missing or wrong? Where do my numbers fall apart vs your
real-world setup?

---

## 2. r/MachineLearning (https://reddit.com/r/MachineLearning)

**Title:** [P] AI Cost Calculator — open-source AI cost estimator with live OpenRouter pricing + local GPU math

**Body:**

Open-sourced this weekend. AI Cost Calculator (aicostcalculator.net) is a free AI cost
calculator that pulls live pricing from OpenRouter's 349-model catalog
and lets you estimate costs for any workload. Built it for my own
budgeting, figured other people might find it useful.

What it does:
- Live OpenRouter pricing for 349 models (refreshes every 6h via cron)
- 43 project presets with realistic token + iteration defaults (LangChain
  agent, RAG pipeline, full Next.js app, etc.)
- Side-by-side comparison of up to 5 models with cost deltas
- Self-hosted cost math: GPU + power + tokens/sec
- Workflow multipliers: Single chat / Coding assistant / RAG / Agentic /
  Multi-agent (adds sys prompt + tool call + retry overhead)

Backend is FastAPI + Pydantic, frontend is vanilla JS (no React/Vue
build step). One static HTML file per model (349 total) for SEO.

Happy to discuss:
- The data sourcing (OpenRouter + vendor pricing pages + SWE-bench /
  Cursor telemetry for iteration defaults)
- The local cost math (how to estimate tokens/sec from Ollama benchmarks)
- The workflow multiplier model (how I picked 1.4× for agentic, 1.6×
  for multi-agent)

GitHub: https://github.com/[YOUR_GH_USERNAME]/tokentally

---

## 3. r/OpenAI, r/ClaudeAI, r/LocalLLaMA, r/singularity (cross-post variants)

For r/OpenAI:
**Title:** Cost calculator for GPT-4o, o1, o3 — live pricing + agentic overhead

For r/ClaudeAI:
**Title:** Anthropic model cost calculator — Claude Opus, Sonnet, Haiku with side-by-side

For r/singularity:
**Title:** AI cost is collapsing — built a tracker that follows OpenRouter's 349 models in real-time

(Keep cross-posts to 2-3 subreddits max, link to each other in comments
to avoid spam flags.)

---

## Posting notes
- Post between 7-9am US Eastern for peak engagement
- Reply to EVERY comment within 2 hours
- Don't delete if it gets downvotes — edit to address criticism
- Be ready for "you should add model X" type feature requests — keep a list
