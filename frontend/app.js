// AI Cost Calculator frontend v2 — vanilla, no deps.
// All API endpoints are same-origin (the backend has CORS=*).
// API base is overridable via window.TOKENTALLY_API for non-default deployments.
// Empty default ('') means "same origin" — works automatically when the API
// is deployed on Cloudflare Pages as a Pages Function (see /functions/api/).
const API = (window.TOKENTALLY_API || '').replace(/\/$/, '');

// ---- DOM ----------------------------------------------------------------
const $  = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const els = {
  // picker
  selectionBar:       $('#selection-bar'),         // v2.1
  selectionBarName:   $('#selection-bar-name'),
  selectionBarProv:   $('#selection-bar-provider'),
  selectionBarPrice:  $('#selection-bar-price'),
  popularRow:       $('#popular-row'),
  comboButton:      $('#combo-button'),
  comboButtonText:  $('#combo-button-text'),
  comboPanel:       $('#combo-panel'),
  comboSearch:      $('#combo-search'),
  comboClear:       $('#combo-clear'),
  comboList:        $('#combo-list'),
  comboEmpty:       $('#combo-empty'),
  comboHint:        $('#combo-hint'),             // v2.8
  favToggle:        $('#fav-toggle'),             // v2.8
  favCount:         $('#fav-count'),              // v2.8
  allCount:         $('#all-count'),
  popularCount:     $('#popular-count'),          // v2.9
  modelHint:        $('#model-hint'),
  // v2.9 — mode toggle (Single vs Compare)
  modeSingle:      $('#mode-single'),
  modeCompare:     $('#mode-compare'),
  compareTray:     $('#compare-tray'),
  compareTrayChips:$('#compare-tray-chips'),
  compareTrayClear:$('#compare-tray-clear'),
  // v2.9 — compare results
  compareResults:      $('#compare-results'),
  compareResultsGrid:  $('#compare-results-grid'),
  compareResultsCaveat:$('#compare-results-caveat'),
  // form
  projectSelect:    $('#project_id'),
  projectHint:      $('#project-hint'),
  iterations:       $('#iterations'),       // v2.9 (was "quantity") — v2.7b: lives in Customize now
  iterationsHint:   $('#iterations-hint'),  // v2.9 — v2.7b: lives in Customize now
  workflowType:     $('#workflow_type'),    // v2.7b: replaces task_size + task_type + Agentic toggle
  workflowHint:     $('#workflow-hint'),
  assumptionHint:   $('#assumption-hint'),  // v2.7b: live caption under project dropdown
  thinkingSelect:   $('#thinking_level'),
  thinkingHint:     $('#thinking-hint'),
  inputTokens:      $('#input_tokens'),
  outputTokens:     $('#output_tokens'),
  reasoningLvl:     $('#thinking_level'), // alias kept for clarity
  numRuns:          $('#num_runs'),
  calcForm:         $('#calc-form'),
  calcBtn:          $('#calc-btn'),
  result:           $('#result'),
  resultEyebrow:    $('#result-eyebrow'),
  resultAmount:     $('#result-amount'),
  resultBreak:      $('#result-breakdown'),
  resultMulti:      $('#result-multiline'),
  resultCaveat:     $('#result-caveat'),
  formError:        $('#form-error'),
  // local
  localToggle:      $('#local-toggle'),
  localPanel:       $('#local-panel'),
  localGpu:         $('#local_gpu'),
  localModel:       $('#local_model'),
  localTaskSize:    $('#local_task_size'),
  gpuCost:          $('#gpu_cost'),
  powerCost:        $('#power_cost'),
  localForm:        $('#local-form'),
  localBtn:         $('#local-btn'),
  localResult:      $('#local-result'),
  localEyebrow:     $('#local-eyebrow'),
  localAmount:      $('#local-amount'),
  localBreak:       $('#local-breakdown'),
  localCaveat:      $('#local-caveat'),
  // token counter (heuristic chars÷4 — no library, no WASM)
  promptText:          $('#prompt-text'),
  tokenCounterNum:     $('#token-counter-num'),
  tokenCounterChars:   $('#token-counter-chars'),
  tokenCounterApply:   $('#token-counter-apply'),
};

// ---- State --------------------------------------------------------------
const state = {
  models: [],
  byId: new Map(),
  projects: [],
  popular: [],
  root: null,
  localGpus: [],
  localModels: [],
  busy: false,
  // picker
  selectedId: null,         // currently selected model_id
  comboOpen: false,
  comboActiveIdx: -1,       // highlighted option in open list
  comboFiltered: [],        // currently filtered list
  // v2.8: favorites — persisted in localStorage so a starred model
  // survives reloads. IDs only; everything else is looked up against
  // state.models on each render. Stale IDs (model disappeared from
  // /models) are pruned on load.
  favorites: new Set(),
  favoritesOnly: false,     // when true, combo list is filtered to favorites
  // v2.9 — compare mode. compareMode toggles between Single (existing
  // behavior: one selectedId, /calculate, single-result panel) and
  // Compare (ordered list of 2-5 model_ids, /calculate/compare, card
  // grid). compareIds is FIFO-ordered: pushing past 5 evicts index 0.
  // compareInitDone gates the "default to GPT-4o + Claude Sonnet 4 +
  // Gemini 2.5 Pro on first entry" behavior — toggling back and forth
  // shouldn't reset the tray unless it's empty.
  compareMode: false,
  compareIds: [],
  compareInitDone: false,
};

// v2.8: localStorage persistence for favorites. Key is namespaced so it
// doesn't collide with other apps on the same origin. Read is wrapped in
// try/catch (Safari private mode, disabled storage, quota errors all
// throw — we silently degrade to a session-only Set).
const FAV_KEY = 'tokentally.favorites.v1';
function loadFavorites() {
  try {
    const raw = localStorage.getItem(FAV_KEY);
    if (!raw) return;
    const arr = JSON.parse(raw);
    if (Array.isArray(arr)) {
      // Drop IDs that don't exist in the loaded model set. Re-pruned
      // after every successful loadAll().
      const valid = arr.filter((id) => typeof id === 'string');
      state.favorites = new Set(valid);
    }
  } catch { /* ignore */ }
}
function saveFavorites() {
  try {
    localStorage.setItem(FAV_KEY, JSON.stringify([...state.favorites]));
  } catch { /* ignore */ }
}
function pruneFavorites() {
  // After loadAll() resolves, drop favorites that no longer match a
  // known model. Called once on initial load.
  const before = state.favorites.size;
  state.favorites = new Set([...state.favorites].filter((id) => state.byId.has(id)));
  if (state.favorites.size !== before) saveFavorites();
}
function updateFavCount() {
  const n = state.favorites.size;
  if (n === 0) {
    els.favCount.hidden = true;
  } else {
    els.favCount.textContent = String(n);
    els.favCount.hidden = false;
  }
}
function toggleFavorite(modelId) {
  if (state.favorites.has(modelId)) {
    state.favorites.delete(modelId);
  } else {
    state.favorites.add(modelId);
  }
  saveFavorites();
  updateFavCount();
  // Re-paint the combo if it's open so the star state updates.
  if (state.comboOpen) paintCombo();
  // Update the selection-bar star indicator (if the favorited model is selected).
  updateSelectionBarStar();
}
function updateSelectionBarStar() {
  // Small star prefix in the selection bar when the selected model is
  // a favorite. Lives inside .selection-bar__name via a leading span.
  if (!els.selectionBarName) return;
  const m = state.byId.get(state.selectedId);
  const isFav = !!(m && state.favorites.has(state.selectedId));
  let star = els.selectionBarName.querySelector('.selection-bar__star');
  if (isFav && !star) {
    star = document.createElement('span');
    star.className = 'selection-bar__star';
    star.textContent = '★ ';
    star.setAttribute('aria-label', 'favorited');
    els.selectionBarName.prepend(star);
  } else if (!isFav && star) {
    star.remove();
  }
}

// Some endpoints return {id}; others return {model_id}. Accept both.
function idOf(m) { return m.model_id || m.id; }

// Task size multipliers — same math as v1 (documented in HTML hint).
// MUST match the backend's TASK_SIZE_PRESETS semantic: tiny/small/medium/large/huge.
// The backend uses absolute token counts in TASK_SIZE_PRESETS (200/100, 1k/500, 5k/2k,
// 20k/8k, 100k/30k); the frontend uses these multipliers against the project preset's
// avg_input_tokens / avg_output_tokens. The two reconcile at /calculate: when the
// frontend sends explicit input_tokens/output_tokens, the backend uses them verbatim
// (overriding the task_size preset); when the frontend omits them, the backend falls
// back to TASK_SIZE_PRESETS[task_size].
// v2.7b: TASK_SIZE is no longer a user-facing field. The frontend still uses
// these multipliers when auto-filling input/output tokens from a project
// preset — the preset's `typical_task_size` is the implicit multiplier.
const TASK_SIZE_MULT = {
  tiny: 0.04,
  small: 0.2,
  medium: 1,
  large: 4,
  huge: 20,
  // New project-scale entries matching backend TASK_SIZE_PRESETS
  website: 0.3,           // website: 15k/3.5k (~20x tiny)
  webapp: 1,              // webapp: 50k/12k (~medium)
  'codebase-small': 1.2,  // codebase-small: 60k/20k
  'codebase-medium': 6,   // codebase-medium: 300k/100k
  'codebase-large': 24,   // codebase-large: 1.2M/400k
  'mobile-app': 2.4,      // mobile-app: 120k/50k
  'ml-pipeline': 1.4,     // ml-pipeline: 70k/25k
  'game-2d': 1.6,         // game-2d: 80k/30k
  'game-3d': 10,          // game-3d: 500k/200k
  'refactor-large': 16,   // refactor-large: 800k/400k
};

