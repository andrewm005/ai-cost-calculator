"""Tests for the cost calculator."""
import pytest
from app.pricing import ModelPricing
from app.calculator import (
    Calculator,
    CalculationRequest,
    TASK_SIZE_PRESETS,
    REASONING_MULTIPLIERS,
    TASK_TYPE_MULTIPLIERS,
    AGENTIC_DEFAULT_TOOL_CALL_COUNT,
    AGENTIC_DEFAULT_SYSTEM_PROMPT_TOKENS,
    AGENTIC_MULTIPLIER,
)


def make_model(**overrides) -> ModelPricing:
    """Factory for a cheap non-reasoning test model."""
    base = dict(
        model_id="test/cheap",
        provider="test",
        display_name="Test Cheap",
        input_per_1m=1.0,        # $1 per 1M input tokens
        output_per_1m=2.0,       # $2 per 1M output tokens
        cached_input_per_1m=0.1,
        context_window=100000,
        supports_reasoning=False,
        reasoning_per_1m=None,
        tool_call_cost=0.001,
        image_input_cost_per_image=0.005,
        notes="",
    )
    base.update(overrides)
    return ModelPricing(**base)


def make_reasoning_model(**overrides) -> ModelPricing:
    """Factory for a reasoning-capable test model."""
    return make_model(
        model_id="test/reasoning",
        display_name="Test Reasoning",
        input_per_1m=3.0,
        output_per_1m=9.0,
        reasoning_per_1m=9.0,
        supports_reasoning=True,
        **overrides,
    )


def test_basic_input_output_cost():
    """1M input + 500K output at $1/$2 per 1M = $1.00 + $1.00 = $2.00."""
    calc = Calculator(make_model())
    req = CalculationRequest(
        model_id="test/cheap",
        input_tokens=1_000_000,
        output_tokens=500_000,
    )
    result = calc.calculate(req)
    assert result.input_cost == 1.0
    assert result.output_cost == 1.0
    assert result.total_cost == pytest.approx(2.0, abs=1e-9)
    assert result.cost_per_run == pytest.approx(2.0, abs=1e-9)


def test_cached_input_uses_discounted_price():
    """Cached input tokens use the cached rate, not the full rate."""
    calc = Calculator(make_model())
    req = CalculationRequest(
        model_id="test/cheap",
        input_tokens=1_000_000,
        cached_input_tokens=500_000,  # half cached
        output_tokens=0,
    )
    result = calc.calculate(req)
    # 500k @ $1/M + 500k @ $0.10/M = 0.5 + 0.05 = 0.55
    assert result.input_cost == pytest.approx(0.55, abs=1e-9)
    assert result.total_cost == pytest.approx(0.55, abs=1e-9)


def test_reasoning_tokens_charged_separately():
    """Reasoning tokens use the reasoning rate (if model supports it)."""
    calc = Calculator(make_reasoning_model())
    req = CalculationRequest(
        model_id="test/reasoning",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        reasoning_tokens=500_000,
    )
    result = calc.calculate(req)
    # input: 3.0, output: 9.0, reasoning: 500k * 9.0 / 1M = 4.5
    assert result.input_cost == 3.0
    assert result.output_cost == 9.0
    assert result.reasoning_cost == 4.5
    assert result.total_cost == pytest.approx(16.5, abs=1e-9)


def test_reasoning_tokens_ignored_when_model_doesnt_support():
    """If model doesn't support reasoning, reasoning_tokens are silently dropped."""
    calc = Calculator(make_model())  # not reasoning-capable
    req = CalculationRequest(
        model_id="test/cheap",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        reasoning_tokens=500_000,  # should be ignored
    )
    result = calc.calculate(req)
    assert result.reasoning_cost == 0.0
    assert result.total_cost == pytest.approx(3.0, abs=1e-9)  # 1.0 + 2.0


def test_tool_call_cost_added():
    """Tool calls add a flat per-call cost."""
    calc = Calculator(make_model(tool_call_cost=0.01))
    req = CalculationRequest(
        model_id="test/cheap",
        input_tokens=0,
        output_tokens=0,
        tool_call_count=5,
    )
    result = calc.calculate(req)
    assert result.tool_cost == pytest.approx(0.05, abs=1e-9)
    assert result.total_cost == pytest.approx(0.05, abs=1e-9)


def test_image_input_cost_added():
    """Image inputs charge per image."""
    calc = Calculator(make_model(image_input_cost_per_image=0.01))
    req = CalculationRequest(
        model_id="test/cheap",
        input_tokens=0,
        output_tokens=0,
        image_input_count=3,
    )
    result = calc.calculate(req)
    assert result.image_cost == pytest.approx(0.03, abs=1e-9)
    assert result.total_cost == pytest.approx(0.03, abs=1e-9)


