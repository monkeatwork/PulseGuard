"""Cuts the small demo corpus that ships with the repository
(data/demo/demo_events.parquet), so the live demo never needs the 1.1 GB RBA
download: a fixed number of labelled episodes per profile, drawn ONLY from
TEST-split users (never data any model was trained or tuned on), chosen
deterministically from the seed, spread across each profile's length range.

    python -m benchmark.generator.demo_slice --events data/generated/events.parquet \
        --seed 42 --out data/demo/demo_events.parquet
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import pandas as pd

from eval.harness.split import assign_split

PER_PROFILE = 12
COLUMNS = ["event_id", "user_id", "ts", "event_type", "decision", "decision_latency_ms", "src_ip",
           "geo_country", "device_id", "user_agent", "session_id", "ingest_ts", "label_attack",
           "attack_profile", "burst_id"]


def pick(events: pd.DataFrame, seed: int, per_profile: int = PER_PROFILE) -> list[str]:
    labelled = events[events["burst_id"].notna()]
    meta = labelled.groupby("burst_id").agg(user_id=("user_id", "first"), n=("ts", "size")).reset_index()
    meta = meta[meta["user_id"].map(lambda u: assign_split(seed, u) == "test")]
    meta["profile"] = meta["burst_id"].str.split(":").str[-2]
    meta["key"] = meta["burst_id"].map(lambda b: hashlib.md5(f"{seed}:{b}".encode()).hexdigest())
    chosen = []
    for _, group in meta.groupby("profile"):
        group = group.sort_values(["n", "key"]).reset_index(drop=True)
        if len(group) <= per_profile:
            chosen += group["burst_id"].tolist()
            continue
        # evenly spaced through the length-sorted list: short, typical and long episodes
        idx = [round(i * (len(group) - 1) / (per_profile - 1)) for i in range(per_profile)]
        chosen += group.loc[sorted(set(idx)), "burst_id"].tolist()
    return chosen


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    events = pd.read_parquet(args.events)
    chosen = pick(events, args.seed)
    out = events[events["burst_id"].isin(chosen)][COLUMNS].sort_values(["burst_id", "ts"])
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(args.out, index=False)
    print(f"{len(chosen)} episodes, {len(out)} events -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
