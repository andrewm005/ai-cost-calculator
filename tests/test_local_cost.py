"""Tests for the local (self-hosted) cost calculator.

Three layers:

1. Pure math — ``local_cost_per_token()`` happy path, edge cases,
   the formula match to ``findings.md`` §5.
2. Profile loaders — ``load_gpu_profiles()``, ``load_model_profiles()``,
   handling of missing/malformed files.
3. Lookup helpers — ``resolve_gpu()`` (id + display-name), ``resolve_tokens_per_second()``
   (override > profile > fallback).
4. Endpoint — ``POST /calculate/local`` with the bundled ``data/`` JSON
   files, plus 404 / 422 cases.
"""
from __future__ import annotations

import json
import math

import pytest
from fastapi.testclient import TestClient

from app.local_cost import (
    GpuProfile,
    ModelProfile,
    local_cost_per_token,
    load_gpu_profiles,
    load_model_profiles,
    resolve_gpu,
    resolve_tokens_per_second,
)
from app.main import create_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

GPU_JSON = {
    "_meta": {"schema_version": "1.0"},
    "gpus": {
        "test-rtx-4090": {
            "display_name": "Test RTX 4090",
            "tdp_watts": 450.0,
            "vram_gb": 24.0,
            "default_tokens_per_second": 135.0,
            "notes": "test fixture",
        },
        "test-h100": {
            "display_name": "Test H100",
            "tdp_watts": 700.0,
            "vram_gb": 80.0,
            "default_tokens_per_second": 350.0,
            "notes": "",
        },
        "test-cpu": {
            "display_name": "Test CPU",
            "tdp_watts": 200.0,
            "vram_gb": 0.0,
            "default_tokens_per_second": 3.0,
            "notes": "",
        },
    },
}

MODEL_JSON = {
    "_meta": {"schema_version": "1.0"},
    "models": {
        "test-8b": {
            "display_name": "Test 8B",
            "parameters_b": 8.0,
            "default_tokens_per_second": 135.0,
            "tokens_per_second_by_gpu": {
                "test-rtx-4090": 135.0,
                "test-h100": 350.0,
                "test-cpu": 3.0,
            },
            "notes": "reference 8B",
        },
        "test-70b": {
            "display_name": "Test 70B",
            "parameters_b": 70.0,
            "default_tokens_per_second": 25.0,
            "tokens_per_second_by_gpu": {
                "test-h100": 110.0,
            },
            "notes": "needs big VRAM",
        },
    },
}


@pytest.fixture
def tmp_data(tmp_path):
    """Write GPU + model JSON files to tmp and return (gpu_path, model_path)."""
    gp = tmp_path / "gpus.json"
    mp = tmp_path / "models.json"
    gp.write_text(json.dumps(GPU_JSON))
    mp.write_text(json.dumps(MODEL_JSON))
    return gp, mp


@pytest.fixture
def client(tmp_path):
    """A TestClient wired to a minimal pricing + the tmp local profile data."""
    pricing = tmp_path / "pricing.json"
    pricing.write_text(json.dumps({
        "_meta": {"schema_version": "1.0"},
        "models": {},
    }))
    gp = tmp_path / "gpus.json"
    mp = tmp_path / "models.json"
    gp.write_text(json.dumps(GPU_JSON))
    mp.write_text(json.dumps(MODEL_JSON))
    app = create_app(
        pricing_path=str(pricing),
        gpu_profiles_path=str(gp),
        model_profiles_path=str(mp),
    )
    return TestClient(app)


# ---------------------------------------------------------------------------
# local_cost_per_token() — pure math
# ---------------------------------------------------------------------------

def test_local_cost_formula_rental_only():
    """Pure rental: cost_per_token = (gpu_cost_per_hour / 3600) / tokens_per_second."""
    b = local_cost_per_token(tokens_per_second=135.0, gpu_cost_per_hour=1.80)
    # 1.80 / 3600 / 135 = 3.7037e-6
    assert b.cost_per_token_usd == pytest.approx(1.80 / 3600 / 135, rel=1e-9)
    # 1M tokens
    assert b.cost_per_million_tokens_usd == pytest.approx(b.cost_per_token_usd * 1_000_000, rel=1e-9)
    # Per-hour cost = just the rental
    assert b.cost_per_hour_usd == pytest.approx(1.80, rel=1e-9)
    # Components
    assert b.components["gpu_rental"] == pytest.approx(1.80 / 3600 / 135, rel=1e-9)
    assert "power" not in b.components


