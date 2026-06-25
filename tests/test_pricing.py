"""Tests for pricing loader (config/pricing.json + multi-file merge)."""
import json
from pathlib import Path
import pytest
from app.pricing import PricingLoader, ModelPricing, load_pricing_files


@pytest.fixture
def pricing_path(tmp_path):
    """Write a minimal pricing config to tmp and return its path."""
    config = {
        "_meta": {"schema_version": "1.0", "currency": "USD"},
        "models": {
            "test/foo": {
                "provider": "test",
                "display_name": "Test Foo",
                "input_per_1m": 1.0,
                "output_per_1m": 2.0,
                "cached_input_per_1m": 0.5,
                "context_window": 100000,
                "supports_reasoning": False,
                "reasoning_per_1m": None,
                "tool_call_cost": 0.0,
                "image_input_cost_per_image": 0.001,
                "notes": "fixture",
            },
            "test/bar": {
                "provider": "test",
                "display_name": "Test Bar (reasoning)",
                "input_per_1m": 3.0,
                "output_per_1m": 9.0,
                "cached_input_per_1m": 1.5,
                "context_window": 200000,
                "supports_reasoning": True,
                "reasoning_per_1m": 9.0,
                "tool_call_cost": 0.0,
                "image_input_cost_per_image": 0.0,
                "notes": "fixture",
            },
        },
    }
    p = tmp_path / "pricing.json"
    p.write_text(__import__("json").dumps(config))
    return p


def test_loader_returns_models_from_config(pricing_path):
    """Loader reads JSON and exposes all models."""
    loader = PricingLoader(str(pricing_path))
    assert loader.list_model_ids() == ["test/foo", "test/bar"]


def test_loader_get_model_returns_pricing_dataclass(pricing_path):
    """get_model returns a ModelPricing with parsed numeric fields."""
    loader = PricingLoader(str(pricing_path))
    m = loader.get_model("test/foo")
    assert isinstance(m, ModelPricing)
    assert m.model_id == "test/foo"
    assert m.provider == "test"
    assert m.display_name == "Test Foo"
    assert m.input_per_1m == 1.0
    assert m.output_per_1m == 2.0
    assert m.cached_input_per_1m == 0.5
    assert m.context_window == 100000
    assert m.supports_reasoning is False
    assert m.reasoning_per_1m is None
    assert m.image_input_cost_per_image == 0.001


def test_loader_get_unknown_model_raises_keyerror(pricing_path):
    """Asking for a missing model raises KeyError with available ids in the message."""
    loader = PricingLoader(str(pricing_path))
    with pytest.raises(KeyError) as exc:
        loader.get_model("test/does-not-exist")
    assert "test/foo" in str(exc.value)
    assert "test/bar" in str(exc.value)


def test_loader_reload_picks_up_file_changes(pricing_path):
    """Reload re-reads the file so operators can edit pricing without restarting."""
    loader = PricingLoader(str(pricing_path))
    assert loader.get_model("test/foo").input_per_1m == 1.0

    # Operator edits the file directly
    import json
    cfg = json.loads(pricing_path.read_text())
    cfg["models"]["test/foo"]["input_per_1m"] = 99.0
    pricing_path.write_text(json.dumps(cfg))

    loader.reload()
    assert loader.get_model("test/foo").input_per_1m == 99.0


def test_loader_handles_missing_file(tmp_path):
    """Loader raises a clear error if the file is missing."""
    with pytest.raises(FileNotFoundError):
        PricingLoader(str(tmp_path / "nope.json"))


# ---------------- multi-file merge ----------------

def _write_pricing_file(path, models: dict) -> Path:
    """Write a minimal pricing JSON to ``path`` and return it."""
    payload = {"_meta": {"schema_version": "1.0", "currency": "USD"}, "models": models}
    path.write_text(json.dumps(payload))
    return path


def _model_dict(model_id: str, **overrides) -> dict:
    """Build a minimal valid pricing entry."""
    base = {
        "provider": "test",
        "display_name": model_id,
        "input_per_1m": 1.0,
        "output_per_1m": 2.0,
        "cached_input_per_1m": 0.0,
        "context_window": 100000,
        "supports_reasoning": False,
        "reasoning_per_1m": None,
        "tool_call_cost": 0.0,
        "image_input_cost_per_image": 0.0,
        "notes": "",
    }
    base.update(overrides)
    return base


def test_load_pricing_files_merges_multiple_files(tmp_path):
    """Two files with disjoint model ids → both sets present in merged result."""
    f1 = _write_pricing_file(tmp_path / "a.json", {
        "test/a1": _model_dict("Test A1", input_per_1m=1.0),
        "test/a2": _model_dict("Test A2", input_per_1m=2.0),
    })
    f2 = _write_pricing_file(tmp_path / "b.json", {
        "test/b1": _model_dict("Test B1", input_per_1m=10.0),
    })
    merged = load_pricing_files(f1, f2)
    assert set(merged.keys()) == {"test/a1", "test/a2", "test/b1"}
    assert merged["test/b1"].input_per_1m == 10.0


def test_load_pricing_files_later_overrides_earlier(tmp_path):
    """Same model_id in both files → later file wins (used for OR cache replacing placeholder)."""
    f1 = _write_pricing_file(tmp_path / "hand.json", {
        "openrouter/auto": _model_dict("OpenRouter Auto (placeholder)", input_per_1m=99.0),
    })
    f2 = _write_pricing_file(tmp_path / "live.json", {
        "openrouter/auto": _model_dict("OpenRouter Auto (live)", input_per_1m=0.5),
    })
    merged = load_pricing_files(f1, f2)
    assert len(merged) == 1
    assert merged["openrouter/auto"].input_per_1m == 0.5
    assert "live" in merged["openrouter/auto"].display_name


def test_load_pricing_files_missing_raises_by_default(tmp_path):
    """A missing file raises FileNotFoundError unless missing_ok=True."""
    f1 = _write_pricing_file(tmp_path / "real.json", {"test/x": _model_dict("Test X")})
    with pytest.raises(FileNotFoundError):
        load_pricing_files(f1, tmp_path / "nope.json")


def test_load_pricing_files_missing_ok_skips_silently(tmp_path):
    """With missing_ok=True, missing files are silently skipped (for OR cache on first boot)."""
    f1 = _write_pricing_file(tmp_path / "real.json", {"test/x": _model_dict("Test X")})
    merged = load_pricing_files(f1, tmp_path / "nope.json", missing_ok=True)
    assert set(merged.keys()) == {"test/x"}


def test_load_pricing_files_all_missing_with_missing_ok(tmp_path):
    """All files missing + missing_ok=True → empty dict (not an error)."""
    merged = load_pricing_files(
        tmp_path / "a.json", tmp_path / "b.json", missing_ok=True,
    )
    assert merged == {}


def test_load_pricing_files_skips_invalid_entries(tmp_path):
    """Malformed entries (missing fields) are silently skipped; valid entries survive."""
    bad_payload = {
        "_meta": {},
        "models": {
            "good": _model_dict("Good"),
            "missing_input": {"provider": "test", "output_per_1m": 1.0},  # no input_per_1m
            "wrong_type": _model_dict("WrongType"),
        },
    }
    # Make 'wrong_type' actually have a non-numeric input_per_1m
    bad_payload["models"]["wrong_type"]["input_per_1m"] = "not-a-number"
    path = tmp_path / "mixed.json"
    path.write_text(json.dumps(bad_payload))
    merged = load_pricing_files(path)
    assert "good" in merged
    assert "missing_input" not in merged
    assert "wrong_type" not in merged