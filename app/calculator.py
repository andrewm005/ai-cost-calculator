"""Core cost calculation logic.

Pure functions where possible — the Calculator just resolves a model,
multipliers, then sums components. No I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .pricing import ModelPricing


#: Default input/output token counts per task size preset.
TASK_SIZE_PRESETS: dict[str, tuple[int, int]] = {
    "tiny":   (200,    100),
    "small":  (1_000,   500),
    "medium": (5_000,  2_000),
    "large":  (20_000, 8_000),
    "huge":   (100_000, 30_000),
    # New project-scale entries based on research
    "website":         (15_000,   3_500),  # Typical 3D animated site
    "webapp":          (50_000,  12_000),  # Full Next.js app
    "codebase-small":  (60_000,  20_000),  # Python package ~5k lines
    "codebase-medium": (300_000, 100_000), # Node.js webapp ~25k lines
    "codebase-large": (1_200_000, 400_000), # Large monorepo ~100k lines
    "mobile-app":      (120_000,  50_000), # iOS SwiftUI full app
    "ml-pipeline":     (70_000,  25_000), # PyTorch CV pipeline
    "game-2d":         (80_000,  30_000), # Full RPG Phaser.js
    "game-3d":         (500_000, 200_000), # 3D multiplayer
    "refactor-large": (800_000, 400_000), # Monolith to microservices
}

#: Multiplier applied to output tokens based on reasoning effort.
#: Higher reasoning -> model generates more tokens for "thinking".
REASONING_MULTIPLIERS: dict[str, float] = {
    "low":     1.0,
    "medium":  1.2,
    "high":    1.5,
    "extreme": 2.5,
}

#: Per-run cost multiplier by task type. Reflects retry risk / extra tool usage.
#: NOTE: "agentic" is DEPRECATED as of v2.7 — use the dedicated ``agentic: bool``
#: flag on ``CalculationRequest`` instead. The entry is kept so legacy callers
#: that still send ``task_type="agentic"`` keep getting the 1.4× multiplier; the
#: frontend has been updated to use ``agentic: true`` exclusively.
TASK_TYPE_MULTIPLIERS: dict[str, float] = {
    "chat":     1.0,
    "writing":  1.0,
    "coding":   1.1,
    "research": 1.15,
    "agentic":  1.4,   # DEPRECATED — see agentic flag on CalculationRequest
}


#: Defaults applied when ``agentic=True`` and the user did not supply an override.
#: ``system_prompt_tokens`` is added to ``input_tokens`` (it bills as input).
#: ``tool_call_count`` is added at the model's ``tool_call_cost`` per call.
AGENTIC_DEFAULT_TOOL_CALL_COUNT = 5
AGENTIC_DEFAULT_SYSTEM_PROMPT_TOKENS = 2000
AGENTIC_MULTIPLIER = 1.4


@dataclass
class CalculationRequest:
    """User input for one cost estimate."""
    model_id: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cached_input_tokens: int = 0
    reasoning_tokens: int = 0
    tool_call_count: int = 0
    image_input_count: int = 0
    num_runs: int = 1
    task_size: Optional[str] = None           # tiny/small/medium/large/huge
    reasoning_level: str = "low"              # low/medium/high/extreme
    agentic: bool = False                     # v2.7: bundle 5 tool calls + 2k sys prompt + 1.4× retry mult
    system_prompt_tokens: int = 0             # v2.7: override agentic sys-prompt overhead (0 = auto-fill when agentic=True)
    task_type: str = "chat"                   # chat/coding/writing/research/agentic (agentic value DEPRECATED — use agentic flag)


@dataclass
class TokensUsed:
    """Actual tokens after resolving presets and reasoning multiplier."""
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    cached_input_tokens: int


@dataclass
class CalculationResult:
    """One row of cost breakdown for one model + one request."""
    model_id: str
    display_name: str
    input_cost: float
    output_cost: float
    reasoning_cost: float
    tool_cost: float
    image_cost: float
    cost_per_run: float
    total_cost: float
    num_runs: int
    tokens_used: TokensUsed
    explanation: str
    assumptions: dict = field(default_factory=dict)


class Calculator:
    """Resolves a request against a known set of models and returns cost estimates."""

    def __init__(self, *models: ModelPricing):
        self._models = {m.model_id: m for m in models}

    def add_model(self, model: ModelPricing) -> None:
        """Register a model after construction (handy for tests)."""
        self._models[model.model_id] = model

    def _get_model(self, model_id: str) -> ModelPricing:
        if model_id not in self._models:
            available = ", ".join(sorted(self._models.keys()))
            raise KeyError(f"Unknown model '{model_id}'. Available: {available}")
        return self._models[model_id]

    def calculate(self, req: CalculationRequest) -> CalculationResult:
        model = self._get_model(req.model_id)
        # Resolve the effective tool-call count once (agentic auto-fill vs user override).
        effective_tool_calls = self._effective_tool_call_count(req)
        tokens = self._resolve_tokens(req, model)
        components = self._price_components(model, tokens, effective_tool_calls, req)
        per_run_base = sum(components.values())
        type_mult = self._effective_type_multiplier(req)
        cost_per_run = per_run_base * type_mult
        total = cost_per_run * req.num_runs
        explanation = self._build_explanation(
            model, req, tokens, components, cost_per_run, total,
            effective_tool_calls=effective_tool_calls,
            type_mult=type_mult,
        )
        return CalculationResult(
            model_id=model.model_id,
            display_name=model.display_name,
            input_cost=components["input"],
            output_cost=components["output"],
            reasoning_cost=components["reasoning"],
            tool_cost=components["tool"],
            image_cost=components["image"],
            cost_per_run=cost_per_run,
            total_cost=total,
            num_runs=req.num_runs,
            tokens_used=tokens,
            explanation=explanation,
            assumptions={
                "task_type_multiplier": type_mult,
                "reasoning_level_multiplier": REASONING_MULTIPLIERS.get(req.reasoning_level, 1.0),
                "agentic": req.agentic,
                "agentic_tool_call_count_effective": effective_tool_calls,
                "agentic_system_prompt_tokens_effective": self._effective_system_prompt_tokens(req),
                "agentic_multiplier_applied": AGENTIC_MULTIPLIER if req.agentic else 1.0,
            },
        )

    def compare(self, model_ids: list[str], **kwargs) -> list[CalculationResult]:
        """Calculate the same request against multiple models."""
        results = []
        for mid in model_ids:
            req = CalculationRequest(model_id=mid, **kwargs)
            results.append(self.calculate(req))
        return results

    # ----- internals -----

    def _resolve_tokens(self, req: CalculationRequest, model: ModelPricing) -> TokensUsed:
        # Task size preset as a default if tokens omitted
        if req.task_size and req.task_size in TASK_SIZE_PRESETS:
            preset_in, preset_out = TASK_SIZE_PRESETS[req.task_size]
            in_t = req.input_tokens if req.input_tokens is not None else preset_in
            out_t = req.output_tokens if req.output_tokens is not None else preset_out
        else:
            in_t = req.input_tokens or 0
            out_t = req.output_tokens or 0
        # Reasoning level inflates output (model "thinks" more)
        out_mult = REASONING_MULTIPLIERS.get(req.reasoning_level, 1.0)
        out_t = int(out_t * out_mult)
        # Reasoning tokens only valid if model supports them
        reasoning = req.reasoning_tokens if model.supports_reasoning else 0
        # Agentic system-prompt overhead bills as input tokens (default 2k when agentic=True,
        # 0 when agentic=False — even if the user overrode the field).
        sys_prompt = self._effective_system_prompt_tokens(req)
        in_t = in_t + sys_prompt
        # Cached subset cannot exceed total input (including agentic sys prompt).
        cached = max(0, min(req.cached_input_tokens, in_t))
        return TokensUsed(
            input_tokens=in_t,
            output_tokens=out_t,
            reasoning_tokens=reasoning,
            cached_input_tokens=cached,
        )

    @staticmethod
    def _price_components(
        model: ModelPricing,
        tokens: TokensUsed,
        effective_tool_calls: int,
        req: CalculationRequest,
    ) -> dict[str, float]:
        uncached = max(0, tokens.input_tokens - tokens.cached_input_tokens)
        input_cost = (uncached * model.input_per_1m + tokens.cached_input_tokens * model.cached_input_per_1m) / 1_000_000
        output_cost = tokens.output_tokens * model.output_per_1m / 1_000_000
        reasoning_cost = tokens.reasoning_tokens * (model.reasoning_per_1m or 0.0) / 1_000_000
        tool_cost = effective_tool_calls * model.tool_call_cost
        image_cost = req.image_input_count * model.image_input_cost_per_image
        return {
            "input": input_cost,
            "output": output_cost,
            "reasoning": reasoning_cost,
            "tool": tool_cost,
            "image": image_cost,
        }

    @staticmethod
    def _effective_tool_call_count(req: CalculationRequest) -> int:
        """Tool calls applied in pricing: user override (non-zero) wins; otherwise the agentic
        auto-fill default (5) when ``agentic=True``; otherwise the raw request value (0 default)."""
        if req.tool_call_count > 0:
            return req.tool_call_count
        return AGENTIC_DEFAULT_TOOL_CALL_COUNT if req.agentic else 0

    @staticmethod
    def _effective_system_prompt_tokens(req: CalculationRequest) -> int:
        """System-prompt tokens billed as input: agentic-only. When ``agentic=False`` the
        field is always treated as 0 (the user-supplied value is ignored — this field
        represents the agentic bundle's overhead, not a general sys-prompt knob). When
        ``agentic=True`` and the user supplied a non-zero override, that value wins;
        otherwise the agentic default (2000) applies."""
        if not req.agentic:
            return 0
        return req.system_prompt_tokens if req.system_prompt_tokens > 0 else AGENTIC_DEFAULT_SYSTEM_PROMPT_TOKENS

    @staticmethod
    def _effective_type_multiplier(req: CalculationRequest) -> float:
        """Per-run cost multiplier. ``agentic=True`` forces 1.4× (replaces the legacy
        ``task_type='agentic'`` 1.4× and deprecates that slot — see ``TASK_TYPE_MULTIPLIERS``)."""
        if req.agentic:
            return AGENTIC_MULTIPLIER
        return TASK_TYPE_MULTIPLIERS.get(req.task_type, 1.0)

    @staticmethod
    def _build_explanation(
        model: ModelPricing,
        req: CalculationRequest,
        tokens: TokensUsed,
        components: dict[str, float],
        cost_per_run: float,
        total: float,
        effective_tool_calls: int = 0,
        type_mult: float = 1.0,
    ) -> str:
        parts = [
            f"Model: {model.display_name} ({model.model_id}).",
            f"Per-run cost: ${cost_per_run:.4f}.",
            f"Total for {req.num_runs} run(s): ${total:.4f}.",
        ]
        # Largest contributor
        biggest = max(components.items(), key=lambda kv: kv[1])
        if biggest[1] > 0:
            parts.append(f"Largest cost driver: {biggest[0]} (${biggest[1]:.4f}).")
        # Reasoning level note
        if req.reasoning_level and req.reasoning_level != "low":
            mult = REASONING_MULTIPLIERS.get(req.reasoning_level, 1.0)
            parts.append(f"Reasoning level '{req.reasoning_level}' multiplies output tokens by {mult}x.")
        # Task type note (only when not also overridden by agentic flag)
        if not req.agentic:
            legacy_mult = TASK_TYPE_MULTIPLIERS.get(req.task_type, 1.0)
            if legacy_mult > 1.0:
                parts.append(f"Task type '{req.task_type}' applies a {legacy_mult}x multiplier to account for retries / extra tool use.")
        # Agentic overhead note
        if req.agentic:
            sys_prompt = Calculator._effective_system_prompt_tokens(req)
            tool_note = "tool calls"
            if effective_tool_calls == AGENTIC_DEFAULT_TOOL_CALL_COUNT and req.tool_call_count == 0:
                tool_note = f"{AGENTIC_DEFAULT_TOOL_CALL_COUNT} tool calls (default)"
            elif req.tool_call_count > 0:
                tool_note = f"{effective_tool_calls} tool calls (user override)"
            else:
                tool_note = f"{effective_tool_calls} tool calls"
            sys_prompt_note = (
                f"{sys_prompt} system-prompt input tokens"
                + (" (default)" if sys_prompt == AGENTIC_DEFAULT_SYSTEM_PROMPT_TOKENS and req.system_prompt_tokens == 0
                   else " (user override)" if req.system_prompt_tokens > 0
                   else "")
            )
            parts.append(
                f"Agentic workflow overhead: {tool_note}, {sys_prompt_note}, {AGENTIC_MULTIPLIER}x retry multiplier."
            )
        elif type_mult > 1.0:
            # Safety net — if agentic=False but multiplier is somehow >1 (e.g. future task_types).
            parts.append(f"Applied multiplier: {type_mult}x.")
        return " ".join(parts)