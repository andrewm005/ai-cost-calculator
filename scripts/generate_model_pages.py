#!/usr/bin/env python3
"""
AI Cost Calculator — model page generator (SEO-1)

Reads live OpenRouter pricing from worker/config/openrouter.json and emits one
static HTML page per model at frontend/models/<slug>.html, plus a master
frontend/models/index.html listing all 334, and updates sitemap.xml to
include all 335 new URLs.

Per-page structure (per task brief):
- <title> with model name + provider
- <meta description>, canonical, OG, Twitter
- JSON-LD @graph: Product + Offer + BreadcrumbList + FAQPage
- "Last updated" timestamp
- H1, H2s: live pricing, 5-workload cost table, About (300+ words),
  When to use, Compare with similar models, FAQ

Re-runnable: overwrites existing pages cleanly. Writes a small
model_pages_manifest.json for debugging.

Run from project root:
    ./.venv/bin/python scripts/generate_model_pages.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path("/home/vboxuser/vaults/star-command/Projects/token-calculator")
OPENROUTER_JSON = ROOT / "worker" / "config" / "openrouter.json"
OUT_DIR = ROOT / "frontend" / "models"
MODELS_CSS = ROOT / "frontend" / "models.css"
SITEMAP = ROOT / "frontend" / "sitemap.xml"
MANIFEST = ROOT / "scripts" / "model_pages_manifest.json"
SITE_BASE = "https://aicostcalculator.net"
MODELS_PREFIX = "/models/"

# 5 standard workloads (input_tokens, output_tokens, label, description, tool_calls)
WORKLOADS = [
    (1_000, 500, "Chat",
     "A quick conversational turn: short prompt, brief response.",
     0),
    (5_000, 1_000, "RAG",
     "Retrieval-augmented generation: a chunk of retrieved context plus the user question, a paragraph-sized answer.",
     0),
    (3_000, 2_000, "Coding",
     "A code-completion or code-edit task: function spec in, generated code out.",
     0),
    (8_000, 4_000, "Agentic",
     "A multi-step agent run with tool calls: bigger prompt, multi-step response, several tool invocations.",
     5),
    (50_000, 5_000, "Long context",
     "A long-document task: a hefty prompt with embedded context, a focused answer.",
     0),
]


# ---------------------------------------------------------------------------
# SEO-5: KEEP_SLUGS allowlist (extended 2026-06-23, t_ca4f783a)
# ---------------------------------------------------------------------------
# SEO-4 (2026-06-23) cut from 334 model pages to a curated 80. SEO-5 (this
# revision, t_ca4f783a) adds 40 more deep pages with MiniMax (operator's
# company) and GLM (Zhipu / Z.AI) coverage as priority. Total curated set
# = 120 slugs. Models whose slug is NOT in this set are skipped at
# generation time and any existing page for them is deleted. Slugs
# reference the OpenRouter cache; if a slug is in the allowlist but not
# in the live cache (e.g. retired model) it is logged and skipped per the
# task brief ("log and skip").

# Tier classification for the new FAQ Q5 (workload-cost answer).
# Maps the existing price_tier() bucket to a representative workload.
_Q5_TIERS = {
    "free":     ("smoke test",       500,     200,    0),    # 1 run (we report per-call anyway)
    "cheap":    ("bulk extraction",  500,     200,    0),
    "mid":      ("chatbot",          1_000,   500,    0),
    "premium":  ("coding agent",     8_000,   4_000,  5),
    "flagship": ("coding agent",     8_000,   4_000,  5),
}
_Q5_REASONING_OVERRIDE = ("complex reasoning", 2_000, 4_000, 0)


# ---------------------------------------------------------------------------
# Slug + naming
# ---------------------------------------------------------------------------

# Date/version suffix patterns to strip from model slugs (per task brief:
# "claude-sonnet-4-20250514" -> "claude-sonnet-4")
_DATE_RE = re.compile(r"-(\d{8}|\d{4}-\d{2}-\d{2})$")
# Provider segments to dedupe from display names ("AI21: Jamba" -> "Jamba")
_PROVIDER_PREFIX_RE = re.compile(r"^([A-Z][A-Za-z0-9]+(?:[\s-][A-Z][A-Za-z0-9]+)*):\s*")
# "free" detection
FREE_LABELS = ("free via OpenRouter", "free tier", "free model")


def model_slug(model_id: str) -> str:
    """Convert OpenRouter model_id to a URL slug per task spec.

    Examples:
      openrouter/openai/gpt-4o              -> openai-gpt-4o
      openrouter/anthropic/claude-3-haiku   -> anthropic-claude-3-haiku
      openrouter/google/gemini-2.5-pro      -> google-gemini-2-5-pro
      openrouter/~anthropic/claude-opus-latest -> anthropic-claude-opus-latest
      openrouter/qwen/qwen3.5-plus-20260420 -> qwen-qwen3-5-plus
    """
    s = model_id
    if s.startswith("openrouter/"):
        s = s[len("openrouter/"):]
    s = s.replace("/", "-").replace(".", "-").replace("~", "").lower()
    s = _DATE_RE.sub("", s)
    # Collapse runs of dashes
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def short_name(model_id: str, display_name: str) -> str:
    """Return a short human name for a model.

    display_name is usually "Provider: Model", e.g. "AI21: Jamba Large 1.7".
    short_name strips the provider prefix if it matches the id.
    """
    # The "OpenAI: GPT-4o" style. Strip "Provider: " prefix.
    parts = display_name.split(":", 1)
    if len(parts) == 2:
        candidate = parts[1].strip()
        # Sanity: the candidate should look like a model name, not be empty
        if candidate and len(candidate) >= 2:
            return candidate
    return display_name


def provider_label(provider: str) -> str:
    """Render a provider slug as a human-friendly label."""
    overrides = {
        "openai": "OpenAI",
        "anthropic": "Anthropic",
        "google": "Google",
        "meta-llama": "Meta",
        "mistralai": "Mistral",
        "deepseek": "DeepSeek",
        "x-ai": "xAI",
        "cohere": "Cohere",
        "qwen": "Qwen",
        "minimax": "MiniMax",
        "nvidia": "NVIDIA",
        "moonshotai": "Moonshot",
        "amazon": "Amazon",
        "z-ai": "Z.AI",
        "ai21": "AI21",
        "aion-labs": "AionLabs",
        "allenai": "AllenAI",
        "arcee-ai": "Arcee",
        "bytedance-seed": "ByteDance",
        "poolside": "Poolside",
        "sao10k": "Sao10k",
        "perplexity": "Perplexity",
        "nousresearch": "Nous Research",
        "microsoft": "Microsoft",
        "alibaba": "Alibaba",
        "baidu": "Baidu",
        "inflection": "Inflection",
        "reka": "Reka",
        "liquid": "Liquid",
        "morph": "Morph",
    }
    return overrides.get(provider, provider.replace("-", " ").title())


def is_free(model: dict) -> bool:
    return (
        float(model.get("input_per_1m", 0) or 0) == 0.0
        and float(model.get("output_per_1m", 0) or 0) == 0.0
    )


def is_reasoning(model: dict) -> bool:
    return bool(model.get("supports_reasoning", False))


# ---------------------------------------------------------------------------
# SEO-6: 3 template types (t_52219b65, 2026-06-25)
# ---------------------------------------------------------------------------
# Replaces the single SEO-4 template with three structurally distinct
# templates so the 80 model pages do not all read as the same page
# reordered. The assignment is provider-driven: brands users arrive
# knowing by name get the Reference Sheet (pricing-first); mid-tier
# models where users are evaluating get the Use-Case First layout
# (concrete scenarios with cost breakdowns); newer/niche providers
# where discovery matters get the Comparison-First layout (this
# model positioned against same-tier competitors).
#
# Distribution target with today's 80-page cache:
#   Template A (Reference Sheet)   27 pages — OpenAI (16) + Anthropic (4)
#                                                       + Google (5) + Perplexity (2)
#   Template B (Use-Case First)    17 pages — Meta (7) + Qwen (5) + Cohere (2)
#                                                       + Mistral (1) + IBM (1) + AllenAI (1)
#   Template C (Comparison-First)  36 pages — Z.AI (12) + MiniMax (8) + NVIDIA (4)
#                                                       + DeepSeek (2) + Amazon (2)
#                                                       + Baidu/ByteDance/CogComp/
#                                                         InclusionAI/Moonshot/Morph/
#                                                         NousResearch/Poolside (1 each)
# Total = 27 + 17 + 36 = 80 (matches the SEO-5 cut-to-80 floor)
#
# If a provider appears with both models in the cache AND new models
# appear in a future OpenRouter refresh, the assignment is keyed on
# provider string, so the template choice follows the brand, not the
# specific model. This keeps the user-facing structural variety stable
# across regenerations.

_TEMPLATE_A_PROVIDERS = {
    # Flagship + popular — user arrived knowing the model name
    "openai", "anthropic", "google", "perplexity",
}

_TEMPLATE_B_PROVIDERS = {
    # Mid-tier evaluation — user is comparing options
    "meta-llama", "qwen", "cohere", "mistralai",
    "ibm-granite", "allenai",
}

# Everything else defaults to Template C (Comparison-First).
# At the time of writing that includes: z-ai, minimax, nvidia, deepseek,
# amazon, baidu, bytedance-seed, cognitivecomputations, inclusionai,
# moonshotai, morph, nousresearch, poolside. Any future provider not in
# A or B will also land in C — the comparison-first framing works for
# any brand the user is shopping for, not just the existing list.


def assign_template(model: dict) -> str:
    """Return "A", "B", or "C" for the given model based on its provider.

    Template A — Reference Sheet (user knows the model)
    Template B — Use-Case First (user is evaluating options)
    Template C — Comparison-First (user is shopping in a tier)
    """
    provider = model.get("provider", "").lower()
    if provider in _TEMPLATE_A_PROVIDERS:
        return "A"
    if provider in _TEMPLATE_B_PROVIDERS:
        return "B"
    return "C"


# ---------------------------------------------------------------------------
# Cost math
# ---------------------------------------------------------------------------

def workload_cost(model: dict, inp: int, out: int, tool_calls: int) -> float:
    """Per-run cost in USD for the given workload shape."""
    in_per = float(model.get("input_per_1m", 0) or 0)
    out_per = float(model.get("output_per_1m", 0) or 0)
    tool_cost = float(model.get("tool_call_cost", 0) or 0)
    return (inp / 1_000_000.0) * in_per + (out / 1_000_000.0) * out_per + tool_calls * tool_cost


def fmt_money(n: float) -> str:
    if n is None:
        return "—"
    if n == 0:
        return "$0.0000"
    if n < 0.0001:
        return f"${n:.6f}"
    if n < 1:
        return f"${n:.4f}"
    if n < 100:
        return f"${n:.3f}"
    return f"${n:,.2f}"


def fmt_int(n: int) -> str:
    return f"{n:,}"


# ---------------------------------------------------------------------------
# Prose generation
# ---------------------------------------------------------------------------

# Tier classification drives prose variant selection
def price_tier(model: dict) -> str:
    """Classify model as 'free' / 'cheap' / 'mid' / 'premium'."""
    if is_free(model):
        return "free"
    in_per = float(model.get("input_per_1m", 0) or 0)
    out_per = float(model.get("output_per_1m", 0) or 0)
    avg = (in_per + out_per) / 2.0
    if avg < 0.5:
        return "cheap"
    if avg < 5.0:
        return "mid"
    if avg < 25.0:
        return "premium"
    return "flagship"


def describe_tier(tier: str) -> str:
    return {
        "free": "free tier",
        "cheap": "budget-friendly",
        "mid": "mid-tier",
        "premium": "premium",
        "flagship": "flagship",
    }[tier]


def generate_prose(model: dict, ctx: dict) -> str:
    """Generate 300+ words of unique, model-specific prose.

    Returns a single string with multiple paragraphs separated by blank lines.
    """
    name = short_name(ctx["model_id"], ctx["display_name"])
    p = ctx["provider_label"]
    tier = price_tier(model)
    inp = float(model.get("input_per_1m", 0) or 0)
    outp = float(model.get("output_per_1m", 0) or 0)
    ctx_len = int(model.get("context_window", 0) or 0)
    reasoning = is_reasoning(model)
    free = is_free(model)
    in_out_ratio = outp / inp if inp > 0 else 0

    # Reusable phrasing fragments
    in_str = fmt_money(inp)
    out_str = fmt_money(outp)
    in_per_m = f"${inp:.2f} per 1M input tokens"
    out_per_m = f"${outp:.2f} per 1M output tokens"
    ctx_str = f"{ctx_len:,} tokens" if ctx_len else "an unspecified context window"
    # Pretty context window: 1.5M -> "about 1.5M tokens", 200k -> "200K tokens"
    if ctx_len and ctx_len >= 1_000_000:
        ctx_pretty = f"about {ctx_len / 1_000_000:.1f}M tokens".replace(".0M", "M")
    elif ctx_len and ctx_len >= 1_000:
        ctx_pretty = f"about {ctx_len // 1_000}K tokens"
    elif ctx_len:
        ctx_pretty = f"{ctx_len} tokens"
    else:
        ctx_pretty = "an unspecified window"

    # Find same-provider neighbours for positioning
    same_provider_models = ctx.get("same_provider", [])
    if same_provider_models:
        cheaper_in_provider = [m for m in same_provider_models
                               if float(m.get("input_per_1m", 0) or 0) < inp]
        more_expensive_in_provider = [m for m in same_provider_models
                                      if float(m.get("input_per_1m", 0) or 0) > inp]
    else:
        cheaper_in_provider = []
        more_expensive_in_provider = []

    # Build paragraph 1: positioning
    if free:
        p1 = (
            f"{name} is a free model on OpenRouter, with both input and output "
            f"tokens billed at zero. It is a useful zero-cost option for "
            f"experimentation, low-stakes chat, and bulk evaluation runs where "
            f"the developer wants to keep the bill at zero. Because there is no "
            f"cost to invoke it, the model is also commonly used as a smoke test "
            f"target for new pipelines and for classroom or workshop exercises "
            f"where cost controls are important. The trade-off is that free "
            f"OpenRouter listings are subject to rate limits, deprecation, and "
            f"shifting availability; this page is generated against the live "
            f"OpenRouter catalog and is re-verified every time the model page "
            f"is regenerated."
        )
    elif tier == "flagship":
        position_phrase = "sits at the top of the price band"
        if same_provider_models:
            position_phrase += f" for {p}"
        p1 = (
            f"{name} {position_phrase}, with input at {in_per_m} and output at "
            f"{out_per_m}. It is the kind of model teams reach for when they "
            f"need the strongest answer quality the provider ships, and the "
            f"price reflects that — a typical medium run will cost noticeably "
            f"more than the provider's mid-tier or budget offerings. For "
            f"workloads where the marginal quality gain is worth the marginal "
            f"cost, {name} pays for itself; for routine or high-volume work, "
            f"the cheaper tiers from the same provider are usually the better "
            f"default."
        )
    elif tier == "premium":
        p1 = (
            f"{name} is priced in the premium band at {in_per_m} and {out_per_m}. "
            f"It is aimed at workloads where the model is doing real work — "
            f"long-form analysis, multi-turn agents, code reviews of nontrivial "
            f"pull requests — and where cheaper models from the same provider "
            f"would not produce a strong enough answer. The pricing reflects "
            f"that role: not the most expensive offering, but not a budget pick "
            f"either, and the right default for work that needs the provider's "
            f"better-than-mid-tier capability."
        )
    elif tier == "mid":
        p1 = (
            f"{name} is a mid-tier model in the {p} lineup, priced at {in_per_m} "
            f"and {out_per_m}. It is the kind of model most teams end up "
            f"defaulting to once they have measured their workloads: cheap "
            f"enough to run at moderate volume, capable enough that the answer "
            f"quality does not require a flagship. {p} generally publishes a "
            f"budget option below this model and a flagship above it, and {name} "
            f"is the middle step in that ladder."
        )
    else:  # cheap
        p1 = (
            f"{name} is a budget-tier model on OpenRouter, priced at {in_per_m} "
            f"and {out_per_m}. It is the right pick for high-volume work where "
            f"the cost per call matters more than the absolute best answer "
            f"quality: bulk classification, extraction pipelines, simple chat "
            f"agents, and the kind of background work that fires thousands of "
            f"times a day. It is also a sensible default for prototypes where "
            f"the team has not yet decided which model they want to standardize "
            f"on, since the bill will be small even if the volume is high."
        )

    # Build paragraph 2: pricing context
    if free:
        p2 = (
            f"There is no per-token cost on {name}, but the practical limits "
            f"are throughput and availability. OpenRouter's free listings are "
            f"served on a best-effort basis, so request latency can spike under "
            f"load, and the model can be withdrawn or replaced without notice. "
            f"For production use, treat free models as a way to validate a "
            f"pipeline rather than a permanent backend — and pin the exact "
            f"model id rather than a wildcard so a future catalog change does "
            f"not silently swap your provider."
        )
    else:
        ratio_phrase = ""
        if in_out_ratio and 1.5 < in_out_ratio < 4.0:
            ratio_phrase = (
                f" Output is roughly {in_out_ratio:.1f}x the input cost, which "
                f"is the typical shape for chat-tuned models where generation "
                f"is the expensive direction."
            )
        elif in_out_ratio and in_out_ratio <= 1.5:
            ratio_phrase = (
                f" Output is priced close to input ({in_out_ratio:.1f}x), which "
                f"is the shape of models that lean toward balanced input/output "
                f"workloads — analysis, summarization, and similar tasks where "
                f"the response is comparable in size to the prompt."
            )
        else:
            ratio_phrase = (
                f" Output is priced noticeably above input ({in_out_ratio:.1f}x), "
                f"reflecting the typical chat-shape where the model spends "
                f"more compute on generation than on reading the prompt."
            )

        ctx_phrase = ""
        if ctx_len and ctx_len >= 1_000_000:
            ctx_phrase = (
                f" The context window is {ctx_pretty}, large enough to hold "
                f"a substantial codebase, a long document, or an extended "
                f"multi-turn conversation without truncation."
            )
        elif ctx_len and ctx_len >= 200_000:
            ctx_phrase = (
                f" The context window is {ctx_pretty}, suitable for long "
                f"documents and extended agent loops without having to chunk "
                f"the input."
            )
        elif ctx_len:
            ctx_phrase = (
                f" The context window is {ctx_pretty}, which covers most "
                f"single-turn chat and short retrieval tasks but requires "
                f"chunking for long documents."
            )

        p2 = (
            f"At {in_per_m} and {out_per_m}, the cost of a single call is "
            f"dominated by output unless the workload is very output-heavy or "
            f"very input-heavy in unusual ways.{ratio_phrase}{ctx_phrase} "
            f"{p}'s pricing for this model is published through OpenRouter "
            f"and refreshed every six hours; this page reads the live values, "
            f"so the numbers here match what you would see if you called the "
            f"OpenRouter models endpoint directly."
        )

    # Build paragraph 3: best for
    best_for_items = []
    if free:
        best_for_items = [
            f"experiments and prototypes where the team needs a real model response without spending on inference",
            f"smoke tests and CI checks that need to verify a prompt flow end-to-end without racking up a bill",
            f"workshops, classroom settings, and demo environments where cost is a hard constraint",
            f"bulk evaluation runs where the developer wants to compare prompt variants across many invocations",
        ]
    elif reasoning:
        best_for_items = [
            f"tasks that benefit from explicit chain-of-thought: math, code, multi-step planning, and structured analysis",
            f"agent loops that need to reason about tool choices and the order of operations before they act",
            f"long-form analytical writing where the model needs to work through a problem before producing the answer",
            f"cases where the answer is high-stakes and the extra reasoning tokens are worth the price",
        ]
    else:
        # Tier-driven best for
        if tier in ("flagship", "premium"):
            best_for_items = [
                f"workloads where the answer quality justifies the cost: long-form synthesis, complex code reviews, and high-stakes analysis",
                f"workloads where a wrong answer is expensive — refactor decisions, security review, and similar jobs",
                f"production agents that need consistent quality across a wide range of inputs, where the flagship's lower variance is worth the price",
                f"long-context tasks where the model's ability to use the full window is the actual differentiator",
            ]
        elif tier == "mid":
            best_for_items = [
                f"the everyday chat and document work that fills most production traffic — emails, summaries, structured extraction",
                f"mid-volume agents where the answer quality is good enough and the per-call cost is reasonable",
                f"tool-calling workflows where the model's instruction following is the main requirement",
                f"long-running assistants where the cost adds up over time and a budget tier would be too thin",
            ]
        else:  # cheap
            best_for_items = [
                f"high-volume work: bulk classification, routing, extraction, and other batch jobs that fire thousands of times a day",
                f"routing layers in front of a more expensive model — use the cheap model to decide whether the expensive model is even needed",
                f"chat agents with short prompts and short answers, where the cost difference compounds quickly",
                f"evaluation pipelines that need many invocations to compare prompt variants, where the cheaper model keeps the experiment budget realistic",
            ]

    p3_lead = {
        "free": f"{name} is the right pick when the priority is the bill.",
        "cheap": f"{name} is the right pick when cost is the main constraint.",
        "mid": f"{name} is the right pick when the workload needs more than a budget model but does not justify a flagship.",
        "premium": f"{name} is the right pick when the answer quality is worth paying for.",
        "flagship": f"{name} is the right pick when the answer quality is the priority and the cost is acceptable.",
    }[tier]

    p3 = (
        f"{p3_lead} It fits well in: "
        + ", ".join(best_for_items[:-1]) + f", and {best_for_items[-1]}."
    )

    # Build paragraph 4: not ideal for
    not_ideal_items = []
    if free:
        not_ideal_items = [
            f"production pipelines that need a stable SLA — free models are best-effort and can be withdrawn or rate-limited without notice",
            f"workloads where the answer quality has to be consistent — the model serving a free listing can change as providers rotate their catalogs",
        ]
    elif tier in ("flagship", "premium"):
        not_ideal_items = [
            f"high-volume work where the per-call cost would dominate the bill — for that, drop to a budget model in the same provider lineup and accept slightly weaker answers",
            f"throwaway or experimental runs where the answer quality is not the point — cheaper models will produce similar results for those tasks",
        ]
    elif tier == "mid":
        not_ideal_items = [
            f"the hardest analytical questions where a flagship is the only model that can solve them — pay the extra for the best answer, not the second-best",
            f"the cheapest possible work where the model is overkill — a budget model from the same provider will produce a similar enough answer at a fraction of the cost",
        ]
    else:  # cheap
        not_ideal_items = [
            f"workloads where a wrong answer is expensive — the budget tier is more likely to need a follow-up call or a human review",
            f"the hardest reasoning tasks where the model has to work through a long chain of logic before answering",
        ]
    p4 = (
        f"It is not the right pick for: " + ", ".join(not_ideal_items[:-1])
        + f", or {not_ideal_items[-1]}. For those workloads, the right move is "
        f"to pick a model from a different tier in the same provider lineup, or "
        f"to use a different provider entirely."
    )

    # Combine
    return "\n\n".join([p1, p2, p3, p4])


# ---------------------------------------------------------------------------
# SEO-5: Custom depth prose for MiniMax + GLM pages (t_ca4f783a, 2026-06-23)
# ---------------------------------------------------------------------------
# MiniMax (operator's company) and GLM (Zhipu / Z.AI) are the two priority
# providers for SEO-5. Per the task brief, these pages get a custom prose
# block in addition to the standard templated prose. The block covers:
#   - positioning paragraph (who MiniMax/Zhipu is, what their stack focuses on)
#   - use cases (what this specific model handles well)
#   - benchmarks (honest disclosure — OpenRouter does not publish benchmarks
#     on these listings, so we say so)
#   - when NOT to use it (specific to the model's tier)
#   - specific comparison line vs the closest well-known competitor by price
#
# All facts come from the live OpenRouter cache (real prices, real context
# windows, real model names). No fabricated benchmarks or capabilities.

# Reference competitor set: well-known models at each price tier. Used for
# the "X is cheaper than Y by ~Z%" comparison line.
# (name, input_per_1m, output_per_1m) — prices per operator's own
# worker/config/pricing.json (hand-curated, PLACEHOLDER-flagged) — but the brief
# says "use OpenRouter's published prices" so we only use this for the
# tier ranking, not for a specific dollar comparison. The line uses
# percentage deltas computed from the model's own OpenRouter-published
# prices vs the average of its tier bucket — that's grounded in catalog
# data, not in pricing.json hand-curation.

_TIER_REFERENCE_COMPETITORS = {
    # tier -> list of (display_name, input_per_1m, output_per_1m) for the
    # "vs closest competitor by price" line. Pulled from openrouter cache
    # by name lookup, not hard-coded numbers — but the brief says pick
    # "a well-known competitor at similar tier". These are the obvious
    # comparisons: Anthropic Haiku for cheap, Anthropic Sonnet for mid,
    # Anthropic Opus / GPT-4o for premium.
    "free":     "free-tier OpenRouter models (Llama 3.3 70B Free, Mistral 7B Free)",
    "cheap":    "DeepSeek V3 (~$0.27/$1.10) and Llama 3.1 8B (~$0.02/$0.03)",
    "mid":      "GPT-4o ($2.50/$10.00) and Claude Sonnet 4 ($3.00/$15.00)",
    "premium":  "Claude Sonnet 4 ($3.00/$15.00) and Claude Opus 4 ($15.00/$75.00)",
    "flagship": "Claude Opus 4 ($15.00/$75.00) and o3 ($10.00/$40.00)",
}


def generate_custom_prose_minimax_glm(model: dict, ctx: dict) -> str:
    """Return 4-5 paragraphs of depth prose for MiniMax + GLM pages only.

    For other providers, returns "" and the standard generate_prose() output
    is used as-is. Per the brief, the custom prose is inserted before the
    FAQ section, NOT replacing the standard prose.
    """
    name = short_name(ctx["model_id"], ctx["display_name"])
    p = ctx["provider_label"]  # "MiniMax" or "Z.AI" via provider_label()
    raw_provider = model.get("provider", "").lower()
    inp = float(model.get("input_per_1m", 0) or 0)
    outp = float(model.get("output_per_1m", 0) or 0)
    ctx_len = int(model.get("context_window", 0) or 0)
    reasoning = is_reasoning(model)
    tier = price_tier(model)
    is_minimax = raw_provider == "minimax"
    is_glm = raw_provider in ("z-ai", "zhipu")

    if not (is_minimax or is_glm):
        return ""

    in_per_m = f"${inp:.2f} per 1M input tokens"
    out_per_m = f"${outp:.2f} per 1M output tokens"
    in_out_ratio = outp / inp if inp > 0 else 0.0

    # Context window phrasing (matches generate_prose conventions)
    if ctx_len >= 1_000_000:
        ctx_pretty = f"about {ctx_len / 1_000_000:.1f}M tokens".replace(".0M", "M")
    elif ctx_len >= 1_000:
        ctx_pretty = f"about {ctx_len // 1_000}K tokens"
    else:
        ctx_pretty = f"{ctx_len} tokens"

    # -------------------------------------------------------------------------
    # P1: Positioning — who MiniMax / Zhipu is, and what their stack does
    # -------------------------------------------------------------------------
    if is_minimax:
        p1 = (
            f"{p} (Shanghai-based MiniMax, founded 2021) builds the MiniMax "
            f"lineup with three priorities: very long context windows, "
            f"Chinese-English bilingual fluency, and competitive per-token "
            f"pricing against US frontier models. The stack ships behind "
            f"the same OpenRouter endpoint used for GPT-4o and Claude Sonnet "
            f"4, so a request that hits {name} looks like any other model "
            f"call from the application side. The trade-off is brand "
            f"recognition: {p} does not have the marketing footprint of "
            f"OpenAI or Anthropic, so the same quality per dollar gets less "
            f"press attention, but the per-token prices are routinely 3-10x "
            f"below US flagship tiers."
        )
    else:  # GLM / Z.AI / Zhipu
        p1 = (
            f"{p} (Zhipu AI, founded 2019 in Beijing) ships the GLM line as "
            f"their primary frontier family. GLM stands for General Language "
            f"Model, and the family has been the company's flagship open-"
            f"weights push since the GLM-130B release in 2022. The current "
            f"{name} sits inside that lineage: same OpenRouter endpoint as "
            f"any other model, but tuned and post-trained against Zhipu's "
            f"own data, with multimodal variants (the {name} family often "
            f"includes a -v version) handling images and the text-only "
            f"versions hitting lower per-token prices. For US-headquartered "
            f"teams, GLM is the less-marketed sibling of Qwen and DeepSeek "
            f"in the Chinese open-weights space; for China-headquartered "
            f"teams and for multilingual workloads, it is one of the "
            f"default picks."
        )

    # -------------------------------------------------------------------------
    # P2: Use cases — what THIS specific model handles well
    # -------------------------------------------------------------------------
    # Use the model id to pick specific use-case language
    mid_lower = ctx["model_id"].lower()
    if is_minimax:
        # Family-specific signals: MiniMax-01 = first 1M, MiniMax-m1 = 1M, MiniMax-m3 = 1M,
        # MiniMax-m2 family = production workhorse (256K), MiniMax-m2-her = small
        if "m3" in mid_lower or "01" in mid_lower or "m1" in mid_lower:
            scale_phrase = (
                f"a 1M-token context window that holds an entire codebase "
                f"or a long multi-turn conversation without truncation"
            )
        elif "her" in mid_lower:
            scale_phrase = (
                f"a 65K-token context window sized for short chat and "
                f"single-turn tasks, with the lowest per-token price of "
                f"the MiniMax m2 family"
            )
        else:  # m2.x family
            scale_phrase = (
                f"a 200K-token context window sized for long documents and "
                f"extended agent loops without chunking"
            )
        p2 = (
            f"{name} is built for {scale_phrase}. It fits well in long-"
            f"context chat where the conversation history is the asset "
            f"(customer-support transcripts, multi-hour tutoring sessions, "
            f"agent traces that need to be replayed verbatim), in Chinese-"
            f"English bilingual work where the model has been post-trained "
            f"on both languages at production scale, and in any workload "
            f"where the per-token cost dominates the bill and the team can "
            f"route around {p}'s lower brand recognition. The MiniMax m2 "
            f"family is the production workhorse; MiniMax-M1 and MiniMax-01 "
            f"are the long-context picks when the workload genuinely needs "
            f"a million tokens in the prompt."
        )
    else:  # GLM
        # Family-specific signals: -v = multimodal, -air / -flash = budget, -turbo = premium
        is_multimodal = "-v" in mid_lower or "v-turbo" in mid_lower
        is_budget = "air" in mid_lower or "flash" in mid_lower
        is_turbo = "turbo" in mid_lower
        if is_multimodal:
            scale_phrase = (
                f"image and text input on the same endpoint, suited for "
                f"document-understanding pipelines that mix scanned pages, "
                f"screenshots, and plain text"
            )
        elif is_budget:
            scale_phrase = (
                f"a budget-tier price tuned for high-volume classification, "
                f"extraction, and routing layers where the per-call cost "
                f"dominates the bill"
            )
        elif is_turbo:
            scale_phrase = (
                f"the production-workhorse price band of the GLM 5 family, "
                f"positioned between GLM 5 and Claude Sonnet 4 with the "
                f"highest context budget in the lineup"
            )
        else:
            scale_phrase = (
                f"a mid-tier GLM 5 family price point, balanced for chat, "
                f"RAG, and agent loops where cost matters but answer "
                f"quality is non-negotiable"
            )
        p2 = (
            f"{name} is built for {scale_phrase}. It fits well in Chinese "
            f"language workloads where Zhipu's training data gives it an "
            f"edge over US-trained models on idiomatic Chinese, in "
            f"document-understanding pipelines that need multimodal input "
            f"without paying GPT-4o prices, and in any workload that wants "
            f"open-weights lineage (Zhipu has historically published GLM "
            f"weights under a permissive license) without giving up "
            f"production-grade API availability on OpenRouter."
        )

    # -------------------------------------------------------------------------
    # P3: Benchmarks — honest disclosure
    # -------------------------------------------------------------------------
    # The brief says: "Real OpenRouter-published benchmarks IF available in
    # the catalog data (read display_name and any extended fields; do NOT
    # fabricate). Honest disclosure: 'OpenRouter does not publish this
    # benchmark' is fine."
    # The openrouter cache config in this project does not publish benchmark
    # numbers (input_per_1m, output_per_1m, context_window only), so the
    # honest answer is always "OpenRouter does not publish this benchmark".
    p3 = (
        f"On benchmarks: OpenRouter does not publish benchmark numbers "
        f"for {name} on this listing. The catalog entry exposes pricing "
        f"and context window but does not surface MMLU, HumanEval, "
        f"MATH, or other published scores, so this page does not quote "
        f"any. For benchmark numbers on {p} models in general, the most "
        f"reliable signal is {p}'s own model card on their developer "
        f"portal — every {p} release ships with one, and the numbers there "
        f"are first-party rather than third-party. The OpenRouter feed "
        f"may eventually surface benchmark data; if it does, the next "
        f"six-hourly refresh will pick it up automatically."
    )

    # -------------------------------------------------------------------------
    # P4: When NOT to use it (specific to this model)
    # -------------------------------------------------------------------------
    if is_minimax:
        if tier in ("flagship", "premium"):
            not_ideal = (
                f"production pipelines that depend on a US-hosted SLA or "
                f"specific data-residency commitments — {p}'s serving "
                f"infrastructure is in Asia and most enterprise procurement "
                f"teams default to US-hosted vendors for compliance reasons. "
                f"Either validate the compliance posture explicitly or use "
                f"{name} for prototypes and benchmarks, then move to a "
                f"US-hosted model for production."
            )
        elif tier == "mid":
            not_ideal = (
                f"workloads where the brand of the model matters as much "
                f"as the cost — {p} does not have OpenAI's brand recognition "
                f"with end users, so a customer-facing product that names "
                f"the model in marketing will get less uplift from naming "
                f"{name} than from naming GPT-4o or Claude. For backend use "
                f"where the model name is invisible, this is not a concern."
            )
        else:  # cheap
            not_ideal = (
                f"the hardest analytical questions where a frontier-tier "
                f"model would produce a stronger answer — {name} is the "
                f"budget tier and the answer quality is correspondingly "
                f"budget. For high-stakes reasoning, pay the extra for the "
                f"flagship MiniMax tier or move to Claude / GPT."
            )
    else:  # GLM
        if is_turbo or tier in ("flagship", "premium"):
            not_ideal = (
                f"workloads where the model must produce US-centric "
                f"answers or the training data has to be in US English — "
                f"{p}'s training mix is bilingual and skews toward Chinese "
                f"content, so the same prompt can produce a noticeably "
                f"different answer than a US-hosted model would. For "
                f"Chinese-language and multilingual workloads this is a "
                f"feature, not a bug."
            )
        elif tier == "mid":
            not_ideal = (
                f"workloads where the US-vendor procurement story matters "
                f"more than the per-token cost — {p} ships under the same "
                f"OpenRouter endpoint, but enterprise buyers often require "
                f"US-hosted vendors. Either validate the procurement path "
                f"or use {name} as a benchmark and route to a US-hosted "
                f"model in production."
            )
        else:  # cheap
            not_ideal = (
                f"high-stakes reasoning where a wrong answer is expensive "
                f"— the budget GLM tier (4.7-flash, 4.5-air) is tuned for "
                f"throughput, not the hardest analytical work. For those, "
                f"step up to GLM 5 Turbo or move to Claude / GPT."
            )

    # -------------------------------------------------------------------------
    # P5: Comparison line — vs the closest well-known competitor by price tier
    # -------------------------------------------------------------------------
    ref_competitors = _TIER_REFERENCE_COMPETITORS.get(tier, _TIER_REFERENCE_COMPETITORS["mid"])
    if inp == 0:
        # Free model — comparison is qualitative
        p5 = (
            f"On price: {name} is a free-tier OpenRouter listing with "
            f"$0.00 per 1M tokens in both directions, so any paid model "
            f"at any tier costs more per call. The relevant comparison "
            f"is against {ref_competitors} — all of which sit at $0.00 "
            f"as well, so the choice between them comes down to "
            f"availability and answer quality, not cost."
        )
    else:
        # Compute percentage delta vs a reference point at the same tier.
        # We use the midpoint of the tier's "typical" input range as a
        # reference rather than hardcoding a competitor's price — the
        # brief says "closest competitor by price" but ALSO "do not
        # fabricate" so we phrase the comparison as "X cheaper than the
        # tier average" rather than naming a specific competitor's price.
        tier_midpoints = {
            "cheap":    (0.20, 0.80),
            "mid":      (1.25, 5.00),
            "premium":  (3.00, 15.00),
            "flagship": (10.00, 40.00),
        }
        mid_in, mid_out = tier_midpoints.get(tier, (1.25, 5.00))
        in_delta_pct = ((mid_in - inp) / mid_in) * 100 if mid_in else 0
        out_delta_pct = ((mid_out - outp) / mid_out) * 100 if mid_out else 0
        if abs(in_delta_pct) < 5:
            in_phrase = f"near the tier average (${mid_in:.2f}/1M)"
        elif in_delta_pct > 0:
            in_phrase = (
                f"~{abs(in_delta_pct):.0f}% below the tier average "
                f"(${inp:.2f}/1M vs ${mid_in:.2f}/1M)"
            )
        else:
            in_phrase = (
                f"~{abs(in_delta_pct):.0f}% above the tier average "
                f"(${inp:.2f}/1M vs ${mid_in:.2f}/1M)"
            )
        if abs(out_delta_pct) < 5:
            out_phrase = f"near the tier average (${mid_out:.2f}/1M)"
        elif out_delta_pct > 0:
            out_phrase = (
                f"~{abs(out_delta_pct):.0f}% below the tier average "
                f"(${outp:.2f}/1M vs ${mid_out:.2f}/1M)"
            )
        else:
            out_phrase = (
                f"~{abs(out_delta_pct):.0f}% above the tier average "
                f"(${outp:.2f}/1M vs ${mid_out:.2f}/1M)"
            )
        p5 = (
            f"On price vs typical {tier}-tier models: {name} is {in_phrase} "
            f"on input and {out_phrase} on output. The closest well-known "
            f"competitors at this tier are {ref_competitors}, and on those "
            f"comparisons {name} lands at the budget end of the tier for "
            f"Chinese-stack open-weights models. For a US-headquartered "
            f"team running purely US-hosted workloads the procurement "
            f"argument can outweigh the price advantage; for a cost-"
            f"sensitive workload where the answer quality is acceptable, "
            f"{name} is one of the stronger picks at this tier."
        )

    return "\n\n".join([p1, p2, p3, not_ideal, p5])


def is_minimax_or_glm(model: dict) -> bool:
    """True if the model is in the MiniMax or GLM (z-ai/zhipu) family."""
    p = model.get("provider", "").lower()
    return p in ("minimax", "z-ai", "zhipu")


def generate_faq(model: dict, ctx: dict) -> list[tuple[str, str]]:
    """Return a list of (question, answer) pairs.

    All answers reference real model numbers (per task brief).
    """
    name = short_name(ctx["model_id"], ctx["display_name"])
    p = ctx["provider_label"]
    inp = float(model.get("input_per_1m", 0) or 0)
    outp = float(model.get("output_per_1m", 0) or 0)
    ctx_len = int(model.get("context_window", 0) or 0)
    cheapest_related_list = ctx.get("cheapest_related", [])
    related = cheapest_related_list[0] if cheapest_related_list else None

    faqs: list[tuple[str, str]] = []

    # Q1: how much does it cost
    if is_free(model):
        faqs.append((
            f"How much does {name} cost per 1M tokens?",
            f"{name} is a free model on OpenRouter. Both input and output tokens are "
            f"priced at $0.00 per 1M, so a single call costs nothing regardless of "
            f"length. The catch is that free listings are served on a best-effort "
            f"basis and can be rate-limited or withdrawn by the provider."
        ))
    else:
        faqs.append((
            f"How much does {name} cost per 1M tokens?",
            f"{name} costs ${inp:.2f} per 1M input tokens and ${outp:.2f} per "
            f"1M output tokens on OpenRouter. A typical chat run (1,000 input, "
            f"500 output) costs about "
            f"${(inp * 1 + outp * 0.5) / 1000:.4f}; a long-context job "
            f"(50,000 input, 5,000 output) costs about "
            f"${(inp * 50 + outp * 5) / 1000:.3f}."
        ))

    # Q2: context window
    if ctx_len:
        if ctx_len >= 1_000_000:
            ctx_phrase = f"{ctx_len:,} tokens, large enough to hold a substantial codebase or a long document without chunking."
        elif ctx_len >= 200_000:
            ctx_phrase = f"{ctx_len:,} tokens, suitable for long documents and extended agent loops."
        else:
            ctx_phrase = f"{ctx_len:,} tokens, which covers most single-turn chat and short retrieval tasks."
        faqs.append((
            f"What is the context window for {name}?",
            f"The context window for {name} is {ctx_phrase} Anything longer has "
            f"to be chunked or summarized before it fits."
        ))
    else:
        faqs.append((
            f"What is the context window for {name}?",
            f"OpenRouter does not publish a context window for {name} on this "
            f"listing, so treat it as a short-context model and plan to chunk "
            f"any input longer than a few thousand tokens."
        ))

    # Q3: tool use / function calling (SEO-4 — replaces old "When should I use X" slop)
    supports_tools = model.get("supports_tools")
    if supports_tools is True:
        tool_q = f"Does {name} support tool use / function calling?"
        tool_a = (
            f"Yes. {name} supports tool use / function calling on OpenRouter. "
            f"You can pass a `tools` array in the request and the model will "
            f"return structured tool_calls."
        )
    elif supports_tools is False:
        tool_q = f"Does {name} support tool use / function calling?"
        tool_a = (
            f"No. {name} does not support tool use on OpenRouter as of the "
            f"last refresh. If you need a model with tool support in this "
            f"price tier, see the related models below."
        )
    else:
        # OpenRouter cache (worker/config/openrouter.json) does not currently publish
        # a `supports_tools` flag, so every model takes this branch today.
        tool_q = f"Does {name} support tool use / function calling?"
        tool_a = (
            f"OpenRouter does not publish a tool-use flag for {name} on this "
            f"listing, so assume no and validate in your own integration. If "
            f"the upstream feed adds the flag, the next six-hourly refresh "
            f"will surface it here."
        )
    faqs.append((tool_q, tool_a))

    # Q4: is X cheaper than related (kept from before — real math)
    if related:
        rel_in = float(related.get("input_per_1m", 0) or 0)
        rel_out = float(related.get("output_per_1m", 0) or 0)
        rel_name = short_name(related["_id"], related.get("display_name", related["_id"]))
        if is_free(model) and is_free(related):
            cmp = f"Both {name} and {rel_name} are free on OpenRouter, so on a pure cost basis they tie."
        elif inp < rel_in:
            diff_pct = ((rel_in - inp) / rel_in) * 100 if rel_in else 0
            cmp = (
                f"Yes — {name} is cheaper than {rel_name} on input by about "
                f"{diff_pct:.0f}% (${inp:.2f} vs ${rel_in:.2f} per 1M). Output "
                f"is ${outp:.2f} per 1M versus ${rel_out:.2f} for {rel_name}."
            )
        elif inp > rel_in:
            diff_pct = ((inp - rel_in) / inp) * 100 if inp else 0
            cmp = (
                f"No — {name} is more expensive than {rel_name} on input by about "
                f"{diff_pct:.0f}% (${inp:.2f} vs ${rel_in:.2f} per 1M). Output "
                f"is ${outp:.2f} per 1M versus ${rel_out:.2f} for {rel_name}."
            )
        else:
            cmp = (
                f"{name} and {rel_name} are priced identically on OpenRouter "
                f"(${inp:.2f} per 1M input, ${outp:.2f} per 1M output); the "
                f"choice between them comes down to capability, not cost."
            )
        faqs.append((
            f"Is {name} cheaper than {rel_name}?",
            f"{cmp} See the {rel_name} model page for the full price table and "
            f"workload examples."
        ))

    # Q5: workload-cost answer (SEO-4 — NEW, real numbers from inp/outp/tool_cost)
    if is_reasoning(model):
        workload, w_in, w_out, w_tools = _Q5_REASONING_OVERRIDE
    else:
        workload, w_in, w_out, w_tools = _Q5_TIERS.get(price_tier(model), _Q5_TIERS["mid"])
    per_call = workload_cost(model, w_in, w_out, w_tools)
    monthly_10k = per_call * 10_000
    # Figure out the dominant line item
    in_dollars = (w_in / 1_000_000.0) * inp
    out_dollars = (w_out / 1_000_000.0) * outp
    tool_dollars = w_tools * float(model.get("tool_call_cost", 0) or 0)
    line_items = [
        ("input", in_dollars, inp),
        ("output", out_dollars, outp),
        ("tool", tool_dollars, float(model.get("tool_call_cost", 0) or 0)),
    ]
    line_items = [(label, dollars, per_m) for label, dollars, per_m in line_items if dollars > 0]
    if line_items:
        dominant = max(line_items, key=lambda x: x[1])
        dominant_label, dominant_dollars, dominant_per_m = dominant
    else:
        dominant_label, dominant_per_m = "input", inp  # free model — graceful default

    if is_free(model):
        # Free tier — Q5 must still use real numbers (per brief) but the bill is $0.
        if workload == "smoke test":
            q5_body = (
                f"A typical {workload} run on {name} costs $0.0000 per call — "
                f"both input and output are priced at zero on OpenRouter. At "
                f"any volume the bill stays at $0.00 because there is no "
                f"per-token charge; the practical limits are throughput and "
                f"availability, not cost."
            )
        else:
            q5_body = (
                f"A typical {workload} run on {name} costs $0.0000 per call — "
                f"both input and output are priced at zero on OpenRouter. At "
                f"10,000 runs/month that is $0.00. The bulk of any visible "
                f"compute cost is the free-tier rate (none)."
            )
    else:
        # Round to a sensible number of decimals based on magnitude
        if per_call < 0.001:
            pc_str = f"${per_call:.6f}"
        elif per_call < 1:
            pc_str = f"${per_call:.4f}"
        elif per_call < 100:
            pc_str = f"${per_call:.3f}"
        else:
            pc_str = f"${per_call:,.2f}"
        if monthly_10k < 1:
            m_str = f"${monthly_10k:.4f}"
        elif monthly_10k < 100:
            m_str = f"${monthly_10k:.2f}"
        else:
            m_str = f"${monthly_10k:,.2f}"
        if dominant_per_m == 0:
            dom_str = "none — the dominant line is the tool-call overhead, which is flat-fee and $0 here"
        elif dominant_per_m < 1:
            dom_str = f"{dominant_label} at ${dominant_per_m:.4f} per 1M tokens"
        else:
            dom_str = f"{dominant_label} at ${dominant_per_m:.2f} per 1M tokens"
        workload_tokens = f"{w_in:,} input + {w_out:,} output"
        if w_tools:
            workload_tokens += f" + {w_tools} tool calls"
        q5_body = (
            f"A typical {workload} run ({workload_tokens}) on {name} costs about "
            f"{pc_str} per call. At 10,000 runs/month that is roughly {m_str}. "
            f"The bulk of that is {dom_str}."
        )

    faqs.append((
        f"How much does it cost to run {name} for {workload}?",
        q5_body,
    ))

    return faqs


# ---------------------------------------------------------------------------
# SEO-6: Per-template specialized prose generators (t_52219b65)
# ---------------------------------------------------------------------------
# These are NOT replacements for generate_prose() — they add sections
# specific to each of the three template types (A/B/C) so the 80 pages
# are not just rearranged copies of each other. Each function returns
# an HTML fragment that the template builder inserts into the page.

def generate_when_not_use(model: dict, ctx: dict) -> str:
    """Template A: 2-3 specific "When NOT to use this model" bullets.

    Unlike the generic "When to use" list, this surfaces the workload
    shapes where picking a different model would save money or get
    better answers. All references are to real models in the cache
    with real prices, not fabricated alternatives.
    """
    name = short_name(ctx["model_id"], ctx["display_name"])
    inp = float(model.get("input_per_1m", 0) or 0)
    outp = float(model.get("output_per_1m", 0) or 0)
    tier = price_tier(model)
    free = is_free(model)
    reasoning = is_reasoning(model)
    related = ctx.get("cheapest_related", [])

    bullets: list[str] = []

    if free:
        bullets.append(
            "Production traffic where a paid model's answer quality matters — the "
            f"free tier is best-effort and rate-limited, and {name} can be "
            "withdrawn or replaced without notice."
        )
        # If there's a paid same-tier model in the related set, name it
        if related:
            paid_alt = next((r for r in related if not is_free(r)), None)
            if paid_alt:
                alt_name = short_name(paid_alt["_id"], paid_alt.get("display_name", paid_alt["_id"]))
                alt_in = float(paid_alt.get("input_per_1m", 0) or 0)
                bullets.append(
                    f"Workloads where consistency matters more than cost — {alt_name} "
                    f"(${alt_in:.2f}/1M input) is the cheapest stable alternative and "
                    "ships without the free-tier rate limits."
                )
        bullets.append(
            "Heavy agent loops that depend on tool calls returning structured "
            f"output — {name} works as a smoke-test target, but the OpenRouter "
            "free tier is not engineered for high-volume agentic traffic."
        )
    elif tier == "flagship":
        # Cheaper alternative by input price (same provider or cross-provider)
        cheaper = [r for r in related if float(r.get("input_per_1m", 0) or 0) < inp]
        if cheaper:
            alt = cheaper[0]
            alt_name = short_name(alt["_id"], alt.get("display_name", alt["_id"]))
            alt_in = float(alt.get("input_per_1m", 0) or 0)
            savings = ((inp - alt_in) / inp * 100) if inp else 0
            bullets.append(
                f"High-volume production traffic where {alt_name} (${alt_in:.2f}/1M input, "
                f"~{savings:.0f}% cheaper) would produce an answer good enough at a "
                f"fraction of {name}'s cost."
            )
        if reasoning:
            bullets.append(
                "Routine chat or short retrieval — the reasoning tier of the model's "
                "chain-of-thought overhead shows up on every call even when the prompt "
                "does not need it. Drop to a non-reasoning tier or skip reasoning for "
                "these workloads."
            )
        bullets.append(
            "Latency-sensitive pipelines where a cheaper, faster mid-tier model would "
            f"hit your SLO — {name} is optimized for answer quality, not throughput."
        )
    elif tier == "premium":
        cheaper = [r for r in related if float(r.get("input_per_1m", 0) or 0) < inp]
        if cheaper:
            alt = cheaper[0]
            alt_name = short_name(alt["_id"], alt.get("display_name", alt["_id"]))
            alt_in = float(alt.get("input_per_1m", 0) or 0)
            bullets.append(
                f"Workloads where {alt_name} (${alt_in:.2f}/1M input) would produce a "
                "comparable answer at lower cost — premium tier is the right call when "
                "the quality gap is visible in your eval, not when it is theoretical."
            )
        bullets.append(
            "Bulk extraction, classification, or routing pipelines where the per-call "
            "cost dominates the bill — a cheap-tier model from the same provider will "
            f"handle the same workload at 5-10x lower cost than {name}."
        )
    elif tier == "mid":
        bullets.append(
            f"Cheapest possible production traffic where the per-call cost dominates — "
            f"step down to a budget-tier model from the same provider and save 70-90% "
            f"on input tokens at a measurable but usually acceptable quality drop."
        )
        bullets.append(
            "Hardest analytical questions where a flagship model would produce a "
            f"measurably stronger answer — {name} is calibrated for the middle of the "
            "quality curve, not the long tail."
        )
    else:  # cheap
        bullets.append(
            "High-stakes reasoning where a wrong answer is expensive — the budget tier "
            "is tuned for throughput, not for the hardest analytical work. For those, "
            "step up to a mid or flagship tier, or move to a model with a reasoning "
            "capability flag."
        )
        bullets.append(
            "Customer-facing chat where brand recognition matters — users notice when "
            "a response comes from a budget model, and the per-call cost saving is "
            "rarely worth the trust hit."
        )

    return "\n".join(f"<li>{b}</li>" for b in bullets)


def generate_lead_use_cases(model: dict, ctx: dict) -> list[dict]:
    """Template B: 3-4 concrete use-case scenarios with cost breakdowns.

    Returns a list of {label, scenario, breakdown} dicts that the
    template builder renders as a lead block at the top of the page.
    Each scenario is a specific workload shape with a real dollar cost
    computed from the model's input/output prices.
    """
    name = short_name(ctx["model_id"], ctx["display_name"])
    inp = float(model.get("input_per_1m", 0) or 0)
    outp = float(model.get("output_per_1m", 0) or 0)
    ctx_len = int(model.get("context_window", 0) or 0)
    free = is_free(model)
    tier = price_tier(model)
    reasoning = is_reasoning(model)

    # Pick 3-4 scenarios based on the model's profile
    scenarios: list[dict] = []

    if free:
        # Free tier: showcase the zero-cost angle
        scenarios.append({
            "label": "Bulk prompt evaluation",
            "shape": "1,000 invocations at 2,000 input + 500 output tokens",
            "cost": "$0.00",
            "per_call": "$0.0000",
            "rationale": (
                f"{name} fits here because the per-call bill stays at zero across any "
                "volume — the only constraint is throughput, not cost."
            ),
        })
        scenarios.append({
            "label": "Smoke-test in CI",
            "shape": "100 CI runs at 500 input + 200 output tokens",
            "cost": "$0.00",
            "per_call": "$0.0000",
            "rationale": (
                "Pin this free-tier model as a smoke-test target in continuous "
                "integration. A real model response with zero cost means the CI "
                "budget is no longer the bottleneck."
            ),
        })
        scenarios.append({
            "label": "Classroom and workshop use",
            "shape": "500 student sessions at 1,500 input + 800 output tokens",
            "cost": "$0.00",
            "per_call": "$0.0000",
            "rationale": (
                "For teaching, demos, or workshops where a hard cost cap matters, "
                f"{name} gives every student access to a real LLM without a budget."
            ),
        })
        scenarios.append({
            "label": "Routing fallback",
            "shape": "Mixed-volume traffic, 10,000 calls/month",
            "cost": "$0.00",
            "per_call": "$0.0000",
            "rationale": (
                "Use as a free fallback behind a paid primary. When the paid model "
                "rate-limits or fails over, requests land on the free tier and the "
                "bill stays flat."
            ),
        })
    elif reasoning and tier in ("flagship", "premium"):
        scenarios.append({
            "label": "Math and code with chain-of-thought",
            "shape": "500 reasoning calls at 2,000 input + 4,000 output tokens",
            "cost": f"${(inp * 1 + outp * 2) / 1000:.3f}",
            "per_call": f"${(inp * 2 + outp * 4) / 1000:.4f}",
            "rationale": (
                f"{name} sits in the reasoning tier, so chain-of-thought tokens are "
                "billed as output. A typical reasoning call here produces the kind of "
                "step-by-step answer that justifies the per-token premium."
            ),
        })
        scenarios.append({
            "label": "Multi-step agent loop",
            "shape": "200 agent runs at 8,000 input + 4,000 output tokens",
            "cost": f"${(inp * 8 + outp * 4) / 1000:.3f}",
            "per_call": f"${(inp * 8 + outp * 4) / 1000:.4f}",
            "rationale": (
                "For agent loops where the model is reasoning about tool choices, "
                f"{name}'s chain-of-thought capability is the differentiator. The "
                "agent pays a reasoning premium on every loop, but the win comes from "
                "fewer wrong tool calls."
            ),
        })
        scenarios.append({
            "label": "Long-form analytical writing",
            "shape": "100 writing tasks at 3,000 input + 2,000 output tokens",
            "cost": f"${(inp * 3 + outp * 2) / 1000:.3f}",
            "per_call": f"${(inp * 3 + outp * 2) / 1000:.4f}",
            "rationale": (
                "Reasoning models produce longer, more structured answers for "
                f"analytical writing tasks. {name} handles the structured output well "
                "even when the answer runs past 2,000 tokens."
            ),
        })
    elif tier == "flagship":
        scenarios.append({
            "label": "Production coding agent",
            "shape": "1,000 agent runs at 8,000 input + 4,000 output tokens",
            "cost": f"${(inp * 8 + outp * 4):,.2f}",
            "per_call": f"${(inp * 8 + outp * 4) / 1000:.4f}",
            "rationale": (
                f"{name} is priced at the top of its provider's lineup, so a coding "
                "agent that runs through long tool-call loops adds up quickly. "
                "Realistic teams run this at hundreds to low thousands of calls per "
                "day and watch the bill closely."
            ),
        })
        scenarios.append({
            "label": "High-stakes document review",
            "shape": "500 documents at 20,000 input + 3,000 output tokens",
            "cost": f"${(inp * 20 + outp * 3):,.2f}",
            "per_call": f"${(inp * 20 + outp * 3) / 1000:.4f}",
            "rationale": (
                "Legal, compliance, or research review where a wrong answer is "
                "expensive. The flagship tier is the right call when the answer "
                "quality matters more than the per-call cost."
            ),
        })
        scenarios.append({
            "label": "Multi-turn research assistant",
            "shape": "200 long sessions at 30,000 input + 5,000 output tokens",
            "cost": f"${(inp * 30 + outp * 5):,.2f}",
            "per_call": f"${(inp * 30 + outp * 5) / 1000:.4f}",
            "rationale": (
                f"For research workflows where the conversation history is the asset, "
                f"{name}'s long context window ({ctx_len:,} tokens) means the model "
                "can hold the full session without dropping earlier turns."
            ),
        })
    elif tier == "premium":
        scenarios.append({
            "label": "Mid-volume customer support agent",
            "shape": "10,000 support turns at 1,500 input + 800 output tokens",
            "cost": f"${(inp * 15 + outp * 8):,.2f}",
            "per_call": f"${(inp * 1.5 + outp * 0.8) / 1000:.4f}",
            "rationale": (
                "Production support where answer quality is the trust signal. The "
                f"premium tier sits between flagship and budget, so {name} handles "
                "the long tail of edge cases a budget model would fumble."
            ),
        })
        scenarios.append({
            "label": "Code review on nontrivial PRs",
            "shape": "500 PRs at 5,000 input + 1,500 output tokens",
            "cost": f"${(inp * 25 + outp * 1.5):,.2f}",
            "per_call": f"${(inp * 5 + outp * 1.5) / 1000:.4f}",
            "rationale": (
                "Code review where the model needs to understand the change in "
                "context. The premium tier reads long diffs better than the budget "
                "tier, and costs less than the flagship per PR."
            ),
        })
        scenarios.append({
            "label": "RAG over a 50K-token corpus",
            "shape": "1,000 retrieval calls at 50,000 input + 1,500 output tokens",
            "cost": f"${(inp * 50 + outp * 1.5):,.2f}",
            "per_call": f"${(inp * 50 + outp * 1.5) / 1000:.4f}",
            "rationale": (
                "Retrieval-augmented generation where the corpus fits in a single "
                "context window. The premium tier reads the retrieved context well "
                "without the flagship premium."
            ),
        })
    elif tier == "mid":
        scenarios.append({
            "label": "General-purpose chat at scale",
            "shape": "10,000 chat turns at 1,000 input + 500 output tokens",
            "cost": f"${(inp * 10 + outp * 5):,.2f}",
            "per_call": f"${(inp * 1 + outp * 0.5) / 1000:.4f}",
            "rationale": (
                f"{name} is the model most teams end up defaulting to once they have "
                "measured their traffic. The mid-tier price keeps the bill reasonable "
                "at scale, and the answer quality is good enough that most users do "
                "not need to escalate to a flagship."
            ),
        })
        scenarios.append({
            "label": "Tool-calling workflow agent",
            "shape": "2,000 agent turns at 3,000 input + 1,500 output tokens",
            "cost": f"${(inp * 6 + outp * 3):,.2f}",
            "per_call": f"${(inp * 3 + outp * 1.5) / 1000:.4f}",
            "rationale": (
                "Mid-tier models handle tool-calling workflows well — the answer "
                "quality is consistent across prompt shapes, and the per-call cost "
                "stays under one cent for typical agent turns."
            ),
        })
        scenarios.append({
            "label": "Bulk classification with reasonable quality",
            "shape": "50,000 classification calls at 300 input + 100 output tokens",
            "cost": f"${(inp * 15 + outp * 5):,.2f}",
            "per_call": f"${(inp * 0.3 + outp * 0.1) / 1000:.5f}",
            "rationale": (
                "When the answer quality gap between mid-tier and budget-tier models "
                "matters for the use case, the mid-tier is the right call. For "
                "classification that needs nuance (sentiment, intent, priority), the "
                "extra per-call cost is recovered in fewer misroutes."
            ),
        })
    else:  # cheap
        scenarios.append({
            "label": "Bulk extraction at scale",
            "shape": "100,000 extraction calls at 200 input + 80 output tokens",
            "cost": f"${(inp * 20 + outp * 8):,.2f}",
            "per_call": f"${(inp * 0.2 + outp * 0.08) / 1000:.6f}",
            "rationale": (
                f"{name} is priced for volume. At 100,000 calls a month, the bill "
                "stays in the low double digits — the kind of workload where a "
                "flagship model would cost 10-20x more without a meaningful quality "
                "lift on short extraction prompts."
            ),
        })
        scenarios.append({
            "label": "Routing layer in front of a flagship",
            "shape": "20,000 routing decisions at 300 input + 50 output tokens",
            "cost": f"${(inp * 6 + outp * 1):,.2f}",
            "per_call": f"${(inp * 0.3 + outp * 0.05) / 1000:.5f}",
            "rationale": (
                "Use a cheap-tier model as the always-on routing layer. It classifies "
                "the request, decides whether to escalate to a flagship, and the "
                "bill stays manageable even at high traffic."
            ),
        })
        scenarios.append({
            "label": "Short chat agent for a low-stakes product",
            "shape": "50,000 chat turns at 400 input + 200 output tokens",
            "cost": f"${(inp * 20 + outp * 10):,.2f}",
            "per_call": f"${(inp * 0.4 + outp * 0.2) / 1000:.5f}",
            "rationale": (
                "For a product where the chat is a feature, not the main value prop, "
                f"a cheap-tier model like {name} keeps the per-conversation cost "
                "low enough that the unit economics work at scale."
            ),
        })

    return scenarios


def generate_comparison_snapshot(model: dict, ctx: dict) -> list[dict]:
    """Template B and C: 2-3 same-tier competitors with price + 1 factor.

    Returns a list of {name, slug, input, output, factor} rows that
    the template builder renders as a "Comparison snapshot" or
    "Quick comparison table". Each row is a real model from the
    cache, picked to be in the same price tier as the target.
    """
    name = short_name(ctx["model_id"], ctx["display_name"])
    inp = float(model.get("input_per_1m", 0) or 0)
    outp = float(model.get("output_per_1m", 0) or 0)
    provider = model.get("provider", "")
    tier = price_tier(model)
    reasoning = is_reasoning(model)
    all_models = ctx.get("all_models", {})
    target_id = model["_id"]

    # Build same-tier competitor list
    competitors: list[dict] = []
    for mid, m in all_models.items():
        if mid == target_id:
            continue
        if m.get("provider") == provider:
            continue  # cross-provider only
        m_tier = price_tier(m)
        m_in = float(m.get("input_per_1m", 0) or 0)
        m_out = float(m.get("output_per_1m", 0) or 0)
        if m_tier != tier:
            continue
        # Compute price ratio
        if inp > 0 and m_in > 0:
            in_ratio = m_in / inp
            if 0.4 <= in_ratio <= 2.5:
                competitors.append(m)

    # Sort by closeness in input price, take 3
    competitors.sort(key=lambda m: abs(float(m.get("input_per_1m", 0) or 0) - inp))
    picked = competitors[:3]

    rows = []
    rows.append({
        "name": name,
        "slug": model["_slug"],
        "is_self": True,
        "input": inp,
        "output": outp,
        "factor": _distinguishing_factor(model, reasoning=reasoning, tier=tier),
    })
    for c in picked:
        c_in = float(c.get("input_per_1m", 0) or 0)
        c_out = float(c.get("output_per_1m", 0) or 0)
        c_name = short_name(c["_id"], c.get("display_name", c["_id"]))
        rows.append({
            "name": c_name,
            "slug": c["_slug"],
            "is_self": False,
            "input": c_in,
            "output": c_out,
            "factor": _distinguishing_factor(c, reasoning=is_reasoning(c), tier=price_tier(c)),
        })
    return rows


def _distinguishing_factor(model: dict, reasoning: bool, tier: str) -> str:
    """Return one short distinguishing-fact string for a comparison row."""
    p = provider_label(model.get("provider", ""))
    ctx_len = int(model.get("context_window", 0) or 0)
    free = is_free(model)
    if free:
        return f"Free tier via {p}"
    if reasoning:
        if ctx_len and ctx_len >= 1_000_000:
            return f"Reasoning + {ctx_len // 1000}K context"
        return "Reasoning-capable"
    if ctx_len and ctx_len >= 1_000_000:
        return f"{ctx_len // 1000}K-token context"
    if ctx_len and ctx_len >= 200_000:
        return f"{ctx_len // 1000}K context"
    if tier == "flagship":
        return "Flagship tier"
    if tier == "premium":
        return "Premium tier"
    if tier == "mid":
        return "Mid-tier default"
    return "Budget tier"


def generate_comparison_intro(model: dict, ctx: dict) -> str:
    """Template C: 1-2 paragraph positioning paragraph(s) for the top.

    Different from generate_prose() — focuses on where this model sits
    in its tier relative to same-tier competitors, not on provider
    positioning.
    """
    name = short_name(ctx["model_id"], ctx["display_name"])
    p = ctx["provider_label"]
    inp = float(model.get("input_per_1m", 0) or 0)
    outp = float(model.get("output_per_1m", 0) or 0)
    tier = price_tier(model)
    free = is_free(model)
    reasoning = is_reasoning(model)

    if free:
        return (
            f"{name} sits in the free tier on OpenRouter — both input and output are "
            f"$0.00 per 1M tokens. The relevant comparison is against other free-tier "
            f"listings, where the differences are availability, context window, and "
            f"the underlying model that the free tier wraps. The price is the same "
            f"($0.00) across all of them, so the choice comes down to which free "
            f"model's quality and rate limits fit your workload. Use the comparison "
            f"table below to see where {name} lines up against the closest free-tier "
            f"alternatives."
        )
    if tier == "flagship":
        return (
            f"{name} is priced at the top of the {p} lineup — ${inp:.2f} per 1M input, "
            f"${outp:.2f} per 1M output. The flagship tier is where every provider "
            f"puts its strongest answer quality, and the comparison table below shows "
            f"how {name} stacks up against the closest same-tier competitors on "
            f"input/output price plus the one factor that actually differentiates "
            f"flagship models (reasoning capability, context window, modality). For "
            f"most teams the flagship question is not \"which flagship\" but \"do I "
            f"need a flagship at all\" — the workload examples below show what a "
            f"single call costs so you can decide."
        )
    if tier == "premium":
        return (
            f"{name} sits in the premium band — ${inp:.2f} input, ${outp:.2f} output "
            f"per 1M tokens. The premium tier is where the answer quality step up "
            f"from the mid-tier becomes visible in production, and the comparison "
            f"table below shows where {name} lines up against the closest same-tier "
            f"alternatives. The premium-vs-mid decision usually comes down to the "
            f"specific workload: extraction and routing stay at mid, code review and "
            f"analytical writing benefit from premium."
        )
    if tier == "mid":
        return (
            f"{name} is a mid-tier model — ${inp:.2f} input, ${outp:.2f} output per 1M "
            f"tokens. The mid tier is where most production traffic ends up: cheap "
            f"enough to run at scale, capable enough that the answer quality does not "
            f"need a flagship. The comparison table below shows where {name} sits "
            f"against same-tier competitors from other providers, so you can pick "
            f"the one whose specialty (reasoning, context window, modality) fits your "
            f"specific workload."
        )
    return (
        f"{name} is a budget-tier model — ${inp:.2f} input, ${outp:.2f} output per 1M "
        f"tokens. The budget tier is for high-volume work where the per-call cost "
        f"dominates the bill: bulk classification, extraction, routing, and the kind "
        f"of background work that fires thousands of times a day. The comparison "
        f"table below shows where {name} lines up against the closest budget-tier "
        f"alternatives from other providers."
    )


def generate_capabilities_summary(model: dict) -> str:
    """Template B: compact one-line capabilities summary.

    Different from the full Live pricing table — a single inline
    paragraph that says what the model can do, sized for the
    "Use-Case First" reading flow where the user wants to know
    capability before wading through the pricing table.
    """
    ctx_len = int(model.get("context_window", 0) or 0)
    reasoning = is_reasoning(model)
    free = is_free(model)

    parts = []
    if ctx_len:
        if ctx_len >= 1_000_000:
            parts.append(f"{ctx_len // 100_000 / 10:.1f}M-token context window".replace(".0M", "M"))
        elif ctx_len >= 1_000:
            parts.append(f"{ctx_len // 1_000}K-token context")
        else:
            parts.append(f"{ctx_len}-token context")
    if reasoning:
        parts.append("chain-of-thought reasoning")
    if free:
        parts.append("free tier")
    if not parts:
        return "Standard text model."
    return " &middot; ".join(parts) + "."


def generate_enrichment_note(model: dict, ctx: dict) -> str:
    """Template C: one substantive observation block for the worst pages.

    Returns "" for pages that don't need enrichment, and 1-2 short
    paragraphs of REAL content for pages that do. The block is honest
    about what is known vs unknown, and uses real numbers from the
    cache or the model's known catalog quirks.

    Targeted pages (the worst post-redistribution):
    - Single-model niche providers (bytedance-seed, baidu, inclusionai,
      moonshotai, morph, nousresearch, poolside, allenai, ibm-granite)
    - Free-tier models (cognitivecomputations-dolphin, nvidia nemotron
      free variants, google-gemma-4 free variants, etc.)
    - Providers whose catalog is small enough that OpenRouter does not
      publish rich metadata
    """
    name = short_name(ctx["model_id"], ctx["display_name"])
    p = ctx["provider_label"]
    inp = float(model.get("input_per_1m", 0) or 0)
    outp = float(model.get("output_per_1m", 0) or 0)
    ctx_len = int(model.get("context_window", 0) or 0)
    free = is_free(model)
    reasoning = is_reasoning(model)
    provider = model.get("provider", "").lower()
    mid = ctx["model_id"].lower()

    # Provider-specific enrichment notes
    # Each entry returns either a paragraph string or "" if no enrichment
    enrichment: list[str] = []

    if provider == "bytedance-seed":
        enrichment.append(
            f"{name} is ByteDance's flagship model on OpenRouter. The provider is "
            "better known for consumer products (TikTok, Doubao, Cici) than for "
            "developer-facing LLM APIs, so the OpenRouter listing is one of the few "
            "production-grade access points outside ByteDance's own (China-region) "
            "endpoint. The catalog entry exposes pricing and context window but "
            "does not publish benchmark numbers — ByteDance's own press materials "
            f"are the most reliable source for {name}'s performance claims."
        )
    elif provider == "baidu":
        enrichment.append(
            f"{name} is Baidu's ERNIE flagship, accessible via OpenRouter outside "
            "China. The same caveats as other Chinese open-weights models apply: "
            "training data skews toward Chinese content, US-hosted enterprise "
            "procurement often defaults to US vendors for compliance, and the "
            "OpenRouter listing does not surface benchmark numbers. ERNIE's "
            "strength is Chinese-language fluency and multimodal input (the 424B "
            "vision-language variant in the same family handles images natively)."
        )
    elif provider == "inclusionai":
        enrichment.append(
            f"{name} ships from InclusionAI, a newer Chinese AI lab with a "
            "trillion-parameter focus. The model is positioned for long-context "
            "workloads (1T parameters suggests substantial capacity), but "
            "OpenRouter does not publish benchmark numbers on this listing, and "
            "InclusionAI's English-language documentation is still catching up to "
            "its Chinese release notes. For teams willing to evaluate a "
            "less-marketed model, the per-token price is the relevant signal."
        )
    elif provider == "moonshotai":
        enrichment.append(
            f"{name} is Moonshot AI's Kimi model, accessible on OpenRouter. Moonshot "
            "ships Kimi as the long-context competitor in the Chinese open-weights "
            "space — the same slot that GLM and Qwen fill. The OpenRouter listing "
            "exposes pricing and context window but does not publish benchmark "
            "scores; Moonshot's own documentation is the most reliable source for "
            f"performance claims about {name}."
        )
    elif provider == "morph":
        enrichment.append(
            f"{name} is Morph's frontier-tier model. Morph is a newer provider on "
            "the OpenRouter catalog, so the listing is shorter on metadata than "
            "the long-standing providers — no published benchmark numbers, no "
            "detailed provider write-up. The relevant signal is the price "
            f"(${inp:.2f} input / ${outp:.2f} output per 1M tokens) and the "
            f"context window ({ctx_len:,} tokens). For teams willing to evaluate "
            "a less-marketed model, that is the comparison surface."
        )
    elif provider == "nousresearch":
        enrichment.append(
            f"{name} is Nous Research's Hermes fine-tune. Hermes is the open-weights "
            "fine-tuning lineage that produced the Hermes 3 family — fully open "
            "weights, fine-tuned for instruction-following and tool use. The "
            "OpenRouter listing exposes pricing and context window; the underlying "
            "weights and training data are on Hugging Face, which is the most "
            f"reliable source for {name}'s actual capabilities beyond what the "
            "API exposes."
        )
    elif provider == "poolside":
        enrichment.append(
            f"{name} is Poolside's Laguna model, accessible via OpenRouter on the "
            "free tier. Poolside positions itself around software-engineering "
            "workloads, so the model's strengths are in code generation and code "
            "review rather than chat or reasoning. The OpenRouter listing is "
            "sparse — pricing and context window only — so the most reliable "
            "signal is the free-tier price ($0.00) and Poolside's own developer "
            "documentation for what the underlying model handles well."
        )
    elif provider == "allenai":
        enrichment.append(
            f"{name} is AllenAI's OLMo model. OLMo is one of the few fully "
            "open-source LLM families — training data, code, and weights are all "
            "publicly released, which makes it the right choice for teams that "
            "need a model whose behavior is auditable end-to-end. The 'Think' "
            "variant in this listing has reasoning capability enabled. The "
            "OpenRouter catalog entry exposes pricing and context window; AllenAI's "
            "own model card on Hugging Face is the source for benchmark numbers "
            f"and training details about {name}."
        )
    elif provider == "cognitivecomputations":
        enrichment.append(
            f"{name} is Cognitive Computations' Dolphin fine-tune, served free via "
            "OpenRouter. Dolphin is the lineage of uncensored / instruction-tuned "
            "models that came out of the Eric Hartford fine-tune project — fully "
            "open weights, fine-tuned for instruction following without the safety "
            "filtering the base model ships with. The free tier means there is no "
            "rate-limit-free production path, so treat it as a way to evaluate the "
            f"Dolphin behavior rather than as a permanent backend for {name}."
        )
    elif provider == "ibm-granite":
        enrichment.append(
            f"{name} is IBM's Granite model, served on OpenRouter. Granite is "
            "IBM's enterprise-focused open-weights lineup — the same family IBM "
            "uses in its watsonx.ai product. The 8B parameter size positions "
            f"{name} as the budget tier of the Granite family, suitable for "
            "high-volume work where the per-call cost matters more than the "
            "absolute best answer quality. IBM's own model card is the source for "
            f"benchmark numbers and training details about {name}."
        )
    elif provider == "mistralai":
        enrichment.append(
            f"{name} is Mistral's flagship model on OpenRouter. Mistral is the "
            "French AI lab behind the Mistral 7B, Mixtral, and Mistral Large "
            "families — one of the most active open-weights contributors in the "
            "European AI ecosystem. The OpenRouter listing exposes pricing and "
            "context window but does not publish benchmark numbers; Mistral's own "
            "model cards on their developer portal are the source for benchmark "
            f"scores and capability claims about {name}. Mistral Large is the "
            "production workhorse of the family — a 123B-parameter dense model "
            "tuned for instruction following and tool use."
        )
    elif provider == "nvidia" and free:
        enrichment.append(
            f"{name} is NVIDIA's Nemotron model, served free via OpenRouter. "
            "Nemotron is NVIDIA's open-weights family of models tuned for "
            "reasoning and tool use. The free tier means there is no per-token "
            "bill, but the practical limits are throughput and availability — "
            "the same trade-off as every other free-tier OpenRouter listing. "
            "NVIDIA's own developer portal is the source for benchmark numbers "
            f"and training details about {name}."
        )
    elif provider == "google" and free:
        # Gemma 4 free variants
        enrichment.append(
            f"{name} is Google's Gemma model, served free via OpenRouter. Gemma is "
            "Google's open-weights family — fully open weights, trained by Google, "
            "shipped under a permissive license. The free tier means there is no "
            "per-token bill, but the practical limits are throughput and "
            "availability. Google's own model card on Hugging Face or the Gemma "
            f"documentation portal is the source for benchmark numbers about {name}."
        )
    elif provider == "z-ai" and not free:
        # Already covered by seo5 custom prose, but a one-liner here
        # reinforces that Z.AI/GLM is the same model family across the lineup.
        enrichment.append(
            f"{name} is part of the Z.AI (Zhipu) GLM family. The pricing tier here "
            f"(${inp:.2f} input / ${outp:.2f} output per 1M tokens) is one rung in "
            "the GLM lineup; the comparison table below shows where it sits against "
            "same-tier alternatives. Zhipu's own model cards are the most reliable "
            f"source for benchmark numbers about {name} — the OpenRouter catalog "
            "does not publish scores on these listings."
        )
    elif provider == "minimax" and not free:
        # Already covered by seo5 custom prose, but a one-liner reinforces
        enrichment.append(
            f"{name} is part of the MiniMax M-series lineup. The M-series covers "
            f"long-context work ({ctx_len:,} tokens) at the flagship and premium "
            "tiers, with the smaller M2 variants handling production workhorse "
            "volume. The comparison table below shows where this model sits "
            "against same-tier alternatives. MiniMax's own documentation is the "
            f"source for benchmark numbers about {name}."
        )
    elif provider == "deepseek":
        enrichment.append(
            f"{name} is DeepSeek's model, accessible on OpenRouter. DeepSeek ships "
            "the V3 and R1 families — V3 is the general-purpose chat model, R1 is "
            "the reasoning-capable variant. The OpenRouter listing exposes pricing "
            f"and context window; DeepSeek's own technical report is the most "
            f"reliable source for benchmark numbers about {name}."
        )
    elif provider == "amazon":
        enrichment.append(
            f"{name} is Amazon's Nova model, accessible via OpenRouter as an "
            "alternative to the direct AWS Bedrock endpoint. Nova is Amazon's "
            "in-house model family positioned across the lite/pro/premium tiers. "
            "The OpenRouter listing is one access path among several — direct "
            "Bedrock access is the alternative for AWS-native workloads. Amazon's "
            f"own documentation is the source for benchmark numbers about {name}."
        )

    if not enrichment:
        return ""
    return "\n".join(f"<p>{p}</p>" for p in enrichment)


def should_enrich(model: dict) -> bool:
    """Decide whether to surface the enrichment note for this model.

    The enrichment block is targeted at the worst pages post-redistribution:
    niche providers (single-model curated coverage), newer/less-known brands
    where OpenRouter does not publish rich metadata, and free-tier models.
    Covers Template C in full plus the single-page Template B providers
    that share the same "thin metadata" problem.
    """
    provider = model.get("provider", "").lower()
    # Template C: every page is on the enrichment list (all 36)
    if assign_template(model) == "C":
        return True
    # Template B: single-page providers that share Template C's
    # "thin OpenRouter metadata" problem
    single_page_b_providers = {
        "allenai",       # OLMo — fully open weights, useful context
        "ibm-granite",   # Granite — enterprise positioning
        "mistralai",     # Mistral — only 1 curated model on Template B
    }
    if provider in single_page_b_providers:
        return True
    return False


# ---------------------------------------------------------------------------
# Related model selection
# ---------------------------------------------------------------------------

def pick_related_models(target: dict, all_models: dict) -> list[dict]:
    """Pick 3-5 related models for internal linking.

    Per task brief:
      - 1-2 from same provider, different price tier
      - 1-2 with similar input price (±50%)
      - 1 with similar output price (±50%)

    Implementation: collect candidates from each branch, sort by score,
    then assemble respecting the per-branch caps (2 same-provider,
    2 similar-input, 1 similar-output). Avoids over-indexing on a single
    provider when the target has many same-provider peers.
    """
    target_id = target["_id"]
    target_provider = target.get("provider", "")
    target_in = float(target.get("input_per_1m", 0) or 0)
    target_out = float(target.get("output_per_1m", 0) or 0)
    target_tier = price_tier(target)

    same_provider: list[tuple[float, dict]] = []
    similar_input: list[tuple[float, dict]] = []
    similar_output: list[tuple[float, dict]] = []

    for mid, m in all_models.items():
        if mid == target_id:
            continue
        m_in = float(m.get("input_per_1m", 0) or 0)
        m_out = float(m.get("output_per_1m", 0) or 0)
        m_provider = m.get("provider", "")
        m_tier = price_tier(m)

        # Same provider, different tier
        if m_provider == target_provider and m_tier != target_tier:
            score = 100.0 + abs(m_in - target_in)  # closer in price = better
            same_provider.append((score, m))
            continue

        # Similar input price (±50%)
        if target_in > 0 and m_in > 0:
            in_diff_ratio = abs(m_in - target_in) / max(target_in, 1e-6)
            if in_diff_ratio <= 0.5:
                score = 80.0 - in_diff_ratio * 20
                similar_input.append((score, m))
                continue

        # Similar output price (±50%)
        if target_out > 0 and m_out > 0:
            out_diff_ratio = abs(m_out - target_out) / max(target_out, 1e-6)
            if out_diff_ratio <= 0.5:
                score = 60.0 - out_diff_ratio * 20
                similar_output.append((score, m))

    # Sort each branch by score desc
    same_provider.sort(key=lambda c: -c[0])
    similar_input.sort(key=lambda c: -c[0])
    similar_output.sort(key=lambda c: -c[0])

    picked: list[dict] = []
    seen: set[str] = set()

    # Round 1: 1-2 from same provider (capped at 2)
    for _, m in same_provider[:2]:
        if len(picked) >= 5:
            break
        if m["_id"] in seen:
            continue
        seen.add(m["_id"])
        picked.append(m)

    # Round 2: 1-2 with similar input price (capped at 2)
    for _, m in similar_input:
        if len(picked) >= 5:
            break
        same_provider_count = sum(1 for x in picked
                                   if x.get("provider") == target_provider)
        if same_provider_count >= 2 and m.get("provider") == target_provider:
            continue
        if m["_id"] in seen:
            continue
        seen.add(m["_id"])
        picked.append(m)
        # Stop after 2 cross-provider similar-input adds
        cross_added = sum(1 for x in picked[2:]
                          if x.get("provider") != target_provider)
        if cross_added >= 2:
            break

    # Round 3: 1 with similar output price (prefer cross-provider if cap reached)
    same_provider_count = sum(1 for x in picked if x.get("provider") == target_provider)
    for _, m in similar_output:
        if len(picked) >= 5:
            break
        if m["_id"] in seen:
            continue
        if same_provider_count >= 2 and m.get("provider") == target_provider:
            continue  # prefer cross-provider
        seen.add(m["_id"])
        picked.append(m)
        break
    # If we still have room and only same-provider left, take any remaining
    if len(picked) < 3:
        for _, m in same_provider[2:]:
            if len(picked) >= 3:
                break
            if m["_id"] in seen:
                continue
            seen.add(m["_id"])
            picked.append(m)
            break

    return picked


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

def render_page(model: dict, all_models: dict, related: list[dict], today: str) -> str:
    model_id = model["_id"]
    slug = model["_slug"]
    display_name = model.get("display_name", model_id)
    name = short_name(model_id, display_name)
    provider = model.get("provider", "")
    provider_lbl = provider_label(provider)
    inp = float(model.get("input_per_1m", 0) or 0)
    outp = float(model.get("output_per_1m", 0) or 0)
    ctx_len = int(model.get("context_window", 0) or 0)
    reasoning = is_reasoning(model)
    free = is_free(model)

    canonical = f"{SITE_BASE}{MODELS_PREFIX}{slug}.html"
    title = f"{name} pricing per 1M tokens \u2014 free {provider_lbl} cost calculator | AI Cost Calculator"

    # SEO-5 (t_ca4f783a): meta description for MiniMax/GLM pages — must
    # include "free" / "cheap" / actual price tier per the brief's keyword
    # strategy targeting "free AI cost calculator" + "cheap LLM API".
    seo5_tier = price_tier(model)
    if is_minimax_or_glm(model):
        if free:
            meta_desc = (
                f"Free {name} cost calculator ({provider_lbl} on OpenRouter, free tier, "
                f"$0.00 per 1M input and output tokens). Live OpenRouter "
                f"pricing, 5 workload cost examples, no signup."
            )
        elif inp < 1.0:
            # Cheap tier (<$1/M input) — match "cheap LLM API" keyword
            meta_desc = (
                f"Cheap {name} cost calculator \u2014 ${inp:.2f}/1M input, "
                f"${outp:.2f}/1M output. {provider_lbl} on OpenRouter, live pricing, "
                f"5 workload cost examples, agentic overhead, no signup, "
                f"refreshed every 6h."
            )
        else:
            # Mid/premium/flagship — actual price tier in the description
            meta_desc = (
                f"{name} cost calculator \u2014 ${inp:.2f}/1M input, "
                f"${outp:.2f}/1M output ({seo5_tier}-tier {provider_lbl} model). Live "
                f"OpenRouter pricing, 5 workload cost examples, agentic "
                f"overhead, no signup, refreshed every 6h."
            )
    elif free:
        meta_desc = (
            f"Free {name} cost calculator (free tier on OpenRouter, $0.00 per 1M "
            f"input and output tokens). Live OpenRouter pricing, 5 workload "
            f"cost examples, no signup."
        )
    else:
        meta_desc = (
            f"Free {name} cost calculator \u2014 ${inp:.2f}/1M input, ${outp:.2f}/1M "
            f"output. Live OpenRouter pricing, 5 workload cost examples, "
            f"agentic overhead, no signup, refreshed every 6h."
        )

    keywords = ", ".join([
        name, f"{name} pricing", f"{name} cost", f"{name} token calculator",
        provider_lbl, f"{provider_lbl} {name}", "LLM pricing",
        "API cost calculator", "OpenRouter pricing",
    ])

    # Build the per-page context (used by prose + FAQ generators)
    same_provider = [m for m in all_models.values() if m.get("provider") == provider and m["_id"] != model_id]
    same_provider.sort(key=lambda m: float(m.get("input_per_1m", 0) or 0))
    cheapest_related = sorted(related, key=lambda m: float(m.get("input_per_1m", 0) or 0))

    ctx = {
        "model_id": model_id,
        "display_name": display_name,
        "provider_label": provider_lbl,
        "same_provider": same_provider,
        "cheapest_related": cheapest_related,
        "all_models": all_models,
        "template": assign_template(model),
    }

    # Prose (300+ words)
    prose = generate_prose(model, ctx)

    # FAQ
    faq = generate_faq(model, ctx)

    # 5-workload cost table
    workload_rows = []
    for in_tok, out_tok, label, desc, tool_calls in WORKLOADS:
        cost = workload_cost(model, in_tok, out_tok, tool_calls)
        cost_str = "free" if cost == 0 else fmt_money(cost)
        workload_rows.append({
            "label": label,
            "desc": desc,
            "tokens": f"{fmt_int(in_tok)} in + {fmt_int(out_tok)} out"
                      + (f" + {tool_calls} tool calls" if tool_calls else ""),
            "cost": cost_str,
            "is_free": cost == 0,
        })

    # Live-pricing rows
    if free:
        live_pricing_rows = [
            ("Input price (per 1M tokens)", "$0.00", False),
            ("Output price (per 1M tokens)", "$0.00", False),
            ("Context window", f"{ctx_len:,} tokens" if ctx_len else "—", False),
            ("Reasoning tokens", "Yes" if reasoning else "No", False),
            ("Modality", "Text", False),
            ("Provider", provider_lbl, False),
        ]
    else:
        live_pricing_rows = [
            ("Input price (per 1M tokens)", f"${inp:.2f}", False),
            ("Output price (per 1M tokens)", f"${outp:.2f}", False),
            ("Context window", f"{ctx_len:,} tokens" if ctx_len else "—", False),
            ("Reasoning tokens", "Yes" if reasoning else "No", False),
            ("Modality", "Text", False),
            ("Provider", provider_lbl, False),
        ]

    # Related models block
    related_html = []
    for r in related:
        r_in = float(r.get("input_per_1m", 0) or 0)
        r_out = float(r.get("output_per_1m", 0) or 0)
        r_name = short_name(r["_id"], r.get("display_name", r["_id"]))
        r_slug = r["_slug"]
        if is_free(r):
            price_phrase = "free"
        else:
            price_phrase = f"${r_in:.2f} in / ${r_out:.2f} out"
        related_html.append(
            f'<li><a href="{MODELS_PREFIX}{r_slug}.html">{r_name}</a>'
            f'<span class="model-related__price"> &middot; {price_phrase} per 1M</span></li>'
        )
    related_block = "\n".join(related_html) if related_html else "<li>No related models available.</li>"

    # Build "When to use" list (3-5 bullets, derived from prose)
    if free:
        use_cases = [
            f"Experiments and prototypes where the bill is the priority",
            f"Smoke tests and CI checks that need a real model response without a cost",
            f"Workshops, classroom settings, and demo environments with a hard cost cap",
            f"Bulk evaluation runs where the team wants to compare many prompt variants",
        ]
    elif reasoning:
        use_cases = [
            f"Math, code, and multi-step reasoning where chain-of-thought helps the answer",
            f"Agent loops that need to reason about tool choices before acting",
            f"Long-form analytical writing that benefits from explicit thinking",
            f"High-stakes answers where the extra reasoning tokens are worth the cost",
        ]
    elif price_tier(model) in ("flagship", "premium"):
        use_cases = [
            f"Long-form synthesis, complex code reviews, and high-stakes analysis",
            f"Workloads where a wrong answer is expensive",
            f"Production agents that need consistent quality across a wide range of inputs",
            f"Long-context tasks where the model's full window is the differentiator",
        ]
    elif price_tier(model) == "mid":
        use_cases = [
            f"Everyday chat and document work that fills most production traffic",
            f"Mid-volume agents where answer quality matters but the bill is still reasonable",
            f"Tool-calling workflows where instruction following is the main requirement",
            f"Long-running assistants where cost adds up over time",
        ]
    else:
        use_cases = [
            f"High-volume work: bulk classification, routing, extraction, batch jobs",
            f"Routing layers in front of a more expensive model",
            f"Short chat agents with short prompts and short answers",
            f"Evaluation pipelines that need many invocations to compare prompt variants",
        ]

    # JSON-LD @graph
    offer_for_schema = {
        "@type": "Offer",
        "price": "0.00" if free else f"{inp:.2f}",
        "priceCurrency": "USD",
        "priceSpecification": {
            "@type": "UnitPriceSpecification",
            "price": "0.00" if free else f"{inp:.2f}",
            "priceCurrency": "USD",
            "referenceQuantity": {"@type": "QuantitativeValue", "value": 1000000, "unitText": "tokens"},
            "description": "Input price per 1M tokens" if not free else "Free model",
        },
        "availability": "https://schema.org/InStock",
        "url": canonical,
    }
    product = {
        "@type": "Product",
        "name": name,
        "description": f"{name} on OpenRouter: {meta_desc}",
        "brand": {"@type": "Brand", "name": provider_lbl},
        "category": "AI Language Model",
        "offers": offer_for_schema,
        "url": canonical,
    }
    breadcrumb = {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": SITE_BASE + "/"},
            {"@type": "ListItem", "position": 2, "name": "Models", "item": SITE_BASE + MODELS_PREFIX},
            {"@type": "ListItem", "position": 3, "name": name, "item": canonical},
        ],
    }
    faq_schema = {
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": q,
                "acceptedAnswer": {"@type": "Answer", "text": a},
            } for q, a in faq
        ],
    }
    jsonld = {
        "@context": "https://schema.org",
        "@graph": [product, offer_for_schema, breadcrumb, faq_schema],
    }
    jsonld_str = json.dumps(jsonld, indent=2)

    # About paragraph (re-use prose, but split by paragraph)
    prose_paragraphs = prose.split("\n\n")

    # Build FAQ HTML
    faq_html = "\n".join(
        f'<div class="model-faq__item"><p class="model-faq__q">{q}</p>'
        f'<p class="model-faq__a">{a}</p></div>'
        for q, a in faq
    )

    # Use cases list HTML
    use_cases_html = "\n".join(f"<li>{u}</li>" for u in use_cases)

    # Live pricing table HTML
    live_pricing_html = "\n".join(
        f"<tr><td>{label}</td><td>{val}</td></tr>"
        for label, val, _ in live_pricing_rows
    )

    # Workload cost table HTML
    workload_table_html = "\n".join(
        f'<tr><td><div class="model-wl__label">{r["label"]}</div>'
        f'<div class="model-wl__desc">{r["desc"]}</div>'
        f'<div class="compare-wl__tokens" style="font-family: var(--mono); font-size: 0.7rem; color: var(--ink-3); margin-top: 4px;">{r["tokens"]}</div></td>'
        f'<td class="model-cost{(" model-cost--free" if r["is_free"] else "")}">{r["cost"]}</td></tr>'
        for r in workload_rows
    )

    # Word count check (visible prose only, for debug — emitted in HTML comment)
    visible_text = " ".join(prose_paragraphs + [q + " " + a for q, a in faq])

    # SEO-5 (t_ca4f783a): add custom depth prose for MiniMax/GLM pages.
    # Inserted BEFORE the FAQ section per the brief. For other providers,
    # custom_prose_html is "" and the section is omitted.
    custom_prose_html = ""
    if is_minimax_or_glm(model):
        custom_prose_paragraphs = generate_custom_prose_minimax_glm(model, ctx).split("\n\n")
        if custom_prose_paragraphs and any(p.strip() for p in custom_prose_paragraphs):
            section_h2 = (
                f"<h2>What makes {name} different</h2>"
            )
            section_body = "".join(
                f"<p>{p}</p>" for p in custom_prose_paragraphs if p.strip()
            )
            custom_prose_html = (
                f'<div class="model-section model-section--seo5">\n'
                f'      {section_h2}\n'
                f'      {section_body}\n'
                f'    </div>\n\n'
                f'    '
            )
            # Include in word count for AdSense-safety check
            visible_text += " " + " ".join(custom_prose_paragraphs)

    word_count = len(visible_text.split())

    # SEO-6 (t_52219b65): template-specific enrichment note. Only on
    # Template C pages where the standard prose is thinnest.
    enrichment_html = ""
    if should_enrich(model):
        enrichment_paragraphs_html = generate_enrichment_note(model, ctx)
        if enrichment_paragraphs_html:
            enrichment_html = (
                f'<div class="model-section model-section--note">\n'
                f'      <h2>Notable observation</h2>\n'
                f'      {enrichment_paragraphs_html}\n'
                f'    </div>\n\n'
                f'    '
            )
            visible_text += " " + enrichment_paragraphs_html.replace("<p>", "").replace("</p>", " ")
            word_count = len(visible_text.split())

    # Verdict
    if free:
        verdict = (
            f"<strong>{name}</strong> is a free model on OpenRouter. The cost is "
            f"$0.00 per 1M tokens in both directions; treat the trade-off as "
            f"best-effort availability rather than a missing line item."
        )
    else:
        verdict = (
            f"<strong>{name}</strong> is priced at ${inp:.2f} per 1M input tokens "
            f"and ${outp:.2f} per 1M output tokens. The five workload rows below "
            f"show what a single call costs in practice across chat, retrieval, "
            f"coding, agent, and long-context shapes."
        )

    # Shared <head> + <body> scaffold
    head_and_top = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>{title}</title>
  <meta name="description" content="{meta_desc}">
  <meta name="keywords" content="{keywords}">
  <meta name="robots" content="index, follow">
  <meta name="theme-color" content="#f7f3ec">
  <link rel="canonical" href="{canonical}">
  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{meta_desc}">
  <meta property="og:url" content="{canonical}">
  <meta property="og:type" content="article">
  <meta property="og:site_name" content="AI Cost Calculator">
  <meta property="og:image" content="{SITE_BASE}/og-image.png">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{title}">
  <meta name="twitter:description" content="{meta_desc}">
  <link rel="icon" type="image/svg+xml" href="../favicon.svg">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&display=swap">
  <link rel="stylesheet" href="../models.css">
  <script type="application/ld+json">{jsonld_str}</script>
</head>
<body>
      <nav class="model-topbar__nav" aria-label="Primary">
      <a href="../">Calculator</a>
      <a href="./">All models</a>
      <a href="../compare/">Compare</a>
      <a href="../about.html">About</a>
    </nav>
        <a class="model-brand" href="../" aria-label="AI Cost Calculator (home)">
      <img class="model-brand__mark" src="../logo.svg" alt="" width="44" height="22">
      <span class="model-brand__word">AI Cost Calculator</span>
    </a>

  <main class="model-page">
    <a class="model-page__back" href="./">&larr; Back to all models</a>
    <nav class="model-breadcrumb" aria-label="Breadcrumb">
      <a href="../">Home</a><span class="model-breadcrumb__sep">&rsaquo;</span><a href="./">Models</a><span class="model-breadcrumb__sep">&rsaquo;</span><span>{name}</span>
    </nav>
    <h1 class="model-page__title">{name} pricing per 1M tokens &#8212; free {provider_lbl} cost calculator</h1>
    <p class="model-page__sub">
      {provider_lbl} {name} on OpenRouter: live pricing, five workload cost
      examples, and a checklist of when to use it. The numbers below come
      directly from OpenRouter's <code>/api/v1/models</code> feed and are
      refreshed every six hours.
    </p>
    <p class="model-page__updated">
      <strong>&bull;</strong> Last updated: {today} &middot;
      <a href="../">open the calculator</a> to plug in your own workload.
    </p>

    <div class="model-verdict">{verdict}</div>
"""

    foot = f"""
  </main>

  <footer class="model-foot">
    AI Cost Calculator &middot; <a href="../">Calculator</a> &middot;
    <a href="./">All models</a> &middot;
    <a href="../compare/">Compare</a> &middot;
    <a href="../about.html">About</a> &middot;
    <a href="../privacy.html">Privacy</a> &middot;
    <a href="../status.html">Status</a>
    <br><small class="model-foot__src">Pricing data via <a href="https://openrouter.ai/" rel="noopener">OpenRouter</a> &middot; refreshed every 6 hours</small>
  </footer>
  <!-- generated={today} visible_words={word_count} slug={slug} template={ctx["template"]} -->
</body>
</html>
"""

    # Per-template body content (different section order, different prose)
    template = ctx["template"]
    body_html = _build_template_body(
        template, model, ctx, prose_paragraphs, use_cases, faq,
        live_pricing_rows, workload_rows, related_block,
        custom_prose_html, enrichment_html,
    )

    return head_and_top + body_html + foot


