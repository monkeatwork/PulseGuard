"""Human decision-latency models for the benchmark generator.

Every constant here is named and pinned in DECISIONS.md ("Generator latency
distributions") rather than left as a magic number. LogNormal is used
throughout because human reaction-time data is consistently right-skewed
(a long tail of slow responses), which Normal/Uniform do not capture.

All latencies are returned in milliseconds as non-negative integers.
"""

from __future__ import annotations

import numpy as np

# --- Benign (legitimate, non-fatigued) response latency ---------------------
# LogNormal(mu, sigma) on seconds; mu=1.6 -> median ~= e^1.6 ~= 4.95s.
BENIGN_APPROVE_LATENCY_MU = 1.6
BENIGN_APPROVE_LATENCY_SIGMA = 0.5

# A benign denial (recognizing an unexpected prompt) tends to be faster and
# less variable than a considered approval.
BENIGN_DENY_LATENCY_MU = 1.3
BENIGN_DENY_LATENCY_SIGMA = 0.4

# --- Fatigue-capitulation latency within a burst -----------------------------
# mu decays linearly from FATIGUE_MU_START (first prompt, still deliberating)
# to FATIGUE_MU_END (final prompt, reflexive tap) across the burst. This is
# what produces the strongly negative latency_drift_slope signature.
FATIGUE_MU_START = 1.6  # matches benign median at prompt 0
FATIGUE_MU_END = -0.3  # median ~= e^-0.3 ~= 0.74s by the last prompt
FATIGUE_SIGMA = 0.3  # tighter spread as deliberation collapses into reflex

# --- Social-engineering lure ---------------------------------------------
# A lure event (e.g. a spoofed "IT support" call) forces a near-immediate
# tap regardless of where in the burst it lands.
LURE_LATENCY_FLOOR_MS = 1000
LURE_LATENCY_CEILING_MS = 2000

MIN_LATENCY_MS = 200  # floor so no sample rounds down to ~0ms


def _lognormal_ms(rng: np.random.Generator, mu: float, sigma: float) -> int:
    seconds = rng.lognormal(mean=mu, sigma=sigma)
    return max(MIN_LATENCY_MS, int(round(seconds * 1000)))


def sample_benign_approve_latency_ms(rng: np.random.Generator) -> int:
    return _lognormal_ms(rng, BENIGN_APPROVE_LATENCY_MU, BENIGN_APPROVE_LATENCY_SIGMA)


def sample_benign_deny_latency_ms(rng: np.random.Generator) -> int:
    return _lognormal_ms(rng, BENIGN_DENY_LATENCY_MU, BENIGN_DENY_LATENCY_SIGMA)


def fatigue_mu_at(prompt_index: int, burst_length: int) -> float:
    """Linear interpolation of mu across the burst. `burst_length` is the
    total number of prompts in the burst; `prompt_index` is 0-based."""
    if burst_length <= 1:
        return FATIGUE_MU_START
    progress = prompt_index / (burst_length - 1)
    return FATIGUE_MU_START + progress * (FATIGUE_MU_END - FATIGUE_MU_START)


def sample_fatigue_latency_ms(rng: np.random.Generator, prompt_index: int, burst_length: int) -> int:
    mu = fatigue_mu_at(prompt_index, burst_length)
    return _lognormal_ms(rng, mu, FATIGUE_SIGMA)


def sample_lure_latency_ms(rng: np.random.Generator) -> int:
    return int(rng.integers(LURE_LATENCY_FLOOR_MS, LURE_LATENCY_CEILING_MS + 1))
