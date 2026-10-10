"""Precision / recall / false-positive-rate computation.

FPR is a primary reported metric, not an afterthought (CLAUDE.md, evaluation
rule #3) — it is always computed and surfaced alongside precision/recall,
never omitted because it looks unfavorable.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Optional, TypedDict


@dataclass(frozen=True)
class ConfusionCounts:
    tp: int
    fp: int
    tn: int
    fn: int

    @property
    def precision(self) -> Optional[float]:
        denom = self.tp + self.fp
        return self.tp / denom if denom else None

    @property
    def recall(self) -> Optional[float]:
        denom = self.tp + self.fn
        return self.tp / denom if denom else None

    @property
    def fpr(self) -> Optional[float]:
        denom = self.fp + self.tn
        return self.fp / denom if denom else None

    def as_dict(self) -> dict:
        return {
            "tp": self.tp,
            "fp": self.fp,
            "tn": self.tn,
            "fn": self.fn,
            "precision": self.precision,
            "recall": self.recall,
            "fpr": self.fpr,
        }


class LabelledPrediction(TypedDict):
    attack_profile: Optional[str]
    y_true: bool
    y_pred: bool


def compute_confusion(y_true: list[bool], y_pred: list[bool]) -> ConfusionCounts:
    tp = fp = tn = fn = 0
    for t, p in zip(y_true, y_pred):
        if t and p:
            tp += 1
        elif not t and p:
            fp += 1
        elif not t and not p:
            tn += 1
        else:
            fn += 1
    return ConfusionCounts(tp, fp, tn, fn)


def breakdown_by_profile(rows: list[LabelledPrediction]) -> dict[str, dict]:
    """Groups by `attack_profile` (benign hard negatives use the sentinel
    key "benign_high_activity"). Reports recall for attack strata and FPR
    for the benign stratum — the two halves of the confusion matrix that
    are actually meaningful per group."""
    buckets: dict[str, list[LabelledPrediction]] = defaultdict(list)
    for row in rows:
        profile = row["attack_profile"]
        # `profile` can arrive as Python None, or as float NaN after a
        # parquet round-trip of a column that also holds strings (pandas/
        # pyarrow represent a missing value in an object column as NaN,
        # not None, once written and re-read) -- NaN is truthy in Python,
        # so a plain `profile or "..."` silently produces a bogus `nan`
        # bucket instead of the benign sentinel. isinstance guards against
        # calling isnan() on an actual profile string.
        is_missing = profile is None or (isinstance(profile, float) and profile != profile)
        key = "benign_high_activity" if is_missing else profile
        buckets[key].append(row)

    result = {}
    for profile, group in buckets.items():
        confusion = compute_confusion([r["y_true"] for r in group], [r["y_pred"] for r in group])
        result[profile] = confusion.as_dict()
    return result
