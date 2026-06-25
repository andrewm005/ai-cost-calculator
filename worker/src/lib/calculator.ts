/**
 * Core cost calculation logic — port of app/calculator.py.
 *
 * Pure functions. The Calculator just resolves a model, applies multipliers,
 * then sums components. No I/O.
 *
 * This is THE most critical file in the TypeScript port: outputs must match
 * the Python implementation byte-for-byte (down to 1e-9 precision in tests).
 * See tests/calculator.test.ts for the equivalence suite.
 */

import type { ModelPricing } from './pricing.js';

// ---------------------------------------------------------------------------
// Presets + multipliers (must match app/calculator.py exactly)
// ---------------------------------------------------------------------------

export const TASK_SIZE_PRESETS: Record<string, [number, number]> = {
  tiny: [200, 100],
  small: [1_000, 500],
  medium: [5_000, 2_000],
  large: [20_000, 8_000],
  huge: [100_000, 30_000],
  // New project-scale entries based on research
  website: [15_000, 3_500],         // Typical 3D animated site
  webapp: [50_000, 12_000],          // Full Next.js app
  'codebase-small': [60_000, 20_000],     // Python package ~5k lines
  'codebase-medium': [300_000, 100_000],  // Node.js webapp ~25k lines
  'codebase-large': [1_200_000, 400_000], // Large monorepo ~100k lines
  'mobile-app': [120_000, 50_000],        // iOS SwiftUI full app
  'ml-pipeline': [70_000, 25_000],        // PyTorch CV pipeline
  'game-2d': [80_000, 30_000],            // Full RPG Phaser.js
  'game-3d': [500_000, 200_000],          // 3D multiplayer
  'refactor-large': [800_000, 400_000],   // Monolith to microservices
};

export const REASONING_MULTIPLIERS: Record<string, number> = {
  low: 1.0,
  medium: 1.2,
  high: 1.5,
  extreme: 2.5,
};

export const TASK_TYPE_MULTIPLIERS: Record<string, number> = {
  chat: 1.0,
  writing: 1.0,
  coding: 1.1,
  research: 1.15,
  agentic: 1.4, // DEPRECATED — use agentic flag on CalculationRequest
};

export const AGENTIC_DEFAULT_TOOL_CALL_COUNT = 5;
export const AGENTIC_DEFAULT_SYSTEM_PROMPT_TOKENS = 2000;
export const AGENTIC_MULTIPLIER = 1.4;

// ---------------------------------------------------------------------------
// Request / Result types
// ---------------------------------------------------------------------------

export interface CalculationRequest {
  model_id: string;
  input_tokens?: number | null;
  output_tokens?: number | null;
  cached_input_tokens?: number;
  reasoning_tokens?: number;
  tool_call_count?: number;
  image_input_count?: number;
  num_runs?: number;
  task_size?: string | null;
  reasoning_level?: string;
  agentic?: boolean;
  system_prompt_tokens?: number;
  task_type?: string;
}

export interface TokensUsed {
  input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  cached_input_tokens: number;
}

export interface CalculationResult {
  model_id: string;
  display_name: string;
  input_cost: number;
  output_cost: number;
  reasoning_cost: number;
  tool_cost: number;
  image_cost: number;
  cost_per_run: number;
  total_cost: number;
  num_runs: number;
  tokens_used: TokensUsed;
  explanation: string;
  assumptions: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Calculator
// ---------------------------------------------------------------------------

export class Calculator {
  private readonly models: Record<string, ModelPricing>;

  constructor(...models: ModelPricing[]) {
    this.models = {};
    for (const m of models) {
      this.models[m.model_id] = m;
    }
  }

  addModel(model: ModelPricing): void {
    this.models[model.model_id] = model;
  }

  private getModel(modelId: string): ModelPricing {
    if (!(modelId in this.models)) {
      const available = Object.keys(this.models).sort().join(', ');
      throw new Error(`Unknown model '${modelId}'. Available: ${available}`);
    }
    return this.models[modelId];
  }

