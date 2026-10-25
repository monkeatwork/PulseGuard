"""Uncertainty for reported rates.

Two sources, reported separately and never mixed:
  - within one run: a Wilson 95% interval on a proportion (recall over the
    test attacks, FPR over the test benign episodes);
  - across runs: mean and a t-based 95% interval over seeds, where each seed
    regenerates the corpus, the split and every trained model, so it
    captures generator and training variance together.
"""

from __future__ import annotations

import math
from typing import Iterable, Optional

from scipy import stats

Z_95 = 1.959963984540054


def wilson(k: int, n: int, z: float = Z_95) -> tuple[Optional[float], Optional[float]]:
    if n == 0:
        return None, None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def with_wilson(summary: dict) -> dict:
    """Adds recall_ci / fpr_ci to a summarize() dict."""
    out = dict(summary)
    out["recall_ci"] = wilson(summary["tp"], summary["tp"] + summary["fn"])
    out["fpr_ci"] = wilson(summary["fp"], summary["fp"] + summary["tn"])
    return out


def across_seeds(values: Iterable[Optional[float]]) -> dict:
    xs = [v for v in values if v is not None]
    n = len(xs)
    if n == 0:
        return {"mean": None, "ci_low": None, "ci_high": None, "n_seeds": 0}
    mean = sum(xs) / n
    if n == 1:
        return {"mean": mean, "ci_low": None, "ci_high": None, "n_seeds": 1}
    sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / (n - 1))
    half = stats.t.ppf(0.975, n - 1) * sd / math.sqrt(n)
    # every reported value is a rate, so the interval is clipped to [0, 1]
    return {"mean": mean, "ci_low": max(0.0, mean - half), "ci_high": min(1.0, mean + half), "sd": sd, "n_seeds": n}
