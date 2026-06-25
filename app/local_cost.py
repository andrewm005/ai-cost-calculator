"""Local (self-hosted) AI inference cost calculator.

Cost formula (per `findings.md` §5 + AGENTS.md operator-locked decision #2):

    cost_per_token = ( (gpu_rental_per_hour + power_per_hour) / 3600 )
                     / (tokens_per_second * utilization)

where:

    power_per_hour = (tdp_watts / 1000) * power_cost_per_kwh

When ``gpu_cost_per_hour`` is given (cloud GPU rental / amortized hardware
purchase), it contributes the rental share. When ``power_cost_per_kwh`` is
given, electricity contributes the power share. Either can be 0 (and in
the no-cost scenario, ``cost_per_token`` is 0 — useful for "free at the
meter" calculations).

This module is deliberately independent from ``app/calculator.py`` (which
handles per-token API pricing). Local inference has no provider billing
contract; the cost is a function of physical hardware and electricity.
Per AGENTS.md decision #2, **local Ollama is NOT merged with cloud
Ollama** — the latter would only land as a normal ``config/pricing.json``
entry with ``provider=\"ollama\"`` if/when Ollama publishes public prices.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union


log = logging.getLogger(__name__)


PathLike = Union[str, Path]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GpuProfile:
    """Static profile of one GPU class.

    Throughput is the headline number for cost calculation, but
    ``tdp_watts`` matters for power-only cost estimates and ``vram_gb``
    is informational (which models will fit on this card).
    """
    gpu_id: str                  # canonical id, e.g. "nvidia-rtx-4090"
    display_name: str            # human-facing name, e.g. "NVIDIA RTX 4090"
    tdp_watts: float             # thermal design power in watts
    vram_gb: float               # VRAM in gigabytes (0 for CPU-only)
    default_tokens_per_second: float  # reference 8B-class throughput
    notes: str = ""


@dataclass(frozen=True)
class ModelProfile:
    """Throughput profile of one Ollama model tag, per GPU class.

    ``tokens_per_second_by_gpu`` maps canonical ``gpu_id`` to per-second
    throughput. Missing entries fall back to the model's
    ``default_tokens_per_second``.
    """
    model_id: str                # Ollama tag, e.g. "llama3.3:70b"
    display_name: str
    parameters_b: float          # parameter count in billions
    default_tokens_per_second: float
    tokens_per_second_by_gpu: dict[str, float] = field(default_factory=dict)
    notes: str = ""


@dataclass(frozen=True)
class LocalCostBreakdown:
    """Result of one local-cost calculation."""
    cost_per_token_usd: float
    cost_per_million_tokens_usd: float
    cost_per_second_usd: float
    cost_per_hour_usd: float
    #: Breakdown of contributing cost components (USD per token).
    components: dict[str, float]
    #: Effective tokens/sec after utilization adjustment.
    effective_tokens_per_second: float
    #: Human-readable explanation of how the number was derived.
    explanation: str
    #: Inputs the calculation used (for transparency / audit).
    assumptions: dict


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def _parse_gpu_profiles(raw: dict) -> dict[str, GpuProfile]:
    """Parse the ``gpus`` section of a GPU profiles JSON file.

    Required fields per entry: ``tdp_watts``, ``default_tokens_per_second``,
    ``display_name``, ``vram_gb``. Entries missing required fields are
    skipped (and logged). ``vram_gb`` is 0 for CPU-only profiles — that
    is a legitimate value, not missing data.
    """
    out: dict[str, GpuProfile] = {}
    for gid, g in raw.items():
        if not isinstance(g, dict):
            continue
        try:
            # Required: tdp_watts and default_tokens_per_second must be present
            # (not defaulted) so a bad entry is filtered rather than silently
            # parsed as 0.0.
            if "tdp_watts" not in g or "default_tokens_per_second" not in g:
                log.warning("Skipping GPU profile %s: missing tdp_watts or default_tokens_per_second", gid)
                continue
            tdp_watts = float(g["tdp_watts"])
            default_tps = float(g["default_tokens_per_second"])
            if tdp_watts < 0 or default_tps < 0:
                log.warning("Skipping GPU profile %s: negative tdp/tps", gid)
                continue
            out[gid] = GpuProfile(
                gpu_id=gid,
                display_name=str(g.get("display_name", gid)),
                tdp_watts=tdp_watts,
                vram_gb=float(g.get("vram_gb", 0.0)),
                default_tokens_per_second=default_tps,
                notes=str(g.get("notes", "")),
            )
        except (TypeError, ValueError) as e:
            log.warning("Skipping malformed GPU profile %s: %s", gid, e)
    return out


def _parse_model_profiles(raw: dict) -> dict[str, ModelProfile]:
    """Parse the ``models`` section of a model profiles JSON file."""
    out: dict[str, ModelProfile] = {}
    for mid, m in raw.items():
        if not isinstance(m, dict):
            continue
        try:
            tps_by_gpu_raw = m.get("tokens_per_second_by_gpu") or {}
            tps_by_gpu: dict[str, float] = {}
            for gpu_id, val in tps_by_gpu_raw.items():
                try:
                    tps_by_gpu[str(gpu_id)] = float(val)
                except (TypeError, ValueError):
                    continue
            out[mid] = ModelProfile(
                model_id=mid,
                display_name=str(m.get("display_name", mid)),
                parameters_b=float(m.get("parameters_b", 0.0)),
                default_tokens_per_second=float(m.get("default_tokens_per_second", 0.0)),
                tokens_per_second_by_gpu=tps_by_gpu,
                notes=str(m.get("notes", "")),
            )
        except (KeyError, TypeError, ValueError) as e:
            log.warning("Skipping malformed model profile %s: %s", mid, e)
    return out


def load_gpu_profiles(path: PathLike) -> dict[str, GpuProfile]:
    """Load GPU profiles from a JSON file. Returns ``{}`` on missing/malformed."""
    p = Path(path)
    if not p.exists():
        log.warning("GPU profiles file not found: %s", p)
        return {}
    try:
        payload = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError) as e:
        log.warning("GPU profiles file %s is unreadable: %s", p, e)
        return {}
    if not isinstance(payload, dict):
        return {}
    return _parse_gpu_profiles(payload.get("gpus") or {})


def load_model_profiles(path: PathLike) -> dict[str, ModelProfile]:
    """Load model profiles from a JSON file. Returns ``{}`` on missing/malformed."""
    p = Path(path)
    if not p.exists():
        log.warning("Model profiles file not found: %s", p)
        return {}
    try:
        payload = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Model profiles file %s is unreadable: %s", p, e)
        return {}
    if not isinstance(payload, dict):
        return {}
    return _parse_model_profiles(payload.get("models") or {})


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def resolve_gpu(
    gpu_id: str,
    profiles: dict[str, GpuProfile],
) -> Optional[GpuProfile]:
    """Resolve a GPU by canonical id or display name (case-insensitive)."""
    if gpu_id in profiles:
        return profiles[gpu_id]
    lower = gpu_id.lower().strip()
    for gid, prof in profiles.items():
        if prof.display_name.lower() == lower:
            return prof
    return None


def resolve_tokens_per_second(
    model: ModelProfile,
    gpu_id: str,
    override: Optional[float] = None,
    gpu_profiles: Optional[dict[str, GpuProfile]] = None,
) -> float:
    """Resolve tokens/sec for a (model, gpu) pair, with override + fallback.

    Priority:
      1. ``override`` argument (operator-supplied measurement)
      2. ``model.tokens_per_second_by_gpu[gpu_id]`` (profile direct hit)
      3. ``model.default_tokens_per_second`` ×
         ``(gpu.default_tokens_per_second / reference_default)``
         (proxy from GPU's reference throughput)
      4. ``model.default_tokens_per_second`` (last resort)
    """
    if override is not None and override > 0:
        return float(override)
    if gpu_id in model.tokens_per_second_by_gpu:
        return float(model.tokens_per_second_by_gpu[gpu_id])
    if gpu_profiles and gpu_id in gpu_profiles:
        gpu = gpu_profiles[gpu_id]
        # Default reference: 135 tok/s on RTX 4090-class hardware (an 8B model).
        # If we knew the model's reference baseline we could scale more accurately,
        # but we don't ship that. So we use the GPU default as a proxy and assume
        # the model scales the same as the reference 8B. This is a heuristic;
        # operators who care should pass `tokens_per_second` explicitly.
        ref = 135.0
        if gpu.default_tokens_per_second > 0:
            return float(model.default_tokens_per_second) * gpu.default_tokens_per_second / ref
    return float(model.default_tokens_per_second)


# ---------------------------------------------------------------------------
# Pure cost math
# ---------------------------------------------------------------------------

def local_cost_per_token(
    tokens_per_second: float,
    tdp_watts: float = 0.0,
    gpu_cost_per_hour: float = 0.0,
    power_cost_per_kwh: float = 0.0,
    utilization: float = 1.0,
) -> LocalCostBreakdown:
    """Compute the per-token cost of running a local model.

    Parameters
    ----------
    tokens_per_second
        Measured (or estimated) throughput for the model on this hardware.
        Must be > 0 — values <= 0 raise ``ValueError``.
    tdp_watts
        GPU power draw in watts. Used only when ``power_cost_per_kwh > 0``.
    gpu_cost_per_hour
        Hourly cost of running this GPU. Typical sources: cloud GPU rental
        (Lambda Labs, RunPod, Vast.ai), amortized hardware purchase
        (e.g. ``$2500 / (5 * 365 * 24)``), or 0 for "free at the meter".
    power_cost_per_kwh
        Electricity rate. ``0`` means don't bill power at all.
    utilization
        Duty cycle in [0, 1]. Lower values spread fixed costs over fewer
        tokens (more expensive per token). Default 1.0 = always busy.

    Returns
    -------
    LocalCostBreakdown

    Raises
    ------
    ValueError
        If ``tokens_per_second <= 0`` or ``utilization`` is outside (0, 1].
    """
    if tokens_per_second <= 0:
        raise ValueError(f"tokens_per_second must be > 0, got {tokens_per_second}")
    if not (0.0 < utilization <= 1.0):
        raise ValueError(f"utilization must be in (0, 1], got {utilization}")
    if gpu_cost_per_hour < 0 or power_cost_per_kwh < 0 or tdp_watts < 0:
        raise ValueError("cost inputs must be non-negative")

    # Per-second cost
    rental_per_second = gpu_cost_per_hour / 3600.0
    power_per_hour = (tdp_watts / 1000.0) * power_cost_per_kwh
    power_per_second = power_per_hour / 3600.0
    cost_per_second = rental_per_second + power_per_second
    cost_per_hour = cost_per_second * 3600.0

    # Effective throughput after duty cycle adjustment.
    effective_tps = tokens_per_second * utilization

    # Per-token
    cost_per_token = cost_per_second / effective_tps
    cost_per_million = cost_per_token * 1_000_000.0

    components = {}
    if rental_per_second > 0:
        components["gpu_rental"] = rental_per_second / effective_tps
    if power_per_second > 0:
        components["power"] = power_per_second / effective_tps
    if not components:
        components["none"] = 0.0

    # Explanation
    parts: list[str] = []
    parts.append(f"Cost rate: ${cost_per_second:.6f}/sec = ${cost_per_hour:.4f}/hr.")
    if rental_per_second > 0:
        parts.append(
            f"GPU rental ${gpu_cost_per_hour:.4f}/hr ÷ 3600 = ${rental_per_second:.6f}/sec."
        )
    if power_per_second > 0:
        parts.append(
            f"Power: {tdp_watts:.0f}W × ${power_cost_per_kwh:.4f}/kWh ÷ 3600 = ${power_per_second:.6f}/sec."
        )
    parts.append(
        f"Effective throughput: {tokens_per_second:.1f} tok/s × utilization {utilization:.2f} "
        f"= {effective_tps:.1f} tok/s."
    )
    parts.append(
        f"Per-token: ${cost_per_second:.6f}/sec ÷ {effective_tps:.1f} tok/s = "
        f"${cost_per_token:.10f}/token (${cost_per_million:.4f}/1M tokens)."
    )
    if utilization < 1.0:
        parts.append(
            f"Note: utilization={utilization:.2f} — fixed costs amortized over "
            f"{effective_tps:.1f} tok/s instead of {tokens_per_second:.1f} tok/s."
        )

    assumptions = {
        "tokens_per_second_input": tokens_per_second,
        "utilization": utilization,
        "gpu_cost_per_hour": gpu_cost_per_hour,
        "power_cost_per_kwh": power_cost_per_kwh,
        "tdp_watts": tdp_watts,
    }

    return LocalCostBreakdown(
        cost_per_token_usd=cost_per_token,
        cost_per_million_tokens_usd=cost_per_million,
        cost_per_second_usd=cost_per_second,
        cost_per_hour_usd=cost_per_hour,
        components=components,
        effective_tokens_per_second=effective_tps,
        explanation=" ".join(parts),
        assumptions=assumptions,
    )