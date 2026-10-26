# Changelog

One entry per working iteration: what changed, why, files touched, known issues, next step.

## 2026-10-26 — Iteration 1: reproduce the committed results (HANDOFF.md task 0)

**What changed**
- Ran the full offline pipeline (`make generate baselines train evaluate report SEED=42`) from a fresh clone and compared every number with the committed `eval/results/*.json`.
- 49 of 50 headline numbers match exactly; the one difference is Stage C's validation-chosen threshold (0.76 vs 0.74) with identical test metrics.
- Fixed two macOS-only crashes: torch and xgboost each ship an OpenMP runtime, which segfaulted or deadlocked depending on import order.

**Why:** HANDOFF.md says to treat every reported number as untrusted until reproduced. They reproduce, but reproducible is not trustworthy: the latency signal is written into the generator. That is what the next iterations test.

**Files touched**
- `pulseguard/services/detection_engine/app/__init__.py` (OpenMP load order)
- `pulseguard/eval/adversarial/run_adversarial_eval.py` (unused torch import removed)
- `pulseguard/eval/research/reproduction.py` (new), `pulseguard/eval/results/REPRODUCTION.md` (new)
- `pulseguard/DECISIONS.md`, `.gitignore`, `HANDOFF.md`, `docs/CHANGELOG.md`

**Known issues**
- 28 tests need Docker (testcontainers) and were not run; Docker was not running. 235 other tests pass.
- The `events.parquet` SHA-256 differs from the one in `operating_point.json` because pyarrow 26 writes different file metadata; the content is identical (checked through the demo slice).

**Next step:** task 1, the fatigue-strength sweep.

## 2026-10-26 — Iteration 2: fatigue parameter, research tooling, detection before capitulation (tasks 1-2 tooling, task 2 results)

**What changed**
- Generator: fatigue strength, shape, null model, DuoLungo-fitted benign latency and per-victim heterogeneity are now parameters (`FatigueConfig`). Defaults reproduce the original corpus byte for byte (golden-hash test).
- `eval/research/`: train-once/score-anywhere suite, fatigue sweep with train/test strength grid, detection before capitulation, adaptive attacker, robustness to the assumed fatigue model, Isolation Forest and logistic-regression baselines, report sections appended by `make report`, `make research`.
- New baseline in every experiment: a one-line rule that fires on two consecutive denials.
- `eval/results/before_capitulation.json` (seed 42, default corpus): PulseGuard fires before the approving tap in 99.2% of capitulating test attacks, at a median of 2 prompts with 7 to spare; Splunk 32.4% (median 10 prompts); Elastic 0% by construction (its rule needs the approval).

**Why:** HANDOFF.md tasks 1-4 need corpora at several fatigue strengths and models scored across corpora without touching the deployed model registry.

**Files touched:** `pulseguard/benchmark/generator/{latency_models,attack_profiles,cli}.py`, `pulseguard/benchmark/tests/*`, `pulseguard/eval/research/*` (new), `pulseguard/eval/tests/test_research_experiments.py` (new), `pulseguard/eval/results/before_capitulation.json`, `pulseguard/Makefile`, `pulseguard/README.md`, `pulseguard/requirements-dev.txt`, `pulseguard/DECISIONS.md`.

**Known issues**
- **The benchmark is separable by decision sequence alone.** No benign episode in the seed-42 corpus has two consecutive denials (0 of 10,012), while 99.2% of attack episodes do. `deny_run_length` carries 84% of the deployed Stage B model's total gain, `latency_drift_slope` about 0%. The deny-run rule baseline is reported everywhere so this stays visible.
- Early sweep results (seed 42): with the matched null at s = 0 (no latency signal at all) PulseGuard still reaches recall 0.994 at FPR 0.002, so latency contributes little on this benchmark.

**Next step:** finish the 5-seed sweep, the legacy sweep, the adaptive attacker and the robustness runs; regenerate the report.

## 2026-10-26 — Iteration 3: adaptive attacker results (task 3); opt-in benign deny runs

**What changed**
- `eval/results/adaptive_attacker.json/.png`: 72 settings (9 gaps x usual hours on/off x lure on/off x 2 victim models), 400 test-split victims each. PulseGuard keeps recall >= 0.985 up to 1-hour gaps without a lure, then drops to 0 at 2 h and beyond: once the gap passes the 60-minute session boundary every prompt is its own session. Elastic is at 0 from 10-minute gaps, Splunk from 2 minutes. The windowless two-denials rule stays at 1.0 at every gap. The anti-lockout invariant holds at all 72 settings.
- Generator: opt-in `--benign-deny-run-rate r` (`HardNegativeConfig`): a share r of benign high-activity logins is preceded by 2-4 denied prompts. Default 0 keeps the corpus unchanged (golden hash). A small-scale check at r = 0.1 gives the two-denials rule and Elastic FPR 0.38 while PulseGuard stays at 0.03.
- Report section for the hard-negative sweep.