  calculate(req: CalculationRequest): CalculationResult {
    const model = this.getModel(req.model_id);
    const numRuns = req.num_runs ?? 1;
    const effectiveToolCalls = effectiveToolCallCount(req);
    const tokens = this.resolveTokens(req, model);
    const components = priceComponents(
      model,
      tokens,
      effectiveToolCalls,
      req.image_input_count ?? 0,
    );
    const perRunBase = components.input + components.output + components.reasoning + components.tool + components.image;
    const typeMult = effectiveTypeMultiplier(req);
    const costPerRun = perRunBase * typeMult;
    const total = costPerRun * numRuns;

    const explanation = buildExplanation(
      model,
      req,
      tokens,
      components,
      costPerRun,
      total,
      effectiveToolCalls,
      typeMult,
    );

    return {
      model_id: model.model_id,
      display_name: model.display_name,
      input_cost: components.input,
      output_cost: components.output,
      reasoning_cost: components.reasoning,
      tool_cost: components.tool,
      image_cost: components.image,
      cost_per_run: costPerRun,
      total_cost: total,
      num_runs: numRuns,
      tokens_used: tokens,
      explanation,
      assumptions: {
        task_type_multiplier: typeMult,
        reasoning_level_multiplier: REASONING_MULTIPLIERS[req.reasoning_level ?? 'low'] ?? 1.0,
        agentic: req.agentic ?? false,
        agentic_tool_call_count_effective: effectiveToolCalls,
        agentic_system_prompt_tokens_effective: effectiveSystemPromptTokens(req),
        agentic_multiplier_applied: req.agentic ? AGENTIC_MULTIPLIER : 1.0,
      },
    };
  }

  compare(modelIds: string[], kwargs: Omit<CalculationRequest, 'model_id'> = {}): CalculationResult[] {
    const out: CalculationResult[] = [];
    for (const mid of modelIds) {
      out.push(this.calculate({ ...kwargs, model_id: mid }));
    }
    return out;
  }

  // ---- internals ----