def test_num_runs_multiplies_total():
    """Total cost is per-run * num_runs."""
    calc = Calculator(make_model())
    req = CalculationRequest(
        model_id="test/cheap",
        input_tokens=1_000_000,
        output_tokens=0,
        num_runs=10,
    )
    result = calc.calculate(req)
    assert result.cost_per_run == 1.0
    assert result.total_cost == 10.0


def test_task_size_preset_populates_tokens():
    """If tokens omitted and task_size given, preset is used."""
    calc = Calculator(make_model())
    req = CalculationRequest(
        model_id="test/cheap",
        task_size="medium",
    )
    result = calc.calculate(req)
    in_tokens, out_tokens = TASK_SIZE_PRESETS["medium"]
    expected_input_cost = in_tokens * 1.0 / 1_000_000
    expected_output_cost = out_tokens * 2.0 / 1_000_000
    assert result.input_cost == pytest.approx(expected_input_cost, abs=1e-9)
    assert result.output_cost == pytest.approx(expected_output_cost, abs=1e-9)
    assert result.tokens_used.input_tokens == in_tokens
    assert result.tokens_used.output_tokens == out_tokens


def test_explicit_tokens_override_preset():
    """If both task_size and explicit tokens given, explicit wins."""
    calc = Calculator(make_model())
    req = CalculationRequest(
        model_id="test/cheap",
        task_size="medium",
        input_tokens=999_999,
        output_tokens=888_888,
    )
    result = calc.calculate(req)
    assert result.tokens_used.input_tokens == 999_999
    assert result.tokens_used.output_tokens == 888_888


def test_reasoning_level_multiplies_output_tokens():
    """Higher reasoning level inflates output tokens before pricing."""
    calc = Calculator(make_model())
    req_low = CalculationRequest(model_id="test/cheap", input_tokens=0, output_tokens=1000, reasoning_level="low")
    req_high = CalculationRequest(model_id="test/cheap", input_tokens=0, output_tokens=1000, reasoning_level="high")
    res_low = calc.calculate(req_low)
    res_high = calc.calculate(req_high)
    expected_low = 1000 * REASONING_MULTIPLIERS["low"] * 2.0 / 1_000_000
    expected_high = 1000 * REASONING_MULTIPLIERS["high"] * 2.0 / 1_000_000
    assert res_low.output_cost == pytest.approx(expected_low, abs=1e-9)
    assert res_high.output_cost == pytest.approx(expected_high, abs=1e-9)
    assert res_high.output_cost > res_low.output_cost


def test_task_type_multiplier_inflates_per_run_cost():
    """Agentic work inflates cost (more retries / tool usage)."""
    calc = Calculator(make_model())
    req_chat = CalculationRequest(model_id="test/cheap", input_tokens=1_000_000, output_tokens=0, task_type="chat")
    req_agentic = CalculationRequest(model_id="test/cheap", input_tokens=1_000_000, output_tokens=0, task_type="agentic")
    res_chat = calc.calculate(req_chat)
    res_agentic = calc.calculate(req_agentic)
    expected_agentic = res_chat.cost_per_run * TASK_TYPE_MULTIPLIERS["agentic"]
    assert res_agentic.cost_per_run == pytest.approx(expected_agentic, abs=1e-9)


def test_all_presets_have_required_keys():
    """Sanity: all task sizes and reasoning levels have presets."""
    for size in ("tiny", "small", "medium", "large", "huge"):
        assert size in TASK_SIZE_PRESETS
    for level in ("low", "medium", "high", "extreme"):
        assert level in REASONING_MULTIPLIERS
    for t in ("chat", "coding", "writing", "research", "agentic"):
        assert t in TASK_TYPE_MULTIPLIERS


def test_compare_returns_one_result_per_model():
    """Compare produces a result per model, in the same order."""
    calc = Calculator(make_model(), make_reasoning_model())
    results = calc.compare(["test/cheap", "test/reasoning"], input_tokens=1_000_000, output_tokens=1_000_000)
    assert len(results) == 2
    assert results[0].model_id == "test/cheap"
    assert results[1].model_id == "test/reasoning"


def test_unknown_model_in_request_raises_keyerror():
    """Calculator rejects unknown model_id at construction (or per-call)."""
    with pytest.raises(KeyError):
        Calculator(make_model()).calculate(
            CalculationRequest(model_id="test/nope", input_tokens=1, output_tokens=1)
        )