// v2.7b: Workflow type presets. Replaces the old Task size dropdown +
// task_type dropdown + the prior brief's Agentic toggle with a single
// dropdown. Each preset bundles the per-call overhead that real
// workflows incur (system-prompt tokens for the agent's role prompt,
// tool-call budget, and a retry multiplier for flaky agent runs).
// MUST match backend AGENTIC_DEFAULT_* + AGENTIC_MULTIPLIER in
// app/calculator.py. Single-chat is the no-overhead default;
// multi-agent is the heaviest.
const WORKFLOW_OVERHEAD = {
  'single-chat':      { system_prompt_tokens: 0,     tool_call_count: 0,  retry_mult: 1.0, label: 'Single chat',                  hint: 'No overhead' },
  'coding-assistant': { system_prompt_tokens: 2000,  tool_call_count: 5,  retry_mult: 1.2, label: 'Coding assistant',             hint: '+2k sys · 5 tools · 1.2×' },
  'rag-pipeline':     { system_prompt_tokens: 800,   tool_call_count: 0,  retry_mult: 1.1, label: 'RAG pipeline',                 hint: '+800 sys · 1.1×' },
  'agentic':          { system_prompt_tokens: 2000,  tool_call_count: 5,  retry_mult: 1.4, label: 'Agentic workflow',             hint: '+2k sys · 5 tools · 1.4×' },
  'multi-agent':      { system_prompt_tokens: 12000, tool_call_count: 20, retry_mult: 1.6, label: 'Multi-agent orchestrator',     hint: '+12k sys · 20 tools · 1.6×' },
};
const WORKFLOW_LABELS = Object.fromEntries(
  Object.entries(WORKFLOW_OVERHEAD).map(([k, v]) => [k, v.label])
);

// Reason multipliers (apply only to OUTPUT tokens at /calculate).
// MUST match app/calculator.py:REASONING_MULTIPLIERS.
// "off" is handled client-side by omitting reasoning_level from the request body
// entirely (the backend Pydantic enum is Literal['low','medium','high','extreme'];
// v2.1 fix per STATUS.md).
const REASONING_MULT_OUT = { off: 1.0, low: 1.0, medium: 1.2, high: 1.5, extreme: 2.5 };

// Average cost per "medium" task: 5k input + 2k output, no reasoning, 1 run.
// Computed client-side from input_per_1m + output_per_1m so we don't have to
// hit /calculate for every model. Cached lazily on first access.
const avgCostCache = new Map();
function avgCostForModel(m) {
  const id = idOf(m);
  if (avgCostCache.has(id)) return avgCostCache.get(id);
  const inP  = m.input_per_1m  ?? 0;
  const outP = m.output_per_1m ?? 0;
  const cost = (5000 * inP + 2000 * outP) / 1_000_000;
  avgCostCache.set(id, cost);
  return cost;
}

// Track whether the user manually typed into input_tokens / output_tokens.
// When true, applyProjectPreset() must NOT overwrite the field with the preset.
// Reset to false whenever a preset is applied (preset fills aren't "user typed").
let inputDirty  = false;
let outputDirty = false;
// v2.7b: same dirty-tracking for the Customize fields that auto-fill from
// the project preset. Prevents the user's manual override from being
// silently overwritten the next time they pick a preset.
let iterationsDirty = false;
let workflowDirty   = false;

// ---- Formatters ---------------------------------------------------------
const fmt2 = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const fmt4 = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 4,
  maximumFractionDigits: 4,
});
const fmtInt = new Intl.NumberFormat('en-US');

function fmtMoney(n)  { return Number.isFinite(n) ? '$' + fmt4.format(n) : 'n/a'; }
function fmtMoney2(n) { return Number.isFinite(n) ? '$' + fmt2.format(n) : 'n/a'; }
function fmtTokens(n) { return Number.isFinite(n) ? fmtInt.format(Math.round(n)) : 'n/a'; }

// ---- Loaders ------------------------------------------------------------
async function loadRoot() {
  const r = await fetch(`${API}/`, { headers: { 'Accept': 'application/json' } });
  if (!r.ok) throw new Error(`/ returned ${r.status}`);
  return r.json();
}
async function loadModels() {
  const r = await fetch(`${API}/models`, { headers: { 'Accept': 'application/json' } });
  if (!r.ok) throw new Error(`/models returned ${r.status}`);
  const d = await r.json();
  return d.models || [];
}
async function loadLocalGpus() {
  const r = await fetch(`${API}/local/gpus`, { headers: { 'Accept': 'application/json' } });
  if (!r.ok) throw new Error(`/local/gpus returned ${r.status}`);
  const d = await r.json();
  return d.gpus || [];
}
async function loadLocalModels() {
  const r = await fetch(`${API}/local/models`, { headers: { 'Accept': 'application/json' } });
  if (!r.ok) throw new Error(`/local/models returned ${r.status}`);
  const d = await r.json();
  return d.models || [];
}
async function loadProjects() {
  const r = await fetch(`./projects.json`, { headers: { 'Accept': 'application/json' } });
  if (!r.ok) throw new Error(`projects.json returned ${r.status}`);
  return r.json();
}
async function loadPopular() {
  const r = await fetch(`./popular_models.json`, { headers: { 'Accept': 'application/json' } });
  if (!r.ok) throw new Error(`popular_models.json returned ${r.status}`);
  return r.json();
}

// ---- Popular row (Row 1) — v2.5: per-card model dropdown -------------
// Each card represents a COMPANY. The card body shows the brand mark +
// company name; below that is a styled <select> listing every model from
// that provider (sorted by display_name). The select doubles as both
// "what you picked" (its selected option) and "pick a different one"
// (open the dropdown to browse). One-click behavior on the card body
// still works: clicking anywhere on the card EXCEPT the select picks
// the company's flagship (popular_models.json:default_model), the same
// as before. Picking from the <select> goes through the same
// selectModel() path the main combobox uses, so cross-row sync, the
// selection-bar, the thinking-support toggle, and Calculate all behave
// identically regardless of which affordance the user came from.
const ICON_SVG = {
  dot:      '<svg viewBox="0 0 22 22" width="22" height="22" fill="currentColor"><circle cx="11" cy="11" r="8"/></svg>',
  diamond:  '<svg viewBox="0 0 22 22" width="22" height="22" fill="currentColor"><path d="M11 2 L20 11 L11 20 L2 11 Z"/></svg>',
  square:   '<svg viewBox="0 0 22 22" width="22" height="22" fill="currentColor"><rect x="3" y="3" width="16" height="16" rx="2"/></svg>',
  ring:     '<svg viewBox="0 0 22 22" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2.4"><circle cx="11" cy="11" r="7.5"/></svg>',
  triangle: '<svg viewBox="0 0 22 22" width="22" height="22" fill="currentColor"><path d="M11 3 L19.5 18.5 L2.5 18.5 Z"/></svg>',
  hex:      '<svg viewBox="0 0 22 22" width="22" height="22" fill="currentColor"><path d="M11 2 L19 6.5 L19 15.5 L11 20 L3 15.5 L3 6.5 Z"/></svg>',
  plus:     '<svg viewBox="0 0 22 22" width="22" height="22" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><path d="M11 3.5 V18.5 M3.5 11 H18.5"/></svg>',
  arc:      '<svg viewBox="0 0 22 22" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M3 17 A 8 8 0 0 1 19 17"/></svg>',
};

function priceBadge(m) {
  const inP = m.input_per_1m ?? 0;
  const outP = m.output_per_1m ?? 0;
  if (inP === 0 && outP === 0) return 'free';
  return `$${fmt2.format(inP)} / $${fmt2.format(outP)} per 1M`;
}

function priceBadgeInline(m) {
  const inP = m.input_per_1m ?? 0;
  const outP = m.output_per_1m ?? 0;
  if (inP === 0 && outP === 0) return 'free';
  return `$${fmt2.format(inP)} / $${fmt2.format(outP)}`;
}

function modelsForProvider(provider) {
  return state.models.filter((m) => m.provider === provider);
}