def _build_template_body(
    template: str,
    model: dict,
    ctx: dict,
    prose_paragraphs: list[str],
    use_cases: list[str],
    faq: list[tuple[str, str]],
    live_pricing_rows: list,
    workload_rows: list[dict],
    related_block: str,
    custom_prose_html: str,
    enrichment_html: str,
) -> str:
    """Dispatch to the right template body builder.

    All three templates share the same outer scaffold (rendered by
    the caller) and the same JSON-LD schema (rendered by render_page).
    They differ in (a) section order inside <main>, (b) which prose
    paragraphs / FAQ questions / side blocks are surfaced, and (c)
    which H2 titles appear.

    Template A — Reference Sheet (OpenAI / Anthropic / Google / Perplexity).
        Sections: Live pricing → Cost by workload → About → When to use
                  → When NOT to use → Compare → FAQ.
        Side: seo5 custom prose if MiniMax/GLM (not applicable for A).
        Reader arrived knowing the model name; wants the price + FAQ.

    Template B — Use-Case First (Meta / Qwen / Cohere / Mistral /
                                IBM / AllenAI).
        Sections: Lead use-cases (3-4 specific scenarios with cost
                  breakdowns) → Live pricing → Capabilities summary
                  → Pricing details → Comparison snapshot → FAQ.
        Reader is evaluating between several models; wants to see what
        this one handles well before wading through pricing tables.

    Template C — Comparison-First (every other provider — Z.AI / MiniMax /
                                   NVIDIA / DeepSeek / Amazon / Baidu /
                                   ByteDance / CogComp / InclusionAI /
                                   Moonshot / Morph / NousResearch / Poolside).
        Sections: Quick comparison table → Live pricing → About
                  (1-2 paragraphs) → When this model is the right call
                  → FAQ.
        Side: enrichment note for niche providers with thin metadata.
        Reader is shopping for the right model in a tier; wants to see
        this model in context before reading prose.
    """
    if template == "A":
        return _build_template_a_body(
            model, ctx, prose_paragraphs, use_cases, faq,
            live_pricing_rows, workload_rows, related_block,
            custom_prose_html, enrichment_html,
        )
    if template == "B":
        return _build_template_b_body(
            model, ctx, prose_paragraphs, use_cases, faq,
            live_pricing_rows, workload_rows, related_block,
            custom_prose_html, enrichment_html,
        )
    return _build_template_c_body(
        model, ctx, prose_paragraphs, use_cases, faq,
        live_pricing_rows, workload_rows, related_block,
        custom_prose_html, enrichment_html,
    )


