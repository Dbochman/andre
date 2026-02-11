#!/usr/bin/env python
"""Master player worker: drives playback for all active nests and cleans up inactive ones."""

import datetime
import logging
import time

import gevent

from db import DB
from nests import NestManager, should_delete_nest, members_key

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def master_player_tick_all(nest_manager=None):
    """Run one master_player tick for every active nest.

    Spawns a greenlet per nest so they run concurrently. Each greenlet
    creates its own DB instance scoped to that nest and calls master_player().

    Args:
        nest_manager: Optional NestManager instance. If None, creates one.
    """
    if nest_manager is None:
        nest_manager = NestManager()

    nests = nest_manager.list_nests()
    greenlets = []
    for nest_id, _meta in nests:
        g = gevent.spawn(_run_nest_player, nest_id)
        greenlets.append(g)

    # Wait for all nest players (they run indefinitely)
    gevent.joinall(greenlets)


def _run_nest_player(nest_id):
    """Run the master_player loop for a single nest."""
    logger.info("Starting master player for nest: %s", nest_id)
    try:
        d = DB(nest_id=nest_id)
        d.master_player()
    except Exception:
        logger.exception("master_player crashed for nest %s", nest_id)


def nest_cleanup_loop(nest_manager=None, interval_seconds=60):
    """Periodically check for inactive nests and delete them.

    Runs in a loop, checking every `interval_seconds`. Uses the
    `should_delete_nest()` predicate from nests.py to decide which
    nests to clean up. The main nest is never deleted.

    Args:
        nest_manager: Optional NestManager instance. If None, creates one.
        interval_seconds: How often to run cleanup (default 60s).
    """
    if nest_manager is None:
        nest_manager = NestManager()

    while True:
        try:
            nests = nest_manager.list_nests()
            now = datetime.datetime.now()

            for nest_id, metadata in nests:
                # Never delete the main nest (also handled by should_delete_nest,
                # but skip early to avoid unnecessary work)
                if metadata.get('is_main'):
                    continue

                # Count active members
                mkey = members_key(nest_id)
                member_count = nest_manager._r.scard(mkey)

                # Count queue size
                queue_key = f"NEST:{nest_id}|MISC|priority-queue"
                queue_size = nest_manager._r.zcard(queue_key)

                if should_delete_nest(metadata, member_count, queue_size, now):
                    logger.info(
                        "Cleaning up nest %s (members=%d, queue=%d, last_activity=%s)",
                        nest_id, member_count, queue_size,
                        metadata.get('last_activity', 'unknown')
                    )
                    nest_manager.delete_nest(nest_id)

        except Exception:
            logger.exception("Error during nest cleanup loop")

        time.sleep(interval_seconds)


def main():
    """Start the master player for all nests with a cleanup worker."""
    try:
        nm = NestManager()
    except Exception:
        logger.exception("Failed to initialize NestManager, falling back to single-nest mode")
        d = DB()
        d.master_player()
        return

    # Spawn cleanup loop in a greenlet
    cleanup_greenlet = gevent.spawn(nest_cleanup_loop, nest_manager=nm, interval_seconds=60)

    # Run master player for all nests
    try:
        master_player_tick_all(nest_manager=nm)
    except Exception:
        logger.exception("master_player_tick_all failed")
    finally:
        cleanup_greenlet.kill()


if __name__ == '__main__':
    main()
