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

# Research extensions (HANDOFF.md tasks 1-4)

## What these results support

1. **Against the industry rules, PulseGuard detects far more attacks at a comparable false-positive rate.** At s = 1: recall 0.999 (FPR 0.0012) vs Elastic 0.618 and Splunk 0.316, mean of 5 seeds.
2. **Response behaviour cuts false positives.** Frequency features alone: FPR 0.066; with the response-behaviour family: 0.0012. The work is done by the decision sequence (consecutive denials): on this benchmark a one-line two-denials rule (recall 0.995, FPR 0.0000) and a logistic regression (recall 0.995) match it.
3. **`latency_drift_slope` and the latency collapse are a hypothesis, not a measured contribution.** Removing every latency difference between attack and benign (s = 0, matched null) moves PulseGuard recall from 0.999 to 0.995. Whether real fatigued users collapse their latency, and by how much, needs a user study; the sweep shows the detector does not depend on it.
4. **Latency becomes useful when denials stop being free evidence.** If 10% of benign high-activity logins follow a run of denials, the two-denials rule's FPR rises to 0.424, while PulseGuard's FPR is 0.0387 [0.0308, 0.0465] without a latency signal and 0.0084 [0.0023, 0.0145] with the full collapse (5 seeds, 95% CI). This is the one setting where the response-latency signal measurably lowers false positives; whether real fatigued users show that latency collapse still needs a user study.
5. **Slow pacing is partly closed.** Against attackers pacing prompts 2-4 h apart, PulseGuard alone catches 0.00 of attacks (victim with no latency change); PulseGuard OR the cross-session guard (K=3, window=7d) catches 1.00 without a lure and 0.75 with one (usual-hours timing on and off), at a benign FPR on never-attacked users of 0.0020 with stray denials at p = 0.3. The lure is what still gets through: it ends the attack after the first denials, before K unresolved denials accumulate.

## Fatigue-strength sweep

Corpus regenerated, every model retrained and evaluated at each fatigue strength s (null model **matched**, shape linear, 50,000 users, seeds 42, 1, 2, 3, 4). s = 0: attack latencies drawn from exactly the benign distributions; s = 1: the full collapse to a 0.74 s median. Cells: mean across seeds [95% CI]. Test split, by user. Figure: `fatigue_sweep.png`.

**Recall**

| Detector | s = 0 | s = 0.25 | s = 0.5 | s = 0.75 | s = 1 |
|---|---|---|---|---|---|
| Splunk (>9 / 10 min) | 0.314 [0.295, 0.332] | 0.315 [0.296, 0.334] | 0.315 [0.297, 0.334] | 0.316 [0.297, 0.334] | 0.316 [0.298, 0.334] |
| Elastic (2 deny + approve) | 0.618 [0.604, 0.633] | 0.618 [0.604, 0.633] | 0.618 [0.604, 0.633] | 0.618 [0.604, 0.633] | 0.618 [0.604, 0.633] |
| 2 consecutive denials (one-line rule) | 0.995 [0.993, 0.996] | 0.995 [0.993, 0.996] | 0.995 [0.993, 0.996] | 0.995 [0.993, 0.996] | 0.995 [0.993, 0.996] |
| Isolation Forest | 0.962 [0.944, 0.980] | 0.962 [0.944, 0.980] | 0.962 [0.944, 0.980] | 0.962 [0.944, 0.980] | 0.962 [0.944, 0.980] |
| Logistic regression | 0.995 [0.993, 0.996] | 0.995 [0.993, 0.996] | 0.995 [0.993, 0.996] | 0.995 [0.993, 0.996] | 0.995 [0.993, 0.996] |
| PulseGuard, frequency features only | 0.991 [0.990, 0.993] | 0.991 [0.989, 0.993] | 0.990 [0.986, 0.994] | 0.992 [0.990, 0.993] | 0.992 [0.990, 0.993] |
| Stage C (GRU) | 0.995 [0.993, 0.996] | 0.995 [0.993, 0.996] | 0.995 [0.993, 0.996] | 0.995 [0.993, 0.996] | 0.995 [0.994, 0.996] |
| PulseGuard, full fusion | 0.995 [0.994, 0.997] | 0.995 [0.994, 0.996] | 0.996 [0.994, 0.997] | 0.998 [0.997, 0.999] | 0.999 [0.999, 1.000] |

**False-positive rate**