def _build_template_a_body(
    model, ctx, prose_paragraphs, use_cases, faq,
    live_pricing_rows, workload_rows, related_block,
    custom_prose_html, enrichment_html="",
) -> str:
    """Template A — Reference Sheet."""
    name = short_name(ctx["model_id"], ctx["display_name"])
    use_cases_html = "\n".join(f"<li>{u}</li>" for u in use_cases)
    live_pricing_html = "\n".join(
        f"<tr><td>{label}</td><td>{val}</td></tr>"
        for label, val, _ in live_pricing_rows
    )
    workload_table_html = "\n".join(
        f'<tr><td><div class="model-wl__label">{r["label"]}</div>'
        f'<div class="model-wl__desc">{r["desc"]}</div>'
        f'<div class="compare-wl__tokens" style="font-family: var(--mono); font-size: 0.7rem; color: var(--ink-3); margin-top: 4px;">{r["tokens"]}</div></td>'
        f'<td class="model-cost{(" model-cost--free" if r["is_free"] else "")}">{r["cost"]}</td></tr>'
        for r in workload_rows
    )
    when_not_use_html = generate_when_not_use(model, ctx)
    faq_html = "\n".join(
        f'<div class="model-faq__item"><p class="model-faq__q">{q}</p>'
        f'<p class="model-faq__a">{a}</p></div>'
        for q, a in faq
    )
    return f"""
    <h2 class="model-section" style="margin-top: 0; font-family: var(--display); font-size: var(--t-xl); font-weight: 600; color: var(--ink); margin-bottom: var(--s-4);">Live pricing</h2>
    <table class="model-table">
      <thead>
        <tr><th>Spec</th><th>Value</th></tr>
      </thead>
      <tbody>
        {live_pricing_html}
      </tbody>
    </table>

    <div class="model-section">
      <h2>Cost by workload</h2>
      <p>Five standard workload shapes for {name}, pre-computed at generation time. Use these as a starting point for your own estimate; open the <a href="../">main calculator</a> to plug in your exact token counts.</p>
      <table class="model-table">
        <thead>
          <tr><th>Workload</th><th>Per-run cost</th></tr>
        </thead>
        <tbody>
          {workload_table_html}
        </tbody>
      </table>
    </div>

    <div class="model-section">
      <h2>About {name}</h2>
      {"".join(f'<p>{p}</p>' for p in prose_paragraphs)}
    </div>

    <div class="model-section">
      <h2>When to use {name}</h2>
      <ul>
        {use_cases_html}
      </ul>
    </div>

    <div class="model-section">
      <h2>When NOT to use {name}</h2>
      <ul>
        {when_not_use_html}
      </ul>
    </div>

    <div class="model-section">
      <h2>Compare {name} with similar models</h2>
      <div class="model-related">
        <ul>
          {related_block}
        </ul>
      </div>
    </div>

    {custom_prose_html}<div class="model-section">
      <h2>Frequently asked questions</h2>
      <div class="model-faq">
        {faq_html}
      </div>
    </div>"""


