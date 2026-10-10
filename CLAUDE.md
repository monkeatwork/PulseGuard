# CLAUDE.md — PulseGuard

## What this project is

PulseGuard is a behaviour-aware detector for **MFA fatigue attacks** (MITRE ATT&CK **T1621**, Multi-Factor Authentication Request Generation). It is a university project for BCSE410L Cyber Security at VIT (SCOPE).

An attacker who already holds a valid password floods a user with MFA push prompts until one is approved. No cryptography is broken — the target is human habituation. PulseGuard detects the attack while it is in progress and forces a step-up challenge **before** the capitulation approval can grant a session.

## The core insight (this is the whole point of the project)

Every deployed defence either **changes the prompt** (number matching, verified push) or **counts the prompts** (SIEM threshold rules). None of them reads the **user's reaction**.

A fatigued human's decision latency **collapses** across a prompt burst as deliberation degrades into a reflexive tap. A legitimate user's decision latency is **stationary**. A fatigued approval and a genuine approval are cryptographically identical — the latency trajectory is the only evidence that separates them.

If a design decision would weaken or bypass response-behaviour modelling, that decision is wrong. The response-behaviour feature family is the contribution; everything else is supporting infrastructure.

## Research gap being filled

No peer-reviewed work in a credible venue detects MFA fatigue by jointly modelling request frequency **and** user response behaviour with reported precision, recall and false-positive rate. Academic work splits into prevention-by-redesign and generic risk-based authentication that scores logins independently. Industry detection is fixed-threshold SIEM correlation applied uniformly to every user in a tenant. No labelled dataset exists.

## Feature families

### Frequency features
`prompts_per_window`, `inter_prompt_mean`, `inter_prompt_std`, `burst_duration`, `off_hours_flag`, `geo_novelty`, `device_novelty`, `impossible_travel`

### Response-behaviour features (the contribution)
| Feature | Definition |
|---|---|
| `deny_run_length` | Consecutive denials before any approval |
| `capitulation_flag` | The deny → deny → … → approve signature |
| `approval_latency_z` | Approval latency scored against that user's own historical distribution |
| `latency_drift_slope` | **Linear regression slope over decision latencies within one burst.** Strongly negative only under fatigue. The single most important feature in the system. |
| `post_burst_approval_gap` | Interval between the final denial and the eventual approval |
| `denial_latency_variance` | Spread of denial response times within the burst |

## Architecture — five layers

- **L1 Telemetry** — Entra ID sign-in logs, Okta System Log, Duo Admin API, Keycloak (prototype), benchmark replay. All behind one adapter interface.
- **L2 Ingestion** — FastAPI collectors → Kafka. Canonical event: `{user_id, ts, event_type, decision, decision_latency_ms, src_ip, geo, device_id, user_agent, session_id}`
- **L3 Feature Engine** — stream windowing; computes both feature families. Per-user baseline store (EWMA prompt rate + latency distribution) in Redis, cohort fallback during cold start (< 30 events).
- **L4 Detection Engine** — Stage A per-user statistical deviation; Stage B XGBoost over the full feature vector; Stage C GRU over the event sequence (catches low-and-slow). Weighted fusion, isotonic calibration, SHAP top-3 reasons per alert.
- **L5 Response** — mitigation controller (suppress blind-approve → force step-up webhook, with cooldown and escalation ceiling to prevent self-inflicted DoS); React SOC dashboard; syslog/CEF egress.

## Technology stack — Python end to end

Python 3.12 · FastAPI · Apache Kafka + Faust · River (incremental EWMA baselines, drift detection) · Redis · PostgreSQL + TimescaleDB · XGBoost + scikit-learn · PyTorch (GRU) · SHAP · React + Recharts · Keycloak (test IdP) · Docker Compose · pytest + Testcontainers.

An all-Python pipeline is deliberate: it removes the cross-language serialisation hop between feature computation and inference. The model loads in-process inside FastAPI so end-to-end scoring stays inside a single-digit-millisecond budget, which in-band mitigation requires.

## Data

No public labelled MFA-fatigue dataset exists. The project builds one as a contributed artifact:

- **Base:** the Wiefling RBA dataset — 3.3M users, 31.3M login attempts (Kaggle `dasgroup/rba-dataset`, Zenodo 10.5281/zenodo.6782156). Provides realistic benign login behaviour but contains no push-flood events and no approve/deny records.
- **Overlay:** a parameterised generator producing labelled push-flood streams with approve/deny decisions and response latencies.
- **Three attack profiles:** high-volume burst; low-and-slow (paced below any fixed threshold); social-engineering-assisted (a lure mid-burst that shortens latency).
- **Hard negatives:** benign high-activity users who legitimately authenticate many times per day. These are what make the false-positive metric meaningful.
- Latency distributions are parameterised from published human-subjects measurements, not invented. The generator must be reproducible from a seed.

## Evaluation rules — non-negotiable

1. **Split train/test BY USER, never by event.** Event-level splits leak per-user baseline state across the split and inflate every metric. This is the first thing a reviewer checks.
2. **Reproduce the industry baselines first and record their numbers.** Splunk: >9 prompts in 10 minutes. Elastic: two denials followed by a success within 10 minutes. Every later claim is measured against these.
3. **False-positive rate is a primary reported metric**, not an afterthought.
4. **Run the ablation:** frequency-only vs frequency + response-behaviour, and with `latency_drift_slope` individually removed. Report the result honestly either way — a negative result reported clearly is worth more than an inflated one.
5. **Adversarial evaluation is required:** 1 prompt / 5 min pacing, and an attacker who deliberately mimics the target's own baseline rhythm.
6. **Anti-DoS check:** the escalation ceiling must never lock out the legitimate user under sustained attack.

## Scope boundaries

**In scope:** detection of push-based MFA fatigue; per-user adaptive baselining; in-band step-up mitigation; the benchmark generator; a SOC dashboard with explanations.

**Out of scope:** replacing FIDO2/passkeys (that is the correct end state — PulseGuard defends the legacy and fallback push paths that remain live during migration); general account-takeover detection; phishing or AiTM detection; production-grade multi-tenancy.

**Established components, used deliberately:** request-frequency detection, geo/device context and per-user baselining are standard UEBA building blocks, chosen because they are proven. The contribution is the response-behaviour dimension, the fusion, and the benchmark — not the idea of anomaly detection.

## Working conventions

- Everything runs from `docker compose up` with no manual setup steps.
- The benchmark generator is seeded and deterministic.
- Any design decision made autonomously gets one line in `DECISIONS.md`: what was decided, what alternative was rejected, and why.
- Feature computation is pure and unit-testable in isolation from the stream.
- Edge cases that must be handled explicitly in `latency_drift_slope`: single-event bursts, missing latency values, clock skew, out-of-order event arrival.