def test_explanation_summarises_cost_breakdown():
    """Result includes a human-readable explanation."""
    calc = Calculator(make_model())
    res = calc.calculate(CalculationRequest(
        model_id="test/cheap", input_tokens=1_000_000, output_tokens=500_000, num_runs=3
    ))
    assert isinstance(res.explanation, str)
    assert len(res.explanation) > 0
    # Should mention the model and the total
    assert "test/cheap" in res.explanation or "$" in res.explanation


# ---------------------------------------------------------------------
# v2.7 — agentic bundle flag
# ---------------------------------------------------------------------

def test_agentic_default_overhead_applied():
    """agentic=True with no overrides: 5 tool calls (auto-fill), 2k sys prompt (auto-fill),
    and 1.4× retry multiplier all apply. Compared to the same chat baseline, agentic adds:
      - 2000 extra input tokens @ $1/M  = $0.002
      - 5 extra tool calls @ $0.001    = $0.005
      - 1.4× on the per-run base.
    """
    calc = Calculator(make_model())
    chat_req = CalculationRequest(
        model_id="test/cheap", input_tokens=1_000_000, output_tokens=0,
    )
    agentic_req = CalculationRequest(
        model_id="test/cheap", input_tokens=1_000_000, output_tokens=0,
        agentic=True,
    )
    chat_res = calc.calculate(chat_req)
    agentic_res = calc.calculate(agentic_req)
    # Per-run base for chat: input=1.0 + tool=0 + rest=0 = $1.00
    # Agentic adds 2k input ($0.002) and 5 tool calls ($0.005) → base = $1.007
    # × 1.4 = $1.4098
    assert agentic_res.tokens_used.input_tokens == 1_002_000
    assert agentic_res.assumptions["agentic"] is True
    assert agentic_res.assumptions["agentic_tool_call_count_effective"] == AGENTIC_DEFAULT_TOOL_CALL_COUNT == 5
    assert agentic_res.assumptions["agentic_system_prompt_tokens_effective"] == AGENTIC_DEFAULT_SYSTEM_PROMPT_TOKENS == 2000
    assert agentic_res.assumptions["agentic_multiplier_applied"] == AGENTIC_MULTIPLIER == 1.4
    # Manual reconstruction
    base = 1_002_000 / 1_000_000 * 1.0 + 5 * 0.001
    expected_per_run = base * 1.4
    assert agentic_res.cost_per_run == pytest.approx(expected_per_run, abs=1e-9)
    # Must be greater than chat baseline (1.4× plus overhead)
    assert agentic_res.cost_per_run > chat_res.cost_per_run


def test_agentic_tool_call_count_override_wins():
    """agentic=True with explicit tool_call_count=10: override wins (10, not 5).
    system_prompt_tokens still uses the 2000 default since user didn't override it."""
    calc = Calculator(make_model())
    req = CalculationRequest(
        model_id="test/cheap",
        input_tokens=1_000_000,
        output_tokens=0,
        agentic=True,
        tool_call_count=10,  # override
    )
    res = calc.calculate(req)
    assert res.assumptions["agentic_tool_call_count_effective"] == 10
    assert res.assumptions["agentic_system_prompt_tokens_effective"] == 2000  # still default
    assert res.tool_cost == pytest.approx(10 * 0.001, abs=1e-9)
    # Token count: 1M input + 2k sys prompt = 1,002,000
    assert res.tokens_used.input_tokens == 1_002_000


def test_agentic_false_no_overhead_applied():
    """agentic=False: no system-prompt auto-fill, no tool-call auto-fill, 1.0× multiplier
    (assuming default task_type='chat'). Even if the user passes system_prompt_tokens=N,
    it's ignored — the field is agentic-bundle-only."""
    calc = Calculator(make_model())
    req = CalculationRequest(
        model_id="test/cheap",
        input_tokens=1_000_000,
        output_tokens=0,
        agentic=False,
        system_prompt_tokens=5000,  # should be ignored
    )
    res = calc.calculate(req)
    assert res.assumptions["agentic"] is False
    assert res.assumptions["agentic_tool_call_count_effective"] == 0
    assert res.assumptions["agentic_system_prompt_tokens_effective"] == 0
    assert res.assumptions["agentic_multiplier_applied"] == 1.0
    # Cost matches the baseline chat run exactly
    assert res.cost_per_run == pytest.approx(1.0, abs=1e-9)
    assert res.tokens_used.input_tokens == 1_000_000  # no sys prompt added