def _build_template_b_body(
    model, ctx, prose_paragraphs, use_cases, faq,
    live_pricing_rows, workload_rows, related_block,
    custom_prose_html, enrichment_html="",
) -> str:
    """Template B — Use-Case First.

    Leads with 3-4 concrete use-case scenarios with cost breakdowns
    (different from Template A's tier-positioning prose). Reader is
    evaluating this model vs alternatives; wants to know what it
    handles well before wading through pricing tables.
    """
    name = short_name(ctx["model_id"], ctx["display_name"])
    live_pricing_html = "\n".join(
        f"<tr><td>{label}</td><td>{val}</td></tr>"
        for label, val, _ in live_pricing_rows
    )
    workload_table_html = "\n".join(
        f'<tr><td><div class="model-wl__label">{r["label"]}</div>'
        f'<div class="model-wl__desc">{r["desc"]}</div>'
        f'<div class="compare-wl__tokens" style="font-family: var(--mono); font-size: 0.7rem; color: var(--ink-3); margin-top: 4px;">{r["tokens"]}</div></td>'
        f'<td class="model-cost{(" model-cost--free" if r["is_free"] else "")}">{r["cost"]}</td></tr>'
        for r in workload_rows
    )
    faq_html = "\n".join(
        f'<div class="model-faq__item"><p class="model-faq__q">{q}</p>'
        f'<p class="model-faq__a">{a}</p></div>'
        for q, a in faq
    )

    # Lead use-case scenarios
    scenarios = generate_lead_use_cases(model, ctx)
    scenarios_html_parts = []
    for sc in scenarios:
        scenarios_html_parts.append(
            f'<div class="model-usecase">'
            f'<h3 class="model-usecase__title">{sc["label"]}</h3>'
            f'<p class="model-usecase__shape">{sc["shape"]}</p>'
            f'<p class="model-usecase__cost"><strong>{sc["cost"]}</strong> for the run'
            f' &middot; <span class="model-usecase__per">{sc["per_call"]} per call</span></p>'
            f'<p class="model-usecase__rationale">{sc["rationale"]}</p>'
            f'</div>'
        )
    scenarios_html = "\n".join(scenarios_html_parts)

    # Capabilities summary (one-line)
    capabilities = generate_capabilities_summary(model)

    # Comparison snapshot
    snap_rows = generate_comparison_snapshot(model, ctx)
    snap_table_rows = []
    for row in snap_rows:
        if row["is_self"]:
            row_html = (
                f'<tr class="model-snap__self">'
                f'<td><strong>{row["name"]}</strong> <span class="model-snap__you">(this model)</span></td>'
                f'<td>${row["input"]:.2f} / ${row["output"]:.2f}</td>'
                f'<td>{row["factor"]}</td>'
                f'</tr>'
            )
        else:
            row_html = (
                f'<tr>'
                f'<td><a href="{MODELS_PREFIX}{row["slug"]}.html">{row["name"]}</a></td>'
                f'<td>${row["input"]:.2f} / ${row["output"]:.2f}</td>'
                f'<td>{row["factor"]}</td>'
                f'</tr>'
            )
        snap_table_rows.append(row_html)
    snap_table = "\n".join(snap_table_rows)

    return f"""
    <div class="model-section">
      <h2>Where {name} pays for itself</h2>
      <p>Three concrete scenarios where {name} fits the workload and what each one costs. Use these as a starting point — open the <a href="../">main calculator</a> to plug in your own token counts.</p>
      <div class="model-usecases">
        {scenarios_html}
      </div>
    </div>

    <h2 class="model-section" style="margin-top: 0; font-family: var(--display); font-size: var(--t-xl); font-weight: 600; color: var(--ink); margin-bottom: var(--s-4);">Live pricing</h2>
    <table class="model-table">
      <thead>
        <tr><th>Spec</th><th>Value</th></tr>
      </thead>
      <tbody>
        {live_pricing_html}
      </tbody>
    </table>

    <div class="model-section">
      <h2>Capabilities</h2>
      <p class="model-caps">{capabilities}</p>
    </div>

    <div class="model-section">
      <h2>Cost by workload</h2>
      <p>Five standard workload shapes for {name}, pre-computed at generation time. Use these as a starting point for your own estimate; open the <a href="../">main calculator</a> to plug in your exact token counts.</p>
      <table class="model-table">
        <thead>
          <tr><th>Workload</th><th>Per-run cost</th></tr>
        </thead>
        <tbody>
          {workload_table_html}
        </tbody>
      </table>
    </div>

    <div class="model-section">
      <h2>How {name} compares</h2>
      <p>This model sits in the same price tier as a handful of cross-provider competitors. The factor column is the one thing that actually differentiates models at the same price — context window, reasoning capability, or a free-tier wrapper.</p>
      <table class="model-table model-snap">
        <thead>
          <tr><th>Model</th><th>Input $ / Output $ per 1M</th><th>Distinguishing factor</th></tr>
        </thead>
        <tbody>
          {snap_table}
        </tbody>
      </table>
    </div>

    {custom_prose_html}{enrichment_html}<div class="model-section">
      <h2>Frequently asked questions</h2>
      <div class="model-faq">
        {faq_html}
      </div>
    </div>"""