| Detector | s = 0 | s = 0.25 | s = 0.5 | s = 0.75 | s = 1 |
|---|---|---|---|---|---|
| Splunk (>9 / 10 min) | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |
| Elastic (2 deny + approve) | 0.002 [0.001, 0.003] | 0.002 [0.001, 0.003] | 0.002 [0.001, 0.003] | 0.002 [0.001, 0.003] | 0.002 [0.001, 0.003] |
| 2 consecutive denials (one-line rule) | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |
| Isolation Forest | 0.153 [0.104, 0.201] | 0.153 [0.104, 0.201] | 0.153 [0.104, 0.201] | 0.153 [0.104, 0.201] | 0.153 [0.104, 0.201] |
| Logistic regression | 0.000 [0.000, 0.001] | 0.000 [0.000, 0.001] | 0.000 [0.000, 0.001] | 0.000 [0.000, 0.001] | 0.000 [0.000, 0.001] |
| PulseGuard, frequency features only | 0.065 [0.058, 0.071] | 0.065 [0.059, 0.071] | 0.064 [0.055, 0.073] | 0.065 [0.060, 0.070] | 0.066 [0.061, 0.071] |
| Stage C (GRU) | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.001 [0.000, 0.002] |
| PulseGuard, full fusion | 0.001 [0.000, 0.003] | 0.002 [0.001, 0.004] | 0.002 [0.000, 0.004] | 0.003 [0.002, 0.004] | 0.001 [0.000, 0.003] |

**Precision**

| Detector | s = 0 | s = 0.25 | s = 0.5 | s = 0.75 | s = 1 |
|---|---|---|---|---|---|
| Splunk (>9 / 10 min) | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| Elastic (2 deny + approve) | 0.998 [0.997, 0.999] | 0.998 [0.997, 0.999] | 0.998 [0.997, 0.999] | 0.998 [0.997, 0.999] | 0.998 [0.997, 0.999] |
| 2 consecutive denials (one-line rule) | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| Isolation Forest | 0.906 [0.879, 0.933] | 0.906 [0.879, 0.933] | 0.906 [0.879, 0.933] | 0.906 [0.879, 0.933] | 0.906 [0.879, 0.933] |
| Logistic regression | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [0.999, 1.000] | 1.000 [1.000, 1.000] |
| PulseGuard, frequency features only | 0.959 [0.954, 0.963] | 0.959 [0.954, 0.963] | 0.959 [0.953, 0.965] | 0.959 [0.955, 0.962] | 0.958 [0.954, 0.962] |
| Stage C (GRU) | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 0.999 [0.998, 1.000] |
| PulseGuard, full fusion | 0.999 [0.998, 1.000] | 0.999 [0.998, 1.000] | 0.999 [0.997, 1.000] | 0.998 [0.997, 0.999] | 0.999 [0.998, 1.000] |

**Key question: at s = 0, does PulseGuard still beat the rules?** Yes, against the industry rules: recall 0.995 vs Elastic 0.618 and Splunk 0.314, with no latency signal in the data at all. But a one-line rule that fires on two consecutive denials reaches recall 0.995 at FPR 0.0000 (PulseGuard: FPR 0.0015), so the margin over the industry rules comes from the decision sequence (no benign profile in the generator ever denies twice in a row), not from learned response behaviour. 

### Trained on one strength, tested on another

PulseGuard (full fusion), each model at its own validation threshold, scored unchanged on the test users of a corpus generated at another strength. Rows: training strength; columns: test strength.

**Recall**

| train \ test | 0 | 0.25 | 0.5 | 0.75 | 1 |
|---|---|---|---|---|---|
| 0 | 0.995 | 0.995 | 0.995 | 0.995 | 0.995 |
| 0.25 | 0.995 | 0.995 | 0.995 | 0.996 | 0.996 |
| 0.5 | 0.995 | 0.995 | 0.996 | 0.997 | 0.998 |
| 0.75 | 0.995 | 0.996 | 0.997 | 0.998 | 0.999 |
| 1 | 0.995 | 0.996 | 0.996 | 0.997 | 0.999 |

**FPR**

| train \ test | 0 | 0.25 | 0.5 | 0.75 | 1 |
|---|---|---|---|---|---|
| 0 | 0.001 | 0.001 | 0.001 | 0.001 | 0.001 |
| 0.25 | 0.002 | 0.002 | 0.002 | 0.002 | 0.002 |
| 0.5 | 0.002 | 0.002 | 0.002 | 0.002 | 0.002 |
| 0.75 | 0.003 | 0.003 | 0.003 | 0.003 | 0.003 |
| 1 | 0.001 | 0.001 | 0.001 | 0.001 | 0.001 |

