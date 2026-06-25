/**
 * Calculator tests — mirror tests/test_calculator.py.
 *
 * Outputs are asserted to be byte-equivalent to the Python implementation
 * (within 1e-9 precision, same as pytest.approx(abs=1e-9)).
 */
import { describe, test, expect } from 'vitest';
import {
  Calculator,
  TASK_SIZE_PRESETS,
  REASONING_MULTIPLIERS,
  TASK_TYPE_MULTIPLIERS,
  AGENTIC_DEFAULT_TOOL_CALL_COUNT,
  AGENTIC_DEFAULT_SYSTEM_PROMPT_TOKENS,
  AGENTIC_MULTIPLIER,
  type CalculationRequest,
} from '../src/lib/calculator.js';
import type { ModelPricing } from '../src/lib/pricing.js';

function makeModel(overrides: Partial<ModelPricing> = {}): ModelPricing {
  const base: ModelPricing = {
    model_id: 'test/cheap',
    provider: 'test',
    display_name: 'Test Cheap',
    input_per_1m: 1.0,
    output_per_1m: 2.0,
    cached_input_per_1m: 0.1,
    context_window: 100_000,
    supports_reasoning: false,
    reasoning_per_1m: null,
    tool_call_cost: 0.001,
    image_input_cost_per_image: 0.005,
    notes: '',
  };
  return { ...base, ...overrides };
}

function makeReasoningModel(overrides: Partial<ModelPricing> = {}): ModelPricing {
  return makeModel({
    model_id: 'test/reasoning',
    display_name: 'Test Reasoning',
    input_per_1m: 3.0,
    output_per_1m: 9.0,
    reasoning_per_1m: 9.0,
    supports_reasoning: true,
    ...overrides,
  });
}

const EPS = 1e-9;

