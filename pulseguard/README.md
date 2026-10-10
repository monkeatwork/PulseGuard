# PulseGuard

Behaviour-aware detector for MFA fatigue attacks (MITRE T1621). See
[`../CLAUDE.md`](../CLAUDE.md) for the full project spec and
[`DECISIONS.md`](DECISIONS.md) for the log of autonomous design decisions.

## Setup

The only setup step is:

```
docker compose up
```

This brings up Postgres/TimescaleDB, Redis, Redpanda (Kafka-API compatible
broker), Keycloak (test IdP), and all four backend services plus the SOC
dashboard, each exposing a `/health` endpoint.

To fetch the benchmark dataset (Wiefling RBA dataset, via Zenodo — see
`DECISIONS.md`, "RBA dataset source"):

```
make data
```

This has no fallback: if the fetch or checksum verification fails, it stops
with an explicit error rather than substituting synthetic data.

## Repo layout

- `services/` — the four backend services (ingestion, feature_engine,
  detection_engine, mitigation) plus the React dashboard.
- `benchmark/` — the seeded, deterministic attack/benign event generator and
  the industry baseline rules (Splunk, Elastic).
- `eval/` — the frozen by-user evaluation harness, ablation study, and
  adversarial evaluation.
- `common/pulseguard_common/` — the canonical event schema and shared
  utilities imported by every service.

## Build order

This project is built in the order the evaluation depends on, not the order
the architecture diagram is drawn in: benchmark generator → industry
baselines + evaluation harness → feature engine → detection engine (Stage
A/B, then Stage C + fusion) → mitigation controller → dashboard → ablation.
See the implementation plan for the full phase breakdown and gates.

## Tests

```
make test
```

Runs the full pytest suite. Integration tests that need Postgres/Redis/
Redpanda use Testcontainers and require Docker to be running.