Lowest cell: recall 0.995 (trained at s = 0.25, tested at s = 0).

## Fatigue-strength sweep, original (legacy) formula

HANDOFF.md's literal definition: only the end point of the collapse moves with s; the attack latency spread and the 1-2 s lure stay as they were, so s = 0 still carries a latency signal. Shown for comparison with the matched sweep above.

Corpus regenerated, every model retrained and evaluated at each fatigue strength s (null model **legacy**, shape linear, 50,000 users, seed 42). s = 0: only the collapse end point is removed; the attack latency spread and the lure still differ from benign; s = 1: the full collapse to a 0.74 s median. Cells: mean across seeds [95% CI]. Test split, by user. Figure: `fatigue_sweep_legacy.png`.

**Recall**

| Detector | s = 0 | s = 0.25 | s = 0.5 | s = 0.75 | s = 1 |
|---|---|---|---|---|---|
| Splunk (>9 / 10 min) | 0.333 | 0.335 | 0.337 | 0.337 | 0.337 |
| Elastic (2 deny + approve) | 0.610 | 0.610 | 0.610 | 0.610 | 0.610 |
| 2 consecutive denials (one-line rule) | 0.993 | 0.993 | 0.993 | 0.993 | 0.993 |
| Isolation Forest | 0.941 | 0.941 | 0.941 | 0.941 | 0.941 |
| Logistic regression | 0.994 | 0.994 | 0.994 | 0.994 | 0.994 |
| PulseGuard, frequency features only | 0.991 | 0.991 | 0.991 | 0.991 | 0.991 |
| Stage C (GRU) | 0.993 | 0.993 | 0.993 | 0.993 | 0.993 |
| PulseGuard, full fusion | 0.999 | 1.000 | 1.000 | 0.999 | 1.000 |

**False-positive rate**

| Detector | s = 0 | s = 0.25 | s = 0.5 | s = 0.75 | s = 1 |
|---|---|---|---|---|---|
| Splunk (>9 / 10 min) | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| Elastic (2 deny + approve) | 0.003 | 0.003 | 0.003 | 0.003 | 0.003 |
| 2 consecutive denials (one-line rule) | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| Isolation Forest | 0.090 | 0.090 | 0.090 | 0.090 | 0.090 |
| Logistic regression | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| PulseGuard, frequency features only | 0.069 | 0.070 | 0.068 | 0.068 | 0.069 |
| Stage C (GRU) | 0.001 | 0.001 | 0.001 | 0.001 | 0.001 |
| PulseGuard, full fusion | 0.001 | 0.001 | 0.001 | 0.001 | 0.001 |

**Precision**

| Detector | s = 0 | s = 0.25 | s = 0.5 | s = 0.75 | s = 1 |
|---|---|---|---|---|---|
| Splunk (>9 / 10 min) | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| Elastic (2 deny + approve) | 0.997 | 0.997 | 0.997 | 0.997 | 0.997 |
| 2 consecutive denials (one-line rule) | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| Isolation Forest | 0.941 | 0.941 | 0.941 | 0.941 | 0.941 |
| Logistic regression | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| PulseGuard, frequency features only | 0.956 | 0.956 | 0.957 | 0.956 | 0.956 |
| Stage C (GRU) | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| PulseGuard, full fusion | 0.999 | 0.999 | 0.999 | 0.999 | 0.999 |

**Key question: at s = 0, does PulseGuard still beat the rules?** Yes, against the industry rules: recall 0.999 vs Elastic 0.610 and Splunk 0.333. But a one-line rule that fires on two consecutive denials reaches recall 0.993 at FPR 0.0000 (PulseGuard: FPR 0.0013), so the margin over the industry rules comes from the decision sequence (no benign profile in the generator ever denies twice in a row), not from learned response behaviour. 

## Detection before capitulation

Share of capitulating test attacks where the detector fired strictly before the victim's approving tap (an alert on the tap itself is too late for an in-band defence), and how many prompts the victim had received when it fired. Corpus: s = 1 (legacy), seed 42.

**Fatigue s = 1, null legacy**

