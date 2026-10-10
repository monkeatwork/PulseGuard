"""L5 mitigation controller service: health check, the live mitigation
worker (consumes real alerts, applies the real cooldown/escalation
controller, writes real mitigation_actions, calls the real webhook), and
the SOC dashboard's read API for a user's mitigation action history
(CLAUDE.md, L5).

The controller logic itself (cooldown.py/escalation.py/controller.py) is
exercised by the live worker (live_worker.py), started as a background
thread in this app's lifespan — not by this HTTP surface, which only
exposes the resulting `mitigation_actions` rows for the dashboard to read.
"""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session

from pulseguard_common.db.models import MitigationAction
from pulseguard_common.db.session import get_db
from services.mitigation.app.live_worker import run_live_mitigation_loop

_stop_event = threading.Event()


def _configure_logging() -> None:
    """See detection_engine/app/main.py's `_configure_logging` for why this
    runs inside the lifespan with `force=True` rather than at import: a
    module-level `basicConfig()` is wiped by uvicorn's own dictConfig, and
    is additionally a no-op if root already has a handler.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_logging()
    thread = threading.Thread(target=run_live_mitigation_loop, args=(_stop_event,), daemon=True)
    thread.start()
    yield
    _stop_event.set()


app = FastAPI(title="pulseguard-mitigation", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "mitigation"}


@app.get("/actions")
def list_actions(user_id: str, limit: int = 50, db: Session = Depends(get_db)) -> list[dict]:
    limit = max(1, min(limit, 500))
    actions = db.scalars(
        select(MitigationAction)
        .where(MitigationAction.user_id == user_id)
        .order_by(MitigationAction.ts.desc())
        .limit(limit)
    ).all()
    return [
        {
            "action_id": str(a.action_id),
            "user_id": a.user_id,
            "ts": a.ts.isoformat(),
            "action_type": a.action_type,
            "consecutive_failures": a.consecutive_failures,
        }
        for a in actions
    ]