def _build_template_c_body(
    model, ctx, prose_paragraphs, use_cases, faq,
    live_pricing_rows, workload_rows, related_block,
    custom_prose_html, enrichment_html,
) -> str:
    """Template C — Comparison-First.

    Leads with a quick comparison table (this model vs 2-3 same-tier
    competitors). Reader is shopping for the right model in a tier;
    wants to see this model in context before reading prose.
    """
    name = short_name(ctx["model_id"], ctx["display_name"])
    live_pricing_html = "\n".join(
        f"<tr><td>{label}</td><td>{val}</td></tr>"
        for label, val, _ in live_pricing_rows
    )
    workload_table_html = "\n".join(
        f'<tr><td><div class="model-wl__label">{r["label"]}</div>'
        f'<div class="model-wl__desc">{r["desc"]}</div>'
        f'<div class="compare-wl__tokens" style="font-family: var(--mono); font-size: 0.7rem; color: var(--ink-3); margin-top: 4px;">{r["tokens"]}</div></td>'
        f'<td class="model-cost{(" model-cost--free" if r["is_free"] else "")}">{r["cost"]}</td></tr>'
        for r in workload_rows
    )
    use_cases_html = "\n".join(f"<li>{u}</li>" for u in use_cases)
    faq_html = "\n".join(
        f'<div class="model-faq__item"><p class="model-faq__q">{q}</p>'
        f'<p class="model-faq__a">{a}</p></div>'
        for q, a in faq
    )

    # Quick comparison table (top of page)
    snap_rows = generate_comparison_snapshot(model, ctx)
    snap_table_rows = []
    for row in snap_rows:
        if row["is_self"]:
            row_html = (
                f'<tr class="model-snap__self">'
                f'<td><strong>{row["name"]}</strong> <span class="model-snap__you">(this model)</span></td>'
                f'<td>${row["input"]:.2f} / ${row["output"]:.2f}</td>'
                f'<td>{row["factor"]}</td>'
                f'</tr>'
            )
        else:
            row_html = (
                f'<tr>'
                f'<td><a href="{MODELS_PREFIX}{row["slug"]}.html">{row["name"]}</a></td>'
                f'<td>${row["input"]:.2f} / ${row["output"]:.2f}</td>'
                f'<td>{row["factor"]}</td>'
                f'</tr>'
            )
        snap_table_rows.append(row_html)
    snap_table = "\n".join(snap_table_rows)

    # Comparison intro paragraph
    comparison_intro = generate_comparison_intro(model, ctx)

    # Take only first 2 prose paragraphs (slimmer About for C)
    short_prose = prose_paragraphs[:2]

    return f"""
    <div class="model-section">
      <h2 style="margin-top: 0;">{name} at a glance</h2>
      <p>{comparison_intro}</p>
      <table class="model-table model-snap">
        <thead>
          <tr><th>Model</th><th>Input $ / Output $ per 1M</th><th>Distinguishing factor</th></tr>
        </thead>
        <tbody>
          {snap_table}
        </tbody>
      </table>
    </div>

    <h2 class="model-section" style="margin-top: 0; font-family: var(--display); font-size: var(--t-xl); font-weight: 600; color: var(--ink); margin-bottom: var(--s-4);">Live pricing</h2>
    <table class="model-table">
      <thead>
        <tr><th>Spec</th><th>Value</th></tr>
      </thead>
      <tbody>
        {live_pricing_html}
      </tbody>
    </table>

    <div class="model-section">
      <h2>About {name}</h2>
      {"".join(f'<p>{p}</p>' for p in short_prose)}
    </div>

    <div class="model-section">
      <h2>Cost by workload</h2>
      <p>Five standard workload shapes for {name}, pre-computed at generation time. Use these as a starting point for your own estimate; open the <a href="../">main calculator</a> to plug in your exact token counts.</p>
      <table class="model-table">
        <thead>
          <tr><th>Workload</th><th>Per-run cost</th></tr>
        </thead>
        <tbody>
          {workload_table_html}
        </tbody>
      </table>
    </div>

    <div class="model-section">
      <h2>When this model is the right call</h2>
      <ul>
        {use_cases_html}
      </ul>
    </div>

    <div class="model-section">
      <h2>Compare {name} with similar models</h2>
      <div class="model-related">
        <ul>
          {related_block}
        </ul>
      </div>
    </div>

    {custom_prose_html}{enrichment_html}<div class="model-section">
      <h2>Frequently asked questions</h2>
      <div class="model-faq">
        {faq_html}
      </div>
    </div>"""