| Detector | Before capitulation [95% CI] | Only at/after | Missed | Median prompts until detection | Median prompts to spare |
|---|---|---|---|---|---|
| Splunk (>9 / 10 min) | 0.324 [0.304, 0.345] | 0.000 | 0.676 | 10.0 | 5.0 |
| Elastic (2 deny + approve) | 0.000 [0.000, 0.002] | 0.686 | 0.314 | 9.0 | — |
| 2 consecutive denials (one-line rule) | 0.992 [0.987, 0.995] | 0.000 | 0.008 | 2.0 | 7.0 |
| PulseGuard, frequency features only | 0.953 [0.942, 0.961] | 0.039 | 0.009 | 2.0 | 7.0 |
| Stage C (GRU) | 0.992 [0.987, 0.995] | 0.000 | 0.008 | 2.0 | 7.0 |
| PulseGuard, full fusion | 0.992 [0.987, 0.995] | 0.007 | 0.000 | 2.0 | 7.0 |

2064 capitulating attacks; 258 where the victim held out.

Per attack profile (before capitulation, PulseGuard / Elastic / Splunk):

- high_volume_burst: 1.000 / 0.000 / 0.836
- low_and_slow: 1.000 / 0.000 / 0.000
- social_engineering_assisted: 0.980 / 0.000 / 0.160

## Adaptive attacker

400 test-split victims per setting; detectors trained once on the default seed-42 corpus, scored at their validation thresholds. The attacker chooses the gap between prompts, whether prompts land in the victim's usual login hours, and a lure. Figure: `adaptive_attacker.png`.

**Victim: default_fatigue; usual hours off; lure off** (recall)

| Gap | Splunk | Elastic | 2 denials | PulseGuard | Logistic reg. | Campaign (median h) |
|---|---|---|---|---|---|---|
| 1 min | 0.555 | 0.875 | 1.000 | 1.000 | 1.000 | 0.2 |
| 2 min | 0.000 | 0.875 | 1.000 | 1.000 | 1.000 | 0.3 |
| 5 min | 0.000 | 0.435 | 1.000 | 1.000 | 1.000 | 0.8 |
| 10 min | 0.000 | 0.000 | 1.000 | 1.000 | 1.000 | 1.5 |
| 20 min | 0.000 | 0.000 | 1.000 | 1.000 | 1.000 | 3.1 |
| 40 min | 0.000 | 0.000 | 1.000 | 1.000 | 1.000 | 6.1 |
| 1 h | 0.000 | 0.000 | 1.000 | 0.985 | 0.598 | 9.2 |
| 2 h | 0.000 | 0.000 | 1.000 | 0.000 | 0.000 | 18.4 |
| 4 h | 0.000 | 0.000 | 1.000 | 0.000 | 0.000 | 36.8 |

**Victim: default_fatigue; usual hours on; lure off** (recall)

| Gap | Splunk | Elastic | 2 denials | PulseGuard | Logistic reg. | Campaign (median h) |
|---|---|---|---|---|---|---|
| 1 min | 0.507 | 0.790 | 1.000 | 1.000 | 1.000 | 0.2 |
| 2 min | 0.000 | 0.770 | 1.000 | 1.000 | 1.000 | 0.4 |
| 5 min | 0.000 | 0.333 | 1.000 | 1.000 | 1.000 | 24.0 |
| 10 min | 0.000 | 0.000 | 1.000 | 1.000 | 1.000 | 48.2 |
| 20 min | 0.000 | 0.000 | 1.000 | 0.995 | 0.995 | 96.0 |
| 40 min | 0.000 | 0.000 | 1.000 | 0.932 | 0.512 | 144.4 |
| 1 h | 0.000 | 0.000 | 1.000 | 0.343 | 0.070 | 192.0 |
| 2 h | 0.000 | 0.000 | 1.000 | 0.000 | 0.000 | 215.3 |
| 4 h | 0.000 | 0.000 | 1.000 | 0.000 | 0.000 | 215.6 |

**Victim: default_fatigue; usual hours off; lure on** (recall)