  private resolveTokens(req: CalculationRequest, model: ModelPricing): TokensUsed {
    let inT: number;
    let outT: number;

    if (req.task_size && req.task_size in TASK_SIZE_PRESETS) {
      const [presetIn, presetOut] = TASK_SIZE_PRESETS[req.task_size]!;
      inT = req.input_tokens != null ? req.input_tokens : presetIn;
      outT = req.output_tokens != null ? req.output_tokens : presetOut;
    } else {
      inT = req.input_tokens ?? 0;
      outT = req.output_tokens ?? 0;
    }

    // Reasoning level inflates output
    const outMult = REASONING_MULTIPLIERS[req.reasoning_level ?? 'low'] ?? 1.0;
    outT = Math.trunc(outT * outMult);

    // Reasoning tokens only valid if model supports them
    const reasoning = model.supports_reasoning ? (req.reasoning_tokens ?? 0) : 0;

    // Agentic system-prompt overhead
    const sysPrompt = effectiveSystemPromptTokens(req);
    inT = inT + sysPrompt;

    // Cached subset cannot exceed total input (including agentic sys prompt)
    const cached = Math.max(0, Math.min(req.cached_input_tokens ?? 0, inT));

    return {
      input_tokens: inT,
      output_tokens: outT,
      reasoning_tokens: reasoning,
      cached_input_tokens: cached,
    };
  }
}

// ---------------------------------------------------------------------------
// Pure helpers (exported for tests + reused by /calculate/local)
// ---------------------------------------------------------------------------

export function effectiveToolCallCount(req: CalculationRequest): number {
  if ((req.tool_call_count ?? 0) > 0) {
    return req.tool_call_count!;
  }
  return req.agentic ? AGENTIC_DEFAULT_TOOL_CALL_COUNT : 0;
}

export function effectiveSystemPromptTokens(req: CalculationRequest): number {
  if (!req.agentic) return 0;
  return (req.system_prompt_tokens ?? 0) > 0
    ? req.system_prompt_tokens!
    : AGENTIC_DEFAULT_SYSTEM_PROMPT_TOKENS;
}

export function effectiveTypeMultiplier(req: CalculationRequest): number {
  if (req.agentic) return AGENTIC_MULTIPLIER;
  return TASK_TYPE_MULTIPLIERS[req.task_type ?? 'chat'] ?? 1.0;
}

export interface PriceComponents {
  input: number;
  output: number;
  reasoning: number;
  tool: number;
  image: number;
}

export function priceComponents(
  model: ModelPricing,
  tokens: TokensUsed,
  effectiveToolCalls: number,
  imageInputCount: number,
): PriceComponents {
  const uncached = Math.max(0, tokens.input_tokens - tokens.cached_input_tokens);
  const inputCost =
    (uncached * model.input_per_1m + tokens.cached_input_tokens * model.cached_input_per_1m) /
    1_000_000;
  const outputCost = (tokens.output_tokens * model.output_per_1m) / 1_000_000;
  const reasoningCost =
    (tokens.reasoning_tokens * (model.reasoning_per_1m ?? 0)) / 1_000_000;
  const toolCost = effectiveToolCalls * model.tool_call_cost;
  const imageCost = imageInputCount * model.image_input_cost_per_image;
  return {
    input: inputCost,
    output: outputCost,
    reasoning: reasoningCost,
    tool: toolCost,
    image: imageCost,
  };
}

function buildExplanation(
  model: ModelPricing,
  req: CalculationRequest,
  tokens: TokensUsed,
  components: PriceComponents,
  costPerRun: number,
  total: number,
  effectiveToolCalls: number,
  typeMult: number,
): string {
  const numRuns = req.num_runs ?? 1;
  const parts: string[] = [
    `Model: ${model.display_name} (${model.model_id}).`,
    `Per-run cost: $${costPerRun.toFixed(4)}.`,
    `Total for ${numRuns} run(s): $${total.toFixed(4)}.`,
  ];

  // Largest contributor
  const compList: [string, number][] = [
    ['input', components.input],
    ['output', components.output],
    ['reasoning', components.reasoning],
    ['tool', components.tool],
    ['image', components.image],
  ];
  const biggest = compList.reduce((a, b) => (b[1] > a[1] ? b : a));
  if (biggest[1] > 0) {
    parts.push(`Largest cost driver: ${biggest[0]} ($${biggest[1].toFixed(4)}).`);
  }

  // Reasoning level note
  if (req.reasoning_level && req.reasoning_level !== 'low') {
    const mult = REASONING_MULTIPLIERS[req.reasoning_level] ?? 1.0;
    parts.push(`Reasoning level '${req.reasoning_level}' multiplies output tokens by ${mult}x.`);
  }

  // Task type note (only when not also overridden by agentic flag)
  if (!req.agentic) {
    const legacyMult = TASK_TYPE_MULTIPLIERS[req.task_type ?? 'chat'] ?? 1.0;
    if (legacyMult > 1.0) {
      parts.push(
        `Task type '${req.task_type}' applies a ${legacyMult}x multiplier to account for retries / extra tool use.`,
      );
    }
  }

  // Agentic overhead note
  if (req.agentic) {
    const sysPrompt = effectiveSystemPromptTokens(req);
    let toolNote: string;
    if (
      effectiveToolCalls === AGENTIC_DEFAULT_TOOL_CALL_COUNT &&
      (req.tool_call_count ?? 0) === 0
    ) {
      toolNote = `${AGENTIC_DEFAULT_TOOL_CALL_COUNT} tool calls (default)`;
    } else if ((req.tool_call_count ?? 0) > 0) {
      toolNote = `${effectiveToolCalls} tool calls (user override)`;
    } else {
      toolNote = `${effectiveToolCalls} tool calls`;
    }
    let sysPromptNote: string;
    if (
      sysPrompt === AGENTIC_DEFAULT_SYSTEM_PROMPT_TOKENS &&
      (req.system_prompt_tokens ?? 0) === 0
    ) {
      sysPromptNote = `${sysPrompt} system-prompt input tokens (default)`;
    } else if ((req.system_prompt_tokens ?? 0) > 0) {
      sysPromptNote = `${sysPrompt} system-prompt input tokens (user override)`;
    } else {
      sysPromptNote = `${sysPrompt} system-prompt input tokens`;
    }
    parts.push(
      `Agentic workflow overhead: ${toolNote}, ${sysPromptNote}, ${AGENTIC_MULTIPLIER}x retry multiplier.`,
    );
  } else if (typeMult > 1.0) {
    parts.push(`Applied multiplier: ${typeMult}x.`);
  }
  return parts.join(' ');
}