def test_local_cost_formula_power_only():
    """Pure electricity: cost_per_token = (tdp/1000 * kwh/3600) / tokens_per_second."""
    # 450W * $0.15/kWh = 67.5W = 0.0675 kW * $0.15 = $0.010125/hr
    b = local_cost_per_token(
        tokens_per_second=135.0,
        tdp_watts=450.0,
        power_cost_per_kwh=0.15,
    )
    expected_per_hour = (450.0 / 1000.0) * 0.15  # $0.0675
    assert b.cost_per_hour_usd == pytest.approx(expected_per_hour, rel=1e-9)
    expected_per_token = expected_per_hour / 3600 / 135
    assert b.cost_per_token_usd == pytest.approx(expected_per_token, rel=1e-9)
    assert "power" in b.components
    assert "gpu_rental" not in b.components


def test_local_cost_combines_rental_and_power():
    """Both inputs present -> both contribute to the per-token cost."""
    b = local_cost_per_token(
        tokens_per_second=100.0,
        tdp_watts=400.0,
        gpu_cost_per_hour=2.0,
        power_cost_per_kwh=0.10,
    )
    expected_per_hour = 2.0 + (0.4 * 0.10)  # 2.0 + 0.04 = 2.04
    assert b.cost_per_hour_usd == pytest.approx(expected_per_hour, rel=1e-9)
    assert b.components["gpu_rental"] == pytest.approx(2.0 / 3600 / 100, rel=1e-9)
    assert b.components["power"] == pytest.approx(0.04 / 3600 / 100, rel=1e-9)
    assert b.cost_per_token_usd == pytest.approx(
        b.components["gpu_rental"] + b.components["power"], rel=1e-9
    )


def test_local_cost_zero_costs_produces_zero():
    """No rental, no power -> $0.00 per token. Useful for "free at the meter"."""
    b = local_cost_per_token(tokens_per_second=100.0, tdp_watts=400.0)
    assert b.cost_per_token_usd == 0.0
    assert b.cost_per_million_tokens_usd == 0.0
    assert b.cost_per_hour_usd == 0.0
    assert b.components == {"none": 0.0}


def test_local_cost_utilization_scales_cost_inversely():
    """50% utilization doubles the per-token cost (fixed costs over fewer tokens)."""
    b_full = local_cost_per_token(tokens_per_second=100.0, gpu_cost_per_hour=1.0, utilization=1.0)
    b_half = local_cost_per_token(tokens_per_second=100.0, gpu_cost_per_hour=1.0, utilization=0.5)
    assert b_half.cost_per_token_usd == pytest.approx(b_full.cost_per_token_usd * 2, rel=1e-9)
    assert b_half.effective_tokens_per_second == pytest.approx(50.0, rel=1e-9)


def test_local_cost_rejects_zero_or_negative_tps():
    """tokens_per_second <= 0 raises ValueError (would divide by zero)."""
    with pytest.raises(ValueError):
        local_cost_per_token(tokens_per_second=0.0, gpu_cost_per_hour=1.0)
    with pytest.raises(ValueError):
        local_cost_per_token(tokens_per_second=-5.0, gpu_cost_per_hour=1.0)


def test_local_cost_rejects_invalid_utilization():
    """utilization must be in (0, 1]."""
    with pytest.raises(ValueError):
        local_cost_per_token(tokens_per_second=100.0, utilization=0.0)
    with pytest.raises(ValueError):
        local_cost_per_token(tokens_per_second=100.0, utilization=1.5)
    with pytest.raises(ValueError):
        local_cost_per_token(tokens_per_second=100.0, utilization=-0.1)


def test_local_cost_rejects_negative_costs():
    """Negative rates don't make sense — explicit guard."""
    with pytest.raises(ValueError):
        local_cost_per_token(tokens_per_second=100.0, gpu_cost_per_hour=-1.0)
    with pytest.raises(ValueError):
        local_cost_per_token(tokens_per_second=100.0, tdp_watts=400.0, power_cost_per_kwh=-0.1)
    with pytest.raises(ValueError):
        local_cost_per_token(tokens_per_second=100.0, tdp_watts=-10.0, power_cost_per_kwh=0.1)


