"""The persisted operating point: the fusion weights and alert threshold
the evaluation measured, which the live scorer must run at.

Written by tune_fusion_weights.py (validation split only), read by
live_scorer.py. There is deliberately NO default: before this file existed
the live scorer silently used the untuned FusionWeights() defaults and a
hand-copied threshold, so the running system was not the system every
reported metric described (REMEDIATION_TASK.md B2). A missing or malformed
file is a startup error, not a fallback.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from services.detection_engine.app.fusion import FusionWeights


class OperatingPointMissing(RuntimeError):
    pass


@dataclass(frozen=True)
class OperatingPoint:
    weight_a: float
    weight_b: float
    weight_c: float
    threshold: float
    stage_b_threshold: float
    stage_c_threshold: float
    seed: int
    events_sha256: str
    tuned_on: str
    unit: str
    created_at: str

    @property
    def weights(self) -> FusionWeights:
        return FusionWeights(self.weight_a, self.weight_b, self.weight_c)


def save_operating_point(point: OperatingPoint, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(point), indent=2) + "\n", encoding="utf-8")


def load_operating_point(path: Path) -> OperatingPoint:
    if not path.exists():
        raise OperatingPointMissing(
            f"{path} not found. The live scorer will not fall back to default fusion weights or a "
            "guessed threshold; run tune_fusion_weights.py (see README) to produce it."
        )
    try:
        point = OperatingPoint(**json.loads(path.read_text(encoding="utf-8")))
    except (TypeError, ValueError) as exc:
        raise OperatingPointMissing(f"{path} is malformed: {exc}") from exc
    if point.tuned_on != "val":
        raise OperatingPointMissing(f"{path} was tuned on {point.tuned_on!r}; only 'val' is acceptable")
    return point