| Gap | Splunk | Elastic | 2 denials | PulseGuard | Logistic reg. | Campaign (median h) |
|---|---|---|---|---|---|---|
| 1 min | 0.142 | 0.875 | 0.875 | 0.993 | 0.895 | 0.1 |
| 2 min | 0.000 | 0.875 | 0.875 | 0.875 | 0.892 | 0.2 |
| 5 min | 0.000 | 0.400 | 0.875 | 0.875 | 0.880 | 0.4 |
| 10 min | 0.000 | 0.000 | 0.875 | 0.875 | 0.875 | 0.8 |
| 20 min | 0.000 | 0.000 | 0.875 | 0.875 | 0.875 | 1.6 |
| 40 min | 0.000 | 0.000 | 0.875 | 0.875 | 0.875 | 3.2 |
| 1 h | 0.000 | 0.000 | 0.875 | 0.755 | 0.520 | 4.7 |
| 2 h | 0.000 | 0.000 | 0.875 | 0.000 | 0.000 | 9.5 |
| 4 h | 0.000 | 0.000 | 0.875 | 0.000 | 0.000 | 19.0 |

**Victim: default_fatigue; usual hours on; lure on** (recall)

| Gap | Splunk | Elastic | 2 denials | PulseGuard | Logistic reg. | Campaign (median h) |
|---|---|---|---|---|---|---|
| 1 min | 0.122 | 0.840 | 0.875 | 0.993 | 0.902 | 0.1 |
| 2 min | 0.000 | 0.810 | 0.875 | 0.873 | 0.895 | 0.2 |
| 5 min | 0.000 | 0.315 | 0.875 | 0.863 | 0.870 | 0.6 |
| 10 min | 0.000 | 0.000 | 0.875 | 0.848 | 0.848 | 24.0 |
| 20 min | 0.000 | 0.000 | 0.875 | 0.815 | 0.805 | 47.9 |
| 40 min | 0.000 | 0.000 | 0.875 | 0.672 | 0.412 | 72.0 |
| 1 h | 0.000 | 0.000 | 0.875 | 0.205 | 0.068 | 96.1 |
| 2 h | 0.000 | 0.000 | 0.875 | 0.000 | 0.000 | 96.5 |
| 4 h | 0.000 | 0.000 | 0.875 | 0.000 | 0.000 | 96.6 |

**Victim: no_latency_signal; usual hours off; lure off** (recall)

| Gap | Splunk | Elastic | 2 denials | PulseGuard | Logistic reg. | Campaign (median h) |
|---|---|---|---|---|---|---|
| 1 min | 0.522 | 0.875 | 1.000 | 1.000 | 1.000 | 0.2 |
| 2 min | 0.000 | 0.875 | 1.000 | 1.000 | 1.000 | 0.3 |
| 5 min | 0.000 | 0.367 | 1.000 | 1.000 | 1.000 | 0.8 |
| 10 min | 0.000 | 0.000 | 1.000 | 1.000 | 1.000 | 1.5 |
| 20 min | 0.000 | 0.000 | 1.000 | 1.000 | 1.000 | 3.1 |
| 40 min | 0.000 | 0.000 | 1.000 | 1.000 | 1.000 | 6.1 |
| 1 h | 0.000 | 0.000 | 1.000 | 0.985 | 0.515 | 9.2 |
| 2 h | 0.000 | 0.000 | 1.000 | 0.000 | 0.000 | 18.4 |
| 4 h | 0.000 | 0.000 | 1.000 | 0.000 | 0.000 | 36.8 |

**Victim: no_latency_signal; usual hours on; lure off** (recall)

| Gap | Splunk | Elastic | 2 denials | PulseGuard | Logistic reg. | Campaign (median h) |
|---|---|---|---|---|---|---|
| 1 min | 0.463 | 0.792 | 1.000 | 1.000 | 1.000 | 0.2 |
| 2 min | 0.000 | 0.760 | 1.000 | 1.000 | 1.000 | 0.4 |
| 5 min | 0.000 | 0.285 | 1.000 | 1.000 | 1.000 | 24.0 |
| 10 min | 0.000 | 0.000 | 1.000 | 1.000 | 1.000 | 48.2 |
| 20 min | 0.000 | 0.000 | 1.000 | 0.995 | 0.978 | 96.0 |
| 40 min | 0.000 | 0.000 | 1.000 | 0.932 | 0.552 | 144.4 |
| 1 h | 0.000 | 0.000 | 1.000 | 0.340 | 0.070 | 192.0 |
| 2 h | 0.000 | 0.000 | 1.000 | 0.000 | 0.000 | 215.3 |
| 4 h | 0.000 | 0.000 | 1.000 | 0.000 | 0.000 | 215.6 |

**Victim: no_latency_signal; usual hours off; lure on** (recall)