def test_local_cost_explanation_includes_components():
    """Explanation should mention rate, throughput, and per-token result."""
    b = local_cost_per_token(
        tokens_per_second=100.0, tdp_watts=400.0,
        gpu_cost_per_hour=1.0, power_cost_per_kwh=0.10,
    )
    assert "/sec" in b.explanation
    assert "tok/s" in b.explanation
    assert "/1M tokens" in b.explanation


def test_local_cost_assumptions_records_inputs():
    """assumptions dict echoes the inputs for audit."""
    b = local_cost_per_token(
        tokens_per_second=42.0, tdp_watts=300.0,
        gpu_cost_per_hour=0.5, power_cost_per_kwh=0.12, utilization=0.8,
    )
    assert b.assumptions["tokens_per_second_input"] == 42.0
    assert b.assumptions["tdp_watts"] == 300.0
    assert b.assumptions["gpu_cost_per_hour"] == 0.5
    assert b.assumptions["power_cost_per_kwh"] == 0.12
    assert b.assumptions["utilization"] == 0.8


# ---------------------------------------------------------------------------
# Profile loaders
# ---------------------------------------------------------------------------

def test_load_gpu_profiles_reads_all_entries(tmp_data):
    """All entries parsed into GpuProfile dataclasses."""
    gp, _ = tmp_data
    profiles = load_gpu_profiles(gp)
    assert len(profiles) == 3
    assert "test-rtx-4090" in profiles
    assert profiles["test-rtx-4090"].display_name == "Test RTX 4090"
    assert profiles["test-rtx-4090"].tdp_watts == 450.0
    assert profiles["test-rtx-4090"].vram_gb == 24.0


def test_load_model_profiles_reads_all_entries(tmp_data):
    """Model profiles parse + per-GPU dict captured."""
    _, mp = tmp_data
    profiles = load_model_profiles(mp)
    assert len(profiles) == 2
    assert "test-8b" in profiles
    m = profiles["test-8b"]
    assert m.parameters_b == 8.0
    assert m.tokens_per_second_by_gpu == {
        "test-rtx-4090": 135.0,
        "test-h100": 350.0,
        "test-cpu": 3.0,
    }


def test_load_gpu_profiles_returns_empty_for_missing_file(tmp_path):
    """Missing file -> empty dict (no exception, logged warning)."""
    assert load_gpu_profiles(tmp_path / "nope.json") == {}


def test_load_model_profiles_returns_empty_for_missing_file(tmp_path):
    """Missing file -> empty dict (no exception, logged warning)."""
    assert load_model_profiles(tmp_path / "nope.json") == {}


def test_load_gpu_profiles_handles_malformed_json(tmp_path):
    """Malformed JSON -> empty dict (no crash)."""
    bad = tmp_path / "bad.json"
    bad.write_text("not valid json {")
    assert load_gpu_profiles(bad) == {}


def test_load_gpu_profiles_skips_malformed_entries(tmp_path):
    """A bad entry inside the gpus dict is skipped; valid entries survive."""
    p = tmp_path / "mixed.json"
    p.write_text(json.dumps({
        "gpus": {
            "good": {
                "display_name": "Good", "tdp_watts": 100.0, "vram_gb": 8.0,
                "default_tokens_per_second": 50.0, "notes": "",
            },
            "bad-no-tdp": {
                "display_name": "Bad", "default_tokens_per_second": 50.0,
            },
        }
    }))
    profiles = load_gpu_profiles(p)
    assert "good" in profiles
    assert "bad-no-tdp" not in profiles


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def test_resolve_gpu_by_canonical_id(tmp_data):
    """Passing the canonical id returns the right profile."""
    gp, _ = tmp_data
    gpus = load_gpu_profiles(gp)
    g = resolve_gpu("test-rtx-4090", gpus)
    assert g is not None
    assert g.display_name == "Test RTX 4090"


def test_resolve_gpu_by_display_name(tmp_data):
    """Passing the display name (case-insensitive) returns the right profile."""
    gp, _ = tmp_data
    gpus = load_gpu_profiles(gp)
    assert resolve_gpu("Test H100", gpus).gpu_id == "test-h100"
    assert resolve_gpu("test h100", gpus).gpu_id == "test-h100"
    assert resolve_gpu("  Test H100  ", gpus).gpu_id == "test-h100"