**Why:** task 3, and removing the "two denials" shortcut so the benchmark can measure whether response latency adds anything.

**Files touched:** `pulseguard/eval/results/adaptive_attacker.{json,png}`, `pulseguard/eval/research/{adaptive_attacker,fatigue_sweep,corpora,report}.py`, `pulseguard/benchmark/generator/{attack_profiles,cli}.py`, `pulseguard/benchmark/tests/test_generator_determinism.py`, `pulseguard/DECISIONS.md`.

**Known issues**
- Session-level scoring has a hard horizon: an attacker pacing prompts more than an hour apart is invisible to PulseGuard. A cross-session deny counter (per user, over days) is the obvious fix and is not built.
- The benign deny-run rate is an assumption; it is swept, not measured.

**Next step:** 5-seed sweep, legacy sweep, robustness and hard-negative sweeps (queued), then the report.

## 2026-10-26 — Iteration 4: 5-seed sweep, robustness, hard negatives, reframed report (tasks 1, 4, 5)

**What changed**
- `fatigue_sweep.json/.png`: matched-null sweep over s in {0, .25, .5, .75, 1}, 5 seeds, 95% CIs, with a train/test strength grid. PulseGuard recall 0.995 at s = 0 and 0.999 at s = 1 (FPR 0.0015 / 0.0012), vs Elastic 0.618 and Splunk 0.316. Every grid cell is between 0.995 and 0.999.
- `fatigue_sweep_legacy.json/.png`: HANDOFF's original formula, seed 42, for comparison. The results are the same.
- `robustness.json`: a model trained on the linear s = 1 collapse, tested on exponential and step shapes, heterogeneous victims and DuoLungo benign latency. Recall stays at or above 0.994 and FPR at 0.0013, so retraining isn't needed.
- `hard_negatives_r{0.01,0.03,0.1}.json`: with benign deny runs, the two-denials rule and Elastic FPR rise to 0.10, 0.23 and 0.42; PulseGuard stays at 0.006-0.037. At r = 0.1, the latency collapse reduces PulseGuard FPR from 0.037 (s = 0) to 0.010 (s = 1). This is the first setting where latency measurably helps.
- `final_report.md`: new "What these results support" section, computed from the result files (task 5 reframing). Response behaviour cuts FPRs, and the decision sequence does the work. `latency_drift_slope` and the latency collapse are presented as a hypothesis. The legacy-sweep text no longer describes s = 0 as signal-free.

**Why:** HANDOFF tasks 1, 4 and 5, plus additions A-F.

**Files touched:** `pulseguard/eval/research/report.py`, `pulseguard/eval/results/{final_report.md,fatigue_sweep*.{json,png},robustness.json,hard_negatives_r*.json}`, `docs/CHANGELOG.md`.

**Known issues**
- The robustness and hard-negative runs use one seed. The r = 0.1 latency effect needs confirming across seeds.
- Pacing beyond the 60-minute session gap evades PulseGuard (iteration 3); no cross-session counter yet.
- The latency model is still synthetic; no user study.

**Next step:** benchmark release bundle (addition G: datasheet, corpus hash, license, Zenodo metadata); cross-session denial counter.

## 2026-10-26 — Iteration 5: cross-session guard, 5-seed hard negatives, release bundle, plain-language explainer

**What changed**
- `docs/HOW_IT_WORKS.md`: plain-language explanation of what PulseGuard is (a trained model), why it scores 99% (it learned that two denials in a row mark an attack), and where reaction speed helps.
- `services/detection_engine/app/cross_session_guard.py`: a per-user counter of unresolved denials (no approval within 10 min) that spans sessions. K = 3 within 7 days, chosen on validation users. `eval/research/cross_session.py` evaluates it with stray benign denials injected at p in {0, 0.02, 0.1, 0.3} per active day.
  - For attackers pacing prompts 2-4 h apart, PulseGuard alone catches 0. PulseGuard OR guard catches 1.00 without a lure and 0.75 with one.
  - Users never attacked who get flagged: at most 0.002.
  - Anti-lockout holds at all 72 settings.