| Gap | Splunk | Elastic | 2 denials | PulseGuard | Logistic reg. | Campaign (median h) |
|---|---|---|---|---|---|---|
| 1 min | 0.128 | 0.875 | 0.875 | 0.882 | 0.875 | 0.1 |
| 2 min | 0.000 | 0.875 | 0.875 | 0.875 | 0.875 | 0.2 |
| 5 min | 0.000 | 0.350 | 0.875 | 0.875 | 0.875 | 0.4 |
| 10 min | 0.000 | 0.000 | 0.875 | 0.875 | 0.875 | 0.8 |
| 20 min | 0.000 | 0.000 | 0.875 | 0.875 | 0.875 | 1.6 |
| 40 min | 0.000 | 0.000 | 0.875 | 0.875 | 0.875 | 3.2 |
| 1 h | 0.000 | 0.000 | 0.875 | 0.755 | 0.470 | 4.8 |
| 2 h | 0.000 | 0.000 | 0.875 | 0.000 | 0.000 | 9.5 |
| 4 h | 0.000 | 0.000 | 0.875 | 0.000 | 0.000 | 19.0 |

**Victim: no_latency_signal; usual hours on; lure on** (recall)

| Gap | Splunk | Elastic | 2 denials | PulseGuard | Logistic reg. | Campaign (median h) |
|---|---|---|---|---|---|---|
| 1 min | 0.113 | 0.843 | 0.875 | 0.882 | 0.875 | 0.1 |
| 2 min | 0.000 | 0.805 | 0.875 | 0.873 | 0.873 | 0.2 |
| 5 min | 0.000 | 0.265 | 0.875 | 0.863 | 0.863 | 0.6 |
| 10 min | 0.000 | 0.000 | 0.875 | 0.848 | 0.845 | 24.0 |
| 20 min | 0.000 | 0.000 | 0.875 | 0.815 | 0.792 | 47.9 |
| 40 min | 0.000 | 0.000 | 0.875 | 0.672 | 0.415 | 72.0 |
| 1 h | 0.000 | 0.000 | 0.875 | 0.205 | 0.068 | 96.1 |
| 2 h | 0.000 | 0.000 | 0.875 | 0.000 | 0.000 | 96.5 |
| 4 h | 0.000 | 0.000 | 0.875 | 0.000 | 0.000 | 96.6 |

Anti-lockout invariant at every setting: **HOLDS** (no lock action ever issued; one cooldown window after the attack the legitimate user is always offered a step-up or an alternate factor).

Benign test FPR at this operating point: Stage B (XGBoost) 0.0007, PulseGuard, frequency features only 0.0690, Stage C (GRU) 0.0007, PulseGuard, full fusion 0.0013, Isolation Forest 0.0898, Logistic regression 0.0000, Splunk (>9 / 10 min) 0.0000, Elastic (2 deny + approve) 0.0026, 2 consecutive denials (one-line rule) 0.0000.

## Robustness to the assumed fatigue model

Trained once on the assumed model (linear collapse, s = 1, matched null), then tested on corpora whose fatigue shape, per-victim strength or benign latency differ; next to a model retrained on each variant. Seed 42, test split.

| Test corpus | PulseGuard (assumed model) recall / FPR | PulseGuard (retrained) recall / FPR | Logistic reg. (assumed) recall / FPR | 2 denials recall / FPR |
|---|---|---|---|---|
| assumed (linear, s=1) | 1.000 / 0.0013 | 1.000 / 0.0013 | 0.993 / 0.0000 | 0.993 / 0.0000 |
| exponential, s=1 | 1.000 / 0.0013 | 1.000 / 0.0013 | 0.993 / 0.0000 | 0.993 / 0.0000 |
| step, s=1 | 1.000 / 0.0013 | 1.000 / 0.0013 | 0.993 / 0.0000 | 0.993 / 0.0000 |
| heterogeneous sd=0.5, s=1 | 0.997 / 0.0013 | 0.998 / 0.0046 | 0.993 / 0.0000 | 0.993 / 0.0000 |
| heterogeneous sd=1.0, s=1 | 0.997 / 0.0013 | 0.997 / 0.0020 | 0.993 / 0.0000 | 0.993 / 0.0000 |
| DuoLungo benign, s=1 | 1.000 / 0.0013 | 1.000 / 0.0013 | 0.994 / 0.0000 | 0.993 / 0.0000 |
| DuoLungo benign, s=0 | 0.994 / 0.0013 | 0.993 / 0.0013 | 0.993 / 0.0000 | 0.993 / 0.0000 |

