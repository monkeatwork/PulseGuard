"""L3 feature engine service health stub.

The Faust streaming app (streaming_app.py) and feature computation modules
are built in Phase 3. This FastAPI app exists in Phase 0 purely so the
feature-engine container has a health endpoint for the compose smoke test.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="pulseguard-feature-engine")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "feature_engine"}
