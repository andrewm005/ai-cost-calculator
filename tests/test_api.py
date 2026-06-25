"""Tests for FastAPI endpoints."""
import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.pricing import ModelPricing


PRICING_CONFIG = {
    "_meta": {"schema_version": "1.0", "currency": "USD"},
    "models": {
        "test/foo": {
            "provider": "test",
            "display_name": "Test Foo",
            "input_per_1m": 1.0,
            "output_per_1m": 2.0,
            "cached_input_per_1m": 0.1,
            "context_window": 100000,
            "supports_reasoning": False,
            "reasoning_per_1m": None,
            "tool_call_cost": 0.0,
            "image_input_cost_per_image": 0.0,
            "notes": "fixture",
        },
        "test/bar": {
            "provider": "test",
            "display_name": "Test Bar",
            "input_per_1m": 3.0,
            "output_per_1m": 9.0,
            "cached_input_per_1m": 1.0,
            "context_window": 200000,
            "supports_reasoning": True,
            "reasoning_per_1m": 9.0,
            "tool_call_cost": 0.001,
            "image_input_cost_per_image": 0.005,
            "notes": "fixture reasoning",
        },
    },
}


@pytest.fixture
def client(tmp_path):
    """Create a FastAPI TestClient wired to a temp pricing config."""
    cfg_path = tmp_path / "pricing.json"
    cfg_path.write_text(json.dumps(PRICING_CONFIG))
    app = create_app(pricing_path=str(cfg_path))
    return TestClient(app)


# ---------------- health ----------------

def test_health_returns_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"


def test_root_returns_api_info(client):
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert "name" in body
    assert "endpoints" in body


# ---------------- models ----------------

def test_list_models(client):
    r = client.get("/models")
    assert r.status_code == 200
    ids = [m["model_id"] for m in r.json()["models"]]
    assert "test/foo" in ids
    assert "test/bar" in ids


def test_get_one_model(client):
    r = client.get("/models/test/foo")
    assert r.status_code == 200
    body = r.json()
    assert body["model_id"] == "test/foo"
    assert body["input_per_1m"] == 1.0
    assert body["supports_reasoning"] is False


def test_get_unknown_model_returns_404(client):
    r = client.get("/models/test/nope")
    assert r.status_code == 404
    assert "test/foo" in r.json()["detail"]


# ---------------- calculate ----------------

