"""L1/L2 ingestion service: runs telemetry adapters and produces their
canonical events to Kafka, and hosts the mock identity provider the
mitigation controller calls.

Adapters (adapters/base.py: TelemetryAdapter):
  * ReplayAdapter     -- labelled benchmark episodes (POST /scenarios/replay)
  * SimulatorSession  -- an interactive attack on a human victim (/simulator)
Entra ID / Okta / Duo adapters are future work and are not implemented
(REMEDIATION_TASK.md D1; CLAUDE.md lists them as such).

Mock IdP (/idp/*): stands in for the IdP's step-up API (REMEDIATION_TASK.md
D2 -- it replaces a Keycloak container nothing used). It records step-up and
alternate-factor challenges, suspends blind push approval for a challenged
user, and reports the challenge outcome back to the mitigation controller.

Scenario metadata (which profile a replay was, its ground-truth label) is
written to `scenario_runs` for the dashboard only; it never travels with the
events, so the detector cannot see it.
"""

from __future__ import annotations

import logging
import os
import random
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select, text

from pulseguard_common.db.models import IdpChallenge, ScenarioRun
from pulseguard_common.db.session import get_session_factory
from services.ingestion.app.adapters.replay import ReplayAdapter, list_replayable_bursts, load_episode
from services.ingestion.app.adapters.simulator import SimulatorSession, wait_for
from services.ingestion.app.kafka_producer import EventProducer

logger = logging.getLogger("pulseguard.ingestion")

DATA_DIR = Path(os.environ.get("DATA_DIR", "/srv/data"))
DEMO_EVENTS_PATH = Path(os.environ.get("DEMO_EVENTS_PATH", DATA_DIR / "demo" / "demo_events.parquet"))
MITIGATION_URL = os.environ.get("MITIGATION_URL", "http://mitigation:8004")
MAX_CONCURRENT_REPLAYS = 6
CHALLENGE_ACTIVE_SECONDS = 15 * 60


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inside the lifespan with force=True: see detection_engine/app/main.py.
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s", force=True)
    yield
    for sim in list(_sims.values()):
        sim.stop()


app = FastAPI(title="pulseguard-ingestion", lifespan=lifespan)

_producer: EventProducer | None = None
_producer_lock = threading.Lock()
_runs: dict[str, dict] = {}
_runs_lock = threading.Lock()
_sims: dict[str, SimulatorSession] = {}


def get_producer() -> EventProducer:
    global _producer
    with _producer_lock:
        if _producer is None:
            _producer = EventProducer()
        return _producer


def _db():
    return get_session_factory()()


def _now() -> datetime:
    return datetime.now(timezone.utc)


@app.get("/health")
def health() -> dict:
    db = _db()
    try:
        db.execute(text("SELECT 1"))
    finally:
        db.close()
    return {"status": "ok", "service": "ingestion", "demo_corpus": DEMO_EVENTS_PATH.exists(), "adapters": ["replay", "simulator"]}


# --- scenario replay --------------------------------------------------------

@app.get("/scenarios")
def list_scenarios(profile: Optional[str] = None, limit: int = 50) -> list[dict]:
    if not DEMO_EVENTS_PATH.exists():
        raise HTTPException(status_code=404, detail=f"{DEMO_EVENTS_PATH} not found")
    return list_replayable_bursts(str(DEMO_EVENTS_PATH), profile=profile, limit=max(1, min(limit, 500)))


class ReplayRequest(BaseModel):
    burst_id: str
    time_mode: Literal["preserve", "realtime"] = "preserve"
    pace_seconds: float = Field(0.6, ge=0.0, le=10.0)
    speedup: float = Field(1.0, gt=0.0, le=10000.0)


def _set_run(run_id: str, **fields) -> None:
    with _runs_lock:
        _runs[run_id].update(fields)
    db = _db()
    try:
        run = db.get(ScenarioRun, uuid.UUID(run_id))
        if run is not None:
            for key in ("n_events", "status", "finished_ts"):
                if key in fields:
                    setattr(run, key, fields[key])
            db.commit()
    finally:
        db.close()


def _run_replay(run_id: str, adapter: ReplayAdapter) -> None:
    progress = {"n": 0}

    def on_event(event) -> None:
        progress["n"] += 1
        with _runs_lock:
            _runs[run_id]["n_events"] = progress["n"]

    try:
        count = adapter.run(get_producer(), on_event=on_event, should_stop=lambda: _runs[run_id].get("stop", False))
        _set_run(run_id, n_events=count, status="stopped" if _runs[run_id].get("stop") else "finished", finished_ts=_now())
    except Exception:
        logger.exception("Replay %s failed", run_id)
        _set_run(run_id, status="failed", finished_ts=_now())


