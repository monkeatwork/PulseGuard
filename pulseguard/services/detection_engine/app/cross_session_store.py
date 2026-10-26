"""Redis-backed state and persisted configuration for the cross-session
guard (cross_session_guard.py holds the pure counting logic).

State: two sorted sets per user (pulseguard_common.redis_keys), member =
event id, score = event time. Event id as the member makes a redelivered
Kafka message a no-op, so the count under redelivery equals the count
without it. Entries older than the guard's horizon behind the user's
newest decision are trimmed on every write, by EVENT time: replayed
historical events carry old IdP timestamps. A wall-clock TTL on the keys is
only a backstop against abandoned users.

Configuration: `model_registry/cross_session_guard.json`, written from
eval/results/cross_session.json by `python -m
services.detection_engine.app.cross_session_store` (make guard-config). The
live service refuses to start without it, as it does without the operating
point: the guard runs at exactly the K and window selected on the
validation users, or not at all.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from pulseguard_common.redis_keys import guard_approvals_key, guard_denials_key
from services.detection_engine.app.cross_session_guard import (
    CrossSessionGuardConfig,
    DenialHistory,
    unresolved_denials,
)

CONFIG_FILENAME = "cross_session_guard.json"
# Backstop only; trimming by event time keeps the sets small.
KEY_TTL_PADDING_SECONDS = 24 * 3600


class GuardConfigMissing(RuntimeError):
    pass


def save_guard_config(config: CrossSessionGuardConfig, path: Path, provenance: dict) -> None:
    path.write_text(json.dumps({**config.as_dict(), "provenance": provenance}, indent=2) + "\n")


def load_guard_config(path: Path) -> CrossSessionGuardConfig:
    if not path.exists():
        raise GuardConfigMissing(f"{path} not found (run `make guard-config`)")
    raw = json.loads(path.read_text())
    if raw.get("provenance", {}).get("selected_on") != "val":
        raise GuardConfigMissing(f"{path} was not selected on the validation split")
    return CrossSessionGuardConfig(
        min_denials=int(raw["min_denials"]),
        window_seconds=int(raw["window_seconds"]),
        resolve_seconds=int(raw["resolve_seconds"]),
    )


def config_from_results(results: dict) -> tuple[CrossSessionGuardConfig, dict]:
    chosen = results["chosen_config"]
    selection = results["selection"]
    provenance = {
        "selected_on": "val",
        "source": "eval/results/cross_session.json",
        "chosen": results["chosen"],
        "seed": results["seed"],
        "scale": results["scale"],
        "stray_rate": selection["stray_rate"],
        "val_fpr_budget": selection["val_fpr_budget"],
        "slow_gaps_seconds": selection["slow_gaps_seconds"],
    }
    return CrossSessionGuardConfig(**chosen), provenance


def _epoch(ts: datetime) -> float:
    return (ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)).timestamp()


def _from_epoch(score: float) -> datetime:
    return datetime.fromtimestamp(score, tz=timezone.utc)


class RedisDenialStore:
    def __init__(self, client, config: CrossSessionGuardConfig):
        self.client = client
        self.config = config

    def record(self, user_id: str, ts: datetime, decision: str, event_id: str | None) -> int:
        """Stores one MFA decision and returns the user's unresolved-denial
        count at `ts` (the decision itself never counts: a denial is
        unresolved only once `resolve_seconds` have passed)."""
        denials_key, approvals_key = guard_denials_key(user_id), guard_approvals_key(user_id)
        key = denials_key if decision == "deny" else approvals_key
        member = event_id or ts.isoformat()
        ttl = self.config.horizon_seconds + KEY_TTL_PADDING_SECONDS

        pipe = self.client.pipeline()
        pipe.zadd(key, {member: _epoch(ts)})
        pipe.expire(key, ttl)
        pipe.zrevrange(denials_key, 0, 0, withscores=True)
        pipe.zrevrange(approvals_key, 0, 0, withscores=True)
        _, _, newest_denial, newest_approval = pipe.execute()

        newest = max(score for _, score in newest_denial + newest_approval)
        horizon = newest - self.config.horizon_seconds
        pipe = self.client.pipeline()
        pipe.zremrangebyscore(denials_key, "-inf", f"({horizon}")
        pipe.zremrangebyscore(approvals_key, "-inf", f"({horizon}")
        pipe.zrangebyscore(denials_key, horizon, "+inf", withscores=True)
        pipe.zrangebyscore(approvals_key, horizon, "+inf", withscores=True)
        _, _, denials, approvals = pipe.execute()

        history = DenialHistory(
            denials=[_from_epoch(s) for _, s in denials],
            approvals=[_from_epoch(s) for _, s in approvals],
        )
        return unresolved_denials(history, ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc), self.config)

    def fired(self, count: int) -> bool:
        return count >= self.config.min_denials


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Write model_registry/cross_session_guard.json from the evaluation")
    parser.add_argument("--results", default="eval/results/cross_session.json")
    parser.add_argument("--model-dir", default="services/detection_engine/app/model_registry")
    args = parser.parse_args(argv)
    config, provenance = config_from_results(json.loads(Path(args.results).read_text()))
    out = Path(args.model_dir) / CONFIG_FILENAME
    save_guard_config(config, out, provenance)
    print(f"{out}: {config.as_dict()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
