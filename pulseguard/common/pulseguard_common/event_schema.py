"""Canonical PulseGuard event schema.

This is the single source of truth for the event shape carried on
`pulseguard.events.raw` / `pulseguard.events.enriched`, produced by the
benchmark generator, and validated by every consumer. See DECISIONS.md,
"Canonical event schema" (2026-09-20), for why JSON+pydantic was chosen
over Avro/schema-registry.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator


class EventType(str, Enum):
    MFA_PROMPT = "mfa_prompt"
    MFA_DECISION = "mfa_decision"
    LOGIN_ATTEMPT = "login_attempt"


class Decision(str, Enum):
    APPROVE = "approve"
    DENY = "deny"
    TIMEOUT = "timeout"


class Geo(BaseModel):
    """`lat`/`lon` are optional because the Wiefling RBA dataset (the
    generator's benign base layer) only carries country/region/city/ASN,
    not coordinates. See DECISIONS.md, "Geo lat/lon made optional"."""

    model_config = ConfigDict(frozen=True)

    country: str
    lat: Optional[float] = None
    lon: Optional[float] = None


class PulseGuardEvent(BaseModel):
    """Canonical event emitted by L1 adapters and consumed through L2-L4.

    `ts` is the identity-provider-issued timestamp and is the only timestamp
    used for burst boundaries and `latency_drift_slope` regression fits.
    `ingest_ts` is set by the L2 collector on receipt and exists solely to
    detect clock skew (see DECISIONS.md, "latency_drift_slope edge cases").
    """

    model_config = ConfigDict(frozen=True)

    event_id: UUID
    user_id: str
    ts: datetime
    event_type: EventType
    decision: Optional[Decision] = None
    decision_latency_ms: Optional[int] = None
    src_ip: str
    geo: Optional[Geo] = None
    device_id: str
    user_agent: str
    session_id: str
    ingest_ts: datetime

    @field_validator("ts", "ingest_ts")
    @classmethod
    def _must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware (UTC)")
        return value

    @field_validator("decision_latency_ms")
    @classmethod
    def _latency_must_be_non_negative(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and value < 0:
            raise ValueError("decision_latency_ms must be non-negative")
        return value