@app.post("/scenarios/replay")
def start_replay(req: ReplayRequest) -> dict:
    with _runs_lock:
        active = sum(1 for r in _runs.values() if r["status"] == "running")
    if active >= MAX_CONCURRENT_REPLAYS:
        raise HTTPException(status_code=409, detail=f"{active} replays already running")
    try:
        episode = load_episode(str(DEMO_EVENTS_PATH), req.burst_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    run_id = str(uuid.uuid4())
    first = episode.iloc[0]
    profile = req.burst_id.split(":")[-2]
    user_id = f"{first['user_id']}#{run_id[:4]}"
    adapter = ReplayAdapter(episode, user_id, req.time_mode, req.pace_seconds, req.speedup)
    record = {
        "run_id": run_id, "source": "replay", "user_id": user_id, "profile": profile,
        "label_attack": bool(first["label_attack"]), "burst_id": req.burst_id, "status": "running",
        "n_events": 0, "n_total": int(len(episode)), "started_ts": _now(), "time_mode": req.time_mode,
    }
    with _runs_lock:
        _runs[run_id] = record
    db = _db()
    try:
        db.add(ScenarioRun(run_id=uuid.UUID(run_id), started_ts=record["started_ts"], source="replay", user_id=user_id,
                           profile=profile, label_attack=record["label_attack"], burst_id=req.burst_id, status="running"))
        db.commit()
    finally:
        db.close()
    threading.Thread(target=_run_replay, args=(run_id, adapter), daemon=True).start()
    return _public_run(record)


def _public_run(r: dict) -> dict:
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in r.items() if k != "stop"}


@app.get("/runs")
def list_runs(limit: int = 30) -> list[dict]:
    with _runs_lock:
        live = {k: dict(v) for k, v in _runs.items()}
    db = _db()
    try:
        rows = db.scalars(select(ScenarioRun).order_by(desc(ScenarioRun.started_ts)).limit(max(1, min(limit, 200)))).all()
    finally:
        db.close()
    out = []
    for r in rows:
        mem = live.get(str(r.run_id), {})
        out.append({
            "run_id": str(r.run_id), "source": r.source, "user_id": r.user_id, "profile": r.profile,
            "label_attack": r.label_attack, "burst_id": r.burst_id, "status": mem.get("status", r.status),
            "n_events": mem.get("n_events", r.n_events), "n_total": mem.get("n_total"),
            "started_ts": r.started_ts.isoformat(), "time_mode": mem.get("time_mode"),
        })
    return out


@app.post("/runs/{run_id}/stop")
def stop_run(run_id: str) -> dict:
    with _runs_lock:
        if run_id not in _runs:
            raise HTTPException(status_code=404, detail="run not found")
        _runs[run_id]["stop"] = True
    return {"run_id": run_id, "stopping": True}


# --- interactive simulator ----------------------------------------------------

class SimulatorRequest(BaseModel):
    mode: Literal["attack", "benign"] = "attack"
    pacing_seconds: float = Field(6.0, ge=2.0, le=120.0)
    max_prompts: int = Field(20, ge=1, le=60)


def _push_blocked(user_id: str) -> bool:
    db = _db()
    try:
        cutoff = _now() - timedelta(seconds=CHALLENGE_ACTIVE_SECONDS)
        return db.scalars(
            select(IdpChallenge).where(IdpChallenge.user_id == user_id, IdpChallenge.ts >= cutoff,
                                       IdpChallenge.status.in_(("pending", "failed")))
        ).first() is not None
    finally:
        db.close()


def _run_sim(sim: SimulatorSession, run_id: str) -> None:
    count = sim.run(get_producer())
    status = {"stopped": "stopped"}.get(sim.status, "finished")
    _set_run(run_id, n_events=count, status=status, finished_ts=_now())


@app.post("/simulator")
def start_simulator(req: SimulatorRequest) -> dict:
    sim = SimulatorSession(mode=req.mode, pacing_seconds=req.pacing_seconds, max_prompts=req.max_prompts,
                           is_push_blocked=_push_blocked)
    _sims[sim.sim_id] = sim
    run_id = str(uuid.uuid4())
    sim.run_id = run_id
    with _runs_lock:
        _runs[run_id] = {"run_id": run_id, "source": "simulator", "user_id": sim.user_id,
                         "profile": f"simulator_{req.mode}", "label_attack": req.mode == "attack",
                         "status": "running", "n_events": 0, "started_ts": _now()}
    db = _db()
    try:
        db.add(ScenarioRun(run_id=uuid.UUID(run_id), started_ts=_now(), source="simulator", user_id=sim.user_id,
                           profile=f"simulator_{req.mode}", label_attack=req.mode == "attack", status="running"))
        db.commit()
    finally:
        db.close()
    threading.Thread(target=_run_sim, args=(sim, run_id), daemon=True).start()
    if req.mode == "attack":
        threading.Thread(target=sim.attacker_loop, daemon=True).start()
    return sim.snapshot()


def _get_sim(sim_id: str) -> SimulatorSession:
    sim = _sims.get(sim_id)
    if sim is None:
        raise HTTPException(status_code=404, detail="simulator session not found")
    return sim


