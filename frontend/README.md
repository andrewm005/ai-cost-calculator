# AI Cost Calculator — Frontend (v2.7b)

A single-page static site that wraps the [Token Cost Calculator](../README.md)
FastAPI backend. **No build step, no dependencies, no framework.** Six files
plus two SVG assets:

```
frontend/
├── index.html           one-page UI (hero + ad slot + 2-tier picker + result)
├── app.css              all styles (paper / ink / deep-teal palette, DM Serif Display type)
├── app.js               vanilla ES module — fetches /, /models, /local/* + projects.json + popular_models.json
├── logo.svg             infinity loop made of token dots — see "Logo" below
├── favicon.svg          same metaphor, optimized for 16–32px
├── projects.json        project preset data (token averages per use case)
├── popular_models.json  popular-row seed list (one entry per big company)
└── README.md            this file
```

## What's new in v2 (over v1)

1. **Two-tier model picker.**
   - **Row 1 — Popular.** A row of 8 large click-targets, one per big company
     (OpenAI, Anthropic, Google, Meta, DeepSeek, Mistral, xAI, Cohere). Each
     card shows the company monogram, the flagship model display name, and
     the input/output price chip. One click selects that company's default.
   - **Row 2 — All models.** A searchable combobox (type-ahead on
     display_name + provider + model_id). Shows all 349 models. Native
     `<select>` couldn't do filter-on-type for 349 items.
2. **Project presets.** A dropdown of 15 real-world project token-cost
   profiles from `findings.md §6` (LangChain Agent, AutoGen, RAG, code review,
   Claude Code, Cursor, Perplexity, v0, SWE-agent, fine-tuning, embeddings,
   summarization, multi-turn chat, plus Custom and Code Review PR-sized). Each
   preset auto-fills the input/output token fields. PLACEHOLDER entries show
   a yellow hint with the source. Citations are in `projects.json`.
3. **Thinking level.** Replaces v1's "Reasoning level". New default is **off**
   (no extra cost). Levels: off / low (1.0×) / medium (1.2×) / high (1.5×) /
   extreme (2.5×). When the selected model doesn't expose reasoning pricing
   (`supports_reasoning: false`), non-Off options are visually de-emphasized
   and the dropdown is forced back to "off".
4. **Ad slot placeholders.** Two `<aside>` elements (`#ad-slot-top` 728×90
   leaderboard below the hero; `#ad-slot-side` 300×250 medium rectangle
   sidebar on desktop, in-flow on mobile). These are intentionally
   placeholder-only — no ad network is wired up; the operator injects the
   network's snippet later. The slots have a subtle diagonal-stripe pattern
   + "Advertisement" label so they're visible but don't compete with the
   calculator.
5. **Stepped form.** Each main picker has a small numeric step badge (1–4) so
   the user reads the workflow as: pick model → pick project → pick size →
   pick thinking → calculate.

Everything Andrew liked in v1 is preserved: the infinity-loop logo, the
"AI Cost Calculator" wordmark, the warm paper / warm ink palette, the DM Serif
Display headline serif, the focal-point result amount, the meta strip with
model count + refresh cadence, and the "Estimate: verify against vendor
pricing before quoting." caveat on every result. The accent was a softer
terra cotta (`#d97757`) through v2.3; v2.4 swaps it for a deep teal
(`#0c4a52`) — operator noted the coral "looks like Claude's", asked for
something distinct.

## What's new in v2.1 (over v2)