## Cross-session guard (slow-pacing fix)

Per user and across sessions, count denials that no approval followed within 10 minutes, and alert once K fall inside a trailing window. Every benign denial in the generator is retried and approved within the hour, so benign users are given stray unresolved denials (own device, one per active day with probability p) and p is swept. K and the window were chosen on validation users: the most slow-attack recall (gaps of 2 h or more) among settings with validation FPR on never-attacked users at most 0.002 at p = 0.1. **Chosen: K=3, window=7d.** Seed 42, test split. Figure: `cross_session.png`.

**Validation grid** (FPR on never-attacked users / slow-attack recall)

| Setting | FPR, never-attacked users | FPR, all benign episodes | Slow-attack recall |
|---|---|---|---|
| K=2, window=1d | 0.0260 | 0.0405 | 0.513 |
| K=2, window=3d | 0.0310 | 0.0450 | 0.934 |
| K=2, window=7d | 0.0310 | 0.0450 | 0.934 |
| K=3, window=1d | 0.0000 | 0.0155 | 0.442 |
| K=3, window=3d | 0.0005 | 0.0159 | 0.852 |
| K=3, window=7d | 0.0005 | 0.0159 | 0.872 |
| K=4, window=1d | 0.0000 | 0.0143 | 0.406 |
| K=4, window=3d | 0.0000 | 0.0143 | 0.450 |
| K=4, window=7d | 0.0000 | 0.0143 | 0.814 |
| K=5, window=1d | 0.0000 | 0.0139 | 0.371 |
| K=5, window=3d | 0.0000 | 0.0139 | 0.410 |
| K=5, window=7d | 0.0000 | 0.0139 | 0.750 |

**Test corpus with stray denials** (recall / FPR over all benign episodes / FPR over users never attacked)

| p | PulseGuard | Guard | PulseGuard OR guard |
|---|---|---|---|
| 0 | 1.000 / 0.0013 / 0.0013 | 0.525 / 0.0000 / 0.0000 | 1.000 / 0.0013 / 0.0013 |
| 0.02 | 1.000 / 0.0012 / 0.0012 | 0.525 / 0.0081 / 0.0000 | 1.000 / 0.0092 / 0.0012 |
| 0.1 | 1.000 / 0.0008 / 0.0009 | 0.527 / 0.0216 / 0.0000 | 1.000 / 0.0224 / 0.0009 |
| 0.3 | 1.000 / 0.0005 / 0.0006 | 0.531 / 0.0352 / 0.0014 | 1.000 / 0.0357 / 0.0020 |

FPR over all benign episodes counts an alert on an account in the days after a real attack on it; the never-attacked column is what an ordinary user would see.

With benign deny runs (r = 0.1, retried and approved within minutes) the guard's FPR is 0.0000 (0.0000 on never-attacked users): runs that end in an approval are resolved, which is why the two-denials rule fails there and this guard does not.

**Adaptive attacker, victim: default_fatigue; usual hours off; no lure** (recall)

| Gap | PulseGuard | Guard | PulseGuard OR guard |
|---|---|---|---|
| 1 min | 1.000 | 0.210 | 1.000 |
| 2 min | 1.000 | 0.708 | 1.000 |
| 5 min | 1.000 | 0.998 | 1.000 |
| 10 min | 1.000 | 1.000 | 1.000 |
| 20 min | 1.000 | 1.000 | 1.000 |
| 40 min | 1.000 | 0.998 | 1.000 |
| 1 h | 0.985 | 1.000 | 1.000 |
| 2 h | 0.000 | 0.998 | 0.998 |
| 4 h | 0.000 | 1.000 | 1.000 |

**Adaptive attacker, victim: default_fatigue; usual hours on; no lure** (recall)

| Gap | PulseGuard | Guard | PulseGuard OR guard |
|---|---|---|---|
| 1 min | 1.000 | 0.323 | 1.000 |
| 2 min | 1.000 | 0.735 | 1.000 |
| 5 min | 1.000 | 0.998 | 1.000 |
| 10 min | 1.000 | 0.998 | 1.000 |
| 20 min | 0.995 | 1.000 | 1.000 |
| 40 min | 0.932 | 1.000 | 1.000 |
| 1 h | 0.343 | 1.000 | 1.000 |
| 2 h | 0.000 | 1.000 | 1.000 |
| 4 h | 0.000 | 1.000 | 1.000 |

