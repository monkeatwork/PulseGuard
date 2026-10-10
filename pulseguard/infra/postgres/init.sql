-- PulseGuard database initialization
-- Creates TimescaleDB extension and the core hypertable/tables described in DECISIONS.md.

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS events (
    event_id UUID NOT NULL,
    user_id TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN ('mfa_prompt', 'mfa_decision', 'login_attempt')),
    decision TEXT CHECK (decision IN ('approve', 'deny', 'timeout')),
    decision_latency_ms INTEGER,
    src_ip TEXT NOT NULL,
    geo_country TEXT,
    geo_lat DOUBLE PRECISION,
    geo_lon DOUBLE PRECISION,
    device_id TEXT NOT NULL,
    user_agent TEXT NOT NULL,
    session_id TEXT NOT NULL,
    ingest_ts TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (event_id, ts)
);

SELECT create_hypertable('events', 'ts', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_events_user_id_ts ON events (user_id, ts DESC);

CREATE TABLE IF NOT EXISTS alerts (
    alert_id UUID PRIMARY KEY,
    user_id TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    stage_a_score DOUBLE PRECISION,
    stage_b_score DOUBLE PRECISION,
    stage_c_score DOUBLE PRECISION,
    fused_score DOUBLE PRECISION NOT NULL,
    calibrated_probability DOUBLE PRECISION,
    shap_top3 JSONB,
    burst_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_alerts_user_id_ts ON alerts (user_id, ts DESC);

CREATE TABLE IF NOT EXISTS users_baseline_snapshot (
    snapshot_id UUID PRIMARY KEY,
    user_id TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    latency_baseline_mean DOUBLE PRECISION,
    latency_baseline_var DOUBLE PRECISION,
    rate_baseline DOUBLE PRECISION,
    event_count INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_baseline_snapshot_user_id_ts ON users_baseline_snapshot (user_id, ts DESC);

CREATE TABLE IF NOT EXISTS mitigation_actions (
    action_id UUID PRIMARY KEY,
    user_id TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    action_type TEXT NOT NULL CHECK (action_type IN ('step_up_required', 'alt_factor_required', 'cooldown_active')),
    alert_id UUID REFERENCES alerts (alert_id),
    consecutive_failures INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_mitigation_actions_user_id_ts ON mitigation_actions (user_id, ts DESC);
