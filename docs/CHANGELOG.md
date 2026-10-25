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
