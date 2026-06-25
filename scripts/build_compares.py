#!/usr/bin/env python3
"""
Comparison page generator for AI Cost Calculator.

Reads live pricing data from the backend, calls /calculate/compare for
each popular model pair at several workload sizes, and emits one static
HTML page per pair to /frontend/compare/{slug}.html.

Run from project root:  .venv/bin/python scripts/build_compares.py
Re-run any time pricing changes (the data is live, not cached).
"""
from __future__ import annotations
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

API = os.environ.get("API", "http://10.10.10.205:8001")
OUT_DIR = Path("/home/vboxuser/vaults/star-command/Projects/token-calculator/frontend/compare")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# (model_a_id, model_b_id) pairs — the most-searched comparisons
# for LLM pricing. Add more as needed; the script handles any pair.
PAIRS = [
    ("openai/gpt-4o", "anthropic/claude-sonnet-4"),
    ("openai/gpt-4o", "openai/gpt-4o-mini"),
    ("openai/gpt-4o", "openrouter/meta-llama/llama-3.3-70b-instruct"),
    ("openai/gpt-4o-mini", "anthropic/claude-haiku-4"),
    ("anthropic/claude-sonnet-4", "google/gemini-2.5-pro"),
    ("openai/gpt-4o", "deepseek/deepseek-chat"),
    ("anthropic/claude-opus-4", "openai/gpt-4o"),
    ("openai/gpt-4o", "google/gemini-2.5-pro"),
    ("anthropic/claude-sonnet-4", "anthropic/claude-haiku-4"),
    ("openai/gpt-4o", "openrouter/x-ai/grok-4.20"),
    ("openai/o3", "anthropic/claude-sonnet-4"),
    ("openai/gpt-4o", "openrouter/mistralai/mistral-large"),
]

# Workload profiles (input tokens, output tokens, label, description)
WORKLOADS = [
    (5_000, 2_000, "Small chat",
     "A typical conversational turn: short prompt, medium response."),
    (50_000, 20_000, "Medium agent",
     "An agent loop with retrieval and tool use: bigger prompt, multi-step response."),
    (500_000, 200_000, "Large batch",
     "A document analysis or batch job: long context, long-form output."),
    (1_000_000, 500_000, "Heavy workload",
     "Whole-codebase review or a long document rewrite: max context, max output."),
]


def fetch_compare(model_ids, input_tokens, output_tokens):
    body = json.dumps({
        "model_ids": list(model_ids),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "num_runs": 1,
        "task_type": "chat",
    }).encode()
    req = urllib.request.Request(
        f"{API}/calculate/compare",
        method="POST",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read()).get("results", [])


def short_name(model_id):
    """Turn 'openai/gpt-4o' into 'GPT-4o', 'anthropic/claude-sonnet-4' into 'Claude Sonnet 4'."""
    bare = model_id.split("/")[-1]
    for prefix in ("openai/", "anthropic/", "google/", "meta-llama/", "mistralai/", "x-ai/", "deepseek/"):
        if model_id.startswith(prefix):
            bare = model_id[len(prefix):]
    vendor_map = {
        "gpt-": "GPT-", "claude-": "Claude ", "gemini-": "Gemini ",
        "llama-": "Llama ", "mistral-": "Mistral ", "grok-": "Grok ",
        "deepseek-": "DeepSeek ", "o1": "o1", "o3": "o3", "o4": "o4",
    }
    for v, disp in vendor_map.items():
        if bare.startswith(v):
            tail = bare[len(v):]
            return disp + tail.replace("-", " ").strip()
    return bare.replace("-", " ").title()


def slugify(model_id):
    return model_id.replace("/", "-").lower()


def page_slug(a, b):
    return f"{slugify(a)}-vs-{slugify(b)}"


def fmt_money(n):
    if n is None or not isinstance(n, (int, float)):
        return "—"
    if n == 0:
        return "free"
    if n < 0.0001:
        return f"${n:.6f}"
    if n < 1:
        return f"${n:.4f}"
    return f"${n:.2f}"


