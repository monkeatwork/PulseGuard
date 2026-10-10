"""Per-profile episode-length distribution of a generated corpus
(REMEDIATION_TASK.md A4): a sequence model must not be able to separate the
classes by counting events, so the ranges must overlap materially. Writes
the distribution and a pairwise overlap table to JSON.

    python -m benchmark.generator.episode_lengths --events data/generated/events.parquet \
        --out eval/results/episode_lengths.json
"""

from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd


def length_table(events: pd.DataFrame) -> pd.DataFrame:
    labelled = events[events["burst_id"].notna()]
    prompts = labelled[labelled["event_type"] == "mfa_prompt"]
    per_episode = prompts.groupby("burst_id").size().rename("n_prompts").reset_index()
    per_episode["profile"] = per_episode["burst_id"].str.split(":").str[-2]
    return per_episode


def summarise(per_episode: pd.DataFrame) -> dict:
    profiles = {}
    for profile, group in per_episode.groupby("profile"):
        n = group["n_prompts"].to_numpy()
        profiles[profile] = {
            "episodes": int(len(n)),
            "min": int(n.min()), "p5": float(np.percentile(n, 5)), "median": float(np.median(n)),
            "p95": float(np.percentile(n, 95)), "max": int(n.max()),
            "histogram": {int(k): int(v) for k, v in zip(*np.unique(n, return_counts=True))},
        }
    overlap = {}
    for a, b in itertools.combinations(sorted(profiles), 2):
        lo = max(profiles[a]["p5"], profiles[b]["p5"])
        hi = min(profiles[a]["p95"], profiles[b]["p95"])
        span = max(profiles[a]["p95"], profiles[b]["p95"]) - min(profiles[a]["p5"], profiles[b]["p5"])
        overlap[f"{a} | {b}"] = round(max(0.0, hi - lo) / span, 3) if span else 1.0
    return {
        "unit": "prompts per episode (generator burst_id)",
        "profiles": profiles,
        "pairwise_overlap_of_p5_p95_ranges": overlap,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    events = pd.read_parquet(args.events, columns=["burst_id", "event_type"])
    result = summarise(length_table(events))
    Path(args.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for profile, s in result["profiles"].items():
        print(f"{profile:30s} n={s['episodes']:6d} prompts min={s['min']} p5={s['p5']:.0f} median={s['median']:.0f} p95={s['p95']:.0f} max={s['max']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