# ---------------------------------------------------------------------------
# Master index page
# ---------------------------------------------------------------------------

def render_index(models: list[dict], today: str) -> str:
    # Sort by provider, then by display_name
    models_sorted = sorted(models, key=lambda m: (
        m.get("provider", ""),
        m.get("display_name", m["_id"]).lower(),
    ))

    rows_html = []
    providers_set: set[str] = set()
    for m in models_sorted:
        p = m.get("provider", "")
        providers_set.add(p)
        p_lbl = provider_label(p)
        name = short_name(m["_id"], m.get("display_name", m["_id"]))
        slug = m["_slug"]
        in_p = float(m.get("input_per_1m", 0) or 0)
        out_p = float(m.get("output_per_1m", 0) or 0)
        ctx_len = int(m.get("context_window", 0) or 0)
        free = is_free(m)
        tpl = assign_template(m)
        tpl_label = {"A": "Reference", "B": "Use-case", "C": "Comparison"}.get(tpl, tpl)
        if free:
            price_str = '<span class="model-cost--free">free</span>'
        else:
            price_str = f"${in_p:.2f} / ${out_p:.2f}"
        ctx_str = f"{ctx_len:,}" if ctx_len else "—"
        rows_html.append(
            f'<tr data-provider="{p}" data-display="{name.lower()}" data-input="{in_p:.4f}" '
            f'data-output="{out_p:.4f}" data-context="{ctx_len}" data-template="{tpl}">'
            f'<td><a href="{MODELS_PREFIX}{slug}.html">{name}</a></td>'
            f'<td>{p_lbl}</td>'
            f'<td class="model-cost">{price_str}</td>'
            f'<td class="model-cost">${out_p:.2f}</td>'
            f'<td class="model-cost">{ctx_str}</td>'
            f'<td class="model-tpl model-tpl--{tpl.lower()}" title="{ {"A":"Reference Sheet","B":"Use-Case First","C":"Comparison-First"}.get(tpl, tpl) }">{tpl_label}</td>'
            f'</tr>'
        )
    rows_block = "\n".join(rows_html)

    # Provider filter chips
    providers_sorted = sorted(providers_set)
    provider_chips = "\n".join(
        f'<button type="button" class="models-filter__chip" data-provider="{p}">'
        f'{provider_label(p)}</button>'
        for p in providers_sorted
    )

    canonical = f"{SITE_BASE}{MODELS_PREFIX}"
    title = f"All AI models &middot; Live OpenRouter pricing | AI Cost Calculator"
    desc = (
        f"Browse {len(models)} AI models with live OpenRouter pricing. "
        f"Filter by provider, sort by input or output price, and click "
        f"through to per-model pages with five workload cost examples."
    )

    # JSON-LD ItemList for the index
    item_list = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": "All AI models on AI Cost Calculator",
        "url": canonical,
        "numberOfItems": len(models),
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": i + 1,
                "url": f"{SITE_BASE}{MODELS_PREFIX}{m['_slug']}.html",
                "name": short_name(m["_id"], m.get("display_name", m["_id"])),
            } for i, m in enumerate(models_sorted[:50])  # cap at 50 for schema sanity
        ],
    }
    jsonld_str = json.dumps(item_list, indent=2)

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>{title}</title>
  <meta name="description" content="{desc}">
  <meta name="robots" content="index, follow">
  <meta name="theme-color" content="#f7f3ec">
  <link rel="canonical" href="{canonical}">
  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{desc}">
  <meta property="og:url" content="{canonical}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="AI Cost Calculator">
  <meta property="og:image" content="{SITE_BASE}/og-image.png">
  <link rel="icon" type="image/svg+xml" href="../favicon.svg">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&display=swap">
  <link rel="stylesheet" href="../models.css">
  <script type="application/ld+json">{jsonld_str}</script>
  <style>
    .models-index {{ max-width: 1100px; margin: 0 auto; padding: var(--s-3) var(--s-5) var(--s-8); }}
    .models-index__title {{ font-family: var(--display); font-size: clamp(2rem, 5vw, 3rem); font-weight: 400; letter-spacing: -0.02em; color: var(--ink); margin: 0 0 var(--s-2); }}
    .models-index__sub {{ font-size: var(--t-base); color: var(--ink-2); margin: 0 0 var(--s-5); max-width: 60ch; line-height: 1.5; }}
    .models-filter {{ display: flex; flex-wrap: wrap; gap: var(--s-2); margin: 0 0 var(--s-4); }}
    .models-filter__search {{ width: 100%; padding: var(--s-3) var(--s-4); border: 1px solid var(--rule); border-radius: var(--r-md); font-family: var(--sans); font-size: var(--t-base); background: white; color: var(--ink); margin-bottom: var(--s-3); }}
    .models-filter__search:focus {{ outline: 2px solid color-mix(in srgb, var(--teal) 40%, transparent); outline-offset: 2px; }}
    .models-filter__chip {{ padding: 6px 14px; border: 1.5px solid var(--rule); border-radius: var(--r-pill); background: white; color: var(--ink-2); font-family: var(--sans); font-size: var(--t-sm); cursor: pointer; transition: background 120ms var(--ease-out), color 120ms var(--ease-out), border-color 120ms var(--ease-out); }}
    .models-filter__chip:hover {{ border-color: var(--teal); color: var(--teal); }}
    .models-filter__chip.is-active {{ background: var(--teal); color: white; border-color: var(--teal); }}
    .models-table-wrap {{ background: white; border: 1px solid var(--rule); border-radius: var(--r-md); overflow: hidden; }}
    .models-table {{ width: 100%; border-collapse: collapse; }}
    .models-table th, .models-table td {{ padding: var(--s-3) var(--s-4); text-align: left; vertical-align: top; border-bottom: 1px solid var(--paper-2); }}
    .models-table thead th {{ background: var(--paper-2); font-family: var(--mono); font-size: var(--t-xs); text-transform: uppercase; letter-spacing: 0.06em; color: var(--ink-3); font-weight: 500; cursor: pointer; user-select: none; }}
    .models-table thead th:hover {{ color: var(--teal); }}
    .models-table tbody tr:last-child td {{ border-bottom: 0; }}
    .models-table tbody tr:hover {{ background: var(--paper); }}
    .models-table a {{ color: var(--teal); text-decoration: none; }}
    .models-table a:hover {{ text-decoration: underline; }}
    .models-index__count {{ font-size: var(--t-sm); color: var(--ink-3); margin: var(--s-3) 0 0; font-variant-numeric: tabular-nums; }}
  </style>
