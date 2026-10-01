"""The background worker (Phase 5.5): runs scheduled jobs every
`ISD_API_WORKER_INTERVAL_SECONDS` (120), in its own container from the
api image (`worker` in docker-compose). Today that's the bus-time emails
(isd_api/eta_notifications.py); the scheduled SIS sync will join it.

Each job is safe to run twice at once (it records what it did in the
database first), so a restart mid-pass or a second worker does no harm.

Usage: python -m isd_api.worker
"""

from __future__ import annotations

import logging
import signal
import threading
from collections.abc import Callable

from sqlalchemy.orm import Session

from isd_api import eta_notifications
from isd_api.config import settings
from isd_api.db import SessionLocal

logger = logging.getLogger("isd_api.worker")

JOBS: list[tuple[str, Callable[[Session], int]]] = [
    ("bus-time emails", eta_notifications.run),
]


def run_once() -> None:
    for name, job in JOBS:
        db = SessionLocal()
        try:
            done = job(db)
            if done:
                logger.info("%s: %d", name, done)
        except Exception:
            # One failing job mustn't stop the others, or the next pass.
            logger.exception("%s failed", name)
            db.rollback()
        finally:
            db.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    settings.require_production_ready()
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    logger.info("worker started; every %ds", settings.worker_interval_seconds)
    while not stop.is_set():
        run_once()
        stop.wait(settings.worker_interval_seconds)
    logger.info("worker stopped")


if __name__ == "__main__":
    main()