function renderPopular() {
  els.popularRow.innerHTML = '';
  for (const p of state.popular) {
    const defaultM = state.byId.get(p.default_model);
    // v2.8: pin the flagship to the top of the dropdown instead of pure
    // alphabetical. The user opens the card dropdown expecting the "most
    // popular" model first; alphabetical sort buried gpt-4o under every
    // gpt-3.5/gpt-4.1/gpt-5 entry. Default is starred (★) via CSS, so the
    // meaning is obvious.
    const providerModels = modelsForProvider(p.provider)
      .slice()
      .sort((a, b) => {
        const aid = idOf(a), bid = idOf(b);
        if (aid === p.default_model) return -1;
        if (bid === p.default_model) return 1;
        return (a.display_name || aid).localeCompare(b.display_name || bid);
      });
    const count = providerModels.length;
    const usable = !!(defaultM && count > 0);

    // The card outer is a <div role="button"> (not a <button>) so we can
    // nest a real <select> inside — putting a <select> inside a <button>
    // is invalid HTML and breaks the click target. The keyboard handler
    // (Enter/Space) restores the button's affordance for keyboard users.
    const card = document.createElement('div');
    card.className = 'pop';
    card.dataset.provider = p.provider;
    card.dataset.defaultModel = p.default_model || '';
    card.setAttribute('role', 'button');
    card.setAttribute('tabindex', usable ? '0' : '-1');
    card.setAttribute('aria-label',
      `${p.provider_label}: ${defaultM ? (defaultM.display_name || p.default_model) : 'no default'}. ` +
      `${count} model${count === 1 ? '' : 's'} available — click to pick the default, or use the dropdown to browse all ${count}.`);
    card.style.setProperty('--pop-brand', p.brand_color);
    if (!usable) card.classList.add('is-empty');

    // Head: brand-color shape icon + company name.
    const head = document.createElement('div');
    head.className = 'pop__head';
    const icon = document.createElement('span');
    icon.className = 'pop__icon';
    icon.innerHTML = ICON_SVG[p.icon] || ICON_SVG.dot;
    const name = document.createElement('span');
    name.className = 'pop__name';
    name.textContent = p.provider_label;
    head.appendChild(icon);
    head.appendChild(name);

    // The per-card <select>. Native select = familiar UX, browser keyboard
    // nav (↑↓/Enter/Esc/Tab), no positioning math or scroll guards (unlike
    // the v2.2 popover). The option text is just the model display_name
    // (short enough to fit inside the 132px-wide card on a single line);
    // the full "name · $price" string is set as the option's title attribute
    // so a hover tooltip reveals the price. The selection-bar at the top of
    // the page shows the current pick's price prominently. The select's
    // initial value is set by syncCardSelects() after the row is built, since
    // state.selectedId is null at first paint but gets set immediately after.
    const sel = document.createElement('select');
    sel.className = 'pop__select';
    sel.dataset.provider = p.provider;
    sel.setAttribute('aria-label', `${p.provider_label} models`);
    if (!usable) sel.disabled = true;

    for (const m of providerModels) {
      const opt = document.createElement('option');
      const id = idOf(m);
      opt.value = id;
      const badge = priceBadgeInline(m);
      const dn = m.display_name || id;
      // v2.6 (t_c2b63a6e): add the avg-cost-per-task to the option's title
      // tooltip so a hover reveals it; the option's visible text stays short.
      const avg = avgCostForModel(m);
      const avgLabel = avg === 0 ? 'free' : `≈ ${fmtMoney(avg)}/run`;
      opt.textContent = dn;                      // trigger text (must fit 132px)
      opt.title = `${dn} · ${badge} · ${avgLabel}`;  // hover tooltip: name + price + avg
      if (id === p.default_model) {
        // v2.8: mark the default with an `is-default` class so the CSS
        // can prefix the option text with a star + bold it. Browsers
        // vary on `::before` support inside <option>, but the class
        // is harmless if the styling is dropped.
        opt.dataset.isDefault = 'true';
        opt.classList.add('is-default');
        opt.textContent = `${dn}  ·  default`;
      }
      sel.appendChild(opt);
    }

    // v2.6 (t_c2b63a6e): per-card avg-cost label. Computed for the company's
    // flagship (default_model) and shown beneath the dropdown. Gives users
    // an at-a-glance cost anchor for the company before they pick a model.
    let avgLabelHtml = '';
    if (usable && defaultM) {
      const avg = avgCostForModel(defaultM);
      avgLabelHtml = avg === 0
        ? `<div class="pop__avg is-free">free</div>`
        : `<div class="pop__avg">≈ ${fmtMoney(avg)}<span class="pop__avg-suffix"> / run</span></div>`;
    }

    card.appendChild(head);
    card.appendChild(sel);
    if (avgLabelHtml) {
      const avgEl = document.createElement('div');
      avgEl.innerHTML = avgLabelHtml;
      card.appendChild(avgEl.firstChild);
    }

    if (usable) {
      // One-click default-selection: click anywhere on the card except
      // the <select> picks the company's flagship. The <select> has its
      // own change handler below — we don't want a parent click to also
      // re-select the default after the user just picked something
      // different from the dropdown. Native <select> doesn't bubble
      // click events up to the card reliably across browsers, so we
      // listen for mousedown on the select and stop propagation there
      // (in addition to relying on the change event).
      sel.addEventListener('mousedown', (e) => e.stopPropagation());
      sel.addEventListener('click',     (e) => e.stopPropagation());
      sel.addEventListener('keydown',   (e) => e.stopPropagation());
      sel.addEventListener('change', () => {
        const id = sel.value;
        // v2.9: route through handlePickerPick — in Compare mode this
        // ADDs to the tray instead of replacing the single selection.
        if (id) handlePickerPick(id, { source: 'card-select' });
      });
      card.addEventListener('click', (e) => {
        // Defensive: even if a click bubbled up from inside the select
        // somehow, don't double-fire. The stops above handle 99% of cases.
        if (e.target.closest('.pop__select')) return;
        // v2.9: same routing as the <select>'s change handler.
        handlePickerPick(p.default_model, { source: 'popular-card' });
      });
      card.addEventListener('keydown', (e) => {
        // Mirror button semantics for keyboard users. Enter/Space picks
        // the default. The <select> inside handles its own keyboard nav
        // when it has focus; we don't want to double-handle.
        if (e.target.closest('.pop__select')) return;
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          // v2.9: same routing as the click handler.
          handlePickerPick(p.default_model, { source: 'popular-card' });
        }
      });
    } else {
      card.title = `No ${p.provider_label} models in the live catalog right now.`;
    }
    els.popularRow.appendChild(card);
  }
  // Sync each card's select to the current selection (default_model for
  // its own provider if the global selection isn't from this provider).
  syncCardSelects();
}

// Walk every card's <select> and set its value to match state.selectedId.
// If the global selection is not from this card's provider, fall back to
// the card's own default_model. Called from selectModel() so all three
// affordances (popular card, card dropdown, main combobox) stay in sync.
function syncCardSelects() {
  const sel = state.selectedId ? state.byId.get(state.selectedId) : null;
  const selProvider = sel ? sel.provider : null;
  for (const card of els.popularRow.querySelectorAll('.pop')) {
    const cardSel = card.querySelector('.pop__select');
    if (!cardSel || cardSel.disabled) continue;
    let targetId;
    if (selProvider === card.dataset.provider) {
      targetId = state.selectedId;
    } else {
      targetId = card.dataset.defaultModel;
    }
    if (targetId && cardSel.value !== targetId) {
      // set the property so the .value setter handles the <option> lookup
      cardSel.value = targetId;
    }
  }
}

function syncPopularSelected() {
  // A card is "selected" when the currently selected model belongs to
  // that provider. The same model can be reached via the popular card
  // or the searchable combobox; this keeps the two affordances in sync.
  const sel = state.selectedId ? state.byId.get(state.selectedId) : null;
  const selProvider = sel ? sel.provider : null;
  for (const btn of els.popularRow.querySelectorAll('.pop')) {
    btn.classList.toggle('is-selected', btn.dataset.provider === selProvider);
  }
}

// ---- Searchable combobox (Row 2) ---------------------------------------
function renderCombo() {
  els.comboList.innerHTML = '';
  els.allCount.textContent = `${state.models.length} models`;
  // v2.8: if the favorites filter is on at first render, start with
  // only favorites in the filtered list. The text-search and the
  // favorites toggle compose: search "claude" + favorites on = only
  // favorited Claudes.
  state.comboFiltered = computeComboList('');
  paintCombo();
}

// v2.8: the combo's "what to show" rule, given the current search query.
// Honors state.favoritesOnly — when on, restrict to starred models.
function computeComboList(query) {
  const needle = (query || '').trim().toLowerCase();
  let list = state.models;
  if (state.favoritesOnly) {
    list = list.filter((m) => state.favorites.has(idOf(m)));
  }
  if (needle) {
    list = list.filter((m) => {
      const hay = `${m.display_name || ''}\n${m.provider || ''}\n${idOf(m)}`.toLowerCase();
      return hay.includes(needle);
    });
  }
  return list;
}

function paintCombo() {
  els.comboList.innerHTML = '';
  if (state.comboFiltered.length === 0) {
    // v2.8: distinguish "no search matches" from "no favorites yet" so
    // the user knows what to do. The hint is one line below the search
    // bar already; the empty state just needs to be informative.
    if (state.favoritesOnly && state.favorites.size === 0) {
      els.comboEmpty.textContent = 'No favorites yet — click ☆ on any model to add it.';
    } else if (state.favoritesOnly) {
      els.comboEmpty.textContent = 'No favorites match your search.';
    } else {
      els.comboEmpty.textContent = 'No matches.';
    }
    els.comboEmpty.hidden = false;
    return;
  }
  els.comboEmpty.hidden = true;

  const frag = document.createDocumentFragment();
  state.comboFiltered.forEach((m, idx) => {
    const li = document.createElement('li');
    li.className = 'combo__option';
    li.setAttribute('role', 'option');
    li.id = `combo-opt-${idx}`;
    li.dataset.modelId = idOf(m);
    if ((m.notes || '').match(/placeholder/i)) li.classList.add('is-placeholder');
    if (m.supports_reasoning) li.classList.add('is-reasoning');
    if (idOf(m) === state.selectedId) li.classList.add('is-selected');

    const name = document.createElement('span');
    name.className = 'combo__option-name';
    name.textContent = m.display_name || idOf(m);

    const meta = document.createElement('span');
    meta.className = 'combo__option-meta';
    const prov = document.createElement('span');
    prov.className = 'combo__option-provider';
    prov.textContent = m.provider || 'other';
    const price = document.createElement('span');
    price.className = 'combo__option-price';
    const badge = priceBadge(m);
    price.textContent = badge;
    if (badge === 'free') price.classList.add('is-free');
    meta.appendChild(prov);
    meta.appendChild(price);

    // v2.6 (t_c2b63a6e): avg-cost-per-model label. Pre-computed from
    // input_per_1m + output_per_1m (5k in / 2k out, no reasoning) so it
    // costs nothing to render for 349 models. Lets users compare at a
    // glance without opening a separate view.
    const avg = avgCostForModel(m);
    const avgEl = document.createElement('span');
    avgEl.className = 'combo__option-avg';
    avgEl.textContent = avg === 0 ? 'free' : `≈ ${fmtMoney(avg)} avg`;
    if (avg === 0) avgEl.classList.add('is-free');

    li.appendChild(name);
    li.appendChild(meta);
    li.appendChild(avgEl);

    // v2.8: star button on the right edge of each option. Clicking it
    // toggles favorite status for the model; we stop the event so the
    // option's own mousedown handler (which selects the model + closes
    // the panel) doesn't also fire. The star has its own hover/focus
    // styling so users can see it's an action, not a label.
    const dnOpt = m.display_name || idOf(m);
    const isFav = state.favorites.has(idOf(m));
    const star = document.createElement('button');
    star.type = 'button';
    star.className = 'combo__option-star';
    if (isFav) star.classList.add('is-on');
    star.setAttribute('aria-label',
      isFav ? `Remove ${dnOpt} from favorites` : `Add ${dnOpt} to favorites`);
    star.textContent = isFav ? '★' : '☆';
    star.addEventListener('mousedown', (e) => {
      e.preventDefault();
      e.stopPropagation();
      toggleFavorite(idOf(m));
    });
    star.addEventListener('click', (e) => e.stopPropagation());
    li.appendChild(star);

    li.addEventListener('mousedown', (e) => {
      // Use mousedown so the click registers before the input blurs + closes panel.
      e.preventDefault();
      // v2.9: route through handlePickerPick — in Compare mode this
      // ADDs to the tray instead of replacing the single selection.
      handlePickerPick(idOf(m), { source: 'combo' });
      closeCombo();
    });
    li.addEventListener('mouseenter', () => setActiveComboIdx(idx));
    frag.appendChild(li);
  });
  els.comboList.appendChild(frag);
}

function filterCombo(q) {
  // v2.8: route through computeComboList so the favorites filter and
  // the text search compose correctly.
  state.comboFiltered = computeComboList(q);
  state.comboActiveIdx = state.comboFiltered.length ? 0 : -1;
  paintCombo();
  scrollActiveIntoView();
}

function setActiveComboIdx(idx) {
  state.comboActiveIdx = idx;
  for (const opt of els.comboList.querySelectorAll('.combo__option')) {
    opt.classList.toggle('is-active', Number(opt.id.replace('combo-opt-', '')) === idx);
  }
}

function scrollActiveIntoView() {
  const active = els.comboList.querySelector('.combo__option.is-active');
  if (active) active.scrollIntoView({ block: 'nearest' });
}

