-- PulseGuard database initialization (schema of record; applied by the
-- postgres container on first start -- `./run` always starts from a fresh
-- volume). Mirrored by common/pulseguard_common/db/models.py.

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Raw MFA telemetry as scored by the detection engine (hypertable).
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
    episode_id TEXT,
    ingest_ts TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (event_id, ts)
);
SELECT create_hypertable('events', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_events_user_id_ts ON events (user_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_events_episode ON events (episode_id, ts);

-- One alert per scored session ("episode"), created at the first decision
-- point that crosses the persisted operating-point threshold and updated
-- as later decision points arrive.
CREATE TABLE IF NOT EXISTS alerts (
    alert_id UUID PRIMARY KEY,
    user_id TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    updated_ts TIMESTAMPTZ NOT NULL,
    stage_a_score DOUBLE PRECISION,
    stage_b_score DOUBLE PRECISION,
    stage_c_score DOUBLE PRECISION,
    fused_score DOUBLE PRECISION NOT NULL,
    calibrated_probability DOUBLE PRECISION,
    shap_top3 JSONB,
    explanation_source TEXT,
    feature_vector JSONB,
    burst_id TEXT UNIQUE,
    n_decisions INTEGER NOT NULL DEFAULT 1,
    first_crossing_decision INTEGER,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'acknowledged', 'resolved'))
);
CREATE INDEX IF NOT EXISTS idx_alerts_user_id_ts ON alerts (user_id, ts DESC);

-- Every decision point the live scorer scored, alerted or not (hypertable):
-- the live feed, score trajectories, and scoring-latency KPIs.
CREATE TABLE IF NOT EXISTS scores (
    ts TIMESTAMPTZ NOT NULL,
    user_id TEXT NOT NULL,
    episode_id TEXT NOT NULL,
    decision_index INTEGER NOT NULL,
    decision TEXT,
    decision_latency_ms INTEGER,
    stage_a_score DOUBLE PRECISION NOT NULL,
    stage_b_score DOUBLE PRECISION NOT NULL,
    stage_c_score DOUBLE PRECISION NOT NULL,
    fused_score DOUBLE PRECISION NOT NULL,
    threshold DOUBLE PRECISION NOT NULL,
    raised BOOLEAN NOT NULL,
    scoring_ms DOUBLE PRECISION NOT NULL,
    -- a redelivered Kafka message re-scores the same decision point; this
    -- key makes that a no-op (hypertable unique keys must include ts)
    UNIQUE (episode_id, decision_index, ts)
);
SELECT create_hypertable('scores', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_scores_episode ON scores (episode_id, ts);

CREATE TABLE IF NOT EXISTS mitigation_actions (
    action_id UUID PRIMARY KEY,
    user_id TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    action_type TEXT NOT NULL CHECK (action_type IN ('step_up_required', 'alt_factor_required', 'cooldown_active')),
    alert_id UUID REFERENCES alerts (alert_id),
    consecutive_failures INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_mitigation_actions_user_id_ts ON mitigation_actions (user_id, ts DESC);

-- Messages a worker could not process, preserved instead of swallowed.
CREATE TABLE IF NOT EXISTS dead_letters (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    source TEXT NOT NULL,
    topic TEXT NOT NULL,
    kafka_partition INTEGER,
    kafka_offset BIGINT,
    error TEXT NOT NULL,
    payload TEXT
);

-- Demo bookkeeping, written by the ingestion service. The detector never
-- reads these: ground-truth labels stay out of the scoring path.
CREATE TABLE IF NOT EXISTS scenario_runs (
    run_id UUID PRIMARY KEY,
    started_ts TIMESTAMPTZ NOT NULL,
    finished_ts TIMESTAMPTZ,
    source TEXT NOT NULL CHECK (source IN ('replay', 'simulator')),
    user_id TEXT NOT NULL,
    profile TEXT,
    label_attack BOOLEAN,
    burst_id TEXT,
    n_events INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'finished', 'failed', 'stopped'))
);
CREATE INDEX IF NOT EXISTS idx_scenario_runs_user ON scenario_runs (user_id, started_ts DESC);

-- Step-up / alternate-factor challenges issued by the mock IdP in response
-- to the mitigation controller's webhook.
CREATE TABLE IF NOT EXISTS idp_challenges (
    challenge_id UUID PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('step_up', 'alt_factor')),
    episode_id TEXT,
    reason TEXT,
    number_match INTEGER,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'passed', 'failed', 'expired')),
    resolved_ts TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_idp_challenges_user ON idp_challenges (user_id, ts DESC);
