"""L2 ingestion service: FastAPI collectors -> Kafka.

The only adapter implemented is `replay` (services/ingestion/app/adapters/
replay.py) — there is no live IdP in this environment, so replaying the
real, already-validated benchmark corpus through the real pipeline is the
only genuinely real event source available. See replay.py's module
docstring for why timestamps are remapped rather than replayed verbatim.
"""

from __future__ import annotations

import logging
import threading

from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException

from services.ingestion.app.adapters.replay import list_replayable_bursts, replay_burst
from services.ingestion.app.kafka_producer import EventProducer

logger = logging.getLogger("pulseguard.ingestion")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Configures the ROOT logger so this module's and replay.py's
    `getLogger(...)` calls actually emit -- uvicorn configures only its own
    `uvicorn.*` loggers, so a bare `getLogger(__name__).info(...)` has no
    handler and goes nowhere.

    Done here rather than at import, with `force=True`: see
    detection_engine/app/main.py's `_configure_logging` for the full
    reasoning (uvicorn's dictConfig can clear root handlers installed at
    import time, and plain `basicConfig()` is a silent no-op whenever root
    already has a handler).
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
    yield


app = FastAPI(title="pulseguard-ingestion", lifespan=lifespan)

_producer: EventProducer | None = None
_replay_lock = threading.Lock()
_replay_in_progress = False


def get_producer() -> EventProducer:
    global _producer
    if _producer is None:
        _producer = EventProducer()
    return _producer


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "ingestion"}


@app.get("/replay/bursts")
def get_replayable_bursts(events_path: str, profile: str | None = None, limit: int = 20) -> list[dict]:
    try:
        return list_replayable_bursts(events_path, profile=profile, limit=limit)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"{events_path} not found")


def _run_replay(events_path: str, burst_id: str, speedup: float) -> None:
    global _replay_in_progress
    try:
        replay_burst(events_path, burst_id, get_producer(), speedup=speedup)
    except Exception:
        logger.exception("Replay of burst_id=%s failed", burst_id)
    finally:
        with _replay_lock:
            _replay_in_progress = False


@app.post("/replay/start")
def start_replay(events_path: str, burst_id: str, speedup: float = 1.0, background_tasks: BackgroundTasks = None) -> dict:
    global _replay_in_progress
    with _replay_lock:
        if _replay_in_progress:
            raise HTTPException(status_code=409, detail="a replay is already in progress")
        _replay_in_progress = True

    thread = threading.Thread(target=_run_replay, args=(events_path, burst_id, speedup), daemon=True)
    thread.start()
    return {"status": "started", "burst_id": burst_id, "speedup": speedup}


@app.get("/replay/status")
def replay_status() -> dict:
    with _replay_lock:
        return {"in_progress": _replay_in_progress}