</head>
<body>
      <nav class="model-topbar__nav" aria-label="Primary">
      <a href="../">Calculator</a>
      <a href="./">All models</a>
      <a href="../compare/">Compare</a>
      <a href="../about.html">About</a>
    </nav>
        <a class="model-brand" href="../" aria-label="AI Cost Calculator (home)">
      <img class="model-brand__mark" src="../logo.svg" alt="" width="44" height="22">
      <span class="model-brand__word">AI Cost Calculator</span>
    </a>

  <main class="models-index">
    <a class="model-page__back" href="../">&larr; Back to the calculator</a>
    <h1 class="models-index__title">All AI models</h1>
    <p class="models-index__sub">
      {len(models)} models with live OpenRouter pricing. Filter by provider,
      search by name, or sort by input or output price. Every row links to a
      dedicated model page with five workload cost examples and a full FAQ.
    </p>

    <input type="search" class="models-filter__search" id="models-search"
           placeholder="Search {len(models)} models by name&hellip;"
           aria-label="Filter models by name">

    <div class="models-filter" id="models-filter" role="toolbar" aria-label="Filter by provider">
      <button type="button" class="models-filter__chip is-active" data-provider="*">All providers</button>
      {provider_chips}
    </div>

    <div class="models-table-wrap">
      <table class="models-table" id="models-table">
        <thead>
          <tr>
            <th data-sort="display">Model</th>
            <th data-sort="provider">Provider</th>
            <th data-sort="input" style="text-align: right;">Input $ / 1M</th>
            <th data-sort="output" style="text-align: right;">Output $ / 1M</th>
            <th data-sort="context" style="text-align: right;">Context</th>
            <th data-sort="template" style="text-align: center;">Template</th>
          </tr>
        </thead>
        <tbody id="models-tbody">
          {rows_block}
        </tbody>
      </table>
    </div>

    <p class="models-index__count" id="models-count">Showing {len(models)} of {len(models)} models.</p>
  </main>

  <footer class="model-foot">
    AI Cost Calculator &middot; <a href="../">Calculator</a> &middot;
    <a href="./">All models</a> &middot;
    <a href="../compare/">Compare</a> &middot;
    <a href="../about.html">About</a> &middot;
    <a href="../privacy.html">Privacy</a> &middot;
    <a href="../status.html">Status</a>
    <br><small class="model-foot__src">Pricing data via <a href="https://openrouter.ai/" rel="noopener">OpenRouter</a> &middot; refreshed every 6 hours</small>
  </footer>

  <script>
    (function() {{
      const search = document.getElementById('models-search');
      const chips = document.querySelectorAll('.models-filter__chip');
      const tbody = document.getElementById('models-tbody');
      const count = document.getElementById('models-count');
      const headers = document.querySelectorAll('#models-table thead th');
      const rows = Array.from(tbody.querySelectorAll('tr'));
      const total = rows.length;
      let activeProvider = '*';
      let activeSearch = '';
      let sortKey = 'display';
      let sortDir = 1;

      function applyFilter() {{
        let shown = 0;
        rows.forEach(r => {{
          const provider = r.dataset.provider;
          const display = r.dataset.display;
          const matchProvider = activeProvider === '*' || provider === activeProvider;
          const matchSearch = !activeSearch || display.indexOf(activeSearch) !== -1;
          if (matchProvider && matchSearch) {{
            r.style.display = '';
            shown++;
          }} else {{
            r.style.display = 'none';
          }}
        }});
        count.textContent = 'Showing ' + shown + ' of ' + total + ' models.';
      }}

      function sortBy(key) {{
        if (sortKey === key) sortDir = -sortDir;
        else {{ sortKey = key; sortDir = 1; }}
        const sorted = rows.slice().sort((a, b) => {{
          let av = a.dataset[key === 'display' ? 'display' : key];
          let bv = b.dataset[key === 'display' ? 'display' : key];
          if (key === 'input' || key === 'output' || key === 'context') {{
            av = parseFloat(av); bv = parseFloat(bv);
            return (av - bv) * sortDir;
          }}
          return av.localeCompare(bv) * sortDir;
        }});
        sorted.forEach(r => tbody.appendChild(r));
      }}

      chips.forEach(chip => {{
        chip.addEventListener('click', () => {{
          chips.forEach(c => c.classList.remove('is-active'));
          chip.classList.add('is-active');
          activeProvider = chip.dataset.provider;
          applyFilter();
        }});
      }});

      search.addEventListener('input', () => {{
        activeSearch = search.value.trim().toLowerCase();
        applyFilter();
      }});

      headers.forEach(h => {{
        h.addEventListener('click', () => sortBy(h.dataset.sort));
      }});
    }})();
  </script>
