"""Loads model pricing from one or more JSON config files.

The config file is intentionally a plain JSON object so non-engineers can
update prices without touching code. See ``config/pricing.json`` for schema.

Multi-file merge: ``load_pricing_files(*paths)`` reads multiple files in
order and returns a single ``{model_id: ModelPricing}`` dict. Later files
override earlier ones on collision (so ``config/openrouter.json`` loaded
after ``config/pricing.json`` replaces any placeholder OpenRouter entries
with live data).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union


@dataclass(frozen=True)
class ModelPricing:
    """Pricing and capability metadata for one model."""
    model_id: str
    provider: str
    display_name: str
    input_per_1m: float           # USD per 1,000,000 input tokens
    output_per_1m: float          # USD per 1,000,000 output tokens
    cached_input_per_1m: float    # USD per 1,000,000 cached input tokens
    context_window: int           # Max input+output tokens the model can handle
    supports_reasoning: bool
    reasoning_per_1m: Optional[float]  # USD per 1,000,000 reasoning tokens (if supported)
    tool_call_cost: float         # Flat USD per tool call (default 0.0)
    image_input_cost_per_image: float  # USD per image
    notes: str = ""


PathLike = Union[str, Path]


def _parse_models(models_raw: dict) -> dict[str, ModelPricing]:
    """Parse the ``models`` dict from a pricing file into ModelPricing objects.

    Invalid entries (missing required fields, bad types) are skipped — they
    would otherwise poison the whole loader and break every endpoint.
    """
    parsed: dict[str, ModelPricing] = {}
    for model_id, m in models_raw.items():
        if not isinstance(m, dict):
            continue
        try:
            parsed[model_id] = ModelPricing(
                model_id=model_id,
                provider=m["provider"],
                display_name=m.get("display_name", model_id),
                input_per_1m=float(m["input_per_1m"]),
                output_per_1m=float(m["output_per_1m"]),
                cached_input_per_1m=float(m.get("cached_input_per_1m", 0.0)),
                context_window=int(m.get("context_window", 0)),
                supports_reasoning=bool(m.get("supports_reasoning", False)),
                reasoning_per_1m=(float(m["reasoning_per_1m"])
                                  if m.get("reasoning_per_1m") is not None else None),
                tool_call_cost=float(m.get("tool_call_cost", 0.0)),
                image_input_cost_per_image=float(m.get("image_input_cost_per_image", 0.0)),
                notes=m.get("notes", ""),
            )
        except (KeyError, TypeError, ValueError):
            continue
    return parsed


class PricingLoader:
    """Loads and caches model pricing from a JSON file on disk."""

    def __init__(self, path: PathLike):
        self._path = Path(path)
        self._models: dict[str, ModelPricing] = {}
        self.reload()

    def reload(self) -> None:
        """Re-read the file from disk. Operators can edit pricing without restarting."""
        if not self._path.exists():
            raise FileNotFoundError(f"Pricing config not found: {self._path}")
        raw = json.loads(self._path.read_text())
        models_raw = raw.get("models", {})
        self._models = _parse_models(models_raw)

    def replace_models(self, models: dict[str, ModelPricing]) -> None:
        """Swap in a pre-built model dict (used after merging multiple files)."""
        self._models = dict(models)

    def list_model_ids(self) -> list[str]:
        return list(self._models.keys())

    def list_models(self) -> list[ModelPricing]:
        return list(self._models.values())

    def get_model(self, model_id: str) -> ModelPricing:
        if model_id not in self._models:
            available = ", ".join(sorted(self._models.keys()))
            raise KeyError(f"Unknown model '{model_id}'. Available: {available}")
        return self._models[model_id]


def load_pricing_files(*paths: PathLike,
                        missing_ok: bool = False) -> dict[str, ModelPricing]:
    """Load and merge multiple pricing files. Later files override earlier on collision.

    Parameters
    ----------
    *paths
        One or more file paths (strings or ``Path`` objects). Loaded in order.
    missing_ok
        If ``True``, missing files are silently skipped (returns whatever was
        loaded from the files that did exist). If ``False`` (the default),
        a missing file raises ``FileNotFoundError``. Set this when the
        OpenRouter cache may not yet exist (first boot before any fetch).

    Returns
    -------
    dict[str, ModelPricing]
        Merged ``{model_id: ModelPricing}`` dict. Same model_id appearing in
        multiple files keeps the value from the *last* file containing it.

    Notes
    -----
    The OpenRouter cache file (``config/openrouter.json``) is intentionally
    written in the same schema as ``config/pricing.json`` so this loader
    can read both interchangeably. Order matters — pass hand-curated first,
    then OpenRouter, so live data wins on collisions.
    """
    merged: dict[str, ModelPricing] = {}
    for p in paths:
        path = Path(p)
        if not path.exists():
            if missing_ok:
                continue
            raise FileNotFoundError(f"Pricing config not found: {path}")
        raw = json.loads(path.read_text())
        models_raw = raw.get("models", {})
        parsed = _parse_models(models_raw)
        merged.update(parsed)
    return merged