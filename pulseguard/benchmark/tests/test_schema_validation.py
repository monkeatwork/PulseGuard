"""Every generated record's canonical-schema subset must validate against
PulseGuardEvent (Phase 1 gate: 100% schema-valid output)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from benchmark.generator.cli import validate_canonical_fields
from pulseguard_common.event_schema import PulseGuardEvent

BASE_TS = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _record(**overrides) -> dict:
    base = dict(
        event_id="11111111-1111-1111-1111-111111111111",
        user_id="user1",
        ts=BASE_TS,
        event_type="login_attempt",
        decision=None,
        decision_latency_ms=None,
        src_ip="10.0.0.1",
        geo_country="US",
        device_id="device-1",
        user_agent="Mozilla/5.0",
        session_id="22222222-2222-2222-2222-222222222222",
        ingest_ts=BASE_TS,
    )
    base.update(overrides)
    return base


def test_login_attempt_record_validates():
    validate_canonical_fields(_record())


def test_mfa_prompt_and_decision_records_validate():
    validate_canonical_fields(_record(event_type="mfa_prompt"))
    validate_canonical_fields(
        _record(event_type="mfa_decision", decision="approve", decision_latency_ms=4200)
    )
    validate_canonical_fields(
        _record(event_type="mfa_decision", decision="deny", decision_latency_ms=1800)
    )
    validate_canonical_fields(
        _record(event_type="mfa_decision", decision="timeout", decision_latency_ms=None)
    )


def test_record_with_no_geo_country_validates():
    validate_canonical_fields(_record(geo_country=None))


def test_naive_timestamp_is_rejected():
    naive_ts = datetime(2026, 1, 1)  # no tzinfo
    with pytest.raises(Exception):
        validate_canonical_fields(_record(ts=naive_ts))


def test_negative_latency_is_rejected():
    with pytest.raises(Exception):
        validate_canonical_fields(
            _record(event_type="mfa_decision", decision="approve", decision_latency_ms=-1)
        )


def test_pulseguard_event_roundtrips_to_json():
    event = PulseGuardEvent(
        event_id="11111111-1111-1111-1111-111111111111",
        user_id="user1",
        ts=BASE_TS,
        event_type="mfa_decision",
        decision="approve",
        decision_latency_ms=3000,
        src_ip="10.0.0.1",
        geo={"country": "US"},
        device_id="device-1",
        user_agent="Mozilla/5.0",
        session_id="22222222-2222-2222-2222-222222222222",
        ingest_ts=BASE_TS,
    )
    payload = event.model_dump_json()
    restored = PulseGuardEvent.model_validate_json(payload)
    assert restored == event