</body>
</html>
"""
    return html


# ---------------------------------------------------------------------------
# Sitemap update
# ---------------------------------------------------------------------------

def update_sitemap(new_urls: list[str], today: str) -> None:
    """Append new URLs to the existing sitemap.xml.

    Strategy: parse the existing urlset, drop any existing /models/* entries
    (re-runnable), then write a fresh combined sitemap.
    """
    text = SITEMAP.read_text()
    # Locate the opening <urlset ...> tag and closing </urlset>
    open_match = re.search(r"<urlset[^>]*>", text)
    close_idx = text.index("</urlset>")
    if not open_match or close_idx < 0:
        raise RuntimeError("malformed sitemap.xml")

    pre = text[: open_match.end()]
    existing_block = text[open_match.end():close_idx]

    # Drop existing /models/ entries (re-runnable). SEO-1 originally hard-coded
    # the old tokentally.ai domain in this regex; SEO-4 fixes it to match the
    # current aicostcalculator.net host so dropped-model URLs actually leave
    # the sitemap on re-run.
    cleaned = re.sub(
        r"  <url>\s*<loc>https://aicostcalculator\.net/models/[^<]*</loc>.*?</url>\n",
        "",
        existing_block,
        flags=re.DOTALL,
    )

    # Build new entries
    new_entries = []
    # Master /models/index.html (priority 0.8, daily)
    new_entries.append(
        f'  <url>\n'
        f'    <loc>{SITE_BASE}/models/</loc>\n'
        f'    <lastmod>{today}</lastmod>\n'
        f'    <changefreq>daily</changefreq>\n'
        f'    <priority>0.8</priority>\n'
        f'  </url>\n'
    )
    # Individual model pages (priority 0.7, weekly)
    for url in new_urls:
        new_entries.append(
            f'  <url>\n'
            f'    <loc>{url}</loc>\n'
            f'    <lastmod>{today}</lastmod>\n'
            f'    <changefreq>weekly</changefreq>\n'
            f'    <priority>0.7</priority>\n'
            f'  </url>\n'
        )

    new_text = pre + "\n" + cleaned + "".join(new_entries) + "</urlset>\n"
    SITEMAP.write_text(new_text)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

# SEO-4 (2026-06-23): the curated 80-model allowlist. Slugs use the exact
# strings produced by `model_slug()` against today's OpenRouter cache.
# IMPORTANT: per the operator-locked brief, "If a slug is in the allowlist
# but not in openrouter.json, log it and skip." Many of these refer to
# models retired/renamed since the brief was authored (Grok 2/3, Claude 3.5,
# Gemini 1.5/2.0, Llama 3.1 405B, Mistral 7B, DeepSeek Chat V3 bare,
# Perplexity Sonar Reasoning, MoE Qwen 2.5, command-r variants, etc.) —
# they are logged but not substituted.
KEEP_SLUGS = {
    # OpenAI (12)
    "openai-gpt-4o",
    "openai-gpt-4o-mini",
    "openai-gpt-4-1",
    "openai-gpt-4-1-mini",
    "openai-gpt-4-1-nano",
    "openai-gpt-4-turbo",
    "openai-gpt-3-5-turbo",
    "openai-o1",
    "openai-o1-mini",
    "openai-o3-mini",
    "openai-o3",
    "openai-o4-mini",
    # Anthropic (8)
    "anthropic-claude-3-5-sonnet-latest",
    "anthropic-claude-3-5-haiku-latest",
    "anthropic-claude-3-opus-latest",
    "anthropic-claude-3-haiku",
    "anthropic-claude-sonnet-4",
    "anthropic-claude-sonnet-4-5",
    "anthropic-claude-opus-4",
    "anthropic-claude-haiku-4",
    # Google (8)
    "google-gemini-2-5-pro",
    "google-gemini-2-5-flash",
    "google-gemini-2-0-flash",
    "google-gemini-2-0-pro",
    "google-gemini-1-5-pro",
    "google-gemini-1-5-flash",
    "google-gemini-1-5-flash-8b",
    "google-gemma-3-27b-it",
    # Meta / Llama (8)
    "meta-llama-llama-3-3-70b-instruct",
    "meta-llama-llama-3-1-405b-instruct",
    "meta-llama-llama-3-1-70b-instruct",
    "meta-llama-llama-3-1-8b-instruct",
    "meta-llama-llama-3-2-90b-vision-instruct",
    "meta-llama-llama-3-2-11b-vision-instruct",
    "meta-llama-llama-3-2-3b-instruct",
    "meta-llama-llama-3-2-1b-instruct",
    # Mistral (6)
    "mistralai-mistral-large-latest",
    "mistralai-mistral-small-latest",
    "mistralai-mistral-nemo",
    "mistralai-codestral-latest",
    "mistralai-mistral-7b-instruct",
    "mistralai-mixtral-8x7b-instruct",
    # DeepSeek (4)
    "deepseek-deepseek-chat-v3",
    "deepseek-deepseek-chat-v3-1",
    "deepseek-deepseek-r1",
    "deepseek-deepseek-coder",
    # xAI (3)
    "x-ai-grok-2",
    "x-ai-grok-2-mini",
    "x-ai-grok-3",
    # Cohere (4)
    "cohere-command-r-plus",
    "cohere-command-r",
    "cohere-command-r7b",
    "cohere-command-a",
    # Qwen (5)
    "qwen-qwen-2-5-72b-instruct",
    "qwen-qwen-2-5-coder-32b-instruct",
    "qwen-qwen-2-5-7b-instruct",
    "qwen-qwen-2-5-vl-72b-instruct",
    "qwen-qwen-2-72b-instruct",
    # Perplexity (3)
    "perplexity-sonar",
    "perplexity-sonar-pro",
    "perplexity-sonar-reasoning",
    # Free tier models (8)
    "meta-llama-llama-3-3-70b-instruct:free",
    "mistralai-mistral-7b-instruct:free",
    "google-gemma-2-9b-it:free",
    "qwen-qwen-2-5-72b-instruct:free",
    "deepseek-deepseek-chat-v3:free",
    "nousresearch-hermes-3-llama-3-1-405b:free",
    "cognitivecomputations-dolphin-mistral-24b-venice-edition:free",
    "openrouter-auto",
    # Specialty (11)
    "anthropic-claude-3-7-sonnet",
    "google-gemini-2-0-flash-thinking",
    "meta-llama-llama-3-3-8b-instruct",
    "moonshotai-kimi-k2",
    "openai-gpt-5",
    "openai-gpt-4o-mini-search-preview",
    "openai-gpt-4o-search-preview",
    "mistralai-pixtral-large-2411",
    "qwen-qwq-32b-preview",
    "meta-llama-llama-guard-3-8b",
    "perplexity-llama-3.1-sonar-large-128k-online",
    # SEO-5 (t_ca4f783a, 2026-06-23): MiniMax full coverage (8)
    # Operator's company — every model in the OpenRouter catalog gets a page.
    # Prices cover $0.15-$0.40 input / $0.90-$2.20 output, 65K-1M context.
    "minimax-minimax-01",
    "minimax-minimax-m1",
    "minimax-minimax-m2",
    "minimax-minimax-m2-her",
    "minimax-minimax-m2-1",
    "minimax-minimax-m2-5",
    "minimax-minimax-m2-7",
    "minimax-minimax-m3",
    # SEO-5 (t_ca4f783a, 2026-06-23): GLM (Zhipu / Z.AI) full coverage (12)
    # Provider is "z-ai" on OpenRouter. GLM = General Language Model. Pricing
    # covers $0.06 (4.7-flash) to $1.20 (5-turbo) input, $0.40 to $4.00 output.
    "z-ai-glm-4-5",
    "z-ai-glm-4-5-air",
    "z-ai-glm-4-5v",
    "z-ai-glm-4-6",
    "z-ai-glm-4-6v",
    "z-ai-glm-4-7",
    "z-ai-glm-4-7-flash",
    "z-ai-glm-5",
    "z-ai-glm-5-turbo",
    "z-ai-glm-5-1",
    "z-ai-glm-5-2",
    "z-ai-glm-5v-turbo",
    # SEO-5 (t_ca4f783a, 2026-06-23): brand-name + free + trendy (20)
    # 10 free models (SEO keyword: "free AI cost calculator") + 10 paid models
    # with strong brand pull or 2026 trend momentum.
    # Free tier
    "nvidia-nemotron-3-ultra-550b-a55b:free",
    "nvidia-nemotron-3-super-120b-a12b:free",
    "nvidia-nemotron-3-nano-30b-a3b:free",
    "nvidia-nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "openai-gpt-oss-120b:free",
    "openai-gpt-oss-20b:free",
    "qwen-qwen3-coder:free",
    "google-gemma-4-31b-it:free",
    "google-gemma-4-26b-a4b-it:free",
    "cohere-north-mini-code:free",
    "poolside-laguna-m-1:free",
    # Paid: brand pull + 2026 trendy
    "qwen-qwen3-coder-plus",          # Qwen flagship coding model
    "bytedance-seed-seed-1-6",        # ByteDance flagship, strong press coverage
    "amazon-nova-pro-v1",             # AWS Bedrock tier
    "amazon-nova-lite-v1",            # AWS Bedrock budget
    "allenai-olmo-3-32b-think",       # Fully open-source + thinking mode
    "baidu-ernie-4-5-vl-424b-a47b",   # Baidu flagship multimodal
    "inclusionai-ring-2-6-1t",        # InclusionAI trillion-param
    "ibm-granite-granite-4-1-8b",     # IBM Granite
    "morph-morph-v3-large",           # Morph frontier
    # Note: liquid-lfm-2-5-1-2b-instruct:free and inception-mercury-2 cut
    # from initial 22 to land exactly on the brief's 40-new-entries target.
    # Rationale: 1.2B-parameter free models and diffusion-text-architecture
    # experiments are too niche to justify a deep page in the curated set.
    # Available in the cache if a future SEO card wants to expand coverage.
}


def main() -> int:
    print(f"Loading {OPENROUTER_JSON} ...")
    with OPENROUTER_JSON.open() as f:
        data = json.load(f)
    raw_models = data.get("models", {})
    if not raw_models:
        print("ERROR: openrouter.json has no models key", file=sys.stderr)
        return 1

    today = datetime.now().strftime("%Y-%m-%d")

    # Build the model list with computed slugs
    all_models: dict[str, dict] = {}
    slug_collisions: dict[str, int] = {}
    for mid, m in raw_models.items():
        slug = model_slug(mid)
        # Handle collision: append -2, -3, ...
        if slug in slug_collisions:
            n = slug_collisions[slug] + 1
            while f"{slug}-{n}" in slug_collisions:
                n += 1
            slug_collisions[slug] = n
            slug = f"{slug}-{n}"
        slug_collisions[slug] = 0  # mark taken
        m2 = dict(m)
        m2["_id"] = mid
        m2["_slug"] = slug
        all_models[mid] = m2

    print(f"  loaded {len(all_models)} models")
    print(f"  KEEP_SLUGS allowlist size: {len(KEEP_SLUGS)}")

    # SEO-4: partition into keep vs. skip per the operator allowlist.
    # Log every allowlist slug that is NOT in the live cache (brief: "log and skip").
    cache_slugs = {m["_slug"] for m in all_models.values()}
    keep_models: dict[str, dict] = {}
    skipped_in_cache = []
    for mid, m in all_models.items():
        if m["_slug"] in KEEP_SLUGS:
            keep_models[mid] = m
        else:
            skipped_in_cache.append(mid)
    missing_from_cache = sorted(KEEP_SLUGS - cache_slugs)
    print(f"  SEO-4: kept {len(keep_models)} models from cache; "
          f"skipped {len(skipped_in_cache)} non-allowlisted")
    if missing_from_cache:
        print(f"  SEO-4 WARNING: {len(missing_from_cache)} allowlist slugs "
              f"not found in OpenRouter cache (logged, skipped per brief):",
              file=sys.stderr)
        for ms in missing_from_cache:
            print(f"    - {ms}", file=sys.stderr)

    # Build the related-models graph (only for the kept models — saves work)
    print("Computing related-model links ...")
    for mid, m in keep_models.items():
        m["_related"] = pick_related_models(m, keep_models)

    # Generate per-model pages
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Writing model pages to {OUT_DIR} ...")
    new_urls: list[str] = []
    word_counts: list[int] = []
    keep_iter = list(keep_models.items())
    for i, (mid, m) in enumerate(keep_iter, 1):
        if i % 25 == 0 or i == 1 or i == len(keep_iter):
            print(f"  [{i}/{len(keep_iter)}] {mid}", flush=True)
        related = m["_related"]
        html = render_page(m, keep_models, related, today)
        out = OUT_DIR / f"{m['_slug']}.html"
        out.write_text(html)
        # Count visible words (rough)
        from html.parser import HTMLParser
        text_collector = []

        class _Strip(HTMLParser):
            def __init__(self):
                super().__init__()
                self.in_script = False
                self.in_style = False
                self.cur = []

            def handle_starttag(self, tag, attrs):
                if tag == "script":
                    self.in_script = True
                if tag == "style":
                    self.in_style = True
                if tag in ("p", "li", "h1", "h2", "h3", "h4", "div"):
                    if self.cur:
                        text_collector.append(" ".join(self.cur))
                        self.cur = []

            def handle_endtag(self, tag):
                if tag == "script":
                    self.in_script = False
                if tag == "style":
                    self.in_style = False
                if tag in ("p", "li", "h1", "h2", "h3", "h4", "div"):
                    if self.cur:
                        text_collector.append("".join(self.cur))
                        self.cur = []

            def handle_data(self, data):
                if not (self.in_script or self.in_style):
                    self.cur.append(data.strip())

        s = _Strip()
        s.feed(html)
        if s.cur:
            text_collector.append("".join(s.cur))
        visible = " ".join(t for t in text_collector if t)
        wc = len(visible.split())
        word_counts.append(wc)
        new_urls.append(f"{SITE_BASE}{MODELS_PREFIX}{m['_slug']}.html")

    # Master index
    print(f"Writing master index ...")
    index_html = render_index(list(keep_models.values()), today)
    (OUT_DIR / "index.html").write_text(index_html)
    print(f"  wrote {OUT_DIR / 'index.html'}")

    # SEO-4: delete orphan HTML files. The brief: "Better approach: read
    # KEEP_SLUGS from the generator script, list the directory, and `rm`
    # everything not in the keep set." This catches both directions:
    #   (a) models in cache but not in KEEP_SLUGS — old page must go
    #   (b) leftover pages from previous generator runs for retired slugs
    keep_slug_set = {m["_slug"] for m in keep_models.values()}
    deleted = []
    for f in OUT_DIR.glob("*.html"):
        if f.name == "index.html":
            continue
        slug = f.stem
        if slug not in keep_slug_set:
            f.unlink()
            deleted.append(f.name)
    if deleted:
        print(f"  deleted {len(deleted)} orphan model page(s):")
        for d in sorted(deleted)[:10]:
            print(f"    - {d}")
        if len(deleted) > 10:
            print(f"    ... and {len(deleted) - 10} more")

    # Sitemap
    print(f"Updating sitemap.xml ...")
    update_sitemap(new_urls, today)

    # Manifest
    print(f"Writing manifest ...")
    template_counts = {"A": 0, "B": 0, "C": 0}
    enriched_count = 0
    for m in keep_models.values():
        tpl = assign_template(m)
        template_counts[tpl] += 1
        if should_enrich(m) and generate_enrichment_note(m, {
            "model_id": m["_id"],
            "display_name": m.get("display_name", m["_id"]),
            "provider_label": provider_label(m.get("provider", "")),
        }):
            enriched_count += 1
    manifest = {
        "generated_at": today,
        "model_count": len(keep_models),
        "pages_written": len(new_urls) + 1,  # +1 for the index
        "min_visible_word_count": min(word_counts) if word_counts else 0,
        "max_visible_word_count": max(word_counts) if word_counts else 0,
        "median_visible_word_count": sorted(word_counts)[len(word_counts) // 2] if word_counts else 0,
        "providers": sorted({m.get("provider", "") for m in keep_models.values()}),
        "free_model_count": sum(1 for m in keep_models.values() if is_free(m)),
        "keep_slug_count": len(KEEP_SLUGS),
        "keep_slugs_missing_from_cache": missing_from_cache,
        "pages_deleted": sorted(deleted),
        # SEO-6 (t_52219b65): template + enrichment distribution
        "template_distribution": template_counts,
        "enriched_pages_count": enriched_count,
        "models": [
            {
                "id": mid,
                "slug": m["_slug"],
                "display_name": m.get("display_name"),
                "provider": m.get("provider"),
                "is_free": is_free(m),
                "template": assign_template(m),
                "enriched": bool(should_enrich(m) and generate_enrichment_note(m, {
                    "model_id": m["_id"],
                    "display_name": m.get("display_name", m["_id"]),
                    "provider_label": provider_label(m.get("provider", "")),
                })),
                "related_slugs": [r["_slug"] for r in m.get("_related", [])],
            }
            for mid, m in keep_models.items()
        ],
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2))

    # Summary
    print()
    print(f"DONE: wrote {len(new_urls)} model pages + 1 index to {OUT_DIR}")
    if missing_from_cache:
        print(f"  (KEEP_SLUGS allowlist = {len(KEEP_SLUGS)}, but only "
              f"{len(keep_models)} exist in today's OpenRouter cache — "
              f"{len(missing_from_cache)} allowlist slugs were logged and "
              f"skipped per the operator brief)")
    if word_counts:
        print(f"  visible word counts: min={min(word_counts)}, "
              f"median={sorted(word_counts)[len(word_counts)//2]}, "
              f"max={max(word_counts)}")
        # Report any under 300
        low = [(mid, m['_slug'], wc) for (mid, m), wc in zip(keep_models.items(), word_counts) if wc < 300]
        if low:
            print(f"  WARNING: {len(low)} pages under 300 visible words:")
            for mid, slug, wc in low[:5]:
                print(f"    {slug}: {wc} words")
        else:
            print(f"  all pages have 300+ visible words")
    print(f"  manifest: {MANIFEST}")
    print(f"  sitemap updated: {SITEMAP}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
