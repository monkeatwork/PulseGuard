"""L4 detection engine service: health check, the live scoring worker
(consumes enriched events, scores via real trained Stage A/B/C models,
writes real Alert rows), and the SOC dashboard's read API for alerts
(CLAUDE.md, L5: "SOC dashboard with explanations").

The live scoring worker (live_scorer.py) runs as a background thread
started in this app's lifespan -- this closes the "Known gap" flagged in
DECISIONS.md's Phase 3 entry (the Faust worker existing but not being the
live process); the corresponding gap on the feature_engine side is closed
by its own Dockerfile CMD running the Faust worker directly.
"""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from pulseguard_common.cef import format_cef
from pulseguard_common.db.models import Alert, Event
from pulseguard_common.db.session import get_db
from services.detection_engine.app.live_scorer import run_live_scorer_loop

_stop_event = threading.Event()


def _configure_logging() -> None:
    """Configures the ROOT logger so `live_scorer.py`'s module-level
    `getLogger(__name__)` actually emits. Two non-obvious details, both
    learned from this logging silently not working:

    1. This must run INSIDE the lifespan, not at module import. uvicorn
       configures logging via `logging.config.dictConfig`, and a
       non-incremental dictConfig clears existing root handlers -- so a
       `basicConfig()` call at import time is installed and then wiped
       before the app ever serves a request.
    2. `force=True` is required because by the time the lifespan runs,
       root may already have a handler, and plain `basicConfig()` is a
       silent no-op whenever root has any handler at all.

    This only touches the root logger; uvicorn's own `uvicorn.*` loggers
    carry their own handlers and are unaffected.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_logging()
    thread = threading.Thread(target=run_live_scorer_loop, args=(_stop_event,), daemon=True)
    thread.start()
    yield
    _stop_event.set()


app = FastAPI(title="pulseguard-detection-engine", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "detection_engine"}


def _alert_summary(alert: Alert) -> dict:
    return {
        "alert_id": str(alert.alert_id),
        "user_id": alert.user_id,
        "ts": alert.ts.isoformat(),
        "fused_score": alert.fused_score,
    }


@app.get("/alerts")
def list_alerts(limit: int = 50, db: Session = Depends(get_db)) -> list[dict]:
    limit = max(1, min(limit, 500))
    alerts = db.scalars(select(Alert).order_by(Alert.ts.desc()).limit(limit)).all()
    return [_alert_summary(a) for a in alerts]


@app.get("/alerts/{alert_id}")
def get_alert(alert_id: str, db: Session = Depends(get_db)) -> dict:
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="alert not found")

    sequence = []
    if alert.burst_id:
        # `Alert.burst_id` stores the production `session_id` that grouped
        # this alert's events (the canonical PulseGuardEvent schema has no
        # separate "burst_id" concept -- that's a benchmark-only artifact).
        events = db.scalars(
            select(Event).where(Event.session_id == alert.burst_id).order_by(Event.ts)
        ).all()
        sequence = [
            {"decision": e.decision, "decision_latency_ms": e.decision_latency_ms}
            for e in events
            if e.event_type == "mfa_decision"
        ]

    return {
        **_alert_summary(alert),
        "shap_top3": alert.shap_top3 or [],
        "sequence": sequence,
    }


@app.get("/alerts/{alert_id}/cef")
def export_alert_cef(alert_id: str, db: Session = Depends(get_db)) -> Response:
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="alert not found")

    severity = min(10, max(0, round((alert.fused_score or 0.0) * 10)))
    line = format_cef(
        signature_id="T1621-01",
        name="MFA fatigue detected",
        severity=severity,
        user_id=alert.user_id,
        action="alert_raised",
        fused_score=alert.fused_score or 0.0,
        timestamp=alert.ts or datetime.now(timezone.utc),
    )
    return Response(content=line, media_type="text/plain")