def test_agentic_combines_with_reasoning_level():
    """agentic=True + reasoning_level=high: agentic overhead stacks with the reasoning
    output multiplier (1.5×). All math is applied exactly once in the right order."""
    calc = Calculator(make_model())
    req = CalculationRequest(
        model_id="test/cheap",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        agentic=True,
        reasoning_level="high",  # 1.5× output multiplier
    )
    res = calc.calculate(req)
    # Input = 1M + 2k sys prompt = 1,002,000 → input_cost = 1.002
    # Output = 1M * 1.5 = 1.5M → output_cost = 1.5M * 2.0 / 1M = 3.0
    # Tool = 5 * 0.001 = 0.005
    # per_run_base = 1.002 + 3.0 + 0.005 = 4.007
    # × 1.4 (agentic) = 5.6098
    expected_base = 1_002_000 / 1_000_000 + 1_500_000 / 1_000_000 * 2.0 + 5 * 0.001
    expected_per_run = expected_base * 1.4
    assert res.cost_per_run == pytest.approx(expected_per_run, abs=1e-9)
    # Reasoning multiplier is reported correctly
    assert res.assumptions["reasoning_level_multiplier"] == 1.5
    # Agentic multiplier applied
    assert res.assumptions["agentic_multiplier_applied"] == 1.4


def test_agentic_system_prompt_tokens_override():
    """agentic=True with explicit system_prompt_tokens=500: 500 wins (not 2000)."""
    calc = Calculator(make_model())
    req = CalculationRequest(
        model_id="test/cheap",
        input_tokens=1_000_000,
        output_tokens=0,
        agentic=True,
        system_prompt_tokens=500,  # override
    )
    res = calc.calculate(req)
    assert res.assumptions["agentic_system_prompt_tokens_effective"] == 500
    assert res.tokens_used.input_tokens == 1_000_500
    # input cost = 1,000,500 * $1 / 1M = $1.0005; tool cost = 5 * 0.001 = $0.005;
    # per_run = (1.0005 + 0.005) * 1.4 = 1.4077
    expected = (1_000_500 / 1_000_000 + 5 * 0.001) * 1.4
    assert res.cost_per_run == pytest.approx(expected, abs=1e-9)


def test_agentic_explanation_mentions_overhead():
    """When agentic=True, the explanation includes the auto-fill numbers and the 1.4× mult."""
    calc = Calculator(make_model())
    res = calc.calculate(CalculationRequest(
        model_id="test/cheap", input_tokens=0, output_tokens=0, agentic=True,
    ))
    assert "Agentic workflow overhead" in res.explanation
    assert "5 tool calls" in res.explanation
    assert "2000 system-prompt input tokens" in res.explanation
    assert "1.4x retry multiplier" in res.explanation


def test_agentic_legacy_task_type_still_works_for_backcompat():
    """Pre-v2.7 callers that send task_type='agentic' (no agentic flag) still get
    the 1.4× multiplier — but the agentic-specific overhead (tool calls + sys prompt)
    is NOT auto-applied. This keeps the old path callable without surprising users."""
    calc = Calculator(make_model())
    req = CalculationRequest(
        model_id="test/cheap",
        input_tokens=1_000_000,
        output_tokens=0,
        task_type="agentic",
        # agentic defaults to False; the task_type 'agentic' still applies its 1.4× via
        # the legacy TASK_TYPE_MULTIPLIERS path.
    )
    res = calc.calculate(req)
    # task_type="agentic" applies 1.4× but the agentic bundle is NOT engaged
    assert res.cost_per_run == pytest.approx(1.0 * 1.4, abs=1e-9)
    assert res.assumptions["agentic"] is False
    assert res.assumptions["agentic_tool_call_count_effective"] == 0
    assert res.assumptions["agentic_system_prompt_tokens_effective"] == 0


def test_agentic_true_overrides_task_type_multiplier():
    """When agentic=True, the type multiplier is 1.4 regardless of task_type
    (e.g. task_type='chat' with agentic=True still gets 1.4× — the agentic flag wins)."""
    calc = Calculator(make_model())
    req = CalculationRequest(
        model_id="test/cheap",
        input_tokens=1_000_000,
        output_tokens=0,
        task_type="chat",  # would normally give 1.0× without agentic
        agentic=True,
    )
    res = calc.calculate(req)
    # Per-run base: input 1.002M * $1/M + tool 5 * $0.001 = 1.007
    # × 1.4 (agentic, not task_type's 1.0) = 1.4098
    expected = (1_002_000 / 1_000_000 + 5 * 0.001) * 1.4
    assert res.cost_per_run == pytest.approx(expected, abs=1e-9)