v2.1 is a polish iteration on top of v2, addressing operator feedback
("more horizontalness / no scroll to Calculate, more obvious All models
label, more obvious selected model, less aggressive coral, more substantive
hero subtext"). Five changes, all in this folder:

1. **Calculate is above the fold on 1366×768 laptops.** The hero is slimmer
   (logo 168×84 instead of 240×120, headline clamp max 2.5rem instead of 3rem).
   The popular row is now a single horizontal-scroll strip (8 cards × 132px
   wide × 86px tall) instead of a 4×2 grid. Project / Task size / Thinking
   sit side-by-side as a 3-column grid row (1.4fr / 1fr / 1fr, stacks at
   ≤720px). `.calc` padding tightened. The top ad slot (728×90 leaderboard)
   moved from above-the-hero to below the result panel.
2. **"All models" label reads as a section heading now.** New
   `.picker__row-label--primary` modifier: Fraunces semibold, 18px,
   no uppercase, ink-1. The small mono `349 models` meta stays on the right.
3. **Selected model is prominent.** New `.selection-bar` block inside `.calc`
   above the form: `SELECTED · {display_name} · {provider} · $X / $Y per 1M`,
   on a soft coral background. Always visible; updates live on selection
   changes.
4. **Coral is terra cotta now.** `--coral` `#ff5b3e` → `#d97757`,
   `--coral-deep` `#e83f20` → `#b25b3e`, `--coral-soft` `#ffe4dc` → `#f3dccd`.
   Still pops as the accent; no longer dominates the page.
5. **Hero subtext is substantive.** Replaced "Pick a company, pick a
   project, get a number." with `**Live OpenRouter prices** across 336
   models, **hand-curated** for 13 hosted APIs. Refreshed every 6 hours.
   Free, no signup.` Same text in the `<meta name="description">`.

**Bonus bug fix (not requested, caught during iteration):** v2's
`thinkingSelect.value === 'off'` sent `reasoning_level: "off"` to the
backend; the Pydantic enum only accepts `low/medium/high/extreme`, so
Calculate returned HTTP 422 every time the dropdown was on its default.
v2.1 omits `reasoning_level` entirely when "off" is selected; backend
default applies no reasoning multiplier (same numeric result).

## What's new in v2.2 (over v2.1)

v2.2 is a focused polish iteration on the popular company row, addressing
operator feedback: "popular models extend past the container, I don't
want specific models pinned, make the color related to the logo, and
make clicking them open another dropdown with that company's models".
Four changes:

1. **Popular row is a single horizontal row that fits the container.**
   The page container (`--col-wide`) is bumped from 880px to 1200px and
   the popular row uses a `position: relative; left: 50%;
   transform: translateX(-50%)` breakout so it extends to 1200px while
   staying centered in the viewport. The form (`.calc`) is capped at
   880px and stays compact. No more horizontal scroll, no wrapping.
2. **Cards represent companies, not pinned models.** Each card in
   `popular_models.json` now declares `provider` + `provider_label` +
   `icon` + `brand_color` + `brand_soft` + `default_model` (instead of
   pinning to a single `model_id`). The card body shows the company
   name, the count of that company's live models, and the input/output
   price range (e.g. "12 models · $0.00 – $0.60 / 1M"). Default first-
   load selection still uses each company's `default_model` (the
   flagship). Provider strings in `popular_models.json` now match
   `/models` exactly: `openai`, `anthropic`, `google`, `meta-llama`,
   `deepseek`, `mistralai`, `x-ai`, `cohere` (the previous v2.1 list
   used `meta` and `xai`, which didn't match any model).
3. **Brand color per card.** Each card has a per-card `--pop-brand`
   CSS variable set inline from `brand_color`. The brand color shows
   up as: (a) a 3px top accent strip on the card, (b) the filled
   abstract shape icon (filled instead of stroked for visibility), and
   (c) the selected/open border + soft brand-color background. Palette:
   OpenAI `#0d0d0d`, Anthropic `#c75a3f`, Google `#4285F4`, Meta
   `#0866E1`, DeepSeek `#0F4C81`, Mistral `#FF7000`, xAI `#2d2d2d`,
   Cohere `#FF0034`. Each company also gets a soft `brand_soft` tint
   (`#ecebe8`, `#f4dccf`, `#dde6fa`, etc.) for the selected state.
4. **Click a card → popover with that company's models.** A click on a
   company card no longer selects a specific model. Instead, a floating
   popover appears anchored to the card (auto-flips up if there's no
   room below, auto-clamps to viewport edges) listing all of that
   company's models with prices and a ✦ mark for reasoning-capable
   models. The popover is a WAI-ARIA dialog with keyboard nav
   (↑/↓/Home/End/Enter/Escape) and a listbox. Picking a model in the
   popover selects it (same path as the searchable combobox). The
   popover caps at 60 visible rows with a "Showing 60 of 65 — use All
   models for the full list" footer for the 4 OpenRouter providers
   with >60 models (only OpenAI today at 65). Closes on outside
   click, Escape, scroll, or resize.

**Cross-row sync:** the popular card and the searchable combobox stay
in sync via shared state. Selecting a model from either highlights the
matching entry in the other; the .selection-bar at the top of the
calculator always reflects the current pick.

## What's new in v2.3 (over v2.2)

v2.3 is a small fix-up iteration addressing two specific complaints from
operator feedback on v2.2:

1. **"The popular models extended past the container; for a moment you had
   it fixed and the top companies collapsed into the container, but that
   broke."** v2.2's `position: relative; left: 50%; transform: translateX(-50%)`
   escaped the 880px `.calc` to span 1200px of viewport. v2.3 contains the
   popular row inside the `.calc` again, as a horizontal-scroll strip —
   8 cards × 135px + 7 × 10px gaps = 1150px of content inside the
   ~832px content area. The user scrolls horizontally to see off-screen
   cards. A subtle mask-fade on the right edge hints that more cards
   scroll into view. Implementation note: the column-flex chain
   `.picker → .picker__row → .popular` all need `min-width: 0`, and
   `.pop` cards need `flex-shrink: 0` — without these, the flex containers
   expand to fit content and the cards squish to fit the visible area
   instead of scrolling.

2. **"I can not scroll through the different models in the company
   dropdowns, it just immediately closes it."** v2.2's `window.addEventListener('scroll', () => closeProviderPopover(), true)`
   was a capture-phase listener that closed the popover on ANY scroll,
   including scrolls inside the popover's own `.popover__list` (which
   is `overflow-y: auto`). The first wheel-tick on the list closed the
   popover before the user could read below the fold. v2.3 adds a
   containment guard: `onPageScrollClosePopover` checks
   `popover.contains(e.target)` and `openCard.contains(e.target)` and
   ignores scrolls that originate inside the popover or the anchor card.
   External page scroll still closes the popover (intended behavior).

