"""FastAPI app exposing the token-cost calculator over HTTP.

Pricing is loaded from ``worker/config/pricing.json`` (hand-curated) merged with
``worker/config/openrouter.json`` (auto-generated cache). Use ``POST /admin/reload``
to re-read from disk, or ``POST /admin/openrouter/refresh`` to fetch fresh
prices from OpenRouter and rewrite the cache.

Background refresh runs every ``OPENROUTER_REFRESH_SECONDS`` seconds when > 0
(default 21600 = 6 hours). Set to 0 to disable the scheduler.
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from .calculator import (
    Calculator,
    CalculationRequest,
    CalculationResult,
    TASK_SIZE_PRESETS,
    REASONING_MULTIPLIERS,
    TASK_TYPE_MULTIPLIERS,
)
from .local_cost import (
    GpuProfile,
    ModelProfile,
    load_gpu_profiles,
    load_model_profiles,
    local_cost_per_token,
    resolve_gpu,
    resolve_tokens_per_second,
)
from .models import (
    CalculateRequest,
    CompareRequest,
    CalculationResultOut,
    LocalCostBreakdownOut,
    LocalCostRequest,
    LocalCostResponse,
    ModelOut,
    TokensUsedOut,
)
from .openrouter import refresh_to_disk
from .pricing import PricingLoader, load_pricing_files


log = logging.getLogger(__name__)


#: Default path to the hand-curated pricing config.
DEFAULT_PRICING_PATH = os.environ.get(
    "PRICING_CONFIG",
    str(Path(__file__).resolve().parent.parent / "worker" / "config" / "pricing.json"),
)

#: Default path to the auto-generated OpenRouter cache.
DEFAULT_OPENROUTER_PATH = str(
    Path(__file__).resolve().parent.parent / "worker" / "config" / "openrouter.json"
)

#: Default background refresh interval (6 hours). 0 disables the scheduler.
DEFAULT_REFRESH_SECONDS = 21600

#: Default path to the GPU profiles file (data/local_gpu_profiles.json).
DEFAULT_GPU_PROFILES_PATH = str(
    Path(__file__).resolve().parent.parent / "data" / "local_gpu_profiles.json"
)

#: Default path to the Ollama model profiles file (data/local_model_profiles.json).
DEFAULT_MODEL_PROFILES_PATH = str(
    Path(__file__).resolve().parent.parent / "data" / "local_model_profiles.json"
)


def _result_to_out(r: CalculationResult) -> CalculationResultOut:
    return CalculationResultOut(
        model_id=r.model_id,
        display_name=r.display_name,
        input_cost=r.input_cost,
        output_cost=r.output_cost,
        reasoning_cost=r.reasoning_cost,
        tool_cost=r.tool_cost,
        image_cost=r.image_cost,
        cost_per_run=r.cost_per_run,
        total_cost=r.total_cost,
        num_runs=r.num_runs,
        tokens_used=TokensUsedOut(
            input_tokens=r.tokens_used.input_tokens,
            output_tokens=r.tokens_used.output_tokens,
            reasoning_tokens=r.tokens_used.reasoning_tokens,
            cached_input_tokens=r.tokens_used.cached_input_tokens,
        ),
        explanation=r.explanation,
        assumptions=r.assumptions,
    )


def _request_to_calc(req: CalculateRequest | CompareRequest, model_id: str) -> CalculationRequest:
    return CalculationRequest(
        model_id=model_id,
        input_tokens=req.input_tokens,
        output_tokens=req.output_tokens,
        cached_input_tokens=req.cached_input_tokens,
        reasoning_tokens=req.reasoning_tokens,
        tool_call_count=req.tool_call_count,
        image_input_count=req.image_input_count,
        num_runs=req.num_runs,
        task_size=req.task_size,
        reasoning_level=req.reasoning_level,
        agentic=req.agentic,
        system_prompt_tokens=req.system_prompt_tokens,
        task_type=req.task_type,
    )


def _build_loader(pricing_paths: list[str]) -> tuple[PricingLoader, dict[str, int]]:
    """Build a PricingLoader from multiple files. Returns (loader, counts_by_source).

    The ``counts_by_source`` dict maps each path to the number of models loaded
    from it — useful for the API responses.
    """
    merged = load_pricing_files(*pricing_paths, missing_ok=True)
    # We need a single PricingLoader; create a stub one and use replace_models.
    # Use the first existing path as the loader's primary file (for reload()).
    primary = next((Path(p) for p in pricing_paths if Path(p).exists()), None)
    if primary is None:
        # No files exist at all — create an empty loader on the first path.
        primary = Path(pricing_paths[0])
        primary.parent.mkdir(parents=True, exist_ok=True)
        primary.write_text('{"_meta": {}, "models": {}}')
    loader = PricingLoader(primary)
    loader.replace_models(merged)
    counts = {p: sum(1 for m in merged.values() if True) for p in pricing_paths}  # placeholder
    # We don't have per-source counts after merging; that's fine — total is reported.
    return loader, {}


def _rebuild_calculator(loader: PricingLoader, calculator: Calculator) -> None:
    """Swap the calculator's model set to whatever the loader currently has."""
    new_models = loader.list_models()
    calculator._models.clear()
    for m in new_models:
        calculator.add_model(m)