def test_resolve_gpu_returns_none_for_unknown(tmp_data):
    """Unknown id / display name -> None (caller decides 404 vs default)."""
    gp, _ = tmp_data
    gpus = load_gpu_profiles(gp)
    assert resolve_gpu("nope", gpus) is None
    assert resolve_gpu("nvidia-totally-fake", gpus) is None


def test_resolve_tokens_per_second_override_wins(tmp_data):
    """Override argument is the first priority regardless of profile."""
    gp, mp = tmp_data
    gpus = load_gpu_profiles(gp)
    models = load_model_profiles(mp)
    m = models["test-8b"]
    # profile says 135 on test-rtx-4090; override forces 999
    tps = resolve_tokens_per_second(m, "test-rtx-4090", override=999.0, gpu_profiles=gpus)
    assert tps == 999.0


def test_resolve_tokens_per_second_uses_profile_when_present(tmp_data):
    """Direct profile hit (model has tps for this gpu) is the second priority."""
    gp, mp = tmp_data
    gpus = load_gpu_profiles(gp)
    models = load_model_profiles(mp)
    m = models["test-8b"]
    # 8B has tps for test-h100 = 350
    tps = resolve_tokens_per_second(m, "test-h100", gpu_profiles=gpus)
    assert tps == 350.0


def test_resolve_tokens_per_second_fallback_to_default(tmp_data):
    """No profile hit, no override -> model's default_tokens_per_second."""
    gp, mp = tmp_data
    gpus = load_gpu_profiles(gp)
    models = load_model_profiles(mp)
    m = models["test-70b"]  # has entry for test-h100 only
    # test-rtx-4090 is not in 70b's tps dict -> fallback
    tps = resolve_tokens_per_second(m, "test-rtx-4090", gpu_profiles=gpus)
    assert tps == 25.0  # m.default_tokens_per_second


def test_resolve_tokens_per_second_proxy_from_gpu_default(tmp_data):
    """No profile hit, no override, but gpu_profiles has a reference default:
    fallback uses the GPU's default scaled by the model's default."""
    gp, mp = tmp_data
    gpus = load_gpu_profiles(gp)
    models = load_model_profiles(mp)
    # Fake a model with no tps for any gpu
    fake = ModelProfile(
        model_id="fake", display_name="Fake", parameters_b=10.0,
        default_tokens_per_second=100.0, tokens_per_second_by_gpu={},
    )
    # On test-h100 (default 350), 100 * 350/135 = 259.26
    tps = resolve_tokens_per_second(fake, "test-h100", gpu_profiles=gpus)
    assert tps == pytest.approx(100.0 * 350.0 / 135.0, rel=1e-9)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

def test_endpoint_health_includes_local_counts(client):
    """/health should now expose local profile counts (was: 64 tests)."""
    r = client.get("/")
    body = r.json()
    assert "local_gpus" in body
    assert body["local_gpus"] == 3
    assert body["local_models"] == 2
    assert "POST /calculate/local" in body["endpoints"]
    assert "GET /local/gpus" in body["endpoints"]
    assert "GET /local/models" in body["endpoints"]


def test_local_gpus_endpoint(client):
    """GET /local/gpus returns all 3 fixture GPUs."""
    r = client.get("/local/gpus")
    assert r.status_code == 200
    body = r.json()
    ids = [g["gpu_id"] for g in body["gpus"]]
    assert "test-rtx-4090" in ids
    assert ids == sorted(ids)  # sorted by gpu_id
    sample = next(g for g in body["gpus"] if g["gpu_id"] == "test-rtx-4090")
    assert sample["display_name"] == "Test RTX 4090"
    assert sample["tdp_watts"] == 450.0
    assert sample["vram_gb"] == 24.0


def test_local_models_endpoint(client):
    """GET /local/models returns all 2 fixture models with supported_gpus list."""
    r = client.get("/local/models")
    assert r.status_code == 200
    body = r.json()
    ids = [m["model_id"] for m in body["models"]]
    assert "test-8b" in ids
    assert "test-70b" in ids
    sample = next(m for m in body["models"] if m["model_id"] == "test-8b")
    assert sample["display_name"] == "Test 8B"
    assert sample["parameters_b"] == 8.0
    assert set(sample["supported_gpus"]) == {"test-rtx-4090", "test-h100", "test-cpu"}