function openCombo() {
  if (state.comboOpen) return;
  state.comboOpen = true;
  els.comboButton.setAttribute('aria-expanded', 'true');
  els.comboButton.classList.add('is-open');
  els.comboPanel.hidden = false;
  els.comboSearch.value = '';
  els.comboClear.hidden = true;
  // v2.8: the open-list default is now routed through computeComboList
  // so the favorites filter is preserved across close/reopen (the user
  // expects "Favorites on, open combo, still favorites").
  state.comboFiltered = computeComboList('');
  state.comboActiveIdx = state.comboFiltered.length ? 0 : -1;
  paintCombo();
  scrollActiveIntoView();
  // Defer focus so the panel has time to render.
  setTimeout(() => els.comboSearch.focus(), 0);
  document.addEventListener('mousedown', onDocMousedown, true);
}

function closeCombo() {
  if (!state.comboOpen) return;
  state.comboOpen = false;
  els.comboButton.setAttribute('aria-expanded', 'false');
  els.comboButton.classList.remove('is-open');
  els.comboPanel.hidden = true;
  document.removeEventListener('mousedown', onDocMousedown, true);
  els.comboButton.focus();
}

function onDocMousedown(e) {
  if (!els.comboPanel.contains(e.target) && !els.comboButton.contains(e.target)) {
    closeCombo();
  }
}

function onComboKey(e) {
  const max = state.comboFiltered.length - 1;
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    setActiveComboIdx(Math.min(max, state.comboActiveIdx + 1));
    scrollActiveIntoView();
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    setActiveComboIdx(Math.max(0, state.comboActiveIdx - 1));
    scrollActiveIntoView();
  } else if (e.key === 'Enter') {
    e.preventDefault();
    const opt = state.comboFiltered[state.comboActiveIdx];
    if (opt) {
      // v2.9: route through handlePickerPick — in Compare mode this
      // ADDs to the tray instead of replacing the single selection.
      handlePickerPick(idOf(opt), { source: 'combo' });
      closeCombo();
    }
  } else if (e.key === 'Escape') {
    e.preventDefault();
    closeCombo();
  } else if (e.key === 'Home') {
    e.preventDefault();
    setActiveComboIdx(0);
    scrollActiveIntoView();
  } else if (e.key === 'End') {
    e.preventDefault();
    setActiveComboIdx(max);
    scrollActiveIntoView();
  }
}

// ---- Selection (shared between popular row + combobox) -----------------
function selectModel(modelId, _opts) {
  const m = state.byId.get(modelId);
  if (!m) return;
  state.selectedId = modelId;

  // Combo button label
  els.comboButtonText.textContent = `${m.display_name || modelId}  ·  ${m.provider || ''}`;
  els.comboButtonText.classList.remove('is-placeholder');

  // v2.1 selection-bar — the prominent "what you picked" indicator
  els.selectionBarName.textContent = m.display_name || modelId;
  els.selectionBarProv.textContent = m.provider ? `· ${m.provider}` : '';
  els.selectionBarPrice.textContent = priceBadge(m);
  // v2.8: favorite star prefix on the selection bar — drawn as a
  // separate span so the rest of the bar layout is unaffected.
  updateSelectionBarStar();

  // Sync popular row + combobox highlight
  syncPopularSelected();
  syncCardSelects();
  for (const opt of els.comboList.querySelectorAll('.combo__option')) {
    opt.classList.toggle('is-selected', opt.dataset.modelId === modelId);
  }

  // Model hint (PLACEHOLDER vs live OpenRouter)
  updateModelHint();
  // Update thinking dropdown enabled state (depends on supports_reasoning).
  syncThinkingSupport();
}

function updateModelHint() {
  const m = state.byId.get(state.selectedId);
  if (!m) {
    els.modelHint.textContent = '\u00a0';
    els.modelHint.classList.remove('is-warn');
    return;
  }
  if ((m.notes || '').match(/placeholder/i)) {
    els.modelHint.textContent = 'PLACEHOLDER pricing: verify against vendor docs.';
    els.modelHint.classList.add('is-warn');
  } else if ((m.notes || '').match(/openrouter/i)) {
    els.modelHint.textContent = 'Live OpenRouter pricing (last refresh on the meta strip above).';
    els.modelHint.classList.remove('is-warn');
  } else {
    els.modelHint.textContent = '\u00a0';
    els.modelHint.classList.remove('is-warn');
  }
}

// ---- Thinking support detection -----------------------------------------
function syncThinkingSupport() {
  const m = state.byId.get(state.selectedId);
  const supports = !!(m && m.supports_reasoning);
  els.thinkingSelect.classList.toggle('is-thinking-locked', !supports);
  // If model doesn't support reasoning, force value to "off" so the API
  // doesn't apply a multiplier that has no effect (and we keep the UI honest).
  if (!supports && els.thinkingSelect.value !== 'off') {
    els.thinkingSelect.value = 'off';
  }
  // v2.9: when a reasoning model is selected, default thinking to "Low"
  // so users see the realistic cost (reasoning models charge for the
  // thinking tokens by default). Only nudges if currently "off" — we
  // don't override an explicit user choice of medium/high/extreme.
  if (supports && els.thinkingSelect.value === 'off') {
    els.thinkingSelect.value = 'low';
  }
  els.thinkingHint.textContent = supports
    ? 'This model supports reasoning tokens. Off means no extra cost; default for reasoning models is Low.'
    : 'This model does not publish reasoning-token pricing; non-Off options are visual only.';
}

// ---- v2.9 — Compare mode -----------------------------------------------
// Compare mode keeps state.selectedId (single-mode model) but layers a
// second ordered list — state.compareIds — on top. In compare mode the
// picker adds to the tray instead of selecting the single model. The
// Calculate button submits to /calculate/compare and renders a row of
// cards sorted by total_cost. Toggling back to Single restores the
// single-mode selection-bar and hides the tray/results.
//
// Cap is 5 (UI sanity; backend allows 10). Adding a 6th model evicts the
// oldest entry (FIFO). Adding the same model twice is a no-op (idempotent).
// Removing clears that slot; the chip's × button doesn't disturb the others.

// Default tray contents when the user first enters compare mode AND the
// tray is empty. Three flagship models so a first-click Calculate returns
// a useful, already-different result. All three are verified live in
// /models (per popular_models.json).
const COMPARE_DEFAULTS = [
  'openai/gpt-4o',
  'anthropic/claude-sonnet-4',
  'google/gemini-2.5-pro',
];

function setMode(mode) {
  const next = mode === 'compare';
  if (next === state.compareMode) return;
  state.compareMode = next;
  // Toggle pill states (visual)
  els.modeSingle.classList.toggle('is-on', !next);
  els.modeCompare.classList.toggle('is-on', next);
  els.modeSingle.setAttribute('aria-selected', String(!next));
  els.modeCompare.setAttribute('aria-selected', String(next));
  // Swap selection-bar ↔ compare-tray visibility
  els.selectionBar.hidden = next;
  els.compareTray.hidden = !next;
  // Swap result panel ↔ compare-results visibility
  els.result.hidden = true;          // hide stale single result in compare
  if (next) {
    // First entry into compare mode: pre-populate with the 3 flagship
    // models so a Calculate right away returns a useful result. Skip
    // if the user already populated the tray (e.g. they toggled away
    // and back).
    if (!state.compareInitDone && state.compareIds.length === 0) {
      state.compareIds = COMPARE_DEFAULTS.filter((id) => state.byId.has(id));
      state.compareInitDone = true;
    }
    renderCompareTray();
    // Hide the single-result block; show compare-results only after a
    // Calculate call. If the user had run a Compare before, re-show.
    els.compareResults.hidden = state.compareResultsGrid.childElementCount === 0;
  } else {
    // Single mode: re-hide compare results, re-show selection-bar.
    // Keep state.compareIds intact — toggling back to Compare restores
    // the tray as the user left it.
    els.compareResults.hidden = true;
    // Refresh selection-bar so the user sees the single-mode pick
    // again after switching back (selectModel was last called by a
    // picker event that may have been in compare mode).
    if (state.selectedId) selectModel(state.selectedId, { source: 'mode-toggle' });
  }
}

function addToCompare(modelId) {
  if (!state.byId.has(modelId)) return;
  // Idempotent: adding an already-tracked model is a no-op (don't dup).
  if (state.compareIds.includes(modelId)) {
    renderCompareTray();          // still re-paint in case order changed
    return;
  }
  state.compareIds.push(modelId);
  // Cap at 5: FIFO-evict the oldest.
  while (state.compareIds.length > 5) state.compareIds.shift();
  renderCompareTray();
}

function removeFromCompare(modelId) {
  const i = state.compareIds.indexOf(modelId);
  if (i === -1) return;
  state.compareIds.splice(i, 1);
  renderCompareTray();
  // If a result was rendered, clear it (the card count just changed).
  if (els.compareResultsGrid.childElementCount > 0) {
    els.compareResultsGrid.innerHTML = '';
    els.compareResultsCaveat.textContent = '';
    els.compareResults.hidden = true;
  }
}

function clearCompare() {
  if (state.compareIds.length === 0) return;
  state.compareIds = [];
  renderCompareTray();
  els.compareResultsGrid.innerHTML = '';
  els.compareResultsCaveat.textContent = '';
  els.compareResults.hidden = true;
}

function renderCompareTray() {
  els.compareTrayChips.innerHTML = '';
  if (state.compareIds.length === 0) {
    // Empty tray — show a hint inside the chip area instead of nothing,
    // so the user knows the picker below is how they add models.
    const hint = document.createElement('span');
    hint.className = 'compare-tray__hint';
    hint.textContent = 'Pick 2–5 models below ↑';
    els.compareTrayChips.appendChild(hint);
    return;
  }
  const frag = document.createDocumentFragment();
  for (const id of state.compareIds) {
    const m = state.byId.get(id);
    if (!m) continue;
    const chip = document.createElement('span');
    chip.className = 'compare-chip';

    const name = document.createElement('span');
    name.className = 'compare-chip__name';
    name.textContent = m.display_name || id;
    chip.appendChild(name);

    if (m.provider) {
      const prov = document.createElement('span');
      prov.className = 'compare-chip__provider';
      prov.textContent = m.provider;
      chip.appendChild(prov);
    }

    const rm = document.createElement('button');
    rm.type = 'button';
    rm.className = 'compare-chip__remove';
    rm.setAttribute('aria-label', `Remove ${m.display_name || id} from comparison`);
    rm.textContent = '×';
    rm.addEventListener('click', () => removeFromCompare(id));
    chip.appendChild(rm);

    frag.appendChild(chip);
  }
  els.compareTrayChips.appendChild(frag);
}

