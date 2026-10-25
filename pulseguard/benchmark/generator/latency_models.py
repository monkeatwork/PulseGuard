"""Human decision-latency models for the benchmark generator.

Every constant here is named and pinned in DECISIONS.md ("Generator latency
distributions") rather than left as a magic number. LogNormal is used
throughout because human reaction-time data is consistently right-skewed
(a long tail of slow responses), which Normal/Uniform do not capture.

All latencies are returned in milliseconds as non-negative integers.

The fatigue signal is a generator PARAMETER (`FatigueConfig`), not a fixed
fact: how strongly, and in what shape, reaction time collapses under a
prompt flood is exactly what no published human-subjects data measures yet.
`FatigueConfig()` (the default) reproduces the original corpus draw for draw,
so `cli.py --seed 42` is unchanged; every other setting exists so the
evaluation can ask how much of the detector's performance depends on the
assumed curve (DECISIONS.md, 2026-10-26 "Fatigue strength is a parameter").
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Literal

import numpy as np

# --- Benign (legitimate, non-fatigued) response latency ---------------------
# LogNormal(mu, sigma) on seconds; mu=1.6 -> median ~= e^1.6 ~= 4.95s.
BENIGN_APPROVE_LATENCY_MU = 1.6
BENIGN_APPROVE_LATENCY_SIGMA = 0.5

# A benign denial (recognizing an unexpected prompt) tends to be faster and
# less variable than a considered approval.
BENIGN_DENY_LATENCY_MU = 1.3
BENIGN_DENY_LATENCY_SIGMA = 0.4

# --- Benign latency fitted to published field data ---------------------------
# Prapty & Tsudik, "DuoLungo: Usability Study of Duo 2FA", NDSS USEC 2026
# (arXiv 2602.01489), Duo Push overhead over 16,851 real logins by 2,559
# users: median 6.89 s, Q1 4.82 s, Q3 10.47 s (untrimmed). LogNormal fit:
# mu = ln(median); sigma = ln(Q3/Q1) / (2 * 0.6745). The overhead includes
# network/server latency, so it upper-bounds pure reaction time.
DUOLUNGO_APPROVE_LATENCY_MU = math.log(6.89)  # ~1.930
DUOLUNGO_APPROVE_LATENCY_SIGMA = math.log(10.47 / 4.82) / (2 * 0.6745)  # ~0.575
# DuoLungo does not separate denials. Assumption: keep the legacy model's
# deny/approve relationship (median 0.74x, spread 0.8x).
DUOLUNGO_DENY_LATENCY_MU = DUOLUNGO_APPROVE_LATENCY_MU + (BENIGN_DENY_LATENCY_MU - BENIGN_APPROVE_LATENCY_MU)
DUOLUNGO_DENY_LATENCY_SIGMA = DUOLUNGO_APPROVE_LATENCY_SIGMA * (BENIGN_DENY_LATENCY_SIGMA / BENIGN_APPROVE_LATENCY_SIGMA)

# --- Fatigue-capitulation latency within a burst -----------------------------
# mu decays from FATIGUE_MU_START (first prompt, still deliberating)
# to FATIGUE_MU_END (final prompt, reflexive tap) across the burst. This is
# what produces the strongly negative latency_drift_slope signature.
FATIGUE_MU_START = 1.6  # matches benign median at prompt 0
FATIGUE_MU_END = -0.3  # median ~= e^-0.3 ~= 0.74s by the last prompt
FATIGUE_SIGMA = 0.3  # tighter spread as deliberation collapses into reflex

# Curvature of the "exponential" shape: most of the collapse happens early.
FATIGUE_EXPONENTIAL_RATE = 3.0
# The "step" shape: no change until this fraction of the burst, then the
# full collapse at once.
FATIGUE_STEP_AT = 0.5

# --- Social-engineering lure ---------------------------------------------
# A lure event (e.g. a spoofed "IT support" call) forces a near-immediate
# tap regardless of where in the burst it lands.
LURE_LATENCY_FLOOR_MS = 1000
LURE_LATENCY_CEILING_MS = 2000
# In the "matched" null model the lure is a LogNormal whose full-strength
# form has the legacy uniform's median (1.5 s) and a tight spread, so it can
# be weakened continuously down to an ordinary benign approval at strength 0.
LURE_MU = math.log(1.5)
LURE_SIGMA = 0.2

MIN_LATENCY_MS = 200  # floor so no sample rounds down to ~0ms
MIN_SIGMA = 0.05  # heterogeneous strengths above 1 must not drive sigma to <= 0

FatigueShape = Literal["linear", "exponential", "step"]
NullModel = Literal["legacy", "matched"]
BenignSource = Literal["legacy", "duolungo"]
Decision = Literal["approve", "deny"]

FATIGUE_SHAPES = ("linear", "exponential", "step")
NULL_MODELS = ("legacy", "matched")
BENIGN_SOURCES = ("legacy", "duolungo")


@dataclass(frozen=True)
class FatigueConfig:
    """How the generator models a fatigued victim.

    strength: 0 = no latency collapse, 1 = the original full collapse to
        FATIGUE_MU_END. Per-episode draws (heterogeneity) may leave [0, 1];
        a negative strength is a victim who slows down when annoyed.
    shape: how the collapse progresses across the burst.
    null_model: what strength 0 means.
        "legacy" -- every attack decision starts from (FATIGUE_MU_START,
            FATIGUE_SIGMA) whatever the decision, and the lure is the fixed
            1-2 s uniform; only mu_end moves with strength. This is the
            original generator. It is NOT signal-free at strength 0: the
            spread (0.3) is tighter than benign (0.5 / 0.4), denials are
            slower than benign denials, and the lure stays at 1-2 s.
        "matched" -- each decision starts from the benign distribution for
            that decision (approve or deny), and spread and lure move with
            strength too, so strength 0 carries no latency signal at all.
    benign_source: benign latency parameters, used for benign users and as
        the matched null ("legacy" hand-picked, "duolungo" fitted to
        published field data).
    heterogeneity: standard deviation of a per-episode multiplier on
        strength (see `episode_strength`). 0 = every attack episode has
        exactly `strength`.
    """

    strength: float = 1.0
    shape: FatigueShape = "linear"
    null_model: NullModel = "legacy"
    benign_source: BenignSource = "legacy"
    heterogeneity: float = 0.0

    def is_default(self) -> bool:
        return self == FatigueConfig()

    def with_strength(self, strength: float) -> "FatigueConfig":
        return replace(self, strength=strength)

    def as_dict(self) -> dict:
        return {
            "strength": self.strength,
            "shape": self.shape,
            "null_model": self.null_model,
            "benign_source": self.benign_source,
            "heterogeneity": self.heterogeneity,
        }


DEFAULT_FATIGUE = FatigueConfig()

# Per-episode strength multiplier bounds (heterogeneity > 0): from a victim
# who slows down noticeably to one who collapses twice as hard as nominal.
EPISODE_STRENGTH_MULTIPLIER_RANGE = (-0.5, 2.0)


def episode_strength(rng: np.random.Generator, config: FatigueConfig) -> float:
    """Strength for one attack episode. Draws from `rng` only when
    heterogeneity is on. Callers pass a dedicated child rng, never the
    profile's own stream, so turning heterogeneity on does not shift any
    other draw in the corpus."""
    if config.heterogeneity <= 0:
        return config.strength
    lo, hi = EPISODE_STRENGTH_MULTIPLIER_RANGE
    return config.strength * float(np.clip(rng.normal(1.0, config.heterogeneity), lo, hi))


def _lognormal_ms(rng: np.random.Generator, mu: float, sigma: float) -> int:
    seconds = rng.lognormal(mean=mu, sigma=sigma)
    return max(MIN_LATENCY_MS, int(round(seconds * 1000)))


def benign_params(decision: Decision, source: BenignSource = "legacy") -> tuple[float, float]:
    if source == "duolungo":
        if decision == "approve":
            return DUOLUNGO_APPROVE_LATENCY_MU, DUOLUNGO_APPROVE_LATENCY_SIGMA
        return DUOLUNGO_DENY_LATENCY_MU, DUOLUNGO_DENY_LATENCY_SIGMA
    if decision == "approve":
        return BENIGN_APPROVE_LATENCY_MU, BENIGN_APPROVE_LATENCY_SIGMA
    return BENIGN_DENY_LATENCY_MU, BENIGN_DENY_LATENCY_SIGMA


def sample_benign_approve_latency_ms(rng: np.random.Generator, source: BenignSource = "legacy") -> int:
    return _lognormal_ms(rng, *benign_params("approve", source))


def sample_benign_deny_latency_ms(rng: np.random.Generator, source: BenignSource = "legacy") -> int:
    return _lognormal_ms(rng, *benign_params("deny", source))


def fatigue_progress(prompt_index: int, burst_length: int, shape: FatigueShape = "linear") -> float:
    """How far into its collapse the victim is at `prompt_index`, in [0, 1]."""
    if burst_length <= 1:
        return 0.0
    progress = prompt_index / (burst_length - 1)
    if shape == "linear":
        return progress
    if shape == "exponential":
        k = FATIGUE_EXPONENTIAL_RATE
        return (1.0 - math.exp(-k * progress)) / (1.0 - math.exp(-k))
    if shape == "step":
        return 1.0 if progress >= FATIGUE_STEP_AT else 0.0
    raise ValueError(f"unknown fatigue shape {shape!r}")


def fatigue_mu_at(prompt_index: int, burst_length: int) -> float:
    """Linear interpolation of mu across the burst (the default model).
    `burst_length` is the total number of prompts in the burst;
    `prompt_index` is 0-based."""
    if burst_length <= 1:
        return FATIGUE_MU_START
    progress = prompt_index / (burst_length - 1)
    return FATIGUE_MU_START + progress * (FATIGUE_MU_END - FATIGUE_MU_START)


def fatigue_params(
    prompt_index: int,
    burst_length: int,
    decision: Decision = "deny",
    config: FatigueConfig = DEFAULT_FATIGUE,
    strength: float | None = None,
) -> tuple[float, float]:
    """(mu, sigma) of a fatigued decision. `strength` overrides
    config.strength (a per-episode heterogeneous draw)."""
    if config.is_default() and strength is None:
        return fatigue_mu_at(prompt_index, burst_length), FATIGUE_SIGMA
    s = config.strength if strength is None else strength
    p = fatigue_progress(prompt_index, burst_length, config.shape)
    if config.null_model == "legacy":
        mu0, sigma0 = FATIGUE_MU_START, FATIGUE_SIGMA
    else:
        mu0, sigma0 = benign_params(decision, config.benign_source)
    mu = mu0 + s * p * (FATIGUE_MU_END - mu0)
    sigma = sigma0 + s * p * (FATIGUE_SIGMA - sigma0)
    return mu, max(sigma, MIN_SIGMA)


def sample_fatigue_latency_ms(
    rng: np.random.Generator,
    prompt_index: int,
    burst_length: int,
    decision: Decision = "deny",
    config: FatigueConfig = DEFAULT_FATIGUE,
    strength: float | None = None,
) -> int:
    mu, sigma = fatigue_params(prompt_index, burst_length, decision, config, strength)
    return _lognormal_ms(rng, mu, sigma)


def sample_lure_latency_ms(
    rng: np.random.Generator,
    config: FatigueConfig = DEFAULT_FATIGUE,
    strength: float | None = None,
) -> int:
    if config.null_model == "legacy":
        return int(rng.integers(LURE_LATENCY_FLOOR_MS, LURE_LATENCY_CEILING_MS + 1))
    s = min(max(config.strength if strength is None else strength, 0.0), 1.0)
    mu0, sigma0 = benign_params("approve", config.benign_source)
    return _lognormal_ms(rng, mu0 + s * (LURE_MU - mu0), sigma0 + s * (LURE_SIGMA - sigma0))