describe('Calculator: core math', () => {
  test('basic input + output cost', () => {
    // 1M input + 500K output at $1/$2 per 1M = $1.00 + $1.00 = $2.00
    const calc = new Calculator(makeModel());
    const req: CalculationRequest = {
      model_id: 'test/cheap',
      input_tokens: 1_000_000,
      output_tokens: 500_000,
    };
    const r = calc.calculate(req);
    expect(r.input_cost).toBe(1.0);
    expect(r.output_cost).toBe(1.0);
    expect(r.total_cost).toBeCloseTo(2.0, 9);
    expect(r.cost_per_run).toBeCloseTo(2.0, 9);
  });

  test('cached input uses discounted rate', () => {
    const calc = new Calculator(makeModel());
    const r = calc.calculate({
      model_id: 'test/cheap',
      input_tokens: 1_000_000,
      cached_input_tokens: 500_000,
      output_tokens: 0,
    });
    // 500k @ $1/M + 500k @ $0.10/M = 0.5 + 0.05 = 0.55
    expect(r.input_cost).toBeCloseTo(0.55, 9);
    expect(r.total_cost).toBeCloseTo(0.55, 9);
  });

  test('reasoning tokens charged separately', () => {
    const calc = new Calculator(makeReasoningModel());
    const r = calc.calculate({
      model_id: 'test/reasoning',
      input_tokens: 1_000_000,
      output_tokens: 1_000_000,
      reasoning_tokens: 500_000,
    });
    // input: 3.0, output: 9.0, reasoning: 500k * 9.0 / 1M = 4.5
    expect(r.input_cost).toBe(3.0);
    expect(r.output_cost).toBe(9.0);
    expect(r.reasoning_cost).toBe(4.5);
    expect(r.total_cost).toBeCloseTo(16.5, 9);
  });

  test('reasoning tokens ignored when model does not support them', () => {
    const calc = new Calculator(makeModel());
    const r = calc.calculate({
      model_id: 'test/cheap',
      input_tokens: 1_000_000,
      output_tokens: 1_000_000,
      reasoning_tokens: 500_000,
    });
    expect(r.reasoning_cost).toBe(0.0);
    expect(r.total_cost).toBeCloseTo(3.0, 9);
  });

  test('tool call cost added', () => {
    const calc = new Calculator(makeModel({ tool_call_cost: 0.01 }));
    const r = calc.calculate({
      model_id: 'test/cheap',
      input_tokens: 0,
      output_tokens: 0,
      tool_call_count: 5,
    });
    expect(r.tool_cost).toBeCloseTo(0.05, 9);
    expect(r.total_cost).toBeCloseTo(0.05, 9);
  });

  test('image input cost added', () => {
    const calc = new Calculator(makeModel({ image_input_cost_per_image: 0.01 }));
    const r = calc.calculate({
      model_id: 'test/cheap',
      input_tokens: 0,
      output_tokens: 0,
      image_input_count: 3,
    });
    expect(r.image_cost).toBeCloseTo(0.03, 9);
    expect(r.total_cost).toBeCloseTo(0.03, 9);
  });

  test('num_runs multiplies total', () => {
    const calc = new Calculator(makeModel());
    const r = calc.calculate({
      model_id: 'test/cheap',
      input_tokens: 1_000_000,
      output_tokens: 0,
      num_runs: 10,
    });
    expect(r.cost_per_run).toBe(1.0);
    expect(r.total_cost).toBe(10.0);
  });

  test('task_size preset populates tokens', () => {
    const calc = new Calculator(makeModel());
    const r = calc.calculate({ model_id: 'test/cheap', task_size: 'medium' });
    const [presetIn, presetOut] = TASK_SIZE_PRESETS.medium!;
    const expectedInputCost = (presetIn * 1.0) / 1_000_000;
    const expectedOutputCost = (presetOut * 2.0) / 1_000_000;
    expect(r.input_cost).toBeCloseTo(expectedInputCost, 9);
    expect(r.output_cost).toBeCloseTo(expectedOutputCost, 9);
    expect(r.tokens_used.input_tokens).toBe(presetIn);
    expect(r.tokens_used.output_tokens).toBe(presetOut);
  });

  test('explicit tokens override preset', () => {
    const calc = new Calculator(makeModel());
    const r = calc.calculate({
      model_id: 'test/cheap',
      task_size: 'medium',
      input_tokens: 999_999,
      output_tokens: 888_888,
    });
    expect(r.tokens_used.input_tokens).toBe(999_999);
    expect(r.tokens_used.output_tokens).toBe(888_888);
  });

  test('reasoning level multiplies output tokens', () => {
    const calc = new Calculator(makeModel());
    const lowR = calc.calculate({ model_id: 'test/cheap', input_tokens: 0, output_tokens: 1000, reasoning_level: 'low' });
    const highR = calc.calculate({ model_id: 'test/cheap', input_tokens: 0, output_tokens: 1000, reasoning_level: 'high' });
    const expectedLow = (1000 * REASONING_MULTIPLIERS.low! * 2.0) / 1_000_000;
    const expectedHigh = (1000 * REASONING_MULTIPLIERS.high! * 2.0) / 1_000_000;
    expect(lowR.output_cost).toBeCloseTo(expectedLow, 9);
    expect(highR.output_cost).toBeCloseTo(expectedHigh, 9);
    expect(highR.output_cost).toBeGreaterThan(lowR.output_cost);
  });

  test('task_type multiplier inflates per-run cost (legacy agentic)', () => {
    const calc = new Calculator(makeModel());
    const chatR = calc.calculate({ model_id: 'test/cheap', input_tokens: 1_000_000, output_tokens: 0, task_type: 'chat' });
    const agenticR = calc.calculate({ model_id: 'test/cheap', input_tokens: 1_000_000, output_tokens: 0, task_type: 'agentic' });
    const expected = chatR.cost_per_run * TASK_TYPE_MULTIPLIERS.agentic!;
    expect(agenticR.cost_per_run).toBeCloseTo(expected, 9);
  });

  test('all presets have required keys', () => {
    for (const size of ['tiny', 'small', 'medium', 'large', 'huge']) {
      expect(TASK_SIZE_PRESETS[size]).toBeDefined();
    }
    for (const level of ['low', 'medium', 'high', 'extreme']) {
      expect(REASONING_MULTIPLIERS[level]).toBeDefined();
    }
    for (const t of ['chat', 'coding', 'writing', 'research', 'agentic']) {
      expect(TASK_TYPE_MULTIPLIERS[t]).toBeDefined();
    }
  });

  test('compare returns one result per model in order', () => {
    const calc = new Calculator(makeModel(), makeReasoningModel());
    const results = calc.compare(['test/cheap', 'test/reasoning'], {
      input_tokens: 1_000_000,
      output_tokens: 1_000_000,
    });
    expect(results).toHaveLength(2);
    expect(results[0]!.model_id).toBe('test/cheap');
    expect(results[1]!.model_id).toBe('test/reasoning');
  });

  test('unknown model raises error', () => {
    const calc = new Calculator(makeModel());
    expect(() =>
      calc.calculate({ model_id: 'test/nope', input_tokens: 1, output_tokens: 1 }),
    ).toThrow();
  });

  test('explanation is a non-empty string mentioning $', () => {
    const calc = new Calculator(makeModel());
    const r = calc.calculate({
      model_id: 'test/cheap',
      input_tokens: 1_000_000,
      output_tokens: 500_000,
      num_runs: 3,
    });
    expect(typeof r.explanation).toBe('string');
    expect(r.explanation.length).toBeGreaterThan(0);
    expect(r.explanation).toContain('$');
  });
});

// ---------------------------------------------------------------------------
// v2.7 — agentic bundle
// ---------------------------------------------------------------------------