The rest of the page (selection bar, all-models combobox, project
dropdown, task size, thinking, result panel, blurb) is unchanged from v2.2.

## What's new in v2.4 (over v2.3)

v2.4 is the third operator-iteration on the popular row, addressing the
remaining round of feedback (font + color + above-the-fold Calculate).
Three changes, all on the surface:

1. **Font swap: Fraunces → DM Serif Display.** Andrew said the hero
   "feels a little bit off" and asked for a new font. DM Serif Display
   (Google Fonts) is a high-contrast Didone serif — heavier strokes,
   editorial / Vogue-class feel. Single weight (400) + italic (400) on
   Google Fonts; we don't need weight variants because the result number
   already gets its emphasis from size + letter-spacing, not weight.
   The `font-variation-settings: 'opsz' X` lines that Fraunces needed are
   removed (DM Serif Display has no opsz axis).
2. **Accent swap: coral/terra-cotta → deep teal (#0c4a52).** Andrew said
   the softened coral "literally is the one that claude uses". Replaced
   `--coral` / `--coral-deep` / `--coral-soft` / `--coral-ink` with
   `--teal: #0c4a52`, `--teal-deep: #093438`, `--teal-soft: #dde8ea`,
   `--teal-ink: #062b30` (a 4-token palette in the same shape as the
   coral one was). The accent is now consistently used on:
   - `::selection` (highlight text)
   - `.brand__mark` and `.hero__mark` (the logo, both default + hero)
   - `.field__select:focus-visible`, `.field__input:focus-visible`,
     `.combo__button:focus-visible`, `.combo__clear:focus-visible`
     (focus rings)
   - `.calc-btn` (Calculate button — primary CTA)
   - `.result__amount` (the result number)
   - `.selection-bar` bg + border + label + price text
   - `.form-error` bg + border + text
   - `.combo__option.is-selected` border + bg
   - `.pop.is-selected` border + bg (the selected-card highlight —
     Andrew's "follow through with that color" ask)
   - `.combo__option.is-reasoning` ✦ marker
   - `.blurb__links a:hover`, `.foot a:hover`
   - `.topbar__meta .dot.is-error`
   - JS `els.localCaveat.style.color = 'var(--teal-ink)'`
   The popular-row per-card brand colors (OpenAI black, Anthropic
   terra cotta, Google blue, etc.) are unchanged — those stay as brand
   identifiers on the top strip + shape icon, but the SELECTED state
   ring + bg is now teal everywhere, giving the page one coherent
   "you picked this" voice. The `--pop-brand-soft` per-card JS variable
   is no longer used; the JSON entries still carry the `brand_soft`
   value for documentation / future reuse.
3. **Hero tightened so Calculate sits above the fold at 1920×1080.**
   Andrew's previous comment was "in a lot of sites the calculate
   button is just BARELY out of reach for the scroll". v2.4 saves
   ~170px of vertical across:
   - `.hero__mark` 168×84 → 132×66 (logo, with margin-bottom s-3 → s-2)
   - `.hero` padding `var(--s-5) 0 var(--s-5)` → `var(--s-4) 0 var(--s-3)`
   - `.hero__headline` clamp max 2.5rem → 2.125rem (margin s-3 → s-2)
   - `.hero__sub` clamp max 1.125rem → 1.0625rem (line-height 1.5 → 1.45)
   - `.selection-bar` padding `s-3 s-4` → `s-2 s-3`, margin `s-4` → `s-3`,
     forced single-line (`white-space: nowrap` + `overflow-x: auto`)
   - `.pop` width 150 → 132px, min-height 138 → 100px
   - `.form` gap `s-4` → `s-3`, `.picker` gap `s-3` → `s-2`,
     `.form-row--3` gap `s-3` → `s-2`
   - `.calc` padding clamp(16,2.4vw,32) → clamp(12,1.8vw,20),
     margin-bottom `s-5` → `s-4`
   - `.calc-btn` min-height 64 → 60px
   - `.advanced__toggle` padding `s-3 s-4` → `s-2 s-3`
   - `.field` gap `s-2` → `s-1`, `.field__hint` min-height 1.2em → 1em
   - `.section-heading` margin-bottom `s-3` → `s-2`
   - `.page` padding `s-5 s-5 s-8` → `s-4 s-5 s-7`
   Measured: at 1280-wide viewport, Calculate bottom moved from 1147px
   (v2.3) to 977px (v2.4). At 1920×1080 the button is now ~100px above
   the fold (was ~250px below).

The previous v2.4-round popover-removal changes (1-click default
selection, "see all N" link as escape hatch, default models aligned to
the brief, the 4-line card layout) are also part of v2.4 — they shipped
on disk before this run. Together they make the page: one click to
select a flagship model, brand-color shape icon for visual identity,
deep-teal selected-state ring, DM Serif Display headline, and Calculate
above the fold at common laptop sizes.

### What's new in v2.5 (over v2.4)

The v2.4 "see all N models" affordance on each popular card was a small
underlined button that opened the main "All models" combobox pre-filtered
to that provider. Operator feedback (2026-06-22 23:08): "this is good,
but what about the dropdowns for each of the companies we show on the
popular cards? I really like see all 50, but instead of a button I think
it should be a dropdown, unless you agree." v2.5 ships the per-card
dropdown — the operator's "unless you agree" was an invitation to push
back if I saw a better pattern, but a native `<select>` is genuinely
simpler than a custom popover (no positioning math, no scroll guards,
no aria-modal) and the user can still see all of that provider's models
in one click.

- **Per-card `<select>` replaces the "see all N" link.** Each card now
  has a styled native `<select>` listing every model from that provider
  (sorted by display_name). The selected option's text is the model
  display_name only (short enough to fit inside the 132px card); the
  full `name · $price` string is set as the option's title attribute
  for hover. Picking from the dropdown goes through the same
  `selectModel()` path the main combobox uses, so cross-row sync
  (selection-bar, popular highlight, main combo, Calculate) is
  identical regardless of which affordance the user came from.
- **Card outer is `<div role="button" tabindex="0">` (not `<button>`).**
  Putting a `<select>` inside a `<button>` is invalid HTML and breaks
  the click target; the div restores valid nesting while keeping the
  same click + Enter/Space keyboard semantics for the one-click
  default-selection affordance.
- **Decorative `.pop__model` and `.pop__price` spans removed.** The
  per-card select is the sole model-info element on the card (no more
  duplication between the spans and the select's closed state). The
  selection-bar at the top of the page shows the current pick's name
  + price prominently, so the price is still always visible somewhere
  even though it's no longer on the card itself.
- **Dead code removed.** `openComboFilteredToProvider()` (only called
  by the old "see all N" link) and the `.pop__see-all` CSS rules are
  gone. Card min-height stays at 100px (no bump — the select replaces
  the two decorative spans, not adds to them).

#### v2.5 known limits

- **Native `<select>` open state uses the OS picker** (browser-specific).
  The closed state is fully styled (custom chevron via background-image
  SVG, brand-tinted focus ring, teal-soft selected state matching the
  page accent). On mobile the OS renders a wheel picker — usable but
  not custom-styled. The v2.2 popover (WAI-ARIA dialog) had a scroll-
  closure bug and required collision-aware positioning; the native
  picker avoids both, at the cost of less control over the open UI.
- **Long model names truncate in the closed state.** The select
  trigger text is the model display_name only; some provider entries
  have long display names ("OpenAI: GPT-4o-mini (2024-07-18)",
  "Anthropic: Claude Opus 4.7 (Fast)") that don't fit in the ~108px
  text area at 0.72rem mono. The full name + price is in the option's
  title attribute (hover tooltip). The selection-bar at the top of
  the page shows the current pick's name prominently, so truncation
  is a card-level cosmetic issue, not a functional one.
- **`text-overflow: ellipsis` on the `<select>` trigger is unreliable
  across browsers** (Safari ignores it; Firefox honors it; Chromium
  falls back to platform-default truncation). The fallback above
  (selection-bar shows the name, title attribute on each option) is
  the practical UX. If a future iteration wants guaranteed truncation
  on the closed state, the move is a custom listbox (significantly
  more code) — not worth it for a single-line cosmetic.

### What's new in v2.6 (over v2.5)

v2.6 is the result of operator feedback (2026-06-22 23:5x, t_c2b63a6e):
"its not accurate AT ALL! we need to have the actual numbers and math
work to calculate the token cost, and avg for the model." Two deliverables:

1. **Fix a real wiring bug in the project-preset math.** Before v2.6,
   `applyProjectPreset()` cleared the Advanced token fields' placeholders
   when the user picked "Custom" but did NOT clear the `.value` — so
   switching from `LangChain Agent + medium` back to `Custom` left the
   Advanced input fields showing 8000/4500. The next Calculate sent those
   stale preset values to the backend, and the user got the LangChain
   price ($0.065) instead of the Custom+medium price ($0.0325). The fix
   adds an `inputDirty` / `outputDirty` flag (set on every keystroke into
   the Advanced input/output fields) and `applyProjectPreset()` now
   clears the field on switch-to-Custom only if it's NOT dirty. If the
   user actually typed a custom value, that survives the preset switch.
   The brief said "If the user has set custom input_tokens, those win
   over the preset" — the dirty flag is the implementation of that rule.
2. **Add a per-model "avg cost" display** on every popular card and
   every "All models" combobox option. Definition: a medium task
   (5,000 input / 2,000 output tokens, no reasoning, 1 run). Computed
   client-side from `input_per_1m + output_per_1m`, cached in a Map
   on first access — no extra `/calculate` requests. The popular-card
   label is a right-aligned mono caption beneath the per-card `<select>`
   (e.g. "≈ $0.0325 / run" for GPT-4o). The combobox label is a small
   mono span at the right edge of each option (e.g. "≈ $0.0450 avg" for
   Claude Sonnet 4). Free models render the literal "free" in the page's
   `--ok` green, with a `is-free` modifier class for both surfaces.
3. **Per-card `<option>` `title` attribute now includes the avg cost.**
   Hovering an option in any per-card dropdown shows
   `name · $in/$out per 1M · ≈ $X.XXXX /run` — gives a precise
   comparison without expanding any panel.
4. **Popular card `min-height` bumped 100px → 116px** to fit the new
   avg-cost label below the per-card select. Net row height impact at
   132px-wide cards is +16px; the horizontal-scroll row still fits at
   1280px+ viewports and wraps to a 2×4 grid below 720px.
5. **No backend changes.** All math is computed from the existing
   `/models` response (which already carries `input_per_1m` and
   `output_per_1m` for every model). Backend tests stay 102/102.

The math is now bulletproof across the 6 main UI scenarios:
Custom+medium (default), LangChain+medium+off, LangChain+large+high+chat,
the previously-buggy Custom-after-LangChain switch, LangChain+custom-
token-override, and per-card Anthropic. All six display the exact
`total_cost` returned by `/calculate`.

#### v2.6 known limits

- **Avg cost does not account for reasoning tokens.** By the brief, avg
  = `5k × input + 2k × output`, no reasoning multiplier. A reasoning-
  capable model like Claude Sonnet 4 shows $0.0450 avg, but the same
  call with `thinking=high` (1.5× output) actually costs $0.0625. This
  is intentional per the brief; the result panel's caveat ("high
  thinking (1.5× output)") still surfaces the actual multiplier after
  Calculate. If the operator wants "avg WITH thinking=medium", that's
  a future iteration — would need a per-model default-reasoning
  assumption baked into the brief.
- **Avg cost is per-run, not per-token.** The label is "≈ $X / run"
  (1 run, the same unit as the result panel). A user comparing
  high-volume costs (e.g. "1M runs/month") should multiply manually.
  Adding a per-1k-tokens or per-1M-tokens variant was deferred; the
  per-run format matches the result panel's primary unit.
- **Dirty flag is per-field, not per-preset.** The flag tracks edits
  to the input/output token fields in the Advanced section; it does
  not track other user overrides (e.g. picking a custom `task_type`
  or `num_runs`). Those are always honored on Calculate regardless
  of any preset. Future iterations could extend the flag to cover
  these, but the brief only specifies token-override survival.

### What's new in v2.7 (over v2.6)

v2.7 replaces the project preset list with real-world, project-scale numbers
from the research report at `token-cost-research.md`. The v2.6 list was
single-agent-turn placeholders (LangChain Agent 8k/4.5k, RAG Pipeline 5k/1.5k,
SWE-agent 25k/8k, fine-tuning 50k/0.5k, summarization 10k/1k, multi-turn
agent 20k/12k, etc.) — useful for a single agent run but a poor match for
the brief Andrew described as "large projects, not agent turns". The v2.7
list replaces all 13 placeholder entries with 27 cited research entries:

| Category             | Examples (3 per category)                                                 |
|----------------------|---------------------------------------------------------------------------|
| ENTIRE Websites      | SaaS Landing (2k/800), Animated 3D Marketing (15k/3.5k), Full Next.js (50k/12k) |
| ENTIRE Databases     | PostgreSQL Schema (8k/2k), Schema + Seed + Migrations (25k/8k), MongoDB + Agg (45k/15k) |
| ENTIRE Codebases     | Small Python 5k lines (60k/20k), Medium Node.js 25k lines (300k/100k), Large Monorepo 100k lines (1.2M/400k) |
| ENTIRE Games         | Simple 2D Canvas (8k/4k), Full Phaser RPG (80k/30k), 3D Multiplayer (500k/200k) |
| ENTIRE ML Pipelines  | Simple sklearn (12k/3k), PyTorch CV (70k/25k), Distributed Databricks (400k/150k) |
| ENTIRE Mobile Apps   | React Native 3 screens (25k/10k), Full iOS SwiftUI (120k/50k), Flutter + Backend (300k/120k) |
| ENTIRE Data Eng      | Simple ETL (15k/5k), Airflow DAGs 20 tasks (80k/30k), Kafka + Flink (350k/150k) |
| ENTIRE Documentation | API Docs 20 endpoints (40k/15k), Developer Portal 100+ pages (250k/80k), Enterprise KB 500+ articles (1M/300k) |
| ENTIRE Refactors     | Migrate 50 files (30k/12k), Framework upgrade React 17→18 (150k/60k), Monolith→Microservices (800k/400k) |

Each entry cites its research-report section in the `note` field
(e.g. `token-cost-research.md §1.1`) and the source name (e.g. "Termdock
landing page generation case study 2026-03-23"). All are `placeholder: false`
— the research report's numbers are cited, not estimated. `source_url` is
`null` for every entry because the research report cites source names, not
URLs; the `note` carries the citation.

**Why a flat list, not optgroups.** A 27-entry dropdown is still scannable
on a 132px-wide field (the default `.field__select` width); optgroups would
require HTML changes (`frontend/index.html`) and CSS (`app.css`). The labels
include the category prefix (`Website —`, `Codebase —`, etc.) so users can
still group visually while scanning. Future iterations can add optgroups if
the list grows past ~50 entries.

**No backend changes.** Same `/calculate` endpoint, same `Calculator` class,
same TASK_SIZE_PRESETS and REASONING_MULTIPLIERS in `app/calculator.py`.
Math verified end-to-end: 12 scenarios comparing the frontend's
`preset * TASK_SIZE_MULT[size]` auto-fill against the backend's
`Calculator.calculate()` output — all 12 match to 1e-9 (see
`/tmp/token-calc-projects-update-verify.md`). Live browser smoke (GPT-4o +
Website SaaS Landing + medium + off → $0.0130; GPT-4o + Codebase Large
Monorepo + medium + high → $9.00) also matches the manual formula
`in × in_per_1m / 1M + (out × think_mult) × out_per_1m / 1M`. Backend tests
stay 102/102.

**Overlap with TASK_SIZE_PRESETS.** The frontend `task_size` dropdown also
has project-scale options (`website`, `webapp`, `codebase-small`,
`codebase-medium`, `codebase-large`, `mobile-app`, `ml-pipeline`, `game-2d`,
`game-3d`, `refactor-large`). These remain in place — they let the user
pick a generic project and scale it up/down via task_size. The research
presets cover the same ground at fixed token counts; users who want a
specific project scale from the research report should pick that preset
with `task_size = medium` (×1, the natural scale).

## Run it

```bash
cd /home/vboxuser/vaults/star-command/Projects/token-calculator/frontend
python3 -m http.server 3018 --bind 0.0.0.0
# Open http://10.10.10.205:3018/ in a browser.
```

Recommended port is **3018** (the backend lives on **8001**; pair the two for
local dev). The server uses `--bind 0.0.0.0` so Twingate users on
`10.10.10.60` can hit it from the laptop.

## Backend wiring

The page talks directly to the FastAPI backend at
`http://10.10.10.205:8001/`. CORS is wide-open on the backend
(`Access-Control-Allow-Origin: *`) so no proxy is needed during development.

To point the page at a different API host (e.g. `http://localhost:8001` for
a local backend), set `window.TOKENTALLY_API` before `app.js` loads:

```html
<script>window.TOKENTALLY_API = 'http://localhost:8001';</script>
<script src="./app.js" type="module"></script>
```

For production, tighten the backend CORS allow-list to the page's real
origin.

## Editing project presets

`projects.json` is the source of truth for the Project dropdown. Each entry:

```json
{
  "id": "codebase-medium-nodejs-webapp",
  "label": "Codebase — Medium Node.js Webapp (25k lines)",
  "avg_input_tokens": 300000,
  "avg_output_tokens": 100000,
  "source_url": null,
  "placeholder": false,
  "note": "token-cost-research.md §3.2. Source: AgentMarketCap cost calculator. ..."
}
```

**v2.7 preset list (28 entries):** 1 `custom` entry plus 27 real-world,
project-scale entries from `token-cost-research.md` (entire websites, databases,
codebases, games, ML pipelines, mobile apps, data-eng pipelines, documentation,
and refactors — three examples per category). Every non-custom entry cites its
research-report section in the `note` field. All are `placeholder: false`; the
research report's numbers are not estimates. `source_url` is `null` for every
entry because the research report cites source names (e.g. "SWE-bench analysis
2026-04-06") rather than URLs — the `note` carries the citation instead.

The `placeholder: false` flag means the yellow "PLACEHOLDER" hint under the
dropdown does NOT show for these entries; the `note` is silently carried
along for future "Learn more" affordances.

## Editing the popular row

`popular_models.json` is the seed list for Row 1. Each entry represents
a company, not a model. Schema (v2.2):

```json
{
  "provider": "openai",
  "provider_label": "OpenAI",
  "icon": "dot",
  "brand_color": "#0d0d0d",
  "brand_soft": "#ecebe8",
  "text_color": "#ffffff",
  "default_model": "openai/gpt-4o"
}
```

- `provider` MUST match the `provider` field on the model objects in
  the backend's `/models` endpoint exactly. As of 2026-06-22 the catalog
  uses `openai`, `anthropic`, `google`, `meta-llama` (not `meta`),
  `deepseek`, `mistralai` (not `mistral`), `x-ai` (not `xai`),
  `cohere`. If a card's provider has zero models in the live catalog,
  the card is disabled and shows "no models".
- `provider_label` is the human-readable company name shown on the card
  and in the popover header.
- `icon` is one of `dot / diamond / square / ring / triangle / hex /
  plus / arc`. Abstract shapes, not corporate logos — the page
  deliberately stays out of trademark territory.
- `brand_color` is the company's recognizable color (top strip + filled
  shape icon). Use a representative hex; the page tints the
  selected/open border and adds a soft `brand_soft` background.
- `default_model` is the flagship model selected on first page load,
  and the model a click on the popular card immediately selects (v2.4
  behavior). The user can pick a different model via the per-card
  `<select>` dropdown that lists every model from that provider
  (v2.5) — sorted alphabetically by display_name, with the
  full `name · $price` string in the option's title attribute for
  hover. Cross-row sync: the per-card dropdown, the All models
  combobox, and the selection-bar all reflect the same
  `state.selectedId` regardless of which affordance the user came
  from. The `default_model` MUST exist in the live `/models` catalog;
  if it doesn't, the card is disabled and shows "no models".

If a company you'd like to add is missing, append a new entry — no code
change required. The popular row is a horizontal-scroll strip contained
inside the `.calc` form. 8 cards × 132px + 7 × 10px gaps = 1126px, which
overflows the ~832px form content area; the row scrolls horizontally
on desktop. Below 720px viewport width the row wraps to a 2-up grid.

## Logo

**Metaphor: an infinity loop made of token dots.**

The brief called for *one* metaphor — token, money, or calculation — committed
to a single visual idea. The infinity loop answers both:

- The **loop** is the shape of *comparison across models* (you flip between
  GPT-4o and Claude Sonnet 4 without ever leaving the page).
- The **dots** are *counted tokens*, flowing along the path so the loop reads
  as a tally, not just a glyph.

It's a single shape — no outline, no extra strokes, no shadow. The dots use
`currentColor` so the host page controls the color (the page renders the
logo in the accent coral). A handful of dots are larger and brighter —
the "current cost" markers — to give the shape focal weight at any size.

## Responsive breakpoints

- **1920px desktop** — centered column, max-width 880px, hero logo at 168×84,
  Popular row is a horizontal scroll strip (150px wide × 138px tall, 8 cards).
  Project / Task size / Thinking sit in a 3-col grid.
- **768px tablet** — same composition, type scales via `clamp()`. The 3-col
  grid stays 3-col as long as the viewport is ≥720px.
- **375px phone** — popular row wraps to a 2-up grid, the 3-col grid stacks
  to 1-col, ad slot sidebar moves in-flow, all dropdowns are full-width.

Touch targets are ≥ 52px (most are 56–64px). The combobox options are 44px
tall, the popular cards are 138px. The Advanced / Local GPU sections use
native `<details>` and ARIA `aria-expanded` for accessibility.

## What's a "model" in the dropdown?

The backend exposes **349 models** at `/models` — 13 hand-curated
(`config/pricing.json`, PLACEHOLDER prices) and **336 live OpenRouter
entries** (`config/openrouter.json`, synced every 6 hours). Models flagged
as PLACEHOLDER show "(PLACEHOLDER)" suffix in the combobox list. Models that
expose reasoning-token pricing (Gemini 2.5 Pro, o3, Claude Opus 4, DeepSeek
R1, etc.) show a small ✦ marker in the list.

## Ad slot injection (operator responsibility, NOT in scope for v2)

The two `<aside>` elements (`#ad-slot-top`, `#ad-slot-side`) are deliberately
empty placeholders. When an ad network is chosen (GAM, BuySellAds, Carbon,
etc.), inject the network's snippet inside those elements. Recommended
guidance:

- Keep `aspect-ratio` intact so the page doesn't reflow.
- Don't fetch ads above the fold before the calculator is interactive.
- Lazy-load the ad SDK after the `Calculate` button has been clicked once
  (improves LCP and protects against third-party blocking the calculator).

## Screenshots

Three reference captures are saved at `/tmp/token-calc-v2.5-screenshots/`:

- `1920.png` — desktop, hero + selection-bar + popular row + dropdowns + Calculate
- `768.png`  — tablet portrait, popular row scrolls horizontally inside .calc
- `375.png`  — iPhone-class phone, popular row wraps to a 2-up grid

Five v2.9 Compare-mode captures are saved at `/tmp/token-calc-v2.9-screenshots/`:

- `01-single-mode.png` — single mode regression check (same as v2.8 + new toggle visible)
- `02-compare-default-tray.png` — Compare mode initial entry with 3 default chips
- `03-compare-5-cards.png` — Compare mode with 5 cards sorted cheapest-first, cheapest highlighted
- `04-compare-mobile.png` — mobile (375px) Compare mode: cards stack vertically, cheapest on top
- `05-compare-tablet.png` — tablet (768px) Compare mode

## What's new in v2.9 (over v2.8)

A "Compare 2-5 models" mode is the headline differentiator against
tokencalculator.ai (they compare per-provider only with manual model
switching). It wires up the existing `/calculate/compare` backend endpoint.

- **Mode toggle** (pill switch above the picker): Single (default) vs
  Compare. Single mode is byte-identical to v2.8.
- **Compare tray**: in Compare mode, a teal-soft strip with one chip per
  selected model. Each chip has an × remove button. "Remove all" link on
  the right. Empty tray shows the hint "Pick 2–5 models below ↑".
- **Compare-mode picker ADDS**: clicking a popular card or picking from the
  "All models" combo adds the model to the tray (instead of replacing the
  single-mode selection). All picker affordances funnel through
  `handlePickerPick`, which branches on `state.compareMode`.
- **Default tray** on first entry into Compare mode: the 3 flagship models
  (gpt-4o + claude-sonnet-4 + gemini-2.5-pro) — so a Calculate right away
  returns a useful, already-different result.
- **FIFO cap at 5** with FIFO eviction on the 6th add. Adding the same
  model twice is a no-op.
- **Compare results**: a row of 1-5 cards sorted cheapest-first. Cheapest
  card has a teal border + a "Cheapest" badge in the top-right corner.
  Same workload (task_size, task_type, reasoning_level, num_runs) applied
  to all models. Mobile (<700px) stacks vertically; cheapest ends up on top.
- **Empty/under-2 error**: clicking Calculate with 0 or 1 model shows
  "Pick at least 2 models to compare." in the existing `.form-error` slot.
  No API call is made.

## What's new in v2.7b (over v2.9)

A form-simplification pass on top of v2.9. The prior brief (v2.7 prior to
v2.7b) had a Task size dropdown + an Agentic toggle; this brief replaces
both with a single **Workflow type dropdown** inside a renamed "Customize"
disclosure. Each preset bundles the per-call overhead a real workflow
incurs (system-prompt tokens, tool-call budget, retry multiplier) so the
user picks a workflow, not knobs.

- **Main form is now 3 controls + caption + Calculate.** Step 2 (Project)
  and Step 3 (Thinking) are the only fields above the fold. Iterations
  moved into Customize. Task size is gone (it's the preset's
  `typical_task_size`, not a user knob).
- **Live assumption caption** under the project dropdown. Renders one
  line like `Assuming multi-agent orchestrator · +12,000 sys prompt · 20
  tool calls · 1.6× retries.` Updates whenever Project or any Customize
  field changes. Uses `.field__hint` (existing pattern, no new style).
- **"Customize" disclosure** (renamed from "Advanced"). Reuses the
  existing `.advanced__toggle` / `.advanced__panel` markup — only the
  label changed. Contents (top to bottom): Workflow type dropdown →
  Iterations → Input tokens override → Output tokens override → Number
  of runs. The old `task_type` dropdown (chat/coding/writing/research/
  agentic) is gone.
- **Workflow type dropdown** has 5 options that match the brief's
  exact sys-prompt + tool-call + retry values:
  - `single-chat` — 0 sys · 0 tools · 1.0× (default, no overhead)
  - `coding-assistant` — 2,000 sys · 5 tools · 1.2×
  - `rag-pipeline` — 800 sys · 0 tools · 1.1×
  - `agentic` — 2,000 sys · 5 tools · 1.4×
  - `multi-agent` — 12,000 sys · 20 tools · 1.6×
- **Per-project workflow auto-fill.** Projects in `projects.json` can
  declare an optional `typical_workflow` field; when the user picks a
  project, the dropdown auto-selects the matching preset (and the
  assumption caption updates). Five entries wired up in this release:
  `codebase-medium-nodejs-webapp` → coding-assistant;
  `codebase-large-monorepo` + `refactor-monolith-microservices` →
  multi-agent; `database-mongodb-aggregation` + `docs-enterprise-kb` →
  rag-pipeline. Other projects default to `single-chat`.
- **Per-toggle impact lines** in the result. After cost is computed,
  the caveat renders one line per active multiplier, e.g.
  `+$0.02 from Agentic workflow: 2,000 sys · 5 tools · 1.4×` and
  `+$0.04 from medium reasoning (1.2×)`. Uses the actual values from the
  backend's `assumptions` dict, not the requested ones — the backend
  currently hardcodes the agentic retry multiplier to 1.4× regardless of
  the workflow preset, so all non-single-chat workflows get 1.4×. (The
  dropdown labels still show the per-workflow multipliers for the
  user's stated intent; the impact line shows the actual cost math.)
- **No new colors / fonts / layout primitives.** Reused `.field__hint`
  for the caption, `.advanced__toggle` / `.advanced__panel` for the
  disclosure, and added a `.form-row--2` sibling to the existing
  `.form-row--3` / `.form-row--4` variants for the simplified 2-col
  Project + Thinking row.
- **Backend payload is simpler.** `POST /calculate` no longer sends
  `task_type` (deprecated). Sends `agentic: bool`,
  `system_prompt_tokens: int`, `tool_call_count: int` derived from the
  workflow preset — the backend's existing `agentic` flag handling
  (t_8c0e2eaf) does the rest.
- **All v2.6 / v2.8 / v2.9 features preserved.** Mode toggle, favorites
  toggle, popular cards, compare tray, local mode (Ollama), ad slots,
  Compare-mode result cards, schema.org JSON-LD — all untouched.

## Known caveats

- **PLACEHOLDER prices.** The 13 hand-curated models in `config/pricing.json`
  are PLACEHOLDER. OpenRouter prices (336 models) are live. The UI surfaces
  this honestly — PLACEHOLDER entries show a yellow suffix in the combobox
  list, and the result panel always says "Estimate — verify before quoting."
- **PLACEHOLDER project presets.** Every preset in `projects.json` is flagged
  `placeholder: true` until vendor-validated numbers replace the estimates
  from `findings.md §6`. Yellow hint surfaces this under the Project
  dropdown.
- **No Ollama Cloud entries.** Research confirmed Ollama Cloud has no
  per-token pricing; the local-GPU panel covers self-hosted only.
- **Animated logo.** The page prefers-reduced-motion-aware. Users who set
  the OS reduced-motion flag see no animation.