// Centralized picker handler. In single mode this is the existing
// selectModel() flow (unchanged). In compare mode the picker ADDDS to
// the tray instead of replacing the single selection. All picker
// affordances (popular card body click, popular card <select>, main
// combo) funnel through this so mode-aware behavior is in one place.
function handlePickerPick(modelId, source) {
  if (state.compareMode) {
    addToCompare(modelId);
    // Also keep state.selectedId in sync so if the user toggles back
    // to Single mid-session, the most recent pick shows up in the
    // selection-bar. We don't paint selection-bar here (it's hidden
    // in compare mode); selectModel's side effects are cheap and
    // idempotent.
    if (state.byId.has(modelId)) selectModel(modelId, { source: source + '+compare' });
  } else {
    selectModel(modelId, { source });
  }
}

// ---- Projects (Row 1 — preset dropdown) --------------------------------
// v2.7b: Project picker is now a custom dropdown with category tabs
// (Web / Games / Code / Data). The hidden #project_id input holds the
// selected value so applyProjectPreset() (which reads els.projectSelect.value)
// keeps working unchanged.
const TAB_TO_PREFIX = {
  web:   ['website-', 'mobile-'],
  games: ['game-'],
  code:  ['codebase-', 'refactor-', 'code-'],
  data:  ['database-', 'dataeng-', 'ml-', 'docs-', 'data-'],
};

function getProjectTab(p) {
  if (p.id === 'custom') return null;
  for (const [tab, prefixes] of Object.entries(TAB_TO_PREFIX)) {
    if (prefixes.some(pref => p.id.startsWith(pref))) return tab;
  }
  return 'data'; // fallback for unknown prefixes
}

function formatProjectOption(p) {
  const unit = p.unit || 'unit';
  return p.id === 'custom'
    ? `${p.label}  ·  enter tokens manually`
    : `${p.label}  ·  per ${unit}`;
}

function renderProjects() {
  // Wire the trigger + panel + tabs + list. The list is re-rendered whenever
  // the user switches tabs. State (selected project, data attrs) lives on
  // the hidden #project_id input and on the option items themselves.
  const picker = document.getElementById('project-picker');
  const trigger = document.getElementById('proj-trigger');
  const panel = document.getElementById('proj-panel');
  const customBtn = document.getElementById('proj-custom-btn');
  const tabs = picker ? picker.querySelectorAll('.proj-tab') : [];
  const list = document.getElementById('proj-list');
  const labelEl = document.getElementById('proj-current-label');
  if (!picker || !trigger || !panel || !list) return;

  let activeTab = 'web';

  function openPanel() {
    panel.hidden = false;
    trigger.setAttribute('aria-expanded', 'true');
  }
  function closePanel() {
    panel.hidden = true;
    trigger.setAttribute('aria-expanded', 'false');
  }
  function isOpen() { return !panel.hidden; }

  function selectProject(p) {
    els.projectSelect.value = p.id;
    els.projectSelect.dataset.in = p.avg_input_tokens;
    els.projectSelect.dataset.out = p.avg_output_tokens;
    els.projectSelect.dataset.unit = p.unit || 'unit';
    els.projectSelect.dataset.unitDefault = p.unit_default || 1;
    els.projectSelect.dataset.typicalIterations = p.typical_iterations || 1;
    els.projectSelect.dataset.typicalSize = p.typical_task_size || 'medium';
    els.projectSelect.dataset.typicalWorkflow = p.typical_workflow || '';
    els.projectSelect.dataset.placeholder = String(!!p.placeholder);
    if (labelEl) labelEl.textContent = p.label;
    // Trigger a change event so applyProjectPreset() runs (it's bound to
    // the change event on els.projectSelect historically).
    els.projectSelect.dispatchEvent(new Event('change', { bubbles: true }));
    closePanel();
  }

  function renderList(tab) {
    list.innerHTML = '';
    const items = state.projects.filter(p => getProjectTab(p) === tab);
    for (const p of items) {
      const li = document.createElement('li');
      li.className = 'proj-list__item';
      li.setAttribute('role', 'option');
      li.setAttribute('tabindex', '0');
      li.dataset.id = p.id;
      li.dataset.in = p.avg_input_tokens;
      li.dataset.out = p.avg_output_tokens;
      li.dataset.unit = p.unit || 'unit';
      li.dataset.unitDefault = p.unit_default || 1;
      li.dataset.typicalIterations = p.typical_iterations || 1;
      li.dataset.typicalSize = p.typical_task_size || 'medium';
      li.dataset.typicalWorkflow = p.typical_workflow || '';
      li.dataset.placeholder = String(!!p.placeholder);
      li.innerHTML = `
        <span class="proj-list__name">${p.label}</span>
        <span class="proj-list__meta">per ${p.unit || 'unit'} &middot; ${p.avg_input_tokens.toLocaleString()} in / ${p.avg_output_tokens.toLocaleString()} out</span>
      `;
      li.addEventListener('click', () => selectProject(p));
      li.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectProject(p); }
      });
      list.appendChild(li);
    }
  }

  // Tab clicks
  tabs.forEach(tabBtn => {
    tabBtn.addEventListener('click', () => {
      activeTab = tabBtn.dataset.tab;
      tabs.forEach(t => {
        const on = t === tabBtn;
        t.classList.toggle('is-on', on);
        t.setAttribute('aria-selected', String(on));
      });
      renderList(activeTab);
    });
  });

  // Trigger toggles panel
  trigger.addEventListener('click', (e) => {
    e.stopPropagation();
    isOpen() ? closePanel() : openPanel();
  });

  // Custom button
  customBtn.addEventListener('click', () => {
    const custom = state.projects.find(p => p.id === 'custom');
    if (custom) selectProject(custom);
  });

  // Outside click closes
  document.addEventListener('click', (e) => {
    if (!isOpen()) return;
    if (!picker.contains(e.target)) closePanel();
  });

  // Escape closes
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && isOpen()) { closePanel(); trigger.focus(); }
  });

  // Initial state
  const custom = state.projects.find(p => p.id === 'custom');
  if (custom && labelEl) labelEl.textContent = custom.label;
  renderList(activeTab);
  updateProjectHint();
}

function applyProjectPreset() {
  const opt = els.projectSelect  // hidden input (was <select>; selectedOptions gone);
  if (!opt) return;
  const projectId = opt.value;
  if (projectId === 'custom') {
    // BUGFIX (t_c2b63a6e): switching back to Custom must clear stale preset
    // values from the Advanced token fields, otherwise the user sees the old
    // project's tokens re-priced (e.g. switch LangChain→Custom with no edits
    // and Calculate still uses 8k/4.5k instead of medium preset 5k/2k).
    // If the user actually typed custom values, the dirty flag preserves them.
    if (!inputDirty)  els.inputTokens.value  = '';
    if (!outputDirty) els.outputTokens.value = '';
    els.inputTokens.placeholder  = 'manual';
    els.outputTokens.placeholder = 'manual';
    // v2.7b: revert workflow type to the no-overhead default when the user
    // switches back to Custom (the user is starting from scratch).
    if (els.workflowType && !workflowDirty) {
      els.workflowType.value = 'single-chat';
    }
    updateProjectHint();
    updateAssumptionCaption();
    return;
  }
  // v2.9: auto-fill Iterations and Task size from the preset's typical
  // values. This is what makes the realistic "real-world" cost show up
  // by default — e.g. an animated 3D site defaults to 5 iterations ×
  // large task size, not the 1×medium of the raw preset tokens. User
  // can override either field after.
  const typicalIter = parseInt(opt.dataset.typicalIterations, 10) || 1;
  const typicalSize = opt.dataset.typicalSize || 'medium';
  if (els.iterations && !iterationsDirty) {
    els.iterations.value = String(typicalIter);
  }
  // v2.7b: Workflow type auto-fills from the preset's typical_workflow
  // (optional; falls back to single-chat when unset). Skip if the user
  // manually picked a workflow in Customize for this preset selection.
  if (els.workflowType && !workflowDirty) {
    const tw = opt.dataset.typicalWorkflow;
    els.workflowType.value = tw && WORKFLOW_OVERHEAD[tw] ? tw : 'single-chat';
  }
  const baseIn  = parseInt(opt.dataset.in,  10) || 0;
  const baseOut = parseInt(opt.dataset.out, 10) || 0;
  // v2.7b: task size is no longer a user-facing dropdown. We use the
  // preset's typical_task_size as the implicit multiplier when computing
  // input/output tokens. The backend's task_size default of 'medium' is
  // irrelevant here because we always send explicit input_tokens /
  // output_tokens (the preset math below).
  const mult = TASK_SIZE_MULT[typicalSize] || 1;
  // v2.7b: Iterations still scales the preset's per-unit tokens (same as
  // v2.9) — the field just moved into Customize in the simplified form.
  const iter = Math.max(1, parseInt(els.iterations?.value, 10) || 1);
  const inTok  = Math.max(0, Math.round(baseIn  * mult * iter));
  const outTok = Math.max(0, Math.round(baseOut * mult * iter));
  if (!inputDirty)  els.inputTokens.value  = inTok  || '';
  if (!outputDirty) els.outputTokens.value = outTok || '';
  els.inputTokens.placeholder  = inTok  ? '' : '0';
  els.outputTokens.placeholder = outTok ? '' : '0';
  // Preset fills are NOT user edits — clear the dirty flag so the next
  // Custom switch correctly resets to medium preset instead of preserving
  // these preset values.
  inputDirty  = false;
  outputDirty = false;
  updateProjectHint();
  updateAssumptionCaption();
}

