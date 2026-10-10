# PulseGuard — developer guide

Start with the [root README](../README.md) to run the demo. The spec is [`../CLAUDE.md`](../CLAUDE.md), and every design decision (decided / rejected / why) is in [`DECISIONS.md`](DECISIONS.md).

## Layout

| Path | What lives there |
|---|---|
| `common/pulseguard_common/` | Code shared by every service image: the canonical event schema, windows/sessions, both feature families, baselines, the DB models and the Kafka worker helper. |
| `services/ingestion/` | L1/L2: the `TelemetryAdapter` interface, the replay and simulator adapters, the Kafka producer, the mock IdP (`/idp/*`) and the `kafka-init` topic job. |
| `services/feature_engine/` | L3: the Faust worker (`streaming_app.py`), per-event session logic (`session_processor.py`) and the baseline read API. |
| `services/detection_engine/` | L4: the live scorer and the dashboard API, plus offline training, tuning, explanation and `model_registry/`. |
| `services/mitigation/` | L5: the cooldown/escalation controller, the live worker, the webhook client and the IdP feedback endpoint. |
| `services/dashboard/` | React + Recharts SOC dashboard, built to static files and served by nginx, which proxies `/api/*`. |
| `benchmark/` | The seeded generator (RBA benign base plus attack profiles), the Splunk/Elastic baselines, and the episode-length and demo-slice tools. |
| `eval/` | The frozen by-user harness, the ablation and the adversarial evaluation. `eval/results/` holds every reported number. |
| `infra/postgres/init.sql` | The schema of record. |

## The unit everything is scored on

A **session** is one user's MFA events with no gap longer than 60 minutes (`sessions.py`). At every `mfa_decision` the session-so-far is featurised and scored, live in the feature engine and offline in `feature_table.py`/`sequence_dataset.py`, through the same functions. An episode is positive if any decision point crosses the threshold, which is the live alerting rule. See DECISIONS.md, "A1/A2 — Session-level scoring".

## Live pipeline API

Everything is reachable through the dashboard origin, `http://localhost:3000/api/<service>/…`:

| Path | Purpose |
|---|---|
| `GET /api/ingestion/scenarios?profile=` | Replayable demo episodes |
| `POST /api/ingestion/scenarios/replay` | Body `{"burst_id": …, "pace_seconds": 0.5, "time_mode": "preserve"}` |
| `GET /api/ingestion/runs` | Replay/simulator runs |
| `POST /api/ingestion/simulator` (+ `/{id}`, `/{id}/respond`, `/{id}/login`, `/{id}/stop`) | Interactive victim simulator |
| `POST /api/ingestion/idp/step-up`, `/idp/alt-factor`; `GET /idp/challenges`; `POST /idp/challenges/{id}/resolve` | Mock IdP |
| `GET /api/features/baselines/{user}` | A user's EWMA baseline and open session |
| `GET /api/detection/alerts`, `/alerts/{id}`, `PATCH /alerts/{id}`, `/alerts/{id}/cef` | Alerts and their evidence |
| `GET /api/detection/scores/recent`, `/stats`, `/operating-point`, `/eval/results`, `/dead-letters` | Live feed, KPIs, the running operating point, offline results, the DLQ |
| `GET /api/mitigation/actions`, `/state/{user}`; `POST /feedback` | Mitigation history and controller state |

A replay from the command line:

```bash
curl -s 'localhost:3000/api/ingestion/scenarios?profile=low_and_slow&limit=1'
curl -s -X POST localhost:3000/api/ingestion/scenarios/replay -H 'content-type: application/json' \
     -d '{"burst_id":"<burst_id from above>","pace_seconds":0.3}'
curl -s localhost:3000/api/detection/alerts
```

## Tests

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q --ignore=tests/integration   # unit + Testcontainers tests (Docker required)
python -m pytest -q tests/integration            # DESTRUCTIVE: brings the compose stack up and down -v
cd services/dashboard && npm ci && npx vitest run
```

## Rebuilding the benchmark, models and results (offline)

```bash
make pipeline   # data -> generate -> baselines -> train -> tune -> ablation -> adversarial -> report -> demo slice
```

`make data` fetches the RBA dataset from Zenodo (about 1.1 GB, MD5-verified) and has **no synthetic fallback**: if the fetch fails it stops. Training writes `model_registry/` (`stage_b.json`, `stage_b_calibrator.pkl`, `stage_c.pt`/`.npz`, `operating_point.json`). The live scorer refuses to start without them. Rebuild the images afterwards (`config-everything`).

## Known issues and limits

- The benchmark's attacks are synthetic overlays on real benign RBA logins. Latency parameters come from published human-subjects measurements, and the benign denial rate is an assumption (see DECISIONS.md).
- Low-and-slow attacks are generated *without* within-episode fatigue drift, so `latency_drift_slope` carries no signal for that profile by construction. See the ablation result in `final_report.md`.
- The mitigation controller's per-user state is in memory and resets when the service restarts. `run` always starts fresh anyway.
- Only the replay and simulator adapters exist; Entra ID, Okta and Duo are future work. The IdP is a mock.
- `tests/integration/test_compose_health.py` is destructive to a running stack (it tears down with `--volumes`).
