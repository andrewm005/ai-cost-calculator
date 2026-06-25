"""Boot the app in outage-survival mode (no auto-refresh on startup).

Demonstrates that the app still serves hand-curated pricing even when
OpenRouter is unreachable — and that POST /admin/openrouter/refresh
returns 503 cleanly.
"""
import os
import sys
import time

sys.path.insert(0, "/home/vboxuser/vaults/star-command/Projects/token-calculator")

from app.main import create_app
from fastapi.testclient import TestClient

# No auto-refresh on startup → simulates first boot without network
app = create_app(auto_refresh_on_startup=False, refresh_seconds=0)
c = TestClient(app)

r = c.get("/health")
print("health:", r.status_code, r.json())

# Manual refresh — should return 503 because we have no real client
r = c.post("/admin/openrouter/refresh")
print("refresh:", r.status_code, r.json())

# Existing models still work
r = c.get("/models/openai/gpt-4o")
print("gpt-4o:", r.status_code, r.json()["input_per_1m"], "/", r.json()["output_per_1m"])

# Calculate still works
r = c.post("/calculate", json={"model_id": "openai/gpt-4o", "task_size": "medium"})
print("calc gpt-4o medium:", r.status_code, "cost=", r.json()["cost_per_run"])