function updateProjectHint() {
  const opt = els.projectSelect  // hidden input (was <select>; selectedOptions gone);
  if (!opt) {
    els.projectHint.textContent = 'Pick a preset to auto-fill the token counts below.';
    els.projectHint.classList.remove('is-warn');
    return;
  }
  const project = state.projects.find((p) => p.id === opt.value);
  if (!project) return;
  if (project.id === 'custom') {
    els.projectHint.textContent = 'Enter your own input/output token counts below.';
    els.projectHint.classList.remove('is-warn');
    return;
  }
  // v2.9: hint shows the per-unit baseline, the current Iterations ×
  // Task size math, and (in plain English) what the typical real-world
  // workload looks like for this project. The typical_* values come from
  // projects.json; users see realistic defaults without touching the
  // form, but every field is editable.
  const unit = project.unit || 'unit';
  const perUnitTxt = `Per 1 ${unit}: ${fmtInt.format(project.avg_input_tokens)} in / ${fmtInt.format(project.avg_output_tokens)} out.`;
  const sizeMult = TASK_SIZE_MULT[els.taskSize?.value || project.typical_task_size || 'medium'] || 1;
  const sizeName = `${(els.taskSize?.value || project.typical_task_size || 'medium')[0].toUpperCase()}${(els.taskSize?.value || project.typical_task_size || 'medium').slice(1)} × ${sizeMult}`;
  const iters = Math.max(1, parseInt(els.iterations?.value, 10) || 1);
  const totalIn = fmtInt.format(project.avg_input_tokens * sizeMult * iters);
  const totalOut = fmtInt.format(project.avg_output_tokens * sizeMult * iters);
  const mathTxt = `${iters} ${unit}${iters === 1 ? '' : 's'} × ${sizeName} → ${totalIn} in / ${totalOut} out`;
  const typicalIter = project.typical_iterations || 1;
  const typicalSize = project.typical_task_size || 'medium';
  const typicalTxt = `Typical real-world: ${typicalIter} ${unit}${typicalIter === 1 ? '' : 's'} × ${typicalSize[0].toUpperCase()}${typicalSize.slice(1)}.`;
  const fullTxt = `${perUnitTxt}  ·  Current: ${mathTxt}  ·  ${typicalTxt}`;
  if (project.placeholder) {
    els.projectHint.textContent = `${fullTxt}  ·  PLACEHOLDER numbers from findings.md §6: refine with vendor-validated data.`;
    els.projectHint.classList.add('is-warn');
  } else {
    els.projectHint.textContent = fullTxt + '.';
    els.projectHint.classList.remove('is-warn');
  }
}

// v2.7b: live assumption caption under the project dropdown. Summarizes
// the current Workflow overhead so the user can see at a glance why a
// calculation might cost more than a baseline single-chat call.
// Updates whenever project / workflow type / iterations / thinking change.
function updateAssumptionCaption() {
  if (!els.assumptionHint) return;
  const wt = els.workflowType?.value || 'single-chat';
  const ov = WORKFLOW_OVERHEAD[wt] || WORKFLOW_OVERHEAD['single-chat'];
  const parts = [];
  parts.push(`Assuming ${ov.label.toLowerCase()}`);
  if (ov.system_prompt_tokens > 0) {
    parts.push(`+${fmtInt.format(ov.system_prompt_tokens)} sys prompt`);
  } else {
    parts.push('no sys prompt');
  }
  if (ov.tool_call_count > 0) {
    parts.push(`${ov.tool_call_count} tool calls`);
  } else {
    parts.push('no tool calls');
  }
  if (ov.retry_mult > 1) {
    parts.push(`${ov.retry_mult}× retries`);
  } else {
    parts.push('1× retries');
  }
  els.assumptionHint.textContent = parts.join(' · ') + '.';
}

// ---- Meta strip ---------------------------------------------------------
// v2.9: the topbar meta-strip ("348 models (336 live via OpenRouter) ·
// refresh 6h" + green dot) was removed — it read as "AI status pill" and
// duplicated info already in the hero subtext and the picker label.
// setMeta() is kept as a no-op stub in case we ever add a status pill
// somewhere subtler (a small refresh-time caption under the hero, etc.).
// For now it just stashes the root on state so /health callers can still
// inspect it via the dev console.
function setMeta(root) {
  state.root = root;
}

// v2.9: update the popular-row label to read "N of M" where N is the
// number of company cards rendered and M is the live model count. Cheap
// to compute; lets the label stay accurate as OpenRouter refreshes
// every 6h. Called once after loadAll() resolves.
function setPopularCount() {
  if (!els.popularCount) return;
  const n = state.popular.length;
  const m = state.models.length;
  els.popularCount.textContent = `${n} of ${m}`;
}

