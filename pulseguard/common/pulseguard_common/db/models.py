"""SQLAlchemy models mirroring infra/postgres/init.sql.

Kept as plain declarative models (no Alembic autogenerate dependency yet);
`infra/postgres/init.sql` is the schema of record applied at container start.
Future migrations belong under common/pulseguard_common/db/migrations/.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Event(Base):
    __tablename__ = "events"

    event_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String, nullable=False, primary_key=False, index=True)
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
    stage_a_score = Column(Float, nullable=True)
    stage_b_score = Column(Float, nullable=True)
    stage_c_score = Column(Float, nullable=True)
    fused_score = Column(Float, nullable=False)
    calibrated_probability = Column(Float, nullable=True)
    shap_top3 = Column(JSONB, nullable=True)
    burst_id = Column(String, nullable=True)


class UserBaselineSnapshot(Base):
    __tablename__ = "users_baseline_snapshot"

    snapshot_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String, nullable=False, index=True)
    ts = Column(DateTime(timezone=True), nullable=False)
    latency_baseline_mean = Column(Float, nullable=True)
    latency_baseline_var = Column(Float, nullable=True)
    rate_baseline = Column(Float, nullable=True)
    event_count = Column(Integer, nullable=False)


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
