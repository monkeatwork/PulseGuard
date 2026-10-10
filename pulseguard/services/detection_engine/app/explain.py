"""Per-alert "top-3 reasons", attributed to the component that actually
drove the alert's fused score (REMEDIATION_TASK.md B4).

The old explanation always came from Stage B's SHAP values, even when the
tuned fusion gave Stage B zero weight -- so the dashboard explained a model
that had not contributed to the score that fired. Now:

  * each stage's contribution to the fused score is computed
    (weight x normalised stage score);
  * the explanation comes from the stage with the largest contribution, and
    is labelled with that stage (`source`);
  * Stage A explains itself (its score IS the most deviant signal);
    Stage B uses TreeSHAP over XGBoost; Stage C uses gradient x input over
    the GRU's input sequence, summed per step feature.

So the reasons shown are always attributable to the component that drove
the score, and the label says which one it was.
"""

from __future__ import annotations

import numpy as np
import torch

from services.detection_engine.app.fusion import FusionWeights, normalize_stage_a_score
from services.detection_engine.app.stage_a_statistical import DRIFT_SLOPE_NORMALIZATION_MS

STEP_FEATURE_NAMES = [
    "sequence: denials",
    "sequence: approvals",
    "sequence: unanswered prompts",
    "sequence: latency present",
    "sequence: decision latency",
    "sequence: inter-prompt gap",
]


def contributions(a_raw: float, b: float, c: float, weights: FusionWeights) -> dict[str, float]:
    w = weights.normalized()
    return {
        "stage_a": w.weight_a * normalize_stage_a_score(a_raw),
        "stage_b": w.weight_b * b,
        "stage_c": w.weight_c * c,
    }


def dominant_stage(contrib: dict[str, float]) -> str:
    return max(contrib, key=contrib.get)


def stage_a_reasons(vector: dict) -> list[dict]:
    """Stage A's own signals, on the same scale stage_a_score() uses."""
    signals = []
    if vector.get("approval_latency_z_valid") and vector.get("approval_latency_z") is not None:
        z = float(vector["approval_latency_z"])
        signals.append({"feature": "approval_latency_z", "contribution": abs(z), "feature_value": z})
    if vector.get("latency_drift_slope_valid") and vector.get("latency_drift_slope", 0) < 0:
        slope = float(vector["latency_drift_slope"])
        signals.append({"feature": "latency_drift_slope", "contribution": abs(slope) / DRIFT_SLOPE_NORMALIZATION_MS, "feature_value": slope})
    if vector.get("deny_run_length", 0) >= 2:
        run = int(vector["deny_run_length"])
        signals.append({"feature": "deny_run_length", "contribution": run / 2.0, "feature_value": run})
    if vector.get("prompts_per_window", 0) > 9:
        n = int(vector["prompts_per_window"])
        signals.append({"feature": "prompts_per_window", "contribution": n / 9.0, "feature_value": n})
    signals.sort(key=lambda s: s["contribution"], reverse=True)
    return [{"feature": s["feature"], "shap_value": s["contribution"], "feature_value": s["feature_value"]} for s in signals[:3]]


def stage_c_reasons(model, seq: np.ndarray, length: int) -> list[dict]:
    """Gradient x input of the GRU's attack logit w.r.t. its input sequence,
    summed over time per step feature. Positive = pushed towards attack."""
    x = torch.tensor(seq[None, ...], dtype=torch.float32, requires_grad=True)
    model.eval()
    logit = model(x, torch.tensor([length], dtype=torch.long))
    logit.sum().backward()
    attribution = (x.grad[0] * x[0]).detach().numpy()[:length].sum(axis=0)
    steps = seq[:length]
    values = [
        float(steps[:, 0].sum()),  # denials
        float(steps[:, 1].sum()),  # approvals
        float(steps[:, 2].sum()),  # unanswered
        float(steps[:, 3].sum()),  # with latency
        float(np.expm1(steps[:, 4][steps[:, 3] > 0] * 10).mean()) if (steps[:, 3] > 0).any() else 0.0,  # mean latency ms
        float(np.expm1(steps[1:, 5] * 10).mean()) if length > 1 else 0.0,  # mean gap s
    ]
    order = np.argsort(-np.abs(attribution))[:3]
    return [
        {"feature": STEP_FEATURE_NAMES[i], "shap_value": float(attribution[i]), "feature_value": values[i]}
        for i in order
    ]
