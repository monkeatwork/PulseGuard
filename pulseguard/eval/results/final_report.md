# PulseGuard — Final Evaluation Report

_Generated entirely from `eval/results/*.json` — see DECISIONS.md for the full narrative, methodology notes, and honestly-reported limitations behind every number here._

## Headline detector comparison (frozen test split)

| Detector | Precision | Recall | FPR | N evaluated |
|---|---|---|---|---|
| Splunk (>9/10min) | 1.000 | 0.337 | 0.000 | 3859 |
| Elastic (2 deny+success/10min) | 0.997 | 0.610 | 0.003 | 3859 |
| Stage A+B | 0.705 | 1.000 | 0.633 | 3859 |
|   Stage A alone | 0.696 | 0.960 | 0.633 | 3859 |
|   Stage B alone | 1.000 | 0.999 | 0.001 | 3859 |
| Stage C (GRU) | 1.000 | 0.993 | 0.001 | 3859 |
| Full fusion (A+B+C) | 0.999 | 1.000 | 0.001 | 3859 |

Operating point (tuned on the validation split, loaded by the live scorer): weights A=0.10 / B=0.85 / C=0.05, threshold 0.67.
Unit: episode (positive if any decision point crosses the threshold).

## Ablation: frequency-only vs +response-behaviour vs -latency_drift_slope

| Variant | Features | Recall | Precision | FPR |
|---|---|---|---|---|
| frequency_only | 9 | 0.991 | 0.956 | 0.069 |
| frequency_plus_response_behaviour | 19 | 0.999 | 1.000 | 0.001 |
| response_behaviour_minus_latency_drift_slope | 17 | 1.000 | 0.999 | 0.001 |

Response-behaviour lift: **0.8 percentage points** (below the 2.0-point noise floor).
latency_drift_slope lift: **-0.1 percentage points**.

Supplementary deltas (full minus ablated variant; reported alongside the recall lift, never instead of it): response-behaviour F1 +0.026, FPR -0.068, average precision +0.002; latency_drift_slope F1 -0.000, FPR -0.001, average precision -0.000.

> **NO MEASURABLE LIFT:** `latency_drift_slope` did not improve recall beyond the noise floor on this benchmark. See DECISIONS.md for the full investigation and why this is a structural, understood result rather than an unexplained gap.

## Adversarial evaluation (1-prompt/5-min pacing, mimicry attacker)

| Detector | Mimicry recall | Slow-pacing recall |
|---|---|---|
| splunk | 0.025 | 0.000 |
| elastic | 0.110 | 0.000 |
| Stage A+B | 0.935 | 1.000 |
| Stage C | 0.935 | 1.000 |
| Full fusion | 0.935 | 1.000 |

Anti-DoS invariant under mimicry pacing: **HOLDS**.
