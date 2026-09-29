from __future__ import annotations

import argparse
import json
import os
import socket
import time

from .config import Settings
from .container import build_container


def main() -> None:
    parser = argparse.ArgumentParser(description="Process Nebula One outbox tasks.")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--worker-id")
    parser.add_argument("--lease-seconds", type=int, default=60)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    args = parser.parse_args()
    if not 0.05 <= args.poll_seconds <= 60:
        raise SystemExit("poll-seconds must be between 0.05 and 60")
    worker_id = (
        (args.worker_id or "").strip()
        or os.getenv("NEBULA_ONE_WORKER_ID", "").strip()
        or f"{socket.gethostname()}:{os.getpid()}"
    )
    container = build_container(Settings.from_env())
    try:
        container.database.prepare_schema()
        while True:
            event = container.worker.process_one(
                worker_id=worker_id,
                lease_seconds=args.lease_seconds,
            )
            if event is not None:
                print(
                    json.dumps(
                        {
                            "event_id": event.id,
                            "topic": event.topic,
                            "aggregate_id": event.aggregate_id,
                            "status": event.status,
                            "attempt_count": event.attempt_count,
                        },
                        separators=(",", ":"),
                    )
                )
            if args.once:
                return
            if event is None:
                time.sleep(args.poll_seconds)
    finally:
        container.client.close()
        container.database.dispose()


if __name__ == "__main__":
    main()
