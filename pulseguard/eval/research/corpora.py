"""Builds benchmark corpora in memory for the research experiments, with the
generator's own functions (cli.collect_benign_users / build_corpus /
finalize_records), so a corpus here is exactly what
`cli.py --seed S --scale N --fatigue-...` would write to disk.

The RBA benign users depend only on `scale` (the loader does not use the
seed), so they are read from the 1.1 GB zip once and cached as a pickle under
data/generated_research/. Every corpus gets a deep copy: finalize_records
fills ids into the record dicts in place, and a second corpus built from
the same dicts would otherwise inherit the first one's session ids.
"""

from __future__ import annotations

import copy
import io
import logging
import pickle
from pathlib import Path

import pandas as pd

from benchmark.generator.cli import DEFAULT_MAX_ROWS_SCANNED, build_corpus, collect_benign_users, finalize_records
from benchmark.generator.latency_models import FatigueConfig

logger = logging.getLogger("pulseguard.eval.research.corpora")

CACHE_DIR = Path("data/generated_research")


def load_users(rba_zip: Path, scale: int, cache_dir: Path = CACHE_DIR) -> dict[str, list[dict]]:
    cache = cache_dir / f"rba_users_{scale}.pkl"
    if cache.exists():
        with cache.open("rb") as f:
            return pickle.load(f)
    users, rows = collect_benign_users(rba_zip, scale, DEFAULT_MAX_ROWS_SCANNED)
    logger.info("Collected %d RBA users from %d rows", len(users), rows)
    cache_dir.mkdir(parents=True, exist_ok=True)
    with cache.open("wb") as f:
        pickle.dump(users, f)
    return users


def build_events(users: dict[str, list[dict]], seed: int, fatigue: FatigueConfig) -> pd.DataFrame:
    """The corpus as the pipeline sees it: written to parquet and read back
    (a round trip changes dtypes, e.g. None -> NaN in attack_profile), but in
    memory instead of on disk."""
    records, _ = build_corpus(seed, copy.deepcopy(users), fatigue)
    buffer = io.BytesIO()
    finalize_records(records, seed).to_parquet(buffer, index=False)
    buffer.seek(0)
    return pd.read_parquet(buffer)