def fmt_int(n):
    return f"{int(n):,}"


def render_pair(a, b):
    name_a, name_b = short_name(a), short_name(b)
    slug = page_slug(a, b)
    title = f"{name_a} vs {name_b}: API Cost Comparison (2026) | AI Cost Calculator"
    description = (
        f"Compare {name_a} and {name_b} API costs side-by-side. "
        f"Live pricing per million tokens, four workload sizes, "
        f"no signup, refreshed every 6 hours."
    )
    canonical = f"https://aicostcalculator.net/compare/{slug}.html"

    # Fetch all workload results
    rows = []  # list of (workload_label, workload_desc, a_result, b_result, ca, cb)
    skipped = []
    for inp, outp, label, desc in WORKLOADS:
        try:
            results = fetch_compare((a, b), inp, outp)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                skipped.append((label, a, b))
                continue
            raise
        by_id = {r["model_id"]: r for r in results}
        ra = by_id.get(a)
        rb = by_id.get(b)
        if not ra or not rb:
            skipped.append((label, a, b))
            continue
        ca, cb = ra["total_cost"], rb["total_cost"]
        rows.append((label, desc, inp, outp, ra, rb, ca, cb))

    if not rows:
        return None, skipped

    # Verdict
    cheapest_at_small = min(rows, key=lambda r: r[6] if r[0] == "Small chat" else float("inf"))
    cheapest_at_large = min(rows, key=lambda r: r[6] if r[0] == "Heavy workload" else float("inf"))
    if cheapest_at_small[5]["model_id"] == cheapest_at_large[5]["model_id"]:
        winner_name = cheapest_at_small[5]["display_name"]
        verdict = (
            f"<strong>{winner_name}</strong> wins across every workload size we tested. "
            f"It's the cheaper option for both quick chat turns and heavy document jobs."
        )
    else:
        small_winner = cheapest_at_small[5]["display_name"]
        large_winner = cheapest_at_large[5]["display_name"]
        verdict = (
            f"For <strong>short tasks</strong> (chat, single-turn), <strong>{small_winner}</strong> is cheaper. "
            f"For <strong>heavy workloads</strong> (long context, batch jobs), <strong>{large_winner}</strong> wins. "
            f"Pick by your typical workload size."
        )

    # JSON-LD
    jsonld = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": title,
        "description": description,
        "url": canonical,
        "datePublished": "2026-06-23",
        "dateModified": datetime.now().strftime("%Y-%m-%d"),
        "author": {"@type": "Organization", "name": "AI Cost Calculator"},
        "publisher": {"@type": "Organization", "name": "AI Cost Calculator"},
    }

    # Render workload rows
    rows_html = ""
    for label, desc, inp, outp, ra, rb, ca, cb in rows:
        a_wins = ca < cb
        rows_html += (
            f"<tr>"
            f"<td><div class='compare-wl__label'>{label}</div>"
            f"<div class='compare-wl__desc'>{desc}</div>"
            f"<div class='compare-wl__tokens'>{fmt_int(inp)} in + {fmt_int(outp)} out</div></td>"
            f"<td class='{'compare-cell--winner' if a_wins else ''}'>"
            f"<div class='compare-name'>{ra['display_name']}</div>"
            f"<div class='compare-cost'>{fmt_money(ca)}</div>"
            f"<div class='compare-breakdown'>in {fmt_money(ra['input_cost'])} &middot; out {fmt_money(ra['output_cost'])}</div></td>"
            f"<td class='{'compare-cell--winner' if not a_wins else ''}'>"
            f"<div class='compare-name'>{rb['display_name']}</div>"
            f"<div class='compare-cost'>{fmt_money(cb)}</div>"
            f"<div class='compare-breakdown'>in {fmt_money(rb['input_cost'])} &middot; out {fmt_money(rb['output_cost'])}</div></td>"
            f"</tr>"
        )

    # Spec rows: compute per-1M from the actual cost data we already have
    # (compare returns per-request $cost, not the model catalog's per-1M
    # rate, so we derive: $cost / tokens * 1_000_000). For context window
    # we use the first row's data; if the catalog entry is missing the
    # field we just say "—".
    ra0, rb0 = rows[0][4], rows[0][5]
    inp0, outp0 = rows[0][2], rows[0][3]
    a_in_per_m = (ra0["input_cost"] / inp0) * 1_000_000 if inp0 > 0 else None
    a_out_per_m = (ra0["output_cost"] / outp0) * 1_000_000 if outp0 > 0 else None
    b_in_per_m = (rb0["input_cost"] / inp0) * 1_000_000 if inp0 > 0 else None
    b_out_per_m = (rb0["output_cost"] / outp0) * 1_000_000 if outp0 > 0 else None
    spec_rows = ""
    for lbl, av, bv in [
        ("Input price",  fmt_money(a_in_per_m),  fmt_money(b_in_per_m)),
        ("Output price", fmt_money(a_out_per_m), fmt_money(b_out_per_m)),
        ("Context window", ra0.get("context_window") or "—", rb0.get("context_window") or "—"),
        ("Reasoning tokens", "Yes" if ra0.get("supports_reasoning") else "No", "Yes" if rb0.get("supports_reasoning") else "No"),
    ]:
        # Context window needs formatting if it's a number
        if lbl == "Context window":
            av = f"{int(av):,} tokens" if isinstance(av, (int, float)) and av else av
            bv = f"{int(bv):,} tokens" if isinstance(bv, (int, float)) and bv else bv
        spec_rows += (
            f"<tr><td>{lbl}</td><td>{av}</td><td>{bv}</td></tr>"
        )

    # Updated timestamp
    updated = datetime.now().strftime("%B %d, %Y at %H:%M UTC")

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>{title}</title>
  <meta name="description" content="{description}">
  <meta name="keywords" content="{name_a}, {name_b}, {name_a} vs {name_b}, {name_a} pricing, {name_b} pricing, LLM cost comparison, API cost calculator, OpenRouter pricing">
  <meta name="robots" content="index, follow">
  <meta name="theme-color" content="#f7f3ec">
  <link rel="canonical" href="{canonical}">
  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{description}">
  <meta property="og:url" content="{canonical}">
  <meta property="og:type" content="article">
  <meta property="og:site_name" content="AI Cost Calculator">
  <meta property="og:image" content="https://aicostcalculator.net/og-image.png">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{title}">
  <meta name="twitter:description" content="{description}">
  <link rel="icon" type="image/svg+xml" href="../favicon.svg">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&display=swap">
  <link rel="stylesheet" href="../app.css">
  <script type="application/ld+json">{json.dumps(jsonld)}</script>
  <style>
    .compare-page {{ max-width: 880px; margin: 0 auto; padding: var(--s-4) var(--s-5) var(--s-8); }}
    .compare-page__back {{ display: inline-block; font-size: var(--t-sm); color: var(--ink-2); text-decoration: none; margin-bottom: var(--s-5); }}
    .compare-page__back:hover {{ color: var(--teal); }}
    .compare-page__title {{ font-family: var(--display); font-size: clamp(2rem, 5vw, 3rem); font-weight: 400; letter-spacing: -0.02em; color: var(--ink); margin: 0 0 var(--s-2); line-height: 1.1; }}
    .compare-page__sub {{ font-size: var(--t-base); color: var(--ink-2); margin: 0 0 var(--s-6); line-height: 1.5; max-width: 60ch; }}
    .compare-page__updated {{ font-size: var(--t-xs); color: var(--ink-3); margin: 0 0 var(--s-7); font-variant-numeric: tabular-nums; }}
    .compare-page__updated strong {{ color: var(--ok); }}
    .compare-verdict {{ background: var(--teal-soft); border: 1px solid color-mix(in srgb, var(--teal) 30%, transparent); border-radius: var(--r-md); padding: var(--s-4) var(--s-5); margin: 0 0 var(--s-6); font-size: var(--t-base); line-height: 1.5; color: var(--teal-ink); }}
    .compare-verdict strong {{ color: var(--teal-deep); font-weight: 600; }}
    .compare-table {{ width: 100%; border-collapse: collapse; background: white; border: 1px solid var(--rule); border-radius: var(--r-md); overflow: hidden; margin: 0 0 var(--s-6); }}
    .compare-table th, .compare-table td {{ padding: var(--s-4); text-align: left; vertical-align: top; border-bottom: 1px solid var(--paper-2); }}
    .compare-table thead th {{ background: var(--paper-2); font-family: var(--mono); font-size: var(--t-xs); text-transform: uppercase; letter-spacing: 0.06em; color: var(--ink-3); font-weight: 500; }}
    .compare-table tr:last-child td {{ border-bottom: 0; }}
    .compare-wl__label {{ font-family: var(--sans); font-size: var(--t-sm); font-weight: 600; color: var(--ink); }}
    .compare-wl__desc {{ font-size: var(--t-xs); color: var(--ink-3); margin-top: 2px; }}
    .compare-wl__tokens {{ font-family: var(--mono); font-size: 0.7rem; color: var(--ink-3); margin-top: 4px; font-variant-numeric: tabular-nums; }}
    .compare-cell--winner {{ background: color-mix(in srgb, var(--ok) 8%, transparent); }}
    .compare-cell--winner .compare-cost {{ color: var(--ok); font-weight: 700; }}
    .compare-name {{ font-family: var(--sans); font-size: var(--t-sm); font-weight: 500; color: var(--ink); margin-bottom: 4px; }}
    .compare-cost {{ font-family: var(--display); font-size: var(--t-2xl); font-weight: 600; color: var(--ink); font-variant-numeric: tabular-nums; line-height: 1.1; }}
    .compare-breakdown {{ font-family: var(--mono); font-size: 0.7rem; color: var(--ink-3); margin-top: 4px; font-variant-numeric: tabular-nums; }}
    .compare-section {{ margin-top: var(--s-7); }}
    .compare-section h2 {{ font-family: var(--display); font-size: var(--t-xl); font-weight: 600; color: var(--ink); margin: 0 0 var(--s-4); }}
    .compare-section p {{ font-size: var(--t-base); line-height: 1.65; color: var(--ink-2); margin: 0 0 var(--s-3); max-width: 60ch; }}
    .compare-section a {{ color: var(--teal); text-decoration: underline; text-decoration-color: color-mix(in srgb, var(--teal) 40%, transparent); text-underline-offset: 3px; }}
    .compare-section a:hover {{ color: var(--teal-deep); }}
    .compare-related {{ background: var(--paper-2); border: 1px solid var(--rule); border-radius: var(--r-md); padding: var(--s-4) var(--s-5); }}
    .compare-related h2 {{ font-family: var(--display); font-size: var(--t-lg); margin: 0 0 var(--s-3); color: var(--ink); }}
    .compare-related ul {{ list-style: none; padding: 0; margin: 0; }}
    .compare-related li {{ padding: var(--s-2) 0; border-bottom: 1px solid var(--rule); font-size: var(--t-sm); }}
    .compare-related li:last-child {{ border-bottom: 0; }}
    .compare-related a {{ color: var(--teal); text-decoration: none; }}
    .compare-related a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <header class="topbar" role="banner">
    <a class="brand" href="../" aria-label="AI Cost Calculator (home)">
      <img class="brand__mark" src="../logo.svg" alt="" width="44" height="22">
      <span class="brand__word">AI Cost Calculator</span>
    </a>
    <nav class="topbar__nav" aria-label="Primary">
      <a href="../">Calculator</a>
      <a href="../models/">All models</a>
      <a href="./">Compare</a>
      <a href="../about.html">About</a>
    </nav>
  </header>

  <main class="compare-page">
    <a class="compare-page__back" href="../">&larr; Back to the calculator</a>
    <h1 class="compare-page__title">{name_a} vs {name_b}: which is cheaper?</h1>
    <p class="compare-page__sub">
      Side-by-side API cost for {name_a} and {name_b} across four
      realistic workload sizes. Prices are live from
      <a href="https://openrouter.ai" rel="noopener">OpenRouter</a>
      and refreshed every 6 hours.
    </p>
    <p class="compare-page__updated">
      <strong>&bull;</strong> Prices verified {updated} &middot;
      <a href="../">open the calculator</a> to plug in your own workload.
    </p>

    <div class="compare-verdict">{verdict}</div>

    <table class="compare-table">
      <thead>
        <tr>
          <th>Workload</th>
          <th>{name_a}</th>
          <th>{name_b}</th>
        </tr>
      </thead>
      <tbody>
        {rows_html}
      </tbody>
    </table>

    <div class="compare-section">
      <h2>Pricing per million tokens</h2>
      <table class="compare-table">
        <thead>
          <tr>
            <th></th>
            <th>{name_a}</th>
            <th>{name_b}</th>
          </tr>
        </thead>
        <tbody>
          {spec_rows}
        </tbody>
      </table>
    </div>

    <div class="compare-section">
      <h2>How to read this comparison</h2>
      <p>
        The numbers above are the per-call cost of running the same
        workload &mdash; same input token count, same output token count &mdash;
        against each model. We don't add per-request fees, batch
        discounts, or commitment pricing; the table is the headline
        on-demand rate from OpenRouter's feed. If your workload uses
        cached inputs or reasoning tokens, both are priced
        separately in the
        <a href="../">main calculator</a> (open the Advanced panel).
      </p>
      <p>
        <strong>When to use {name_a}:</strong> depends on the workload
        size and your priorities. Pick by the workload that matches
        your use case in the table above.
      </p>
      <p>
        <strong>When to use {name_b}:</strong> same answer &mdash; the
        verdict block at the top of this page gives the one-line
        summary.
      </p>
    </div>

    <div class="compare-section">
      <h2>More comparisons</h2>
      <div class="compare-related">
        <ul>
          <li><a href="./openai-gpt-4o-vs-anthropic-claude-sonnet-4.html">GPT-4o vs Claude Sonnet 4</a> &mdash; the most-asked pair in 2026</li>
          <li><a href="./openai-gpt-4o-mini-vs-anthropic-claude-haiku-4.html">GPT-4o mini vs Claude Haiku 4.5</a> &mdash; cheap tier head-to-head</li>
          <li><a href="./openai-gpt-4o-vs-openrouter-meta-llama-llama-3.3-70b-instruct.html">GPT-4o vs Llama 3.3 70B</a> &mdash; closed vs open-weights</li>
          <li><a href="../">Open the full calculator</a> &mdash; compare 2-5 models side-by-side, any combination</li>
        </ul>
      </div>
    </div>
  </main>

  <footer class="foot">
    <p>
      AI Cost Calculator &middot; <a href="../">Calculator</a> &middot; <a href="../about.html">About</a> &middot; <a href="../privacy.html">Privacy</a> &middot; <a href="../status.html">Status</a>
    </p>
  </footer>
</body>
</html>
"""
    return html, []


def main():
    print(f"API: {API}")
    print(f"OUT: {OUT_DIR}")
    print(f"PAIRS: {len(PAIRS)}")
    written = []
    skipped = []
    for a, b in PAIRS:
        print(f"  building {short_name(a)} vs {short_name(b)} ...", end=" ", flush=True)
        try:
            html, _ = render_pair(a, b)
        except Exception as e:
            print(f"ERROR: {e}")
            skipped.append((a, b, str(e)))
            continue
        if not html:
            print("NO DATA (404 from backend)")
            skipped.append((a, b, "no data"))
            continue
        out = OUT_DIR / f"{page_slug(a, b)}.html"
        out.write_text(html)
        written.append(out)
        print(f"OK ({len(html)//1024}kb)")
    print(f"\nwrote {len(written)} files to {OUT_DIR}")
    if skipped:
        print(f"skipped: {skipped}")


if __name__ == "__main__":
    main()
