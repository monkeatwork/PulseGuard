"""L4 detection engine service: the live scoring worker (background thread)
and the SOC dashboard's read API -- alerts with their full evidence, the
live score feed, KPIs, the persisted operating point, and the offline
evaluation results.

Startup fails loudly if the operating point or any model artifact is
missing (live_scorer.LiveScorer): a detector running at a configuration
nothing evaluated is worse than one that does not start. Set
LIVE_SCORER=off only for API tests that do not need the worker.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import desc, func, select, text
from sqlalchemy.orm import Session

from pulseguard_common.cef import format_cef
from pulseguard_common.db.models import Alert, DeadLetter, Event, IdpChallenge, MitigationAction, ScenarioRun, Score
from pulseguard_common.db.session import get_db

_stop_event = threading.Event()
_state: dict = {"scorer": None}
# <repo>/eval/results locally; /srv/eval/results in the container (same layout).
EVAL_RESULTS_DIR = Path(os.environ.get("EVAL_RESULTS_DIR", Path(__file__).resolve().parents[3] / "eval" / "results"))


def _configure_logging() -> None:
    """Root logger configured INSIDE the lifespan with force=True: uvicorn's
    dictConfig wipes handlers installed at import time, and a plain
    basicConfig() is a silent no-op once root has any handler."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s", force=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_logging()
    if os.environ.get("LIVE_SCORER", "on") != "off":
        from services.detection_engine.app.live_scorer import LiveScorer, run_live_scorer_loop

        scorer = LiveScorer()  # raises on a missing operating point / model: startup fails
        _state["scorer"] = scorer
        threading.Thread(target=run_live_scorer_loop, args=(_stop_event, scorer), daemon=True).start()
    yield
    _stop_event.set()


app = FastAPI(title="pulseguard-detection-engine", lifespan=lifespan)


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    db.execute(text("SELECT 1"))
    return {"status": "ok", "service": "detection_engine", "live_scorer": _state["scorer"] is not None}


def _latest_scenario(db: Session, user_id: str) -> Optional[dict]:
    run = db.scalars(
        select(ScenarioRun).where(ScenarioRun.user_id == user_id).order_by(desc(ScenarioRun.started_ts)).limit(1)
    ).first()
    if run is None:
        return None
    return {"source": run.source, "profile": run.profile, "label_attack": run.label_attack, "status": run.status}


def _alert_summary(alert: Alert, db: Session) -> dict:
    last_action = db.scalars(
        select(MitigationAction).where(MitigationAction.alert_id == alert.alert_id).order_by(desc(MitigationAction.ts)).limit(1)
    ).first()
    return {
        "alert_id": str(alert.alert_id),
        "user_id": alert.user_id,
        "ts": alert.ts.isoformat(),
        "updated_ts": alert.updated_ts.isoformat() if alert.updated_ts else None,
        "fused_score": alert.fused_score,
        "stage_a_score": alert.stage_a_score,
        "stage_b_score": alert.stage_b_score,
        "stage_c_score": alert.stage_c_score,
        "explanation_source": alert.explanation_source,
        "episode_id": alert.burst_id,
        "n_decisions": alert.n_decisions,
        "first_crossing_decision": alert.first_crossing_decision,
        "status": alert.status,
        "scenario": _latest_scenario(db, alert.user_id),
        "last_action": last_action.action_type if last_action else None,
    }


@app.get("/alerts")
def list_alerts(limit: int = 50, status: Optional[str] = None, db: Session = Depends(get_db)) -> list[dict]:
    limit = max(1, min(limit, 500))
    query = select(Alert).order_by(desc(Alert.ts)).limit(limit)
    if status:
        query = query.where(Alert.status == status)
    return [_alert_summary(a, db) for a in db.scalars(query).all()]


@app.get("/alerts/{alert_id}")
def get_alert(alert_id: str, db: Session = Depends(get_db)) -> dict:
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="alert not found")

    events = db.scalars(select(Event).where(Event.episode_id == alert.burst_id).order_by(Event.ts)).all() if alert.burst_id else []
    sequence = [
        {
            "ts": e.ts.isoformat(),
            "decision": e.decision,
            "decision_latency_ms": e.decision_latency_ms,
            "device_id": e.device_id,
            "src_ip": e.src_ip,
            "geo_country": e.geo_country,
        }
        for e in events
        if e.event_type == "mfa_decision"
    ]
    prompts = [
        {"ts": e.ts.isoformat(), "src_ip": e.src_ip, "device_id": e.device_id, "user_agent": e.user_agent}
        for e in events
        if e.event_type == "mfa_prompt"
    ]
    trajectory = [
        {
            "decision_index": s.decision_index,
            "fused_score": s.fused_score,
            "stage_a_score": s.stage_a_score,
            "stage_b_score": s.stage_b_score,
            "stage_c_score": s.stage_c_score,
            "raised": s.raised,
            "decision": s.decision,
            "decision_latency_ms": s.decision_latency_ms,
        }
        for s in db.scalars(select(Score).where(Score.episode_id == alert.burst_id).order_by(Score.decision_index)).all()
    ]
    actions = [
        {"action_id": str(a.action_id), "ts": a.ts.isoformat(), "action_type": a.action_type,
         "consecutive_failures": a.consecutive_failures}
        for a in db.scalars(select(MitigationAction).where(MitigationAction.alert_id == alert.alert_id).order_by(MitigationAction.ts)).all()
    ]
    challenges = [
        {"challenge_id": str(c.challenge_id), "ts": c.ts.isoformat(), "kind": c.kind, "status": c.status,
         "resolved_ts": c.resolved_ts.isoformat() if c.resolved_ts else None}
        for c in db.scalars(select(IdpChallenge).where(IdpChallenge.episode_id == alert.burst_id).order_by(IdpChallenge.ts)).all()
    ]
    scorer = _state["scorer"]
    operating_point = None
    if scorer is not None:
        w = scorer.weights.normalized()
        operating_point = {"weights": {"a": w.weight_a, "b": w.weight_b, "c": w.weight_c}, "threshold": scorer.threshold}

    return {
        **_alert_summary(alert, db),
        "calibrated_probability": alert.calibrated_probability,
        "shap_top3": alert.shap_top3 or [],
        "feature_vector": alert.feature_vector or {},
        "sequence": sequence,
        "prompts": prompts,
        "score_trajectory": trajectory,
        "mitigation_actions": actions,
        "idp_challenges": challenges,
        "operating_point": operating_point,
    }