@app.get("/simulator/{sim_id}")
def simulator_state(sim_id: str) -> dict:
    sim = _get_sim(sim_id)
    return {**sim.snapshot(), "challenges": _challenges_for(sim.user_id)}


class SimulatorAnswer(BaseModel):
    decision: Literal["approve", "deny"]


@app.post("/simulator/{sim_id}/respond")
def simulator_respond(sim_id: str, answer: SimulatorAnswer) -> dict:
    sim = _get_sim(sim_id)
    try:
        entry = sim.respond(answer.decision)
    except LookupError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    outcome = "denied"
    if answer.decision == "approve":
        if entry["origin"] == "you":
            outcome = "signed_in"
        else:
            # In-band: give the pipeline a moment to score this very decision.
            # If PulseGuard forces a step-up, the IdP holds the approval.
            held = wait_for(lambda: _push_blocked(sim.user_id), timeout=3.0)
            outcome = "held_for_step_up" if held else "attacker_signed_in"
            if held:
                sim.status = "protected"
                sim._note("protected", "Your approval was intercepted: PulseGuard required a number-matching step-up the attacker cannot answer.")
            else:
                sim.status = "compromised"
                sim._note("compromised", "Your approval let the attacker in.")
                sim.stop()
    return {**entry, "outcome": outcome, "state": simulator_state(sim_id)}


@app.post("/simulator/{sim_id}/login")
def simulator_login(sim_id: str) -> dict:
    """Benign mode: the user starts a login from their own laptop."""
    sim = _get_sim(sim_id)
    if sim.mode != "benign":
        raise HTTPException(status_code=409, detail="only benign sessions start their own logins")
    if sim.send_prompt("you") is None:
        raise HTTPException(status_code=409, detail="a prompt is already waiting")
    return sim.snapshot()


@app.post("/simulator/{sim_id}/stop")
def simulator_stop(sim_id: str) -> dict:
    sim = _get_sim(sim_id)
    sim.stop()
    return sim.snapshot()


# --- mock identity provider ---------------------------------------------------

class WebhookBody(BaseModel):
    user_id: str
    session_id: str = ""
    reason: str = ""


def _issue(kind: str, body: WebhookBody) -> dict:
    challenge = IdpChallenge(challenge_id=uuid.uuid4(), ts=_now(), user_id=body.user_id, kind=kind,
                             episode_id=body.session_id or None, reason=body.reason,
                             number_match=random.randint(10, 99), status="pending")
    db = _db()
    try:
        db.add(challenge)
        db.commit()
        cid = str(challenge.challenge_id)
    finally:
        db.close()
    logger.info("IdP issued %s challenge %s for %s (%s)", kind, cid, body.user_id, body.reason)
    return {"accepted": True, "challenge_id": cid}


@app.post("/idp/step-up")
def idp_step_up(body: WebhookBody) -> dict:
    return _issue("step_up", body)


@app.post("/idp/alt-factor")
def idp_alt_factor(body: WebhookBody) -> dict:
    return _issue("alt_factor", body)


def _challenges_for(user_id: Optional[str] = None, limit: int = 50) -> list[dict]:
    db = _db()
    try:
        query = select(IdpChallenge).order_by(desc(IdpChallenge.ts)).limit(limit)
        if user_id:
            query = query.where(IdpChallenge.user_id == user_id)
        return [
            {"challenge_id": str(c.challenge_id), "ts": c.ts.isoformat(), "user_id": c.user_id, "kind": c.kind,
             "episode_id": c.episode_id, "reason": c.reason, "number_match": c.number_match, "status": c.status,
             "resolved_ts": c.resolved_ts.isoformat() if c.resolved_ts else None}
            for c in db.scalars(query).all()
        ]
    finally:
        db.close()


@app.get("/idp/challenges")
def idp_challenges(user_id: Optional[str] = None, limit: int = 50) -> list[dict]:
    return _challenges_for(user_id, max(1, min(limit, 500)))


class ChallengeAnswer(BaseModel):
    passed: bool


@app.post("/idp/challenges/{challenge_id}/resolve")
def idp_resolve(challenge_id: str, answer: ChallengeAnswer) -> dict:
    db = _db()
    try:
        challenge = db.get(IdpChallenge, uuid.UUID(challenge_id))
        if challenge is None:
            raise HTTPException(status_code=404, detail="challenge not found")
        if challenge.status != "pending":
            raise HTTPException(status_code=409, detail=f"challenge already {challenge.status}")
        challenge.status = "passed" if answer.passed else "failed"
        challenge.resolved_ts = _now()
        user_id = challenge.user_id
        db.commit()
    finally:
        db.close()
    try:  # report the outcome to the mitigation controller (drives escalation)
        httpx.post(f"{MITIGATION_URL}/feedback", json={"user_id": user_id, "passed": answer.passed}, timeout=3.0)
    except httpx.HTTPError:
        logger.warning("Could not report challenge outcome to mitigation")
    return {"challenge_id": challenge_id, "status": "passed" if answer.passed else "failed"}