def _openrouter_model_count(loader: PricingLoader) -> int:
    """Count models with namespaced 'openrouter/' ids in the loader."""
    return sum(1 for mid in loader.list_model_ids() if mid.startswith("openrouter/"))


def create_app(
    pricing_path: Optional[str] = None,
    pricing_paths: Optional[list[str]] = None,
    refresh_seconds: Optional[int] = None,
    auto_refresh_on_startup: bool = False,
    gpu_profiles_path: Optional[str] = None,
    model_profiles_path: Optional[str] = None,
) -> FastAPI:
    """Build the FastAPI app.

    Parameters
    ----------
    pricing_path
        Legacy single-file path. If both ``pricing_path`` and ``pricing_paths``
        are given, ``pricing_paths`` wins.
    pricing_paths
        List of paths to merge (hand-curated first, then openrouter cache).
        Missing files are tolerated (``missing_ok=True``).
    refresh_seconds
        Background refresh interval. ``None`` = use env var / default. 0 disables.
    auto_refresh_on_startup
        If True, the lifespan tries a network refresh on startup (used in
        production). Tests should leave this False to avoid hitting the network.
    """
    # Resolve paths (legacy single-file param still works)
    if pricing_paths is None:
        if pricing_path is not None:
            pricing_paths = [pricing_path]
        else:
            pricing_paths = [DEFAULT_PRICING_PATH, DEFAULT_OPENROUTER_PATH]

    # The OpenRouter cache path is the last entry by convention.
    # When the user passes a single pricing_path (legacy mode), there's no
    # OR cache to refresh — set openrouter_cache_path to None and the
    # refresh endpoint will refuse with 503.
    openrouter_cache_path: Optional[str] = None
    if len(pricing_paths) >= 2:
        openrouter_cache_path = pricing_paths[-1]

    # Resolve refresh interval
    if refresh_seconds is None:
        env_val = os.environ.get("OPENROUTER_REFRESH_SECONDS", str(DEFAULT_REFRESH_SECONDS))
        try:
            refresh_seconds = int(env_val)
        except ValueError:
            refresh_seconds = DEFAULT_REFRESH_SECONDS

    loader, _ = _build_loader(pricing_paths)
    calculator = Calculator(*loader.list_models())

    # Local-cost profiles (GPU + Ollama model throughput).
    # Missing files are tolerated — the endpoint returns 503 instead of 500.
    gpu_profiles = load_gpu_profiles(gpu_profiles_path or DEFAULT_GPU_PROFILES_PATH)
    model_profiles = load_model_profiles(model_profiles_path or DEFAULT_MODEL_PROFILES_PATH)

    # State the lifespan + endpoint need access to at runtime
    state = {
        "loader": loader,
        "calculator": calculator,
        "pricing_paths": pricing_paths,
        "openrouter_cache_path": openrouter_cache_path,
        "refresh_seconds": refresh_seconds,
        "auto_refresh_on_startup": auto_refresh_on_startup,
        "gpu_profiles": gpu_profiles,
        "model_profiles": model_profiles,
    }

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Best-effort initial refresh + optional background scheduler."""
        background_task = None
        if state["auto_refresh_on_startup"] and state["openrouter_cache_path"]:
            try:
                count = await asyncio.to_thread(
                    refresh_to_disk, Path(state["openrouter_cache_path"])
                )
                if count > 0:
                    merged = load_pricing_files(*state["pricing_paths"], missing_ok=True)
                    state["loader"].replace_models(merged)
                    _rebuild_calculator(state["loader"], state["calculator"])
                    log.info("Initial OpenRouter refresh: %d models", count)
            except Exception as e:
                log.warning("Initial OpenRouter refresh failed (keeping stale cache): %s", e)

        if state["refresh_seconds"] and state["refresh_seconds"] > 0 and state["openrouter_cache_path"]:
            background_task = asyncio.create_task(_refresh_loop())

        try:
            yield
        finally:
            if background_task is not None:
                background_task.cancel()
                try:
                    await background_task
                except asyncio.CancelledError:
                    pass

    async def _refresh_loop() -> None:
        """Periodically refresh the OpenRouter cache. Runs until cancelled."""
        while True:
            try:
                await asyncio.sleep(state["refresh_seconds"])
            except asyncio.CancelledError:
                raise
            try:
                count = await asyncio.to_thread(
                    refresh_to_disk, Path(state["openrouter_cache_path"])
                )
                merged = load_pricing_files(*state["pricing_paths"], missing_ok=True)
                state["loader"].replace_models(merged)
                _rebuild_calculator(state["loader"], state["calculator"])
                log.info("Background OpenRouter refresh: %d models", count)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("Background OpenRouter refresh failed: %s", e)

    app = FastAPI(
        title="Token Cost Calculator API",
        description="Estimate AI inference cost from a model + token usage. "
                    "Pricing is loaded from a JSON config and reloadable at runtime. "
                    "Includes live OpenRouter sync (340+ models) and a local-cost "
                    "calculator for self-hosted Ollama (GPU + power -> $/token).",
        version="1.2.0",
        lifespan=lifespan,
    )

    # CORS for the static frontend. Allow all origins because the frontend is
    # served from a separate vault port (e.g. :3018) during dev. Tighten this
    # before public launch.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.get("/")
    def root():
        total = len(loader.list_model_ids())
        or_count = _openrouter_model_count(loader)
        return {
            "name": "Token Cost Calculator API",
            "version": "1.2.0",
            "models_loaded": total,
            "openrouter_models": or_count,
            "local_gpus": len(state["gpu_profiles"]),
            "local_models": len(state["model_profiles"]),
            "refresh_seconds": state["refresh_seconds"],
            "endpoints": [
                "GET /health",
                "GET /models",
                "GET /models/{model_id}",
                "POST /calculate",
                "POST /calculate/compare",
                "POST /calculate/local",
                "GET /local/gpus",
                "GET /local/models",
                "POST /admin/reload",
                "POST /admin/openrouter/refresh",
            ],
        }

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "models_loaded": len(loader.list_model_ids()),
            "openrouter_models": _openrouter_model_count(loader),
        }

    @app.get("/models")
    def list_models():
        return {"models": [
            ModelOut(
                model_id=m.model_id,
                provider=m.provider,
                display_name=m.display_name,
                input_per_1m=m.input_per_1m,
                output_per_1m=m.output_per_1m,
                cached_input_per_1m=m.cached_input_per_1m,
                context_window=m.context_window,
                supports_reasoning=m.supports_reasoning,
                reasoning_per_1m=m.reasoning_per_1m,
                tool_call_cost=m.tool_call_cost,
                image_input_cost_per_image=m.image_input_cost_per_image,
                notes=m.notes,
            ).model_dump() for m in loader.list_models()
        ]}

    @app.get("/models/{model_id:path}")
    def get_model(model_id: str):
        try:
            m = loader.get_model(model_id)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e))
        return ModelOut(
            model_id=m.model_id, provider=m.provider, display_name=m.display_name,
            input_per_1m=m.input_per_1m, output_per_1m=m.output_per_1m,
            cached_input_per_1m=m.cached_input_per_1m, context_window=m.context_window,
            supports_reasoning=m.supports_reasoning, reasoning_per_1m=m.reasoning_per_1m,
            tool_call_cost=m.tool_call_cost, image_input_cost_per_image=m.image_input_cost_per_image,
            notes=m.notes,
        )

    @app.post("/calculate")
    def calculate(req: CalculateRequest):
        try:
            calc_req = _request_to_calc(req, req.model_id)
            result = calculator.calculate(calc_req)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e))
        return _result_to_out(result).model_dump()

    @app.post("/calculate/compare")
    def compare(req: CompareRequest):
        results = []
        for mid in req.model_ids:
            try:
                calc_req = _request_to_calc(req, mid)
                r = calculator.calculate(calc_req)
            except KeyError as e:
                raise HTTPException(status_code=404, detail=str(e))
            results.append(_result_to_out(r).model_dump())
        return {"results": results}

    @app.post("/calculate/local")
    def calculate_local(req: LocalCostRequest):
        """Self-hosted (Ollama) cost estimate.

        Resolves the GPU + model from the local profile data, looks up (or
        accepts an override for) tokens/sec, then computes:

            cost_per_token = (rental_per_sec + power_per_sec) / (tps * utilization)

        Returns both the per-token cost and a per-task total that mirrors the
        ``/calculate`` endpoint's task_size / reasoning / task_type conventions.
        """
        gpus = state["gpu_profiles"]
        models = state["model_profiles"]
        if not gpus or not models:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Local-cost profiles are not loaded (missing data/local_*.json?)",
            )

        gpu = resolve_gpu(req.gpu_id, gpus)
        if gpu is None:
            avail = ", ".join(sorted(gpus.keys()))
            raise HTTPException(
                status_code=404,
                detail=f"Unknown GPU '{req.gpu_id}'. Available (canonical ids): {avail}",
            )
        if req.model_id not in models:
            avail = ", ".join(sorted(models.keys()))
            raise HTTPException(
                status_code=404,
                detail=f"Unknown local model '{req.model_id}'. Available: {avail}",
            )
        model = models[req.model_id]

        tokens_per_second = resolve_tokens_per_second(
            model=model,
            gpu_id=gpu.gpu_id,
            override=req.tokens_per_second,
            gpu_profiles=gpus,
        )

        tdp_watts = req.gpu_tdp_watts if req.gpu_tdp_watts is not None else gpu.tdp_watts
        breakdown = local_cost_per_token(
            tokens_per_second=tokens_per_second,
            tdp_watts=tdp_watts,
            gpu_cost_per_hour=req.gpu_cost_per_hour,
            power_cost_per_kwh=req.power_cost_per_kwh,
            utilization=req.utilization,
        )

        # Apply task-size / reasoning / task-type so the per-task total
        # matches the /calculate endpoint's shape.
        if req.task_size and req.task_size in TASK_SIZE_PRESETS:
            preset_in, preset_out = TASK_SIZE_PRESETS[req.task_size]
            in_t = req.input_tokens if req.input_tokens is not None else preset_in
            out_t = req.output_tokens if req.output_tokens is not None else preset_out
        else:
            in_t = req.input_tokens or 0
            out_t = req.output_tokens or 0
        out_mult = REASONING_MULTIPLIERS.get(req.reasoning_level, 1.0)
        out_t = int(out_t * out_mult)
        total_tokens = in_t + out_t
        type_mult = TASK_TYPE_MULTIPLIERS.get(req.task_type, 1.0)
        cost_per_run = breakdown.cost_per_token_usd * total_tokens * type_mult
        total_cost = cost_per_run * req.num_runs

        return LocalCostResponse(
            model_id=model.model_id,
            gpu_id=gpu.gpu_id,
            gpu_display_name=gpu.display_name,
            model_display_name=model.display_name,
            tokens_per_second=tokens_per_second,
            effective_tokens_per_second=breakdown.effective_tokens_per_second,
            cost_per_token_usd=breakdown.cost_per_token_usd,
            cost_per_million_tokens_usd=breakdown.cost_per_million_tokens_usd,
            cost_per_hour_usd=breakdown.cost_per_hour_usd,
            total_tokens=total_tokens,
            cost_per_run=cost_per_run,
            total_cost=total_cost,
            num_runs=req.num_runs,
            tokens_used=TokensUsedOut(
                input_tokens=in_t,
                output_tokens=out_t,
                reasoning_tokens=0,
                cached_input_tokens=0,
            ),
            breakdown=LocalCostBreakdownOut(
                gpu_rental=breakdown.components.get("gpu_rental"),
                power=breakdown.components.get("power"),
            ),
            explanation=breakdown.explanation,
            assumptions={
                **breakdown.assumptions,
                "task_type_multiplier": type_mult,
                "reasoning_level_multiplier": out_mult,
                "tokens_per_second_source": (
                    "override" if req.tokens_per_second is not None
                    else "profile" if gpu.gpu_id in model.tokens_per_second_by_gpu
                    else "fallback"
                ),
            },
        ).model_dump()

    @app.get("/local/gpus")
    def list_local_gpus():
        """List all known GPU profiles (canonical id + display name + tdp + tps)."""
        sorted_gpus = sorted(state["gpu_profiles"].values(), key=lambda g: g.gpu_id)
        return {"gpus": [
            {
                "gpu_id": g.gpu_id,
                "display_name": g.display_name,
                "tdp_watts": g.tdp_watts,
                "vram_gb": g.vram_gb,
                "default_tokens_per_second": g.default_tokens_per_second,
                "notes": g.notes,
            } for g in sorted_gpus
        ]}

    @app.get("/local/models")
    def list_local_models():
        """List all known local (Ollama) model profiles."""
        sorted_models = sorted(state["model_profiles"].values(), key=lambda m: m.model_id)
        return {"models": [
            {
                "model_id": m.model_id,
                "display_name": m.display_name,
                "parameters_b": m.parameters_b,
                "default_tokens_per_second": m.default_tokens_per_second,
                "supported_gpus": sorted(m.tokens_per_second_by_gpu.keys()),
                "notes": m.notes,
            } for m in sorted_models
        ]}

    @app.post("/admin/reload")
    def reload_pricing():
        """Re-read all configured pricing files from disk (no network)."""
        merged = load_pricing_files(*state["pricing_paths"], missing_ok=True)
        state["loader"].replace_models(merged)
        _rebuild_calculator(state["loader"], state["calculator"])
        return {
            "status": "reloaded",
            "models_loaded": len(merged),
            "openrouter_models": _openrouter_model_count(state["loader"]),
        }

    @app.post("/admin/openrouter/refresh")
    def refresh_openrouter():
        """Fetch live OpenRouter prices and rewrite the cache file.

        On network failure returns 503 (stale cache remains in use). On
        success returns the new model count and reloads the merged pricing
        so the changes take effect immediately.
        """
        if not state["openrouter_cache_path"]:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OpenRouter cache is not configured (no second pricing path)",
            )
        try:
            count = refresh_to_disk(Path(state["openrouter_cache_path"]))
        except Exception as e:
            log.warning("Manual OpenRouter refresh failed: %s", e)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"OpenRouter refresh failed: {e}",
            )
        # Reload merged pricing (hand-curated + freshly-written cache)
        merged = load_pricing_files(*state["pricing_paths"], missing_ok=True)
        state["loader"].replace_models(merged)
        _rebuild_calculator(state["loader"], state["calculator"])
        return {
            "status": "reloaded",
            "models_loaded": len(merged),
            "openrouter_models": count,
        }

    return app


# Convenience: `python -m app.main` or `uvicorn app.main:app` works directly.
app = create_app(auto_refresh_on_startup=True)