class AlertStatusUpdate(BaseModel):
    status: str


@app.patch("/alerts/{alert_id}")
def update_alert_status(alert_id: str, body: AlertStatusUpdate, db: Session = Depends(get_db)) -> dict:
    if body.status not in ("open", "acknowledged", "resolved"):
        raise HTTPException(status_code=422, detail="status must be open, acknowledged or resolved")
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="alert not found")
    alert.status = body.status
    db.commit()
    return {"alert_id": alert_id, "status": alert.status}


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


@app.get("/scores/recent")
def recent_scores(limit: int = 100, user_id: Optional[str] = None, db: Session = Depends(get_db)) -> list[dict]:
    limit = max(1, min(limit, 1000))
    query = select(Score).order_by(desc(Score.ts)).limit(limit)
    if user_id:
        query = query.where(Score.user_id == user_id)
    return [
        {
            "ts": s.ts.isoformat(), "user_id": s.user_id, "episode_id": s.episode_id,
            "decision_index": s.decision_index, "decision": s.decision,
            "decision_latency_ms": s.decision_latency_ms, "fused_score": s.fused_score,
            "stage_a_score": s.stage_a_score, "stage_b_score": s.stage_b_score, "stage_c_score": s.stage_c_score,
            "threshold": s.threshold, "raised": s.raised, "scoring_ms": s.scoring_ms,
        }
        for s in db.scalars(query).all()
    ]


@app.get("/stats")
def stats(db: Session = Depends(get_db)) -> dict:
    alerts_total = db.scalar(select(func.count()).select_from(Alert)) or 0
    alerts_open = db.scalar(select(func.count()).select_from(Alert).where(Alert.status == "open")) or 0
    decisions = db.scalar(select(func.count()).select_from(Score)) or 0
    sessions = db.scalar(select(func.count(func.distinct(Score.episode_id)))) or 0
    p50, p95 = db.execute(
        text("SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY scoring_ms), "
             "percentile_cont(0.95) WITHIN GROUP (ORDER BY scoring_ms) FROM scores")
    ).one()
    actions = dict(db.execute(select(MitigationAction.action_type, func.count()).group_by(MitigationAction.action_type)).all())
    challenges = dict(db.execute(select(IdpChallenge.status, func.count()).group_by(IdpChallenge.status)).all())
    dead = db.scalar(select(func.count()).select_from(DeadLetter)) or 0
    return {
        "alerts_total": alerts_total,
        "alerts_open": alerts_open,
        "decisions_scored": decisions,
        "sessions_scored": sessions,
        "scoring_ms_p50": p50,
        "scoring_ms_p95": p95,
        "mitigation_actions": actions,
        "idp_challenges": challenges,
        "dead_letters": dead,
    }


@app.get("/dead-letters")
def dead_letters(limit: int = 50, db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(DeadLetter).order_by(desc(DeadLetter.id)).limit(max(1, min(limit, 500)))).all()
    return [
        {"id": d.id, "ts": d.ts.isoformat() if d.ts else None, "source": d.source, "topic": d.topic,
         "error": d.error, "payload": (d.payload or "")[:2000]}
        for d in rows
    ]


@app.get("/operating-point")
def operating_point() -> dict:
    scorer = _state["scorer"]
    if scorer is None:
        raise HTTPException(status_code=503, detail="live scorer not running")
    from dataclasses import asdict

    return asdict(scorer.operating_point)


@app.get("/eval/results")
def eval_results() -> dict:
    """The committed offline evaluation (eval/results/*.json + the generated
    report), served verbatim -- the dashboard never recomputes a number."""
    out: dict = {}
    if EVAL_RESULTS_DIR.is_dir():
        for path in sorted(EVAL_RESULTS_DIR.glob("*.json")):
            out[path.stem] = json.loads(path.read_text(encoding="utf-8"))
        report = EVAL_RESULTS_DIR / "final_report.md"
        if report.exists():
            out["final_report_md"] = report.read_text(encoding="utf-8")
    return out