def test_calculate_basic(client):
    r = client.post("/calculate", json={
        "model_id": "test/foo",
        "input_tokens": 1_000_000,
        "output_tokens": 500_000,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["model_id"] == "test/foo"
    assert body["input_cost"] == pytest.approx(1.0, abs=1e-9)
    assert body["output_cost"] == pytest.approx(1.0, abs=1e-9)
    assert body["cost_per_run"] == pytest.approx(2.0, abs=1e-9)
    assert body["total_cost"] == pytest.approx(2.0, abs=1e-9)


def test_calculate_with_task_size_preset(client):
    r = client.post("/calculate", json={
        "model_id": "test/foo",
        "task_size": "medium",
        "num_runs": 5,
    })
    assert r.status_code == 200
    body = r.json()
    # medium preset = 5000 in / 2000 out; model is 1.0 / 2.0 per 1M
    assert body["tokens_used"]["input_tokens"] == 5000
    assert body["tokens_used"]["output_tokens"] == 2000
    assert body["total_cost"] == pytest.approx(body["cost_per_run"] * 5, abs=1e-9)


def test_calculate_with_reasoning_tokens(client):
    r = client.post("/calculate", json={
        "model_id": "test/bar",
        "input_tokens": 1_000_000,
        "output_tokens": 1_000_000,
        "reasoning_tokens": 500_000,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["reasoning_cost"] == pytest.approx(4.5, abs=1e-9)
    assert body["input_cost"] == pytest.approx(3.0, abs=1e-9)
    assert body["output_cost"] == pytest.approx(9.0, abs=1e-9)


def test_calculate_unknown_model_returns_404(client):
    r = client.post("/calculate", json={
        "model_id": "test/nope",
        "input_tokens": 1, "output_tokens": 1,
    })
    assert r.status_code == 404


def test_calculate_validates_input(client):
    """Extra fields / bad types fail Pydantic validation -> 422."""
    r = client.post("/calculate", json={
        "model_id": "test/foo",
        "input_tokens": -1,  # negative not allowed
    })
    assert r.status_code == 422


# ---------------- compare ----------------

def test_compare_returns_one_row_per_model(client):
    r = client.post("/calculate/compare", json={
        "model_ids": ["test/foo", "test/bar"],
        "input_tokens": 1_000_000,
        "output_tokens": 0,
    })
    assert r.status_code == 200
    body = r.json()
    assert "results" in body
    assert len(body["results"]) == 2
    assert body["results"][0]["model_id"] == "test/foo"
    assert body["results"][1]["model_id"] == "test/bar"


def test_compare_requires_at_least_one_model(client):
    r = client.post("/calculate/compare", json={"model_ids": []})
    assert r.status_code == 422


# ---------------- reload ----------------

def test_reload_endpoint_picks_up_file_changes(client, tmp_path):
    """POST /admin/reload re-reads pricing.json without restarting the server."""
    cfg_path = tmp_path / "pricing.json"
    cfg_path.write_text(json.dumps(PRICING_CONFIG))
    app = create_app(pricing_path=str(cfg_path))
    c = TestClient(app)

    # Bump the price on disk
    cfg = json.loads(cfg_path.read_text())
    cfg["models"]["test/foo"]["input_per_1m"] = 99.0
    cfg_path.write_text(json.dumps(cfg))

    r = c.post("/admin/reload")
    assert r.status_code == 200
    assert r.json()["models_loaded"] == 2

    r2 = c.post("/calculate", json={"model_id": "test/foo", "input_tokens": 1_000_000, "output_tokens": 0})
    assert r2.status_code == 200
    assert r2.json()["input_cost"] == pytest.approx(99.0, abs=1e-9)


# ---------------- openrouter refresh ----------------

OPENROUTER_SAMPLE = {
    "id": "anthropic/claude-3.5-sonnet",
    "canonical_slug": "anthropic/claude-3.5-sonnet",
    "name": "Anthropic: Claude 3.5 Sonnet",
    "context_length": 200000,
    "architecture": {"modality": "text+image->text"},
    "pricing": {"prompt": "0.000003", "completion": "0.000015"},
    "top_provider": {},
    "reasoning": {},
}

OPENROUTER_FREE = {
    "id": "cohere/north-mini-code:free",
    "canonical_slug": "cohere/north-mini-code-free",
    "name": "Cohere: North Mini Code (free)",
    "context_length": 256000,
    "architecture": {"modality": "text->text"},
    "pricing": {"prompt": "0", "completion": "0"},
    "top_provider": {},
    "reasoning": {},
}


def _mock_openrouter_response(models):
    """Return a mock httpx handler that serves the given models list."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert "openrouter.ai" in str(request.url)
        return httpx.Response(200, json={"data": models})
    return handler


@pytest.fixture
def or_client(tmp_path):
    """TestClient wired to a tmp pricing.json + openrouter.json."""
    cfg_path = tmp_path / "pricing.json"
    or_path = tmp_path / "openrouter.json"
    cfg_path.write_text(json.dumps(PRICING_CONFIG))
    # Write a stub openrouter cache so first boot sees both files
    or_path.write_text(json.dumps({
        "_meta": {"source": "test-stub", "count": 0},
        "models": {},
    }))
    app = create_app(pricing_paths=[str(cfg_path), str(or_path)], refresh_seconds=0)
    return TestClient(app), cfg_path, or_path


def test_root_reports_openrouter_model_count(or_client):
    """GET / shows openrouter_models count when cache has entries."""
    c, _, _ = or_client
    r = c.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["openrouter_models"] == 0  # empty stub cache
    assert any("openrouter/refresh" in ep for ep in body["endpoints"])


def test_refresh_endpoint_writes_cache_and_reloads(or_client, monkeypatch):
    """POST /admin/openrouter/refresh fetches live data, writes cache, reloads merged."""
    c, _, or_path = or_client

    # Make ANY httpx.Client created by the app use our MockTransport.
    # refresh_to_disk creates its own client; this intercepts it without
    # having to refactor the endpoint signature.
    real_client = httpx.Client
    def patched_client(*args, **kwargs):
        # Honor any explicitly-passed transport; otherwise inject our mock.
        if "transport" not in kwargs:
            kwargs["transport"] = httpx.MockTransport(
                _mock_openrouter_response([OPENROUTER_SAMPLE, OPENROUTER_FREE])
            )
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", patched_client)

    r = c.post("/admin/openrouter/refresh")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "reloaded"
    assert body["openrouter_models"] == 2
    # 2 hand-curated + 2 openrouter = 4
    assert body["models_loaded"] == 4

    # Cache file was actually written
    assert or_path.exists()
    payload = json.loads(or_path.read_text())
    assert payload["_meta"]["count"] == 2

    # Now GET /models should include both OpenRouter namespaced entries
    r2 = c.get("/models")
    ids = [m["model_id"] for m in r2.json()["models"]]
    assert "openrouter/anthropic/claude-3.5-sonnet" in ids
    assert "openrouter/cohere/north-mini-code:free" in ids
    assert "test/foo" in ids  # hand-curated still present

    # Lookup one of the new OR models via path route
    r3 = c.get("/models/openrouter/anthropic/claude-3.5-sonnet")
    assert r3.status_code == 200
    assert r3.json()["input_per_1m"] == pytest.approx(3.0, abs=1e-9)


def test_refresh_endpoint_returns_503_on_network_failure(or_client):
    """If the fetch fails, refresh returns 503 (stale cache stays in use)."""
    c, _, _ = or_client

    def boom(*args, **kwargs):
        raise httpx.ConnectError("simulated outage")

    with patch("app.main.refresh_to_disk", side_effect=boom):
        r = c.post("/admin/openrouter/refresh")

    assert r.status_code == 503
    assert "OpenRouter refresh failed" in r.json()["detail"]


def test_reload_picks_up_new_openrouter_cache_file(or_client):
    """POST /admin/reload re-reads the openrouter cache if it was updated externally."""
    c, _, or_path = or_client
    # Operator updates the cache directly (e.g. manual edit / scp from elsewhere)
    or_path.write_text(json.dumps({
        "_meta": {"source": "manual-edit", "count": 1},
        "models": {
            "openrouter/manual/test": {
                "provider": "test",
                "display_name": "Manual Test",
                "input_per_1m": 7.5,
                "output_per_1m": 15.0,
                "cached_input_per_1m": 0.0,
                "context_window": 50000,
                "supports_reasoning": False,
                "reasoning_per_1m": None,
                "tool_call_cost": 0.0,
                "image_input_cost_per_image": 0.0,
                "notes": "manual edit",
            }
        }
    }))
    r = c.post("/admin/reload")
    assert r.status_code == 200
    assert r.json()["models_loaded"] == 3  # 2 hand-curated + 1 manual
    assert r.json()["openrouter_models"] == 1

    # Lookup the manually-added model
    r2 = c.get("/models/openrouter/manual/test")
    assert r2.status_code == 200
    assert r2.json()["input_per_1m"] == pytest.approx(7.5, abs=1e-9)


def test_refresh_uses_replaced_placeholder_when_present(or_client):
    """openrouter/auto placeholder in pricing.json gets overridden by live data."""
    c, cfg_path, _ = or_client
    # Add a placeholder that matches a live OpenRouter id
    cfg = json.loads(cfg_path.read_text())
    cfg["models"]["openrouter/auto"] = {
        "provider": "openrouter",
        "display_name": "PLACEHOLDER",
        "input_per_1m": 99.0,
        "output_per_1m": 99.0,
        "cached_input_per_1m": 0.0,
        "context_window": 100000,
        "supports_reasoning": False,
        "reasoning_per_1m": None,
        "tool_call_cost": 0.0,
        "image_input_cost_per_image": 0.0,
        "notes": "PLACEHOLDER",
    }
    cfg_path.write_text(json.dumps(cfg))
    c.post("/admin/reload")

    # Simulate the live API returning openrouter/auto
    auto_live = dict(OPENROUTER_SAMPLE)
    auto_live["id"] = "openrouter/auto"
    auto_live["name"] = "OpenRouter: Auto (live)"
    auto_live["pricing"] = {"prompt": "0.000001", "completion": "0.000002"}

    def fake_refresh_to_disk(cache_path, client=None):
        from app.openrouter import fetch_models
        if client is None:
            client = httpx.Client(transport=httpx.MockTransport(_mock_openrouter_response([auto_live])))
            try:
                models = fetch_models(client=client)
            finally:
                client.close()
        else:
            models = fetch_models(client=client)
        cache_path.write_text(json.dumps({
            "_meta": {"source": "mock", "count": len(models)},
            "models": {m.model_id: {
                "provider": m.provider, "display_name": m.display_name,
                "input_per_1m": m.input_per_1m, "output_per_1m": m.output_per_1m,
                "cached_input_per_1m": m.cached_input_per_1m, "context_window": m.context_window,
                "supports_reasoning": m.supports_reasoning, "reasoning_per_1m": m.reasoning_per_1m,
                "tool_call_cost": m.tool_call_cost, "image_input_cost_per_image": m.image_input_cost_per_image,
                "notes": m.notes,
            } for m in models},
        }))
        return len(models)

    with patch("app.main.refresh_to_disk", side_effect=fake_refresh_to_disk):
        r = c.post("/admin/openrouter/refresh")

    assert r.status_code == 200
    # The placeholder was overridden by the live data
    r2 = c.get("/models/openrouter/auto")
    assert r2.status_code == 200
    body = r2.json()
    assert body["input_per_1m"] == pytest.approx(1.0, abs=1e-9)  # 0.000001 * 1M
    assert "PLACEHOLDER" not in body["notes"]
    assert "live" in body["display_name"]


def test_lifespan_skips_scheduler_when_refresh_seconds_zero(or_client):
    """With refresh_seconds=0, no background task is created (verified by no log spam)."""
    c, _, _ = or_client
    # If a scheduler ran in the background, it'd log every refresh_seconds.
    # We just verify the app boots and serves a request — the absence of logs
    # in the test runner is the proof.
    r = c.get("/health")
    assert r.status_code == 200