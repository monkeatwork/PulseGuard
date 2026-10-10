"""One-shot Kafka topic setup (the `kafka-init` compose job): waits for the
broker, then creates every PulseGuard topic with an explicit partition
count, so nothing depends on broker auto-creation defaults.

Multi-partition is now safe (REMEDIATION_TASK.md C4): the feature engine
keeps per-user state in Redis, not a Faust table, so there is no
co-partitioning constraint. Every producer keys by user_id, so one user's
events stay ordered within one partition.
"""

from __future__ import annotations

import os
import sys
import time

from confluent_kafka.admin import AdminClient, NewTopic

TOPICS = {
    "pulseguard.events.raw": 3,
    "pulseguard.events.enriched": 3,
    "pulseguard.alerts": 3,
    "pulseguard.dlq": 1,
}


def main() -> int:
    admin = AdminClient({"bootstrap.servers": os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")})
    deadline = time.monotonic() + 120
    while True:
        try:
            existing = set(admin.list_topics(timeout=5).topics)
            break
        except Exception as exc:  # broker not up yet
            if time.monotonic() > deadline:
                print(f"kafka not reachable: {exc}", file=sys.stderr)
                return 1
            time.sleep(2)
    missing = [NewTopic(name, num_partitions=n, replication_factor=1) for name, n in TOPICS.items() if name not in existing]
    for name, future in admin.create_topics(missing).items() if missing else []:
        future.result()
        print(f"created {name}")
    print("topics ready:", ", ".join(TOPICS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