def test_calculate_local_happy_path(client):
    """The canonical example: rental + 8B model, sanity-check the response shape."""
    r = client.post("/calculate/local", json={
        "model_id": "test-8b",
        "gpu_id": "test-rtx-4090",
        "gpu_cost_per_hour": 1.80,
        "task_size": "medium",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    # Per-token: 1.80 / 3600 / 135 = 3.7037e-6
    assert body["cost_per_token_usd"] == pytest.approx(1.80 / 3600 / 135, rel=1e-9)
    assert body["cost_per_million_tokens_usd"] == pytest.approx(body["cost_per_token_usd"] * 1e6, rel=1e-9)
    # 5000 + 2000 = 7000 tokens, no reasoning, no task-type multiplier
    assert body["total_tokens"] == 7000
    assert body["cost_per_run"] == pytest.approx(body["cost_per_token_usd"] * 7000, rel=1e-9)
    assert body["total_cost"] == pytest.approx(body["cost_per_run"], rel=1e-9)
    assert body["num_runs"] == 1
    # Display
    assert body["model_display_name"] == "Test 8B"
    assert body["gpu_display_name"] == "Test RTX 4090"
    assert body["tokens_per_second"] == 135.0
    assert body["effective_tokens_per_second"] == 135.0
    # Breakdown
    assert body["breakdown"]["gpu_rental"] == pytest.approx(1.80 / 3600 / 135, rel=1e-9)
    assert body["breakdown"]["power"] is None
    # assumptions record tokens_per_second_source = "profile" (direct hit)
    assert body["assumptions"]["tokens_per_second_source"] == "profile"


def test_calculate_local_with_power_only(client):
    """No rental, just electricity -> power component present, no rental."""
    r = client.post("/calculate/local", json={
        "model_id": "test-8b",
        "gpu_id": "test-rtx-4090",
        "power_cost_per_kwh": 0.15,
        "task_size": "tiny",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    expected_per_hour = (450.0 / 1000.0) * 0.15
    assert body["cost_per_hour_usd"] == pytest.approx(expected_per_hour, rel=1e-9)
    assert body["breakdown"]["gpu_rental"] is None
    assert body["breakdown"]["power"] is not None
    assert body["breakdown"]["power"] > 0


def test_calculate_local_with_tokens_per_second_override(client):
    """Override beats the profile lookup."""
    r = client.post("/calculate/local", json={
        "model_id": "test-8b",
        "gpu_id": "test-rtx-4090",
        "tokens_per_second": 250.0,  # override — RTX 4090 is actually 135 in profile
        "gpu_cost_per_hour": 1.80,
        "input_tokens": 1000,
        "output_tokens": 500,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["tokens_per_second"] == 250.0
    assert body["assumptions"]["tokens_per_second_source"] == "override"
    # Per-token: 1.80/3600/250 = 2e-6
    assert body["cost_per_token_usd"] == pytest.approx(1.80 / 3600 / 250.0, rel=1e-9)


def test_calculate_local_fallback_tps(client):
    """Model has no per-gpu entry for this GPU -> falls back to model default."""
    r = client.post("/calculate/local", json={
        "model_id": "test-70b",   # only has test-h100 in profile
        "gpu_id": "test-rtx-4090",  # not in test-70b's tps dict
        "gpu_cost_per_hour": 1.0,
        "input_tokens": 100,
        "output_tokens": 50,
    })
    assert r.status_code == 200
    body = r.json()
    # test-70b's default_tokens_per_second = 25.0
    assert body["tokens_per_second"] == 25.0
    assert body["assumptions"]["tokens_per_second_source"] == "fallback"


def test_calculate_local_accepts_display_name(client):
    """GPU id field accepts display name (case-insensitive)."""
    r = client.post("/calculate/local", json={
        "model_id": "test-8b",
        "gpu_id": "Test H100",   # display name, not canonical id
        "gpu_cost_per_hour": 3.0,
        "input_tokens": 1,
        "output_tokens": 0,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["gpu_id"] == "test-h100"  # canonical id returned
    assert body["gpu_display_name"] == "Test H100"


def test_calculate_local_unknown_gpu_404(client):
    r = client.post("/calculate/local", json={
        "model_id": "test-8b",
        "gpu_id": "nvidia-totally-fake",
        "gpu_cost_per_hour": 1.0,
    })
    assert r.status_code == 404
    detail = r.json()["detail"]
    assert "nvidia-totally-fake" in detail
    assert "test-rtx-4090" in detail  # available list includes canonical ids


def test_calculate_local_unknown_model_404(client):
    r = client.post("/calculate/local", json={
        "model_id": "ollama/does-not-exist",
        "gpu_id": "test-rtx-4090",
        "gpu_cost_per_hour": 1.0,
    })
    assert r.status_code == 404
    assert "does-not-exist" in r.json()["detail"]


def test_calculate_local_validates_input(client):
    """Pydantic validation: utilization=0 -> 422; negative cost -> 422."""
    r = client.post("/calculate/local", json={
        "model_id": "test-8b",
        "gpu_id": "test-rtx-4090",
        "utilization": 0.0,
    })
    assert r.status_code == 422

    r = client.post("/calculate/local", json={
        "model_id": "test-8b",
        "gpu_id": "test-rtx-4090",
        "gpu_cost_per_hour": -1.0,
    })
    assert r.status_code == 422


def test_calculate_local_num_runs_multiplies_total(client):
    r = client.post("/calculate/local", json={
        "model_id": "test-8b",
        "gpu_id": "test-rtx-4090",
        "gpu_cost_per_hour": 1.0,
        "input_tokens": 1000,
        "output_tokens": 500,
        "num_runs": 10,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["num_runs"] == 10
    assert body["total_cost"] == pytest.approx(body["cost_per_run"] * 10, rel=1e-9)


def test_calculate_local_task_type_multiplier_applies(client):
    """agentic task type -> 1.4x multiplier on cost_per_run."""
    r = client.post("/calculate/local", json={
        "model_id": "test-8b",
        "gpu_id": "test-rtx-4090",
        "gpu_cost_per_hour": 1.0,
        "input_tokens": 1000,
        "output_tokens": 500,
        "task_type": "agentic",
    })
    body = r.json()
    raw = body["cost_per_token_usd"] * 1500
    assert body["cost_per_run"] == pytest.approx(raw * 1.4, rel=1e-9)
    assert body["assumptions"]["task_type_multiplier"] == 1.4


def test_calculate_local_returns_503_when_profiles_missing(tmp_path):
    """If data/local_*.json are missing, the endpoint must 503 (not 500)."""
    pricing = tmp_path / "pricing.json"
    pricing.write_text(json.dumps({"_meta": {}, "models": {}}))
    app = create_app(
        pricing_path=str(pricing),
        gpu_profiles_path=str(tmp_path / "no-gpus.json"),
        model_profiles_path=str(tmp_path / "no-models.json"),
    )
    c = TestClient(app)
    r = c.post("/calculate/local", json={
        "model_id": "x", "gpu_id": "y", "gpu_cost_per_hour": 1.0,
    })
    assert r.status_code == 503
    assert "Local-cost profiles are not loaded" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Integration: data/ files actually load and produce sane numbers
# ---------------------------------------------------------------------------

def test_bundled_data_files_load_and_compute():
    """The committed data/ files must be parseable + produce nonzero cost."""
    from pathlib import Path
    base = Path(__file__).resolve().parent.parent / "data"
    gpus = load_gpu_profiles(base / "local_gpu_profiles.json")
    models = load_model_profiles(base / "local_model_profiles.json")
    assert len(gpus) >= 8, f"Expected >=8 GPUs, got {len(gpus)}"
    assert len(models) >= 8, f"Expected >=8 models, got {len(models)}"

    # Canonical example from findings.md: 70B on H100, $3/hr
    h100 = gpus.get("nvidia-h100-80gb")
    assert h100 is not None
    m70b = models.get("llama3.3:70b")
    assert m70b is not None
    tps = resolve_tokens_per_second(m70b, h100.gpu_id, gpu_profiles=gpus)
    b = local_cost_per_token(
        tokens_per_second=tps, tdp_watts=h100.tdp_watts,
        gpu_cost_per_hour=3.0, power_cost_per_kwh=0.0,
    )
    assert b.cost_per_token_usd > 0
    assert b.cost_per_million_tokens_usd > 0
    # No all-zero cost: a $3/hr GPU at ~110 tok/s must be in single-digit $/M
    assert 0.5 < b.cost_per_million_tokens_usd < 100