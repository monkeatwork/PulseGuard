# PulseGuard — behaviour-aware MFA fatigue detection

PulseGuard detects **MFA fatigue attacks** (MITRE ATT&CK **T1621**) while they are happening. In this attack, someone who already has the password floods the victim with push prompts until one gets approved. PulseGuard reads the **user's reaction** rather than just counting prompts: a fatigued user's decision latency collapses into reflexive taps, while a legitimate user's stays steady. Every approve/deny is scored the moment it arrives. When the score crosses the evaluated threshold, PulseGuard forces a number-matching step-up **before** the capitulation approval can open a session.

University project for BCSE410L Cyber Security, VIT (SCOPE). The full specification is [`CLAUDE.md`](CLAUDE.md), every design decision is logged in [`pulseguard/DECISIONS.md`](pulseguard/DECISIONS.md), and the offline results are in [`pulseguard/eval/results/final_report.md`](pulseguard/eval/results/final_report.md).

---

## Run it (Windows, macOS or Linux)

You need only **Docker Desktop** (with Docker Compose v2, which it includes) and **Git**. Give Docker at least **1.5 GB of memory** (Docker Desktop → Settings → Resources). The whole stack uses about 0.7–0.9 GB.

```powershell
git clone <this repository>
cd PulseGuard

.\config-everything     # once: checks Docker, writes config, pulls + builds images, self-test
.\run                   # starts everything from a clean slate and opens http://localhost:3000
.\stop                  # stops and removes every PulseGuard container, network and volume
```

On macOS/Linux, use `./config-everything.sh`, `./run.sh` and `./stop.sh`.

| Command | What it does |
|---|---|
| `config-everything` | Checks that Docker is installed, running and has enough memory. Creates `pulseguard/.env` from `.env.example`. Checks that the trained models and demo corpus are present. Pulls Postgres/Redis/Kafka and builds the five PulseGuard images. Runs a self-test that loads the detector's evaluated operating point. Safe to re-run. |
| `run` | Removes any previous run, including its data, so every run starts fresh. Starts the stack, waits for every health check and opens the dashboard. A cold start takes about 15 s once the images are built. |
| `stop` | `docker compose down --volumes --remove-orphans` and confirms nothing is left. Built images are kept, so the next `run` is fast. |

No accounts, keys or cloud services are needed. Everything runs locally in Docker, and the trained models plus a demo corpus ship with the repository.

If port 3000 is taken, set `PULSEGUARD_PORT=3100` (any free port) in `pulseguard/.env` and run again.

## What you will see (demo walkthrough)

1. **Overview** (`http://localhost:3000`): KPIs, the live L1–L5 pipeline, a live feed of every scored decision and the latest alerts.
2. **Attack Lab → Scenario replay:** pick a profile and press **Replay**.
   - *High-volume burst*, *Low-and-slow* and *Social-engineering assisted* are attacks.
   - *Benign power user* and *Benign occasional denial* are the hard negatives that must not alert.
   - The run watcher shows the fused score climbing at each decision, and the decision-latency chart shows the collapse.
   - The episodes are held-out test-split users; their ground-truth label is shown to you but never reaches the detector.
3. **Alerts:** open an alert to see the full evidence:
   - the latency trajectory with the feature engine's own drift-slope line;
   - the score at every decision against the threshold;
   - the top-3 reasons, labelled with the stage that produced them;
   - how the three stages combine at the operating point;
   - both feature families, the mitigation/IdP timeline and the user's baseline.

   You can also acknowledge or resolve the alert, or export it as CEF.
4. **Attack Lab → Be the victim:** press **Start**. An attacker pushes prompts to the phone on screen. Deny the first few carefully, then start tapping faster, the way a worn-down user does. Your real reaction times flow through Kafka, the feature engine and the detector. When PulseGuard intervenes, push approvals are suspended and a number-matching challenge appears that the attacker cannot answer. Choose **I log in myself** for the negative control.
5. **Evaluation:** PulseGuard against the Splunk and Elastic industry rules on the same by-user test split, with false-positive rate shown next to recall. It also covers per-profile recall, the ablation (including the **NO MEASURABLE LIFT** banner if it fires), the adversarial evaluation and the anti-DoS invariant. Every number is read from `eval/results/*.json`.
6. **How it works:** the core insight, the five layers with live status, the three detection stages and the escalation ladder that never locks a user out.

## Architecture in one paragraph

**L1** telemetry adapters (benchmark replay, interactive simulator) → **L2** FastAPI ingestion producing canonical events to **Kafka**, keyed by user → **L3** a Faust feature engine that keeps each user's open session in **Redis** and featurises the session-so-far on every decision (frequency + response-behaviour features, per-user EWMA baselines) → **L4** the detection engine fuses Stage A (statistical deviation), Stage B (XGBoost, isotonic-calibrated) and Stage C (GRU over the sequence) at the validation-tuned operating point, in about 1–2 ms per decision, and writes to **PostgreSQL/TimescaleDB** → **L5** a mitigation controller forces step-up through the identity provider with a cooldown and an escalation ceiling (never a lockout), plus the SOC dashboard.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Docker is installed but not running` | Start Docker Desktop and wait for "Engine running". |
| A service is `unhealthy` or keeps restarting | Check that Docker has ≥ 1.5 GB of memory, then `.\run` again. Logs: `docker compose -f pulseguard/docker-compose.yml logs <service>`. |
| Port 3000 in use | Set `PULSEGUARD_PORT` in `pulseguard/.env`. |
| Windows says scripts are disabled | Use `.\run` (the `.cmd` launcher), not `.\scripts\windows\run.ps1`. The launcher bypasses the execution policy for that one call only. |
| First `config-everything` is slow | It downloads about 1 GB of base images once; later runs reuse them. |

## Licence and data

Benign behaviour comes from the Wiefling et al. **RBA dataset** (Zenodo [10.5281/zenodo.6782156](https://doi.org/10.5281/zenodo.6782156), CC BY 4.0). The shipped demo corpus `pulseguard/data/demo/demo_events.parquet` is a small derived slice of it, with seeded synthetic attack overlays.