describe('Calculator: v2.7 agentic bundle', () => {
  test('agentic default overhead applied', () => {
    const calc = new Calculator(makeModel());
    const chatR = calc.calculate({ model_id: 'test/cheap', input_tokens: 1_000_000, output_tokens: 0 });
    const agenticR = calc.calculate({ model_id: 'test/cheap', input_tokens: 1_000_000, output_tokens: 0, agentic: true });
    expect(agenticR.tokens_used.input_tokens).toBe(1_002_000);
    expect(agenticR.assumptions.agentic).toBe(true);
    expect(agenticR.assumptions.agentic_tool_call_count_effective).toBe(AGENTIC_DEFAULT_TOOL_CALL_COUNT);
    expect(AGENTIC_DEFAULT_TOOL_CALL_COUNT).toBe(5);
    expect(agenticR.assumptions.agentic_system_prompt_tokens_effective).toBe(AGENTIC_DEFAULT_SYSTEM_PROMPT_TOKENS);
    expect(AGENTIC_DEFAULT_SYSTEM_PROMPT_TOKENS).toBe(2000);
    expect(agenticR.assumptions.agentic_multiplier_applied).toBe(AGENTIC_MULTIPLIER);
    expect(AGENTIC_MULTIPLIER).toBe(1.4);
    const base = (1_002_000 / 1_000_000) * 1.0 + 5 * 0.001;
    const expected = base * 1.4;
    expect(agenticR.cost_per_run).toBeCloseTo(expected, 9);
    expect(agenticR.cost_per_run).toBeGreaterThan(chatR.cost_per_run);
  });

  test('agentic tool_call_count override wins', () => {
    const calc = new Calculator(makeModel());
    const r = calc.calculate({
      model_id: 'test/cheap',
      input_tokens: 1_000_000,
      output_tokens: 0,
      agentic: true,
      tool_call_count: 10,
    });
    expect(r.assumptions.agentic_tool_call_count_effective).toBe(10);
    expect(r.assumptions.agentic_system_prompt_tokens_effective).toBe(2000);
    expect(r.tool_cost).toBeCloseTo(10 * 0.001, 9);
    expect(r.tokens_used.input_tokens).toBe(1_002_000);
  });

  test('agentic=false ignores system_prompt_tokens override', () => {
    const calc = new Calculator(makeModel());
    const r = calc.calculate({
      model_id: 'test/cheap',
      input_tokens: 1_000_000,
      output_tokens: 0,
      agentic: false,
      system_prompt_tokens: 5000,
    });
    expect(r.assumptions.agentic).toBe(false);
    expect(r.assumptions.agentic_tool_call_count_effective).toBe(0);
    expect(r.assumptions.agentic_system_prompt_tokens_effective).toBe(0);
    expect(r.assumptions.agentic_multiplier_applied).toBe(1.0);
    expect(r.cost_per_run).toBeCloseTo(1.0, 9);
    expect(r.tokens_used.input_tokens).toBe(1_000_000);
  });

  test('agentic combines with reasoning level', () => {
    const calc = new Calculator(makeModel());
    const r = calc.calculate({
      model_id: 'test/cheap',
      input_tokens: 1_000_000,
      output_tokens: 1_000_000,
      agentic: true,
      reasoning_level: 'high',
    });
    const expectedBase = 1_002_000 / 1_000_000 + (1_500_000 / 1_000_000) * 2.0 + 5 * 0.001;
    const expected = expectedBase * 1.4;
    expect(r.cost_per_run).toBeCloseTo(expected, 9);
    expect(r.assumptions.reasoning_level_multiplier).toBe(1.5);
    expect(r.assumptions.agentic_multiplier_applied).toBe(1.4);
  });

  test('agentic system_prompt_tokens override wins', () => {
    const calc = new Calculator(makeModel());
    const r = calc.calculate({
      model_id: 'test/cheap',
      input_tokens: 1_000_000,
      output_tokens: 0,
      agentic: true,
      system_prompt_tokens: 500,
    });
    expect(r.assumptions.agentic_system_prompt_tokens_effective).toBe(500);
    expect(r.tokens_used.input_tokens).toBe(1_000_500);
    const expected = (1_000_500 / 1_000_000 + 5 * 0.001) * 1.4;
    expect(r.cost_per_run).toBeCloseTo(expected, 9);
  });

  test('agentic explanation mentions overhead', () => {
    const calc = new Calculator(makeModel());
    const r = calc.calculate({ model_id: 'test/cheap', input_tokens: 0, output_tokens: 0, agentic: true });
    expect(r.explanation).toContain('Agentic workflow overhead');
    expect(r.explanation).toContain('5 tool calls');
    expect(r.explanation).toContain('2000 system-prompt input tokens');
    expect(r.explanation).toContain('1.4x retry multiplier');
  });

  test('agentic legacy task_type="agentic" still works (backcompat)', () => {
    const calc = new Calculator(makeModel());
    const r = calc.calculate({ model_id: 'test/cheap', input_tokens: 1_000_000, output_tokens: 0, task_type: 'agentic' });
    expect(r.cost_per_run).toBeCloseTo(1.0 * 1.4, 9);
    expect(r.assumptions.agentic).toBe(false);
    expect(r.assumptions.agentic_tool_call_count_effective).toBe(0);
    expect(r.assumptions.agentic_system_prompt_tokens_effective).toBe(0);
  });

  test('agentic=true overrides task_type multiplier', () => {
    const calc = new Calculator(makeModel());
    const r = calc.calculate({
      model_id: 'test/cheap',
      input_tokens: 1_000_000,
      output_tokens: 0,
      task_type: 'chat',
      agentic: true,
    });
    const expected = (1_002_000 / 1_000_000 + 5 * 0.001) * 1.4;
    expect(r.cost_per_run).toBeCloseTo(expected, 9);
  });
});
