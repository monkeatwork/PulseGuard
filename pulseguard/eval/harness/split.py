"""By-user train/val/test split (CLAUDE.md, evaluation rule #1: split by
user, never by event — event-level splits leak per-user baseline state
across the split and inflate every metric).

Deterministic via MD5(seed:user_id) bucketing, per DECISIONS.md ("Train/test
split"): 70/15/15, stable across reruns without storing split assignments.
This module is frozen after Phase 2 and reused verbatim by every later
phase — do not reimplement splitting logic elsewhere.
"""

from __future__ import annotations

import hashlib
from typing import Iterable, Literal

Split = Literal["train", "val", "test"]

TRAIN_PCT = 70
VAL_PCT = 15
# remaining 15% -> test


def assign_split(seed: int, user_id: str) -> Split:
    bucket = int(hashlib.md5(f"{seed}:{user_id}".encode()).hexdigest(), 16) % 100
    if bucket < TRAIN_PCT:
        return "train"
    if bucket < TRAIN_PCT + VAL_PCT:
        return "val"
    return "test"


def split_users(seed: int, user_ids: Iterable[str]) -> dict[Split, list[str]]:
    out: dict[Split, list[str]] = {"train": [], "val": [], "test": []}
    for user_id in user_ids:
        out[assign_split(seed, user_id)].append(user_id)
    return out


def verify_no_leakage(split_map: dict[Split, list[str]]) -> None:
    """Raises ValueError if any user_id appears in more than one split."""
    seen: set[str] = set()
    for split_name, users in split_map.items():
        users_set = set(users)
        overlap = seen & users_set
        if overlap:
            raise ValueError(f"Users leaked across splits: {sorted(overlap)[:10]}...")
        seen |= users_set
