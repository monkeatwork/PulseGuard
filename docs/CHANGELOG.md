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
