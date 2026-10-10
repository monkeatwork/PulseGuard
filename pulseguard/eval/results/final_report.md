# PulseGuard — Final Evaluation Report

_Generated entirely from `eval/results/*.json` — see DECISIONS.md for the full narrative, methodology notes, and honestly-reported limitations behind every number here._

## Headline detector comparison (frozen test split)

| Detector | Precision | Recall | FPR | N evaluated |
|---|---|---|---|---|
| Splunk (>9/10min) | 1.000 | 0.336 | 0.000 | 3859 |
| Elastic (2 deny+success/10min) | 1.000 | 0.623 | 0.000 | 3859 |
| Stage A+B (fragment-level) | 0.806 | 0.936 | 0.088 | 31269 |
| Stage C (sequence-level) | 1.000 | 1.000 | 0.000 | 3859 |
| Full fusion (A+B+C) | 1.000 | 1.000 | 0.000 | 3859 |

## Ablation: frequency-only vs +response-behaviour vs -latency_drift_slope

| Variant | Features | Recall | Precision | FPR |
|---|---|---|---|---|
| frequency_only | 9 | 0.888 | 0.329 | 0.703 |
| frequency_plus_response_behaviour | 19 | 0.926 | 0.915 | 0.033 |
| response_behaviour_minus_latency_drift_slope | 17 | 0.926 | 0.915 | 0.033 |

Response-behaviour lift: **3.8 percentage points** (above the 2.0-point noise floor).
latency_drift_slope lift: **0.0 percentage points**.

> **NO MEASURABLE LIFT:** `latency_drift_slope` did not improve recall beyond the noise floor on this benchmark. See DECISIONS.md for the full investigation and why this is a structural, understood result rather than an unexplained gap.

## Adversarial evaluation (1-prompt/5-min pacing, mimicry attacker)

| Detector | Mimicry recall | Slow-pacing recall |
|---|---|---|
| splunk | 0.025 | 0.000 |
| elastic | 0.110 | 0.000 |
| Stage A+B | 0.928 | 0.921 |
| Stage C | 1.000 | 1.000 |

Anti-DoS invariant under mimicry pacing: **HOLDS**.