**Adaptive attacker, victim: no_latency_signal; usual hours off; no lure** (recall)

| Gap | PulseGuard | Guard | PulseGuard OR guard |
|---|---|---|---|
| 1 min | 1.000 | 0.240 | 1.000 |
| 2 min | 1.000 | 0.723 | 1.000 |
| 5 min | 1.000 | 0.998 | 1.000 |
| 10 min | 1.000 | 1.000 | 1.000 |
| 20 min | 1.000 | 0.998 | 1.000 |
| 40 min | 1.000 | 0.998 | 1.000 |
| 1 h | 0.985 | 1.000 | 1.000 |
| 2 h | 0.000 | 0.998 | 0.998 |
| 4 h | 0.000 | 1.000 | 1.000 |

**Adaptive attacker, victim: no_latency_signal; usual hours on; no lure** (recall)

| Gap | PulseGuard | Guard | PulseGuard OR guard |
|---|---|---|---|
| 1 min | 1.000 | 0.345 | 1.000 |
| 2 min | 1.000 | 0.752 | 1.000 |
| 5 min | 1.000 | 0.998 | 1.000 |
| 10 min | 1.000 | 0.998 | 1.000 |
| 20 min | 0.995 | 1.000 | 1.000 |
| 40 min | 0.932 | 1.000 | 1.000 |
| 1 h | 0.340 | 1.000 | 1.000 |
| 2 h | 0.000 | 1.000 | 1.000 |
| 4 h | 0.000 | 1.000 | 1.000 |

Anti-lockout invariant with the combined detector, all 72 settings: **HOLDS**.

## Benign users who deny several prompts in a row

In the default corpus no benign episode ever has two consecutive denials, so a one-line rule separates the classes. Here a share r of benign high-activity logins is preceded by 2-4 denied prompts (benign denial latency, own device). r is an assumption, so it is swept. Each cell: recall / FPR (mean across seeds where there are several), matched null.

| r | seeds | s | 2 consecutive denials (one-line rule) | Elastic (2 deny + approve) | Logistic regression | PulseGuard, frequency features only | PulseGuard, full fusion |
|---|---|---|---|---|---|---|---|
| 0.01 | 1 | 0 | 0.993 / 0.0995 | 0.610 / 0.1015 | 0.993 / 0.0052 | 0.991 / 0.0761 | 0.994 / 0.0078 |
| 0.01 | 1 | 0.5 | 0.993 / 0.0995 | 0.610 / 0.1015 | 0.993 / 0.0052 | 0.991 / 0.0755 | 0.996 / 0.0085 |
| 0.01 | 1 | 1 | 0.993 / 0.0995 | 0.610 / 0.1015 | 0.993 / 0.0052 | 0.991 / 0.0742 | 0.999 / 0.0059 |
| 0.03 | 1 | 0 | 0.993 / 0.2284 | 0.610 / 0.2297 | 0.993 / 0.0130 | 0.993 / 0.0800 | 0.993 / 0.0091 |
| 0.03 | 1 | 0.5 | 0.993 / 0.2284 | 0.610 / 0.2297 | 0.993 / 0.0111 | 0.992 / 0.0761 | 0.994 / 0.0117 |
| 0.03 | 1 | 1 | 0.993 / 0.2284 | 0.610 / 0.2297 | 0.993 / 0.0111 | 0.991 / 0.0761 | 0.997 / 0.0085 |
| 0.1 | 5 | 0 | 0.995 / 0.4237 | 0.618 / 0.4237 | 0.995 / 0.0529 | 0.985 / 0.0911 | 0.993 / 0.0387 |
| 0.1 | 5 | 0.5 | 0.995 / 0.4237 | 0.618 / 0.4237 | 0.994 / 0.0512 | 0.985 / 0.0903 | 0.988 / 0.0313 |
| 0.1 | 5 | 1 | 0.995 / 0.4237 | 0.618 / 0.4237 | 0.993 / 0.0458 | 0.983 / 0.0884 | 0.992 / 0.0084 |

- r = 0.01: from s = 0 to s = 1, PulseGuard recall changes by +0.005 and FPR by -0.0020: the latency signal does not measurably matter.
- r = 0.03: from s = 0 to s = 1, PulseGuard recall changes by +0.004 and FPR by -0.0007: the latency signal does not measurably matter.
- r = 0.1: from s = 0 to s = 1, PulseGuard recall changes by -0.001 and FPR by -0.0303: the latency signal matters.

