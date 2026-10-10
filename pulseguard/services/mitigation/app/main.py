"""L5 mitigation service: the live mitigation worker (background thread),
the IdP's step-up outcome callback, and the dashboard's read API for
mitigation actions and per-user controller state.
"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI
from pydantic import BaseModel
from sqlalchemy import desc, select, text
from sqlalchemy.orm import Session

from pulseguard_common.db.models import MitigationAction
from pulseguard_common.db.session import get_db
from services.mitigation.app.cooldown import STEP_UP_COOLDOWN_SECONDS
from services.mitigation.app.escalation import ESCALATION_FAILURE_THRESHOLD, ESCALATION_WINDOW_SECONDS
from services.mitigation.app.live_worker import USER_STATES, run_live_mitigation_loop

_stop_event = threading.Event()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inside the lifespan with force=True: see detection_engine/app/main.py.
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s", force=True)
    if os.environ.get("MITIGATION_WORKER", "on") != "off":
        threading.Thread(target=run_live_mitigation_loop, args=(_stop_event,), daemon=True).start()
    yield
    _stop_event.set()


app = FastAPI(title="pulseguard-mitigation", lifespan=lifespan)


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    db.execute(text("SELECT 1"))
    return {"status": "ok", "service": "mitigation"}


@app.get("/actions")
def list_actions(user_id: Optional[str] = None, limit: int = 50, db: Session = Depends(get_db)) -> list[dict]:
    limit = max(1, min(limit, 500))
    query = select(MitigationAction).order_by(desc(MitigationAction.ts)).limit(limit)
    if user_id:
        query = query.where(MitigationAction.user_id == user_id)
    return [
        {
            "action_id": str(a.action_id),
            "user_id": a.user_id,
            "ts": a.ts.isoformat(),
            "action_type": a.action_type,
            "alert_id": str(a.alert_id) if a.alert_id else None,
            "consecutive_failures": a.consecutive_failures,
        }
        for a in db.scalars(query).all()
    ]


class StepUpOutcome(BaseModel):
    user_id: str
    passed: bool


@app.post("/feedback")
def step_up_feedback(outcome: StepUpOutcome) -> dict:
    """Called by the IdP when the user completes (or fails) a step-up
    challenge. A pass clears the escalation history; a fail counts toward
    the alternate-factor escalation -- never a lockout."""
    state = USER_STATES.get(outcome.user_id)
    if outcome.passed:
        state.record_success()
    else:
        state.record_failure(datetime.now(timezone.utc))
    return {"user_id": outcome.user_id, **USER_STATES.snapshot(outcome.user_id)}


@app.get("/state/{user_id}")
def controller_state(user_id: str) -> dict:
    return {
        "user_id": user_id,
        **USER_STATES.snapshot(user_id),
        "policy": {
            "step_up_cooldown_seconds": STEP_UP_COOLDOWN_SECONDS,
            "escalation_failure_threshold": ESCALATION_FAILURE_THRESHOLD,
            "escalation_window_seconds": ESCALATION_WINDOW_SECONDS,
            "lockout_possible": False,
        },
    }
