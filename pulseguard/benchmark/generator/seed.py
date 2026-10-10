"""Deterministic seeding for the benchmark generator.

Every random draw in the generator must trace back to a single seed so that
`cli.py --seed N` run twice produces byte-identical output (Phase 1 gate).
"""

from __future__ import annotations

import hashlib
import uuid

import numpy as np


def make_rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def child_seed(seed: int, *parts: str) -> int:
    """Derive a deterministic child seed for a sub-stream (e.g. per user_id),
    so per-user generation is reproducible independent of iteration order."""
    digest = hashlib.sha256(f"{seed}:{':'.join(parts)}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def child_rng(seed: int, *parts: str) -> np.random.Generator:
    return np.random.default_rng(child_seed(seed, *parts))


def deterministic_uuid(seed: int, *parts: str) -> str:
    """A UUID derived purely from (seed, parts) — used anywhere an id must
    be reproducible byte-for-byte across two runs with the same seed
    (e.g. event_id). Never use uuid.uuid4() in generator code paths."""
    digest = hashlib.sha256(f"{seed}:{':'.join(parts)}".encode()).digest()
    return str(uuid.UUID(bytes=digest[:16]))