- `hard_negatives_r0.1.json` now covers 5 seeds. PulseGuard FPR is 0.039 [0.031, 0.047] at s = 0 and 0.008 [0.002, 0.015] at s = 1. That confirms the one setting where the latency signal lowers false positives.
- `benchmark/release/` and `make release`: Zenodo-ready bundle with corpus, by-user split, datasheet, CC BY 4.0 data license with attribution, CITATION.cff, .zenodo.json, SHA256SUMS and content hash, plus `--verify`.
- Report: cross-session section; claims 4 and 5 are now computed from the result files.

**Why:** the next steps from iteration 4: confirm the latency effect across seeds, close the slow-pacing evasion, and addition G.

**Files touched:** `docs/{HOW_IT_WORKS,CHANGELOG}.md`, `pulseguard/services/detection_engine/{app/cross_session_guard.py,tests/test_cross_session_guard.py}`, `pulseguard/eval/research/{cross_session,adaptive_attacker,report}.py`, `pulseguard/eval/tests/test_research_experiments.py`, `pulseguard/benchmark/release/*`, `pulseguard/benchmark/tests/test_release_bundle.py`, `pulseguard/eval/results/{cross_session.{json,png},hard_negatives_r0.1.json,final_report.md}`, `pulseguard/{Makefile,README.md,DECISIONS.md,.gitignore}`.

**Known issues**
- The guard isn't wired into the live scorer: it needs a per-user Redis store, and the Docker integration tests can't run here.
- The guard's low FPR depends on benign denials being retried. The generator always retries them, so the stray rate p is an assumption. It is swept, not measured.
- A lure that ends the attack after 1-2 denials still gets through the guard (K = 3).
- The release bundle's author list is a placeholder, and no code license has been chosen.

**Next step:** wire the guard into the live scorer (Redis-backed history), fill in the release authors and upload to Zenodo, and plan a user study for the latency hypothesis.

## 2026-10-26 — Iteration 6: cross-session guard in the live service

**What changed**
- The cross-session guard now runs in the live detection engine. `services/detection_engine/app/cross_session_store.py` keeps each user's recent denials and approvals in Redis (sorted sets keyed by event id, trimmed by event time). The live handler ORs the guard with the fused score, as the evaluation does.
- `model_registry/cross_session_guard.json` (`make guard-config`) holds K = 3, window 7 days, resolve 10 min, with provenance from `eval/results/cross_session.json` (selected on validation users). The service refuses to start without it.
- `scores` and `alerts` record `guard_unresolved_denials` and `guard_fired`. A guard alert's explanation is the unresolved-denial count, and the dashboard labels it.
- The mitigation worker lets guard alerts past the fused-score gate (0.3): a slow attack's sessions look benign one at a time. `/operating-point` reports the guard config.
- Tests:
  - Redis store matches the pure guard on a random stream; redelivery doesn't double-count; trimming; config must be selected on val.
  - Handler raises a slow attack the model scores as benign (real Postgres + Redis).
  - Mitigation gate.
  - End to end: a slow attack (prompts 2 h apart) produced to Kafka is alerted by the guard and stepped up by the mock IdP.
- The full suite, including the Docker tests, now runs: 315 passed.

**Why:** iteration 5 left the guard offline-only because Docker wasn't available. With Docker installed, it can be wired and tested in the running stack.

**Files touched:** `pulseguard/services/detection_engine/app/{cross_session_store,cross_session_guard,live_scorer,main}.py`, `pulseguard/services/detection_engine/app/model_registry/cross_session_guard.json`, `pulseguard/services/detection_engine/{pyproject.toml,tests/test_cross_session_store.py,tests/test_live_scorer.py}`, `pulseguard/services/mitigation/{app/live_worker.py,tests/test_controller.py}`, `pulseguard/services/dashboard/src/{lib/features.js,charts/Reasons.jsx}`, `pulseguard/common/pulseguard_common/{redis_keys.py,db/models.py}`, `pulseguard/infra/postgres/init.sql`, `pulseguard/docker-compose.yml`, `pulseguard/tests/integration/test_compose_health.py`, `pulseguard/{Makefile,README.md,DECISIONS.md}`, `docs/{HOW_IT_WORKS,CHANGELOG}.md`.

**Known issues**
- Once the guard fires for a user, each of their later sessions in the 7-day window is alerted until the denials age out. These are step-ups, not lockouts.
- A decision that arrives more than a session gap late isn't sent by the feature engine, so the guard never counts it.
- `test_live_scorer.py` segfaults when run on its own on macOS (torch/xgboost OpenMP clash). This is pre-existing and unrelated to this change; it passes inside the full suite.
- The latency model is still synthetic; the release authors and code license are still open.

**Next step:** fill in the release authors and choose a code license, upload the bundle to Zenodo, and plan a user study for the latency hypothesis.
