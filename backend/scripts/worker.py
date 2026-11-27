"""Submit approved enrollments in the background.

    python -m scripts.worker            # keep going, checking every 20 seconds
    python -m scripts.worker --once     # one pass, then exit (for a scheduled job)
    python -m scripts.worker --once --purge   # also erase personal data past RETENTION_DAYS

Each pass first returns enrollments left half-way by a stopped worker to the queue, then submits up to --limit
approved ones, oldest first. Several workers can run at once: each submission is locked.
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from app.config import get_settings
from app.services import build, setup_logging
from app.submit.runner import InFlight, NotReady

log = logging.getLogger("worker")


async def one_pass(limit: int, purge_old: bool = False) -> int:
    settings = get_settings()
    services = await build(settings)
    try:
        if purge_old:
            from app.maintenance import purge
            from app.security.crypto import FieldCipher
            erased = await purge(services.pool, FieldCipher.from_setting(settings.encryption_keys),
                                 settings.retention_days)
            log.info("erased personal data of %d finished enrollment(s)", len(erased))
        recovered = await services.runs.interrupted(900)
        if recovered:
            log.info("returned %d interrupted submission(s) to the queue", len(recovered))
        rows = await services.pool.fetch("SELECT enrollment_id FROM enrollments WHERE status = 'approved' "
                                         "ORDER BY updated_at LIMIT $1", limit)
        for row in rows:
            e = await services.enrollments.get(row["enrollment_id"])
            if e is None:
                continue
            try:
                result = await services.submitter.submit(e, "worker")
            except (NotReady, InFlight):
                continue
            log.info("%s: %s %s (%s, %d attempt(s))", result.enrollment_id, result.status,
                     result.confirmation_ref or "", result.path, result.attempts)
        return len(rows)
    finally:
        await services.aclose()


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=20.0)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--purge", action="store_true", help="also apply the retention period")
    args = parser.parse_args()
    setup_logging()
    while True:
        done = await one_pass(args.limit, args.purge)
        if args.once:
            break
        if done == 0:
            await asyncio.sleep(args.interval)


if __name__ == "__main__":
    asyncio.run(main())
