"""SQLAlchemy models mirroring infra/postgres/init.sql, the schema of record
(applied by the postgres container at first start; there are no migrations
because `./run` always starts from a fresh database)."""

from __future__ import annotations

import uuid

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Event(Base):
    __tablename__ = "events"

    event_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String, nullable=False, index=True)
    ts = Column(DateTime(timezone=True), nullable=False, primary_key=True)
    event_type = Column(String, nullable=False)
    decision = Column(String, nullable=True)
    decision_latency_ms = Column(Integer, nullable=True)
    src_ip = Column(String, nullable=False)
    geo_country = Column(String, nullable=True)
    geo_lat = Column(Float, nullable=True)
    geo_lon = Column(Float, nullable=True)
    device_id = Column(String, nullable=False)
    user_agent = Column(String, nullable=False)
    session_id = Column(String, nullable=False)
    episode_id = Column(String, nullable=True)
    ingest_ts = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("event_type IN ('mfa_prompt','mfa_decision','login_attempt')"),
        CheckConstraint("decision IN ('approve','deny','timeout') OR decision IS NULL"),
    )


class Alert(Base):
    __tablename__ = "alerts"

    alert_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String, nullable=False, index=True)
    ts = Column(DateTime(timezone=True), nullable=False)
    updated_ts = Column(DateTime(timezone=True), nullable=False)
    stage_a_score = Column(Float, nullable=True)
    stage_b_score = Column(Float, nullable=True)
    stage_c_score = Column(Float, nullable=True)
    fused_score = Column(Float, nullable=False)
    calibrated_probability = Column(Float, nullable=True)
    shap_top3 = Column(JSONB, nullable=True)
    explanation_source = Column(String, nullable=True)
    feature_vector = Column(JSONB, nullable=True)
    burst_id = Column(String, nullable=True, unique=True)  # the scored session's episode id
    n_decisions = Column(Integer, nullable=False, default=1)
    first_crossing_decision = Column(Integer, nullable=True)
    status = Column(String, nullable=False, default="open")


class Score(Base):
    __tablename__ = "scores"

    ts = Column(DateTime(timezone=True), primary_key=True)
    episode_id = Column(String, primary_key=True)
    decision_index = Column(Integer, primary_key=True)
    user_id = Column(String, nullable=False)
    decision = Column(String, nullable=True)
    decision_latency_ms = Column(Integer, nullable=True)
    stage_a_score = Column(Float, nullable=False)
    stage_b_score = Column(Float, nullable=False)
    stage_c_score = Column(Float, nullable=False)
    fused_score = Column(Float, nullable=False)
    threshold = Column(Float, nullable=False)
    raised = Column(Boolean, nullable=False)
    scoring_ms = Column(Float, nullable=False)


class MitigationAction(Base):
    __tablename__ = "mitigation_actions"

    action_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String, nullable=False, index=True)
    ts = Column(DateTime(timezone=True), nullable=False)
    action_type = Column(String, nullable=False)
    alert_id = Column(UUID(as_uuid=True), ForeignKey("alerts.alert_id"), nullable=True)
    consecutive_failures = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        CheckConstraint(
            "action_type IN ('step_up_required','alt_factor_required','cooldown_active')"
        ),
    )


class DeadLetter(Base):
    __tablename__ = "dead_letters"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    ts = Column(DateTime(timezone=True), nullable=True)
    source = Column(String, nullable=False)
    topic = Column(String, nullable=False)
    kafka_partition = Column(Integer, nullable=True)
    kafka_offset = Column(BigInteger, nullable=True)
    error = Column(String, nullable=False)
    payload = Column(String, nullable=True)


class ScenarioRun(Base):
    __tablename__ = "scenario_runs"

    run_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    started_ts = Column(DateTime(timezone=True), nullable=False)
    finished_ts = Column(DateTime(timezone=True), nullable=True)
    source = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    profile = Column(String, nullable=True)
    label_attack = Column(Boolean, nullable=True)
    burst_id = Column(String, nullable=True)
    n_events = Column(Integer, nullable=False, default=0)
    status = Column(String, nullable=False, default="running")


class IdpChallenge(Base):
    __tablename__ = "idp_challenges"

    challenge_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ts = Column(DateTime(timezone=True), nullable=False)
    user_id = Column(String, nullable=False)
    kind = Column(String, nullable=False)
    episode_id = Column(String, nullable=True)
    reason = Column(String, nullable=True)
    number_match = Column(Integer, nullable=True)
    status = Column(String, nullable=False, default="pending")
    resolved_ts = Column(DateTime(timezone=True), nullable=True)
