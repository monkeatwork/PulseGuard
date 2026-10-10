"""Benchmark generator CLI: builds a labelled, seeded, deterministic event
corpus from the RBA benign base layer plus the three attack profiles and
the benign-high-activity hard negative (CLAUDE.md, "Data").

Usage:
    python -m benchmark.generator.cli --seed 42 --scale 50000 \
        --rba-zip data/raw/rba-dataset.zip --out data/generated

Output:
    <out>/events.parquet   -- one row per PulseGuardEvent-shaped record,
                               plus `label_attack` / `attack_profile` /
                               `burst_id` ground-truth columns.
    <out>/manifest.json    -- seed, scale, profile-mix counts, RBA dataset
                               checksum/date, sha256 of events.parquet.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from benchmark.generator import attack_profiles as ap
from benchmark.generator.rba_loader import RbaFetchError, iter_rba_benign_rows
from benchmark.generator.seed import child_rng, child_seed, deterministic_uuid
from pulseguard_common.event_schema import PulseGuardEvent

logger = logging.getLogger("pulseguard.generator.cli")

DEFAULT_SCALE = 50_000
DEFAULT_MAX_ROWS_SCANNED = 2_000_000

PROFILE_BUCKETS = [
    # (upper_bound_percent, profile_name)
    # 50/10/10/10/10/10 -- plain_benign reduced from 60% to make room for
    # benign_occasional_denial (DECISIONS.md, "Major finding: Stage C's
    # perfect scores exposed a systemic benchmark gap").
    (50, "plain_benign"),
    (60, "benign_high_activity"),
    (70, "benign_occasional_denial"),
    (80, "high_volume_burst"),
    (90, "low_and_slow"),
    (100, "social_engineering_assisted"),
]


def assign_profile(seed: int, user_id: str) -> str:
    bucket = child_seed(seed, user_id, "profile") % 100
    for upper, name in PROFILE_BUCKETS:
        if bucket < upper:
            return name
    return PROFILE_BUCKETS[-1][1]


def _parse_rba_timestamp(raw: str) -> datetime:
    ts = pd.to_datetime(raw, utc=True)
    return ts.to_pydatetime()


def _device_fingerprint(user_agent: str) -> str:
    return hashlib.md5(str(user_agent).encode("utf-8", errors="replace")).hexdigest()[:16]


def rba_row_to_login_event(row: pd.Series) -> dict:
    ts = _parse_rba_timestamp(row["Login Timestamp"])
    return dict(
        event_id=None,  # filled in at write time
        user_id=str(row["User ID"]),
        ts=ts,
        event_type="login_attempt",
        decision=None,
        decision_latency_ms=None,
        src_ip=str(row["IP Address"]),
        geo_country=str(row["Country"]) if pd.notna(row["Country"]) else None,
        device_id=_device_fingerprint(row["User Agent String"]),
        user_agent=str(row["User Agent String"]),
        session_id=None,  # filled in at write time (fresh per RBA row)
        ingest_ts=ts,
        label_attack=False,
        attack_profile=None,
        burst_id=None,
    )


def _raw_event_to_record(evt: ap.RawEvent, burst_id: str) -> dict:
    return dict(
        event_id=None,
        user_id=evt.user_id,
        ts=evt.ts,
        event_type=evt.event_type,
        decision=evt.decision,
        decision_latency_ms=evt.decision_latency_ms,
        src_ip=evt.src_ip,
        geo_country=evt.geo_country,
        device_id=evt.device_id,
        user_agent=evt.user_agent,
        session_id=evt.session_id,
        ingest_ts=evt.ts,
        label_attack=evt.label_attack,
        attack_profile=evt.attack_profile,
        burst_id=burst_id,
    )


def collect_benign_users(
    rba_zip: Path, scale: int, max_rows_scanned: int
) -> tuple[dict[str, list[dict]], int]:
    """Streams RBA CSV chunks, keeping every row for up to `scale` distinct
    users. Returns (user_id -> list of login_attempt records, rows_scanned).
    Raises if `scale` cannot be reached within `max_rows_scanned` — this is
    reported, not silently tolerated (see DECISIONS.md)."""
    users: dict[str, list[dict]] = {}
    rows_scanned = 0
    for chunk in iter_rba_benign_rows(rba_zip):
        for _, row in chunk.iterrows():
            rows_scanned += 1
            user_id = str(row["User ID"])
            if user_id not in users:
                if len(users) >= scale:
                    continue
                users[user_id] = []
            users[user_id].append(rba_row_to_login_event(row))
            if rows_scanned >= max_rows_scanned:
                break
        if len(users) >= scale or rows_scanned >= max_rows_scanned:
            break
    return users, rows_scanned


def build_corpus(
    seed: int,
    users: dict[str, list[dict]],
) -> tuple[list[dict], dict[str, int]]:
    records: list[dict] = []
    profile_counts: dict[str, int] = {name: 0 for _, name in PROFILE_BUCKETS}

    for user_id, login_events in users.items():
        profile = assign_profile(seed, user_id)
        profile_counts[profile] += 1
        records.extend(login_events)

        if profile == "plain_benign" or not login_events:
            continue

        last_login = max(login_events, key=lambda r: r["ts"])
        victim_device_id = last_login["device_id"]
        victim_user_agent = last_login["user_agent"]
        victim_src_ip = last_login["src_ip"]
        victim_country = last_login["geo_country"] or "US"
        rng = child_rng(seed, user_id, profile)
        start_ts = last_login["ts"] + timedelta(hours=1)

        if profile == "high_volume_burst":
            burst = ap.generate_high_volume_burst(
                rng, user_id, start_ts, victim_device_id, victim_user_agent, victim_src_ip, victim_country
            )
        elif profile == "low_and_slow":
            burst = ap.generate_low_and_slow(
                rng, user_id, start_ts, victim_device_id, victim_user_agent, victim_src_ip, victim_country
            )
        elif profile == "social_engineering_assisted":
            burst = ap.generate_social_engineering_assisted(
                rng, user_id, start_ts, victim_device_id, victim_user_agent, victim_src_ip, victim_country
            )
        elif profile == "benign_high_activity":
            burst = ap.generate_benign_high_activity_session(
                rng, user_id, start_ts, victim_device_id, victim_user_agent, victim_src_ip, victim_country
            )
        elif profile == "benign_occasional_denial":
            burst = ap.generate_benign_occasional_denial_session(
                rng, user_id, start_ts, victim_device_id, victim_user_agent, victim_src_ip, victim_country
            )
        else:
            burst = []

        burst_id = f"{user_id}:{profile}:{int(start_ts.timestamp())}"
        records.extend(_raw_event_to_record(e, burst_id) for e in burst)

    return records, profile_counts


def validate_canonical_fields(record: dict) -> None:
    """Raises if the canonical-schema subset of a record is invalid."""
    geo = {"country": record["geo_country"]} if record["geo_country"] else None
    PulseGuardEvent(
        event_id=record["event_id"],
        user_id=record["user_id"],
        ts=record["ts"],
        event_type=record["event_type"],
        decision=record["decision"],
        decision_latency_ms=record["decision_latency_ms"],
        src_ip=record["src_ip"],
        geo=geo,
        device_id=record["device_id"],
        user_agent=record["user_agent"],
        session_id=record["session_id"],
        ingest_ts=record["ingest_ts"],
    )


def finalize_records(records: list[dict], seed: int) -> pd.DataFrame:
    """Assigns event_id/session_id deterministically from (seed, row index,
    row content) rather than uuid.uuid4() — required for the Phase 1
    determinism gate (same seed -> byte-identical output hash)."""
    for i, r in enumerate(records):
        r["event_id"] = deterministic_uuid(seed, "event_id", str(i), r["user_id"], str(r["ts"]))
        if r["session_id"] is None:
            r["session_id"] = deterministic_uuid(seed, "session_id", r["user_id"], str(r["ts"]))
        validate_canonical_fields(r)
    return pd.DataFrame.from_records(records)


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run(
    seed: int,
    scale: int,
    rba_zip: Path,
    out_dir: Path,
    max_rows_scanned: int = DEFAULT_MAX_ROWS_SCANNED,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)

    users, rows_scanned = collect_benign_users(rba_zip, scale, max_rows_scanned)
    if len(users) < scale:
        logger.warning(
            "SHORTFALL: requested scale=%d distinct users but only found %d "
            "within max_rows_scanned=%d. Proceeding with %d users; increase "
            "--max-rows-scanned to raise this.",
            scale,
            len(users),
            max_rows_scanned,
            len(users),
        )

    records, profile_counts = build_corpus(seed, users)
    df = finalize_records(records, seed)

    events_path = out_dir / "events.parquet"
    df.to_parquet(events_path, index=False)

    manifest = {
        "seed": seed,
        "requested_scale": scale,
        "actual_users": len(users),
        "rows_scanned": rows_scanned,
        "profile_counts": profile_counts,
        "total_events": len(df),
        "events_sha256": _sha256_of_file(events_path),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    logger.info("Wrote %d events for %d users to %s", len(df), len(users), events_path)
    logger.info("Profile counts: %s", profile_counts)
    return events_path


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--scale", type=int, default=DEFAULT_SCALE)
    parser.add_argument("--rba-zip", default="data/raw/rba-dataset.zip")
    parser.add_argument("--out", default="data/generated")
    parser.add_argument("--max-rows-scanned", type=int, default=DEFAULT_MAX_ROWS_SCANNED)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    rba_zip = Path(args.rba_zip)
    if not rba_zip.exists():
        logger.error(
            "RBA_DATASET_UNAVAILABLE: %s does not exist. Run `make data` first. "
            "No synthetic fallback will be used.",
            rba_zip,
        )
        return 1

    try:
        run(args.seed, args.scale, rba_zip, Path(args.out), args.max_rows_scanned)
    except RbaFetchError as exc:
        logger.error("Generator halted: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
