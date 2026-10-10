"""Stage A: per-user statistical deviation (CLAUDE.md, L4 architecture).

A simple, fully explainable first-pass score over the same feature vector
Stage B consumes — not learned, just how anomalous the single most
deviant signal in this burst is. Deliberately cheap and interpretable;
Stage B (Phase 4b) and Stage C (Phase 5) carry the actual detection power.
"""

from __future__ import annotations

# A drift slope this negative (ms lost per prompt) is already a striking
# fatigue signature; used to normalize the slope signal onto a comparable
# scale to the other z-like signals. Chosen as the magnitude a strong,
# unambiguous fatigue burst produces (DECISIONS.md pattern from Phase 3
# tests: a clear fatigue pattern reaches slope < -100 easily; -500
# represents a pronounced case).
DRIFT_SLOPE_NORMALIZATION_MS = 500.0
STAGE_A_THRESHOLD = 2.0


def stage_a_score(vector: dict) -> float:
    """Returns the single most anomalous signal in the burst's feature
    vector, on a roughly z-score-comparable scale. 0.0 if nothing in the
    vector is anomalous at all (e.g. an ordinary single benign approval)."""
    signals = [0.0]

    if vector.get("approval_latency_z_valid"):
        signals.append(abs(vector["approval_latency_z"]))

    if vector.get("latency_drift_slope_valid") and vector["latency_drift_slope"] < 0:
        signals.append(abs(vector["latency_drift_slope"]) / DRIFT_SLOPE_NORMALIZATION_MS)

    deny_run = vector.get("deny_run_length", 0)
    if deny_run >= 2:
        signals.append(deny_run / 2.0)

    n_prompts = vector.get("n_prompts", 0)
    if n_prompts > 9:  # matches the Splunk baseline's own threshold as a floor signal
        signals.append(n_prompts / 9.0)

    return max(signals)


def stage_a_flag(vector: dict, threshold: float = STAGE_A_THRESHOLD) -> bool:
    return stage_a_score(vector) > threshold
