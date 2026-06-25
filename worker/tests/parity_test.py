"""
Calculator parity test — FastAPI on :8001 vs Hono on :8002.

Hits both endpoints with the same payload and asserts the responses match
to 6 decimal places. This is the canonical "are they the same backend"
check.
"""
import json
import sys
from urllib import request
from urllib.error import HTTPError

PY_URL = "http://localhost:8001"
TS_URL = "http://localhost:8002"

# (label, request_payload)
PAYLOADS = [
    ("basic", {"model_id": "openai/gpt-4o", "task_size": "medium", "num_runs": 1}),
    ("reasoning-high", {"model_id": "openai/gpt-4o", "task_size": "large", "reasoning_level": "high", "num_runs": 5}),
    ("reasoning-extreme", {"model_id": "openai/gpt-4o", "input_tokens": 10000, "output_tokens": 2000, "reasoning_level": "extreme", "num_runs": 10}),
    ("agentic-default", {"model_id": "openai/gpt-4o", "task_size": "medium", "agentic": True, "num_runs": 1}),
    ("agentic-with-overrides", {"model_id": "openai/gpt-4o", "task_size": "medium", "agentic": True, "tool_call_count": 10, "system_prompt_tokens": 500, "num_runs": 3}),
    ("task-type-coding", {"model_id": "openai/gpt-4o", "task_size": "small", "task_type": "coding", "num_runs": 1}),
    ("task-type-agentic-legacy", {"model_id": "openai/gpt-4o", "input_tokens": 5000, "output_tokens": 1000, "task_type": "agentic", "num_runs": 1}),
    ("cached-input", {"model_id": "openai/gpt-4o", "input_tokens": 100000, "cached_input_tokens": 80000, "output_tokens": 5000, "num_runs": 1}),
    ("tool-calls-only", {"model_id": "openai/gpt-4o", "tool_call_count": 8, "num_runs": 1}),
    ("image-input", {"model_id": "openai/gpt-4o", "image_input_count": 3, "num_runs": 1}),
]

def call(url: str, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url + "/calculate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        return {"_error": e.read().decode("utf-8"), "_status": e.code}

def numeric_fields() -> list[str]:
    return [
        "input_cost", "output_cost", "reasoning_cost", "tool_cost", "image_cost",
        "cost_per_run", "total_cost",
    ]

def main() -> int:
    fails = 0
    for label, payload in PAYLOADS:
        py_res = call(PY_URL, payload)
        ts_res = call(TS_URL, payload)

        if "_error" in py_res or "_error" in ts_res:
            print(f"  {label}: ERROR py={py_res.get('_error', '?')[:80]} ts={ts_res.get('_error', '?')[:80]}")
            fails += 1
            continue

        for field in numeric_fields():
            py_v = float(py_res.get(field, 0.0))
            ts_v = float(ts_res.get(field, 0.0))
            if abs(py_v - ts_v) > 1e-6:
                print(f"  {label}.{field}: DRIFT py={py_v!r} ts={ts_v!r} delta={abs(py_v - ts_v):.2e}")
                fails += 1

        # Token counts must be byte-identical
        py_tok = py_res.get("tokens_used", {})
        ts_tok = ts_res.get("tokens_used", {})
        for tk in ("input_tokens", "output_tokens", "reasoning_tokens", "cached_input_tokens"):
            if py_tok.get(tk) != ts_tok.get(tk):
                print(f"  {label}.tokens_used.{tk}: MISMATCH py={py_tok.get(tk)} ts={ts_tok.get(tk)}")
                fails += 1

        if fails == 0:
            print(f"  {label}: OK cost={ts_res['total_cost']:.6f} tokens={ts_tok}")

    if fails == 0:
        print(f"\nALL {len(PAYLOADS)} PAYLOADS PARITY OK (delta < 1e-6)")
        return 0
    else:
        print(f"\n{fails} DRIFT(S) DETECTED")
        return 1

if __name__ == "__main__":
    sys.exit(main())
