"""Pydantic schemas for HTTP request/response shapes."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, ConfigDict


TaskSize = Literal["tiny", "small", "medium", "large", "huge"]
ReasoningLevel = Literal["low", "medium", "high", "extreme"]
TaskType = Literal["chat", "coding", "writing", "research", "agentic"]


class CalculateRequest(BaseModel):
    """Body for POST /calculate — the per-model cost estimate."""
    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(..., description="Model identifier, e.g. 'openai/gpt-4o'")
    input_tokens: Optional[int] = Field(None, ge=0)
    output_tokens: Optional[int] = Field(None, ge=0)
    cached_input_tokens: int = Field(0, ge=0)
    reasoning_tokens: int = Field(0, ge=0)
    tool_call_count: int = Field(0, ge=0)
    image_input_count: int = Field(0, ge=0)
    num_runs: int = Field(1, ge=1, le=1_000_000)
    task_size: Optional[TaskSize] = None
    reasoning_level: ReasoningLevel = "low"
    # v2.7: agentic bundle switch. When True the calculator auto-adds 5 tool calls,
    # 2000 system-prompt input tokens, and a 1.4× retry multiplier to the per-run
    # cost. Replaces the thin `task_type: "agentic"` slot — the frontend sends this
    # flag instead of a category dropdown pick for agentic runs.
    agentic: bool = False
    # v2.7: override the agentic system-prompt overhead (default 2000). Ignored
    # when agentic=False (this field represents the agentic bundle's overhead,
    # not a general sys-prompt knob).
    system_prompt_tokens: int = Field(0, ge=0)
    task_type: TaskType = "chat"


class CompareRequest(BaseModel):
    """Body for POST /calculate/compare — same inputs across multiple models."""
    model_config = ConfigDict(extra="forbid")

    model_ids: list[str] = Field(..., min_length=1, max_length=10)
    input_tokens: Optional[int] = Field(None, ge=0)
    output_tokens: Optional[int] = Field(None, ge=0)
    cached_input_tokens: int = Field(0, ge=0)
    reasoning_tokens: int = Field(0, ge=0)
    tool_call_count: int = Field(0, ge=0)
    image_input_count: int = Field(0, ge=0)
    num_runs: int = Field(1, ge=1, le=1_000_000)
    task_size: Optional[TaskSize] = None
    reasoning_level: ReasoningLevel = "low"
    agentic: bool = False
    system_prompt_tokens: int = Field(0, ge=0)
    task_type: TaskType = "chat"


class TokensUsedOut(BaseModel):
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    cached_input_tokens: int


class CalculationResultOut(BaseModel):
    """One row of the cost breakdown — what the frontend renders."""
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
    tokens_used: TokensUsedOut
    explanation: str
    assumptions: dict


class ModelOut(BaseModel):
    """Public view of a model's pricing — for GET /models."""
    model_id: str
    provider: str
    display_name: str
    input_per_1m: float
    output_per_1m: float
    cached_input_per_1m: float
    context_window: int
    supports_reasoning: bool
    reasoning_per_1m: Optional[float]
    tool_call_cost: float
    image_input_cost_per_image: float
    notes: str


class LocalCostRequest(BaseModel):
    """Body for POST /calculate/local — self-hosted (GPU + power) cost estimate."""
    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(..., description="Ollama tag, e.g. 'llama3.3:70b'")
    gpu_id: str = Field(..., description="GPU canonical id (e.g. 'nvidia-rtx-4090') or display name (e.g. 'NVIDIA RTX 4090')")
    #: Tokens/sec override. If omitted, looks up model.tokens_per_second_by_gpu[gpu_id].
    tokens_per_second: Optional[float] = Field(None, gt=0)
    #: GPU rental / amortized hardware cost per hour (USD). 0 = free at the meter.
    gpu_cost_per_hour: float = Field(0.0, ge=0)
    #: Electricity rate (USD per kWh). Combined with tdp_watts to compute power cost.
    power_cost_per_kwh: float = Field(0.0, ge=0)
    #: TDP override. If omitted, uses the GPU profile's tdp_watts.
    gpu_tdp_watts: Optional[float] = Field(None, gt=0)
    #: Duty cycle in (0, 1]. Lower utilization amortizes fixed cost over fewer tokens.
    utilization: float = Field(1.0, gt=0, le=1.0)
    # Task-size presets mirror /calculate so the per-run total is consistent
    input_tokens: Optional[int] = Field(None, ge=0)
    output_tokens: Optional[int] = Field(None, ge=0)
    task_size: Optional[TaskSize] = None
    reasoning_level: ReasoningLevel = "low"
    task_type: TaskType = "chat"
    num_runs: int = Field(1, ge=1, le=1_000_000)


class LocalCostBreakdownOut(BaseModel):
    """Per-component cost breakdown for one local-cost calculation (USD per token)."""
    gpu_rental: Optional[float] = None
    power: Optional[float] = None


class LocalCostResponse(BaseModel):
    """Body returned by POST /calculate/local."""
    model_id: str
    gpu_id: str
    gpu_display_name: str
    model_display_name: str
    tokens_per_second: float
    effective_tokens_per_second: float
    cost_per_token_usd: float
    cost_per_million_tokens_usd: float
    cost_per_hour_usd: float
    total_tokens: int
    cost_per_run: float
    total_cost: float
    num_runs: int
    tokens_used: TokensUsedOut
    breakdown: LocalCostBreakdownOut
    explanation: str
    assumptions: dict