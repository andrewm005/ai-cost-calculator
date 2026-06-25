"""OpenRouter live sync — fetcher, normalizer, cache writer.

Pulls OpenRouter's public `/api/v1/models` endpoint, normalizes each entry
into our ``ModelPricing`` schema, and writes the result to a local JSON cache
so the backend can boot offline. Fetcher failures must NOT crash the app —
caller decides whether to keep the stale cache or return 503.

Namespacing: all incoming model ids are prefixed with ``openrouter/`` UNLESS
they already start with ``openrouter/``. This prevents collisions with the
hand-curated vendor models in ``worker/config/pricing.json`` (e.g. a live
``anthropic/claude-3.5-sonnet`` becomes ``openrouter/anthropic/claude-3.5-sonnet``).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from .pricing import ModelPricing


log = logging.getLogger(__name__)


#: OpenRouter public models endpoint. Read-only, no auth needed.
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

#: Default request timeout (seconds) for the fetch call.
DEFAULT_TIMEOUT = 30.0


# ---------- helpers ----------

def _safe_float(value: Any, default: float = 0.0) -> float:
    """Parse a value to float, returning default on failure.

    OpenRouter prices are strings like "0.000003" or "0". This handles both.
    """
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _namespaced_model_id(raw_id: str) -> str:
    """Prefix an OpenRouter model id with 'openrouter/' unless already prefixed."""
    if raw_id.startswith("openrouter/"):
        return raw_id
    return f"openrouter/{raw_id}"


def _derive_provider(namespaced_id: str) -> str:
    """Provider is the vendor segment of the namespaced id.

    Spec rule: ``provider = vendor`` — for ``openrouter/anthropic/claude-3.5-sonnet``
    that's 'anthropic' (skip the openrouter/ namespace, take the next segment).
    For ``openrouter/free`` (already prefixed, no vendor) that's 'openrouter' itself.
    For ids without the ``openrouter/`` namespace prefix, take the first segment.
    """
    if namespaced_id.startswith("openrouter/"):
        rest = namespaced_id[len("openrouter/"):]
        if "/" in rest:
            return rest.split("/", 1)[0]
        # Already-prefixed OpenRouter-native model (e.g. openrouter/free)
        return "openrouter"
    # No namespace — first segment is the vendor
    parts = namespaced_id.split("/", 1)
    return parts[0] if parts else "unknown"


def _pick_display_name(raw: dict, namespaced_id: str) -> str:
    """Prefer top-level 'name'; fall back to canonical_slug; fall back to id."""
    name = raw.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    slug = raw.get("canonical_slug")
    if isinstance(slug, str) and slug.strip():
        return slug.strip()
    return namespaced_id


def _supports_reasoning(raw: dict) -> bool:
    """Detect reasoning-capable models via the structured 'reasoning' field first,
    then via 'thinking'/'reasoning' keywords in id or name."""
    # Strongest signal: structured reasoning field with non-empty supported_efforts
    reasoning = raw.get("reasoning") or {}
    if isinstance(reasoning, dict):
        efforts = reasoning.get("supported_efforts") or []
        if isinstance(efforts, list) and len(efforts) > 0:
            return True
        if reasoning.get("mandatory") is True:
            return True
    # Fallback: keyword scan in id / name
    haystack = f"{raw.get('id', '')} {raw.get('name', '')}".lower()
    return "thinking" in haystack or "reasoning" in haystack


# ---------- normalize() ----------

def normalize(raw: dict) -> ModelPricing | None:
    """Convert one OpenRouter API model entry to our ``ModelPricing``.

    Returns ``None`` if the entry lacks required fields (skip rather than crash).

    Schema mapping (locked decisions from the task spec + live API probes):

    - ``id``                       -> ``model_id`` (with ``openrouter/`` prefix unless already prefixed)
    - ``pricing.prompt``           -> ``input_per_1m = float * 1_000_000`` (string $/token)
    - ``pricing.completion``       -> ``output_per_1m = float * 1_000_000``
    - ``pricing.request``          -> ``tool_call_cost = float`` if non-zero (rare in live data)
    - ``pricing.image``            -> ``image_input_cost_per_image = float`` (already $/image, no 1M conv)
    - ``pricing.input_cache_read`` -> ``cached_input_per_1m = float * 1_000_000`` (when present)
    - ``context_length``           -> ``context_window``
    - ``name`` (top-level)         -> ``display_name`` (fallback: canonical_slug, then id)
    - id prefix before first "/"   -> ``provider``
    - structured ``reasoning`` or  -> ``supports_reasoning = True``
      'thinking'/'reasoning' kw in id/name

    Free models (prompt == '0' AND completion == '0'): input/output = 0.0,
    notes get "(free via OpenRouter)" appended.
    """
    raw_id = raw.get("id")
    pricing = raw.get("pricing") or {}
    if not isinstance(raw_id, str) or not raw_id:
        return None
    if not isinstance(pricing, dict):
        return None
    if "prompt" not in pricing or "completion" not in pricing:
        return None

    namespaced_id = _namespaced_model_id(raw_id)
    prompt_per_token = _safe_float(pricing.get("prompt"))
    completion_per_token = _safe_float(pricing.get("completion"))
    # Negative pricing is OpenRouter's sentinel for "dynamic" (e.g. openrouter/auto
    # picks a model at request time — no fixed price). We can't compute cost from
    # a sentinel, so skip these models rather than poison the cache with garbage.
    if prompt_per_token < 0 or completion_per_token < 0:
        return None
    is_free = (pricing.get("prompt") == "0" and pricing.get("completion") == "0")

    input_per_1m = prompt_per_token * 1_000_000
    output_per_1m = completion_per_token * 1_000_000

    # Cached input: prefer input_cache_read, fall back to input_cache_write,
    # otherwise 0.0 (most OpenRouter models don't expose a cached rate).
    cache_rate = pricing.get("input_cache_read") or pricing.get("input_cache_write")
    cached_input_per_1m = _safe_float(cache_rate) * 1_000_000 if cache_rate else 0.0

    # Tool call cost: only set if pricing.request is non-zero (live data has 0/340).
    request_val = pricing.get("request")
    tool_call_cost = _safe_float(request_val) if request_val and _safe_float(request_val) > 0 else 0.0

    # Image input cost: pricing.image is $/image, not $/token — no 1M conversion.
    image_val = pricing.get("image")
    image_input_cost_per_image = _safe_float(image_val) if image_val else 0.0

    notes_parts: list[str] = ["OpenRouter live sync"]
    if is_free:
        notes_parts.append("(free via OpenRouter)")

    return ModelPricing(
        model_id=namespaced_id,
        provider=_derive_provider(namespaced_id),
        display_name=_pick_display_name(raw, namespaced_id),
        input_per_1m=input_per_1m,
        output_per_1m=output_per_1m,
        cached_input_per_1m=cached_input_per_1m,
        context_window=int(raw.get("context_length") or 0),
        supports_reasoning=_supports_reasoning(raw),
        reasoning_per_1m=None,  # OpenRouter doesn't expose a separate reasoning rate
        tool_call_cost=tool_call_cost,
        image_input_cost_per_image=image_input_cost_per_image,
        notes="; ".join(notes_parts),
    )


# ---------- fetch_models() ----------

def fetch_models(client: httpx.Client | None = None) -> list[ModelPricing]:
    """Hit OpenRouter's ``/api/v1/models`` and return a list of ``ModelPricing``.

    Caller may pass an ``httpx.Client`` (used by tests with ``MockTransport``,
    or by the scheduler for connection pooling). If omitted, a fresh client is
    created and closed for this call.

    Raises ``httpx.HTTPError`` on network/HTTP failure — caller decides how
    to handle (log + keep stale cache, or return 503 from the admin endpoint).
    """
    owns_client = client is None
    if owns_client:
        client = httpx.Client(timeout=DEFAULT_TIMEOUT)
    try:
        response = client.get(OPENROUTER_MODELS_URL)
        response.raise_for_status()
        payload = response.json()
    finally:
        if owns_client:
            client.close()

    raw_models = payload.get("data") or []
    out: list[ModelPricing] = []
    for raw in raw_models:
        if not isinstance(raw, dict):
            continue
        m = normalize(raw)
        if m is not None:
            out.append(m)
    return out


# ---------- refresh_to_disk() ----------

def refresh_to_disk(cache_path: Path, client: httpx.Client | None = None) -> int:
    """Fetch live models and write them to the cache file as JSON.

    Format matches the hand-curated ``worker/config/pricing.json`` schema so the
    loader can read both files identically:

    .. code-block:: json

        {
          "_meta": {
            "source": "https://openrouter.ai/api/v1/models",
            "last_synced_at": "2026-06-22T13:54:30Z",
            "count": 340
          },
          "models": { "<model_id>": { ...ModelPricing fields... } }
        }

    Returns the count of models written. Raises ``httpx.HTTPError`` on
    network failure (caller keeps stale cache).
    """
    models = fetch_models(client=client)
    by_id: dict[str, dict[str, Any]] = {}
    for m in models:
        by_id[m.model_id] = {
            "provider": m.provider,
            "display_name": m.display_name,
            "input_per_1m": m.input_per_1m,
            "output_per_1m": m.output_per_1m,
            "cached_input_per_1m": m.cached_input_per_1m,
            "context_window": m.context_window,
            "supports_reasoning": m.supports_reasoning,
            "reasoning_per_1m": m.reasoning_per_1m,
            "tool_call_cost": m.tool_call_cost,
            "image_input_cost_per_image": m.image_input_cost_per_image,
            "notes": m.notes,
        }
    payload = {
        "_meta": {
            "source": OPENROUTER_MODELS_URL,
            "last_synced_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "count": len(by_id),
        },
        "models": by_id,
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return len(by_id)


# ---------- load_cache() ----------

def load_cache(cache_path: Path) -> dict[str, ModelPricing]:
    """Read the cache file and return ``{model_id: ModelPricing}``.

    Returns ``{}`` if the file is missing or malformed (logged at WARNING).
    The caller is expected to merge with the hand-curated pricing — the
    loader's merge handles dedup.
    """
    if not cache_path.exists():
        return {}
    try:
        payload = json.loads(cache_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        log.warning("OpenRouter cache at %s is unreadable: %s", cache_path, e)
        return {}
    if not isinstance(payload, dict):
        log.warning("OpenRouter cache at %s has unexpected top-level type", cache_path)
        return {}
    models_raw = payload.get("models") or {}
    if not isinstance(models_raw, dict):
        return {}

    out: dict[str, ModelPricing] = {}
    for model_id, m in models_raw.items():
        if not isinstance(m, dict):
            continue
        try:
            out[model_id] = ModelPricing(
                model_id=model_id,
                provider=str(m.get("provider", "unknown")),
                display_name=str(m.get("display_name", model_id)),
                input_per_1m=float(m.get("input_per_1m", 0.0)),
                output_per_1m=float(m.get("output_per_1m", 0.0)),
                cached_input_per_1m=float(m.get("cached_input_per_1m", 0.0)),
                context_window=int(m.get("context_window", 0)),
                supports_reasoning=bool(m.get("supports_reasoning", False)),
                reasoning_per_1m=(float(m["reasoning_per_1m"])
                                  if m.get("reasoning_per_1m") is not None else None),
                tool_call_cost=float(m.get("tool_call_cost", 0.0)),
                image_input_cost_per_image=float(m.get("image_input_cost_per_image", 0.0)),
                notes=str(m.get("notes", "")),
            )
        except (KeyError, TypeError, ValueError) as e:
            log.warning("Skipping malformed OpenRouter cache entry %s: %s", model_id, e)
            continue
    return out