// ---- Calculate ---------------------------------------------------------
async function onCalculate(e) {
  e.preventDefault();
  if (state.busy) return;
  hideError();
  hideResult();

  if (!state.selectedId) return showError('Pick a model to estimate.');

  const thinking = els.thinkingSelect.value || 'off';
  const explicitIn  = els.inputTokens.value.trim();
  const explicitOut = els.outputTokens.value.trim();
  // v2.7b: workflow overhead — bundles sys prompt + tool calls + retry
  // multiplier. Maps to backend agentic + system_prompt_tokens +
  // tool_call_count (single-chat is the only "no overhead" preset; every
  // other preset flips agentic=True).
  const wt = els.workflowType?.value || 'single-chat';
  const ov = WORKFLOW_OVERHEAD[wt] || WORKFLOW_OVERHEAD['single-chat'];
  const body = {
    model_id: state.selectedId,
    // task_size is still sent (brief keeps it in payload) but the user
    // can't edit it — it's a backend fallback in case input/output
    // tokens are omitted. We always send them explicitly.
    task_size: 'medium',
    num_runs: Math.max(1, parseInt(els.numRuns.value, 10) || 1),
    // v2.7b: agentic flag + per-overhead knobs. Single-chat sends false
    // and zero overrides so the backend doesn't add any overhead. Other
    // presets flip agentic=True and pass the preset's sys/tools values.
    agentic: ov.retry_mult > 1,
    system_prompt_tokens: ov.system_prompt_tokens,
    tool_call_count: ov.tool_call_count,
  };
  // v2.1 fix: backend reasoning_level enum is low/medium/high/extreme only
  // (no "off" — that was a v2 handoff oversight; the API returned 422).
  // Omit the field entirely when off; backend defaults to no-reasoning.
  if (thinking !== 'off') body.reasoning_level = thinking;
  if (explicitIn)  body.input_tokens  = Math.max(0, parseInt(explicitIn, 10));
  if (explicitOut) body.output_tokens = Math.max(0, parseInt(explicitOut, 10));

  setBusy(true);
  try {
    const r = await fetch(`${API}/calculate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const detail = await safeJson(r);
      throw new Error(detail?.detail || detail?.message || `HTTP ${r.status}`);
    }
    const data = await r.json();
    renderResult(data);
  } catch (err) {
    showError(err.message || String(err));
  } finally {
    setBusy(false);
  }
}

async function safeJson(r) {
  try { return await r.json(); } catch { return null; }
}

function renderResult(d) {
  els.resultEyebrow.textContent = d.num_runs > 1
    ? `Total · ${d.num_runs.toLocaleString()} runs`
    : 'Per call';

  els.resultAmount.textContent = fmtMoney(d.total_cost ?? d.cost_per_run);

  const parts = [];
  if (d.input_cost > 0)    parts.push(`Input ${fmtMoney2(d.input_cost)}`);
  if (d.output_cost > 0)   parts.push(`Output ${fmtMoney2(d.output_cost)}`);
  if (d.reasoning_cost > 0) parts.push(`Reasoning ${fmtMoney2(d.reasoning_cost)}`);
  if (d.tool_cost > 0)     parts.push(`Tools ${fmtMoney2(d.tool_cost)}`);
  if (d.image_cost > 0)    parts.push(`Images ${fmtMoney2(d.image_cost)}`);
  if (parts.length === 0)  parts.push('Free');
  els.resultBreak.textContent = parts.join(' · ');

  const tu = d.tokens_used || {};
  const tokLine = [
    fmtTokens(tu.input_tokens)  + ' in',
    fmtTokens(tu.output_tokens) + ' out',
  ];
  if (tu.reasoning_tokens > 0) tokLine.push(fmtTokens(tu.reasoning_tokens) + ' reasoning');
  if (tu.cached_input_tokens > 0) tokLine.push(fmtTokens(tu.cached_input_tokens) + ' cached');
  els.resultMulti.textContent = tokLine.join(' · ') + ' tokens';

  // v2.7b: per-toggle impact statements. Each active multiplier shows
  // the marginal cost it added so the user can see WHY the total is what
  // it is — without re-running the calc without the toggle. Style: same
  // muted caption as resultCaveat (no new colors, no new classes).
  //
  // Use the ACTUAL values from the backend's response (assumptions dict)
  // instead of the workflow constants — the backend hardcodes the retry
  // multiplier to AGENTIC_MULTIPLIER (1.4×) whenever agentic=True, so the
  // requested per-workflow multipliers (1.0/1.2/1.1/1.4/1.6) only affect
  // sys-prompt + tool-call values. Showing the requested multiplier when
  // the applied one differs would mislead the user.
  const wt = els.workflowType?.value || 'single-chat';
  const ov = WORKFLOW_OVERHEAD[wt] || WORKFLOW_OVERHEAD['single-chat'];
  const m = state.byId.get(state.selectedId);
  const a = d.assumptions || {};
  const actualSys = a.agentic_system_prompt_tokens_effective ?? 0;
  const actualTools = a.agentic_tool_call_count_effective ?? 0;
  const actualMult = a.agentic_multiplier_applied ?? 1.0;
  const impactBits = [];
  // Workflow impact: sys-prompt cost + tool cost + retry-multiplier extra,
  // all computed against the ACTUAL values the backend applied. Sys/tool
  // costs are computed directly from the model's prices; the retry
  // multiplier extra = base_cost × (mult-1) where base_cost = cost_per_run
  // / multiplier. We skip the line entirely when no overhead applied.
  if (actualMult > 1 || actualSys > 0 || actualTools > 0) {
    const sysCost  = (actualSys * (m?.input_per_1m ?? 0)) / 1_000_000;
    const toolCost = actualTools * (m?.tool_call_cost ?? 0);
    // cost_per_run includes the multiplier; back out the base to isolate
    // the retry-only portion. Edge case: cost_per_run === 0 → skip retry.
    let retryExtra = 0;
    if (actualMult > 1 && (d.cost_per_run || 0) > 0) {
      retryExtra = (d.cost_per_run / actualMult) * (actualMult - 1);
    }
    const totalImpact = sysCost + toolCost + retryExtra;
    if (totalImpact > 0) {
      const sysTxt = actualSys > 0 ? `${fmtInt.format(actualSys)} sys` : '';
      const toolTxt = actualTools > 0 ? `${actualTools} tools` : '';
      const detailBits = [sysTxt, toolTxt, `${actualMult}×`].filter(Boolean).join(' · ');
      impactBits.push(`+${fmtMoney2(totalImpact)} from ${ov.label}: ${detailBits}`);
    }
  }
  // Reasoning impact: marginal output-token cost from the multiplier.
  // Only show when reasoning is on (medium/high/extreme). Reasoning models
  // additionally bill reasoning_tokens at the dedicated reasoning_per_1m
  // rate — that's already in the main breakdown, so we surface just the
  // output-multiplier delta here.
  const rMult = d.assumptions?.reasoning_level_multiplier;
  if (rMult && rMult > 1 && (d.output_cost || 0) > 0) {
    const reasonImpact = d.output_cost * (rMult - 1) / rMult;
    const lvl = els.thinkingSelect.value || 'low';
    impactBits.push(`+${fmtMoney2(reasonImpact)} from ${lvl} reasoning (${rMult}×)`);
  }

  let caveat = impactBits.length
    ? impactBits.join('  ·  ')
    : '';
  caveat += '  ·  Estimate: verify against vendor pricing before quoting.';
  els.resultCaveat.textContent = caveat;

  els.result.hidden = false;
  els.result.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function hideResult() { els.result.hidden = true; }
function setBusy(b) {
  state.busy = b;
  els.calcBtn.disabled = b;
  els.calcBtn.querySelector('.calc-btn__label').textContent = b ? 'Calculating…' : 'Calculate';
}
function showError(msg) {
  els.formError.textContent = msg;
  els.formError.hidden = false;
}
function hideError() {
  els.formError.hidden = true;
  els.formError.textContent = '';
}

// ---- v2.9 — Compare calculate + result ---------------------------------
// Same workload (tokens, task_size, task_type, reasoning_level, num_runs)
// applied to all models in the tray. POSTs model_ids[] to /calculate/compare
// and renders a row of cards sorted cheapest-first.
async function onCalculateCompare() {
  if (state.busy) return;
  hideError();
  els.compareResults.hidden = true;
  els.compareResultsGrid.innerHTML = '';
  els.compareResultsCaveat.textContent = '';

  if (state.compareIds.length < 2) {
    return showError('Pick at least 2 models to compare.');
  }

  const thinking = els.thinkingSelect.value || 'off';
  const explicitIn  = els.inputTokens.value.trim();
  const explicitOut = els.outputTokens.value.trim();
  // v2.7b: same workflow overhead mapping as onCalculate — applies to
  // every model in the comparison.
  const wt = els.workflowType?.value || 'single-chat';
  const ov = WORKFLOW_OVERHEAD[wt] || WORKFLOW_OVERHEAD['single-chat'];
  const body = {
    model_ids: state.compareIds.slice(),
    task_size: 'medium',
    num_runs: Math.max(1, parseInt(els.numRuns.value, 10) || 1),
    agentic: ov.retry_mult > 1,
    system_prompt_tokens: ov.system_prompt_tokens,
    tool_call_count: ov.tool_call_count,
  };
  // Same reasoning_level handling as the single-mode path (v2.1 fix).
  if (thinking !== 'off') body.reasoning_level = thinking;
  if (explicitIn)  body.input_tokens  = Math.max(0, parseInt(explicitIn, 10));
  if (explicitOut) body.output_tokens = Math.max(0, parseInt(explicitOut, 10));

  setBusy(true);
  try {
    const r = await fetch(`${API}/calculate/compare`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const detail = await safeJson(r);
      throw new Error(detail?.detail || detail?.message || `HTTP ${r.status}`);
    }
    const data = await r.json();
    renderCompareResult(data, body);
  } catch (err) {
    showError(err.message || String(err));
  } finally {
    setBusy(false);
  }
}

// Render the compare-result row. Backend returns results in REQUEST
// order (not sorted); we sort by total_cost ascending and mark the
// cheapest card with the teal border + "Cheapest" badge.
function renderCompareResult(data, requestBody) {
  const results = Array.isArray(data.results) ? data.results : [];
  // Sort ascending by total_cost (treat missing as Infinity so free /
  // missing cards sort last; cheap-first ordering is the user's intent).
  const sorted = results.slice().sort((a, b) => {
    const ca = Number.isFinite(a.total_cost) ? a.total_cost : Infinity;
    const cb = Number.isFinite(b.total_cost) ? b.total_cost : Infinity;
    return ca - cb;
  });
  els.compareResultsGrid.innerHTML = '';
  const frag = document.createDocumentFragment();
  sorted.forEach((r, i) => {
    const isCheapest = i === 0;
    const isFree = r.total_cost === 0;
    const card = document.createElement('div');
    card.className = 'compare-card' + (isCheapest ? ' is-cheapest' : '') + (isFree ? ' is-free' : '');

    if (isCheapest) {
      const badge = document.createElement('span');
      badge.className = 'compare-card__badge';
      badge.textContent = 'Cheapest';
      card.appendChild(badge);
    }

    const name = document.createElement('div');
    name.className = 'compare-card__name';
    name.textContent = r.display_name || r.model_id;
    name.title = r.model_id;
    card.appendChild(name);

    const amount = document.createElement('p');
    amount.className = 'compare-card__amount';
    amount.textContent = isFree ? 'free' : fmtMoney(r.total_cost ?? r.cost_per_run);
    card.appendChild(amount);

    const breakdown = document.createElement('div');
    breakdown.className = 'compare-card__breakdown';
    const parts = [];
    if (r.input_cost > 0)    parts.push(`In ${fmtMoney2(r.input_cost)}`);
    if (r.output_cost > 0)   parts.push(`Out ${fmtMoney2(r.output_cost)}`);
    if (r.reasoning_cost > 0) parts.push(`Reas ${fmtMoney2(r.reasoning_cost)}`);
    if (parts.length === 0) parts.push('Free');
    breakdown.textContent = parts.join(' · ');
    card.appendChild(breakdown);

    const perRun = document.createElement('div');
    perRun.className = 'compare-card__perrun';
    const runs = r.num_runs || 1;
    if (runs > 1) {
      perRun.textContent = `${runs.toLocaleString()} runs · ${fmtMoney(r.cost_per_run)}/run`;
    } else {
      perRun.textContent = `${fmtMoney(r.cost_per_run)} / run`;
    }
    card.appendChild(perRun);

    frag.appendChild(card);
  });
  els.compareResultsGrid.appendChild(frag);

  // Caveat: surface reasoning/workflow overhead when they apply, and
  // remind that all numbers are estimates (same caveat as single).
  const caveatBits = [];
  if (requestBody.reasoning_level && requestBody.reasoning_level !== 'off') {
    caveatBits.push(`${requestBody.reasoning_level} thinking applied`);
  }
  // v2.7b: replace the old task_type line with the workflow label so
  // the user sees which overhead preset is in play.
  const wt = els.workflowType?.value || 'single-chat';
  const ov = WORKFLOW_OVERHEAD[wt] || WORKFLOW_OVERHEAD['single-chat'];
  if (ov.retry_mult > 1 || ov.system_prompt_tokens > 0 || ov.tool_call_count > 0) {
    caveatBits.push(`${ov.label.toLowerCase()} overhead applied`);
  }
  let caveat = 'Same workload applied to all models — cheapest card highlighted.';
  if (caveatBits.length) caveat += ' ' + caveatBits.join(' · ') + '.';
  caveat += ' Estimate: verify against vendor pricing before quoting.';
  els.compareResultsCaveat.textContent = caveat;

  els.compareResults.hidden = false;
  els.compareResults.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// Form submit dispatcher: in single mode call onCalculate; in compare
// mode call onCalculateCompare. Both handlers do their own validation.
// We always preventDefault here so the form never submits as a GET —
// both handlers are async (fetch) and don't want the browser to
// navigate away before they complete.
function onCalcSubmit(e) {
  e.preventDefault();
  if (state.compareMode) {
    onCalculateCompare();
  } else {
    onCalculate(e);
  }
}

// ---- Local GPU ----------------------------------------------------------
function populateLocalGpus() {
  els.localGpu.innerHTML = '';
  for (const g of state.localGpus) {
    const opt = document.createElement('option');
    opt.value = g.gpu_id || g.id;
    opt.textContent = `${g.display_name || opt.value}  ·  ${g.default_tokens_per_second} tok/s · ${g.vram_gb} GB VRAM`;
    els.localGpu.appendChild(opt);
  }
  if ([...els.localGpu.options].some((o) => o.value === 'nvidia-rtx-4090')) {
    els.localGpu.value = 'nvidia-rtx-4090';
  }
}
function populateLocalModels() {
  els.localModel.innerHTML = '';
  for (const m of state.localModels) {
    const opt = document.createElement('option');
    opt.value = m.model_id || m.id;
    opt.textContent = `${m.display_name || opt.value}  ·  ${m.parameters_b}B params`;
    els.localModel.appendChild(opt);
  }
  if ([...els.localModel.options].some((o) => o.value === 'llama3.3:70b')) {
    els.localModel.value = 'llama3.3:70b';
  }
}

async function onLocalCalculate(e) {
  e.preventDefault();
  if (state.busy) return;
  els.localResult.hidden = true;

  const body = {
    model_id: els.localModel.value,
    gpu_id: els.localGpu.value,
    gpu_cost_per_hour: Math.max(0, parseFloat(els.gpuCost.value) || 0),
    power_cost_per_kwh: Math.max(0, parseFloat(els.powerCost.value) || 0),
    utilization: 1.0,
    task_size: els.localTaskSize.value || 'medium',
    task_type: 'chat',
    num_runs: 1,
  };
  if (!body.model_id || !body.gpu_id) return;

  els.localBtn.disabled = true;
  try {
    const r = await fetch(`${API}/calculate/local`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const detail = await safeJson(r);
      throw new Error(detail?.detail || `HTTP ${r.status}`);
    }
    const d = await r.json();
    renderLocalResult(d);
  } catch (err) {
    els.localCaveat.textContent = (err.message || String(err));
    els.localCaveat.style.color = 'var(--teal-ink)';
    els.localResult.hidden = false;
  } finally {
    els.localBtn.disabled = false;
  }
}

function renderLocalResult(d) {
  els.localEyebrow.textContent = `Self-hosted · ${d.gpu_display_name || d.gpu_id}`;
  els.localAmount.textContent = fmtMoney2(d.cost_per_run);
  const tokLine = `≈ ${fmtTokens(d.total_tokens)} tokens/run · ${d.tokens_per_second} tok/s on ${d.gpu_display_name || d.gpu_id}`;
  const costLine = `$${d.cost_per_million_tokens_usd.toFixed(2)} per 1M tokens · $${d.cost_per_hour_usd.toFixed(2)}/hr`;
  const assumptionNote = d.assumptions?.tokens_per_second_source === 'fallback'
    ? ' (throughput estimated; pass `tokens_per_second` for accuracy)'
    : '';
  els.localBreak.textContent = `${costLine}\n${tokLine}${assumptionNote}`;
  els.localCaveat.style.color = '';
  els.localCaveat.textContent = 'PLACEHOLDER throughput figures: verify against current benchmarks before quoting.';
  els.localResult.hidden = false;
}

function onLocalToggle() {
  const open = els.localToggle.getAttribute('aria-expanded') === 'true';
  const next = !open;
  els.localToggle.setAttribute('aria-expanded', String(next));
  els.localPanel.hidden = !next;
}

// ---- Wire up ------------------------------------------------------------
function init() {
  // v2.7b: prove-once console marker. If you see this in the browser
  // console, you're running THIS version of app.js. If you don't, the
  // browser is still serving a cached copy (or an older v2.9.x build).
  console.log('AI Cost Calculator app.js?v=2.7b loaded (workflow type + simplified form)');
  // Combo
  els.comboButton.addEventListener('click', () => {
    if (state.comboOpen) closeCombo(); else openCombo();
  });
  els.comboSearch.addEventListener('input', () => {
    const v = els.comboSearch.value;
    els.comboClear.hidden = !v;
    filterCombo(v);
  });
  els.comboSearch.addEventListener('keydown', onComboKey);
  els.comboClear.addEventListener('click', () => {
    els.comboSearch.value = '';
    els.comboClear.hidden = true;
    filterCombo('');
    els.comboSearch.focus();
  });

  // Form
  els.projectSelect.addEventListener('change', applyProjectPreset);
  // v2.9: Iterations input re-runs the preset on change. Same trigger
  // v2.9.2: when the user edits Iterations or Task size, just recompute
  // the math (input_tokens, output_tokens) WITHOUT calling applyProjectPreset.
  // v2.7b: Task size dropdown is gone — the implicit multiplier is the
  // preset's typical_task_size. Iterations still scales the math. We
  // also refresh the live assumption caption so the user sees the
  // updated workflow overhead as they type.
  function recomputeFromForm() {
    const opt = els.projectSelect  // hidden input (was <select>; selectedOptions gone);
    if (!opt || opt.value === 'custom') {
      updateProjectHint();
      updateAssumptionCaption();
      return;
    }
    const baseIn  = parseInt(opt.dataset.in,  10) || 0;
    const baseOut = parseInt(opt.dataset.out, 10) || 0;
    const typicalSize = opt.dataset.typicalSize || 'medium';
    const mult = TASK_SIZE_MULT[typicalSize] || 1;
    const iter = Math.max(1, parseInt(els.iterations?.value, 10) || 1);
    const inTok  = Math.max(0, Math.round(baseIn  * mult * iter));
    const outTok = Math.max(0, Math.round(baseOut * mult * iter));
    if (!inputDirty)  els.inputTokens.value  = inTok  || '';
    if (!outputDirty) els.outputTokens.value = outTok || '';
    updateProjectHint();
    updateAssumptionCaption();
  }
  els.iterations.addEventListener('input',  () => { iterationsDirty = true;  });
  els.iterations.addEventListener('input',  recomputeFromForm);
  // Track manual edits to the Advanced token fields. The dirty flag is set on
  // 'input' (every keystroke). applyProjectPreset() clears it whenever a
  // preset fills the field — preset fills are not "user edits", and the next
  // switch to Custom should reset to medium preset, not preserve stale values.
  els.inputTokens.addEventListener('input',  () => { inputDirty  = true;  });
  els.outputTokens.addEventListener('input', () => { outputDirty = true;  });
  // Token counter: heuristic chars÷4 estimator. Pure client-side UX —
  // the textarea content is NEVER sent to the API. "Use this number"
  // writes the estimate into input_tokens so the user can price their
  // actual prompt without re-typing a number. Empty textarea disables
  // the button; overwriting an existing value prompts for confirmation.
  function wireTokenCounter() {
    const ta    = els.promptText;
    const numEl = els.tokenCounterNum;
    const chrEl = els.tokenCounterChars;
    const apply = els.tokenCounterApply;
    if (!ta || !numEl || !chrEl || !apply) return; // defensive — block missing
    function update() {
      const text  = ta.value;
      const chars = text.length;
      // Math.ceil(length / 4) — the rule-of-thumb estimator. Real tokenizers
      // for English prose land within ±20%; code and CJK tokenize heavier
      // (so we undercount there); JSON / structured data tokenizes lighter
      // (so we overcount). The hint above the count makes this trade-off
      // explicit so the user can sanity-check against the char count.
      const tokens = Math.ceil(chars / 4);
      numEl.textContent = fmtInt.format(tokens);
      chrEl.textContent = fmtInt.format(chars);
      apply.disabled = tokens === 0;
    }
    ta.addEventListener('input', update);
    update(); // initial render so the readout shows 0 / 0 instead of empty
    apply.addEventListener('click', () => {
      const text = ta.value;
      const tokens = Math.ceil(text.length / 4);
      if (tokens === 0) return; // disabled, but defensive
      const cur = els.inputTokens.value.trim();
      if (cur !== '' && cur !== '0' &&
          !window.confirm(`Replace the current input_tokens value (${cur}) with ${fmtInt.format(tokens)}?`)) {
        return;
      }
      els.inputTokens.value = tokens;
      // Mark dirty so applyProjectPreset() does not silently clobber the
      // user's paste-derived value the next time they pick a preset.
      inputDirty = true;
      // Brief teal flash on the input field so the user sees the value
      // land, even when the input sits far above the counter button.
      els.inputTokens.classList.remove('is-flash');
      // Force a reflow so the animation re-runs on rapid double-clicks.
      void els.inputTokens.offsetWidth;
      els.inputTokens.classList.add('is-flash');
      setTimeout(() => els.inputTokens.classList.remove('is-flash'), 650);
      els.inputTokens.focus();
    });
  }
  wireTokenCounter();
  els.thinkingSelect.addEventListener('change', () => {
    // If user picks "off" we don't change the hint; otherwise mention it.
    const lvl = els.thinkingSelect.value;
    if (lvl === 'off') {
      const m = state.byId.get(state.selectedId);
      els.thinkingHint.textContent = m && m.supports_reasoning
        ? 'This model supports reasoning tokens. Off means no extra cost.'
        : 'Reasoning disabled, no extra output multiplier.';
    }
  });
  // v2.7b: workflow type change updates the live assumption caption and
  // marks the field dirty so subsequent project changes don't overwrite
  // the user's manual override.
  if (els.workflowType) {
    els.workflowType.addEventListener('change', () => {
      workflowDirty = true;
      updateAssumptionCaption();
    });
  }
  // v2.8: favorites toggle. aria-pressed mirrors state; we re-paint the
  // combo list (if open) so the filter takes effect immediately.
  els.favToggle.addEventListener('click', () => {
    state.favoritesOnly = !state.favoritesOnly;
    els.favToggle.classList.toggle('is-on', state.favoritesOnly);
    els.favToggle.setAttribute('aria-pressed', String(state.favoritesOnly));
    els.favToggle.setAttribute('aria-label',
      state.favoritesOnly ? 'Show all models' : 'Show favorites only');
    state.comboFiltered = computeComboList(els.comboSearch.value);
    state.comboActiveIdx = state.comboFiltered.length ? 0 : -1;
    if (state.comboOpen) paintCombo();
  });
  els.calcForm.addEventListener('submit', onCalcSubmit);
  els.localForm.addEventListener('submit', onLocalCalculate);
  els.localToggle.addEventListener('click', onLocalToggle);

  // v2.9: mode toggle + compare-tray clear button. The mode toggle is
  // a flat switch — no need for aria-controls wiring beyond the role
  // already on the pills. The clear button calls clearCompare() which
  // is a no-op when the tray is empty (so we don't need to disable it).
  els.modeSingle.addEventListener('click',  () => setMode('single'));
  els.modeCompare.addEventListener('click', () => setMode('compare'));
  els.compareTrayClear.addEventListener('click', clearCompare);

  // v2.8: read persisted favorites before the first paint so the count
  // badge + selection-bar star are correct on first load.
  loadFavorites();
  updateFavCount();

  loadAll();
}

async function loadAll() {
  try {
    const [root, models, gpus, localModels, projects, popular] = await Promise.all([
      loadRoot(), loadModels(), loadLocalGpus(), loadLocalModels(),
      loadProjects(), loadPopular(),
    ]);
    state.models = models;
    state.byId = new Map(models.map((m) => [idOf(m), m]));
    state.localGpus = gpus;
    state.localModels = localModels;
    state.projects = projects;
    state.popular = popular;
    // v2.9: root response is no longer surfaced in the topbar (the meta
    // strip was removed); the data is still useful for /health checks
    // and could be reused by future UI (e.g. a "last refreshed" pill).
    state.root = root;

    renderProjects();
    renderPopular();
    renderCombo();
    // v2.9: the popular row label reads "Popular · N of M" where N is the
    // number of company cards rendered and M is the live model count. Keeps
    // the label honest as the OpenRouter feed adds/drops models between
    // refreshes (every 6h). Cheap to compute; the user sees an accurate
    // "subset of the catalog" hint.
    setPopularCount();

    // v2.8: drop favorites whose IDs no longer exist in the live model
    // set (e.g. OpenRouter removed a model). Persisted as soon as it's
    // pruned so the count badge and localStorage stay in sync.
    pruneFavorites();
    updateFavCount();

    // Default selection: first popular whose default_model exists in /models,
    // else first model overall. v2.2: popular cards are no longer pinned to
    // a specific model_id — we use the popular entry's `default_model` field
    // for the first-load selection (typically the company's flagship).
    const firstPopular = popular.find((p) => p.default_model && state.byId.has(p.default_model));
    const defaultId = firstPopular ? firstPopular.default_model : idOf(models[0]);
    if (defaultId) selectModel(defaultId, { source: 'init' });

    // v2.9.1: trigger the project change handler so Iterations and Task
    // size get auto-filled from the selected project's typical_* values.
    // This handles page reload, where the browser preserves the project
    // select value but does NOT fire a synthetic change event. Without
    // this call, the fields stay at 1/medium after every reload.
    // On a fresh page load (project='custom'), applyProjectPreset bails
    // out early in the custom branch, so this is a no-op.
    applyProjectPreset();

    populateLocalGpus();
    populateLocalModels();
  } catch (err) {
    // v2.9: meta-strip + dot are gone; the form error is the only surface
    // for load failures. The .form-error slot is already wired below.
    showError(`Could not reach the AI Cost Calculator API at ${API}. ` +
              `Is the backend running? ${err.message || err}`);
  }
}

document.addEventListener('DOMContentLoaded', init);