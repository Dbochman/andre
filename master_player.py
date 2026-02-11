#!/usr/bin/env python
"""Master player worker: drives playback for all active nests and cleans up inactive ones."""

import datetime
import logging
import time

import gevent

from db import DB
from nests import NestManager, should_delete_nest, count_active_members

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def master_player_tick_all(nest_manager=None, poll_interval=5):
    """Supervisor loop: discover nests and keep a player greenlet per nest.

    Every *poll_interval* seconds the loop re-fetches the nest list, spawns
    greenlets for newly discovered nests, kills greenlets for removed nests,
    and cleans up dead greenlets.

    Args:
        nest_manager: Optional NestManager instance. If None, creates one.
        poll_interval: Seconds between nest-list refreshes (default 5).
    """
    if nest_manager is None:
        nest_manager = NestManager()

    active_greenlets = {}  # nest_id -> gevent.Greenlet

    while True:
        try:
            current_nests = {nid for nid, _ in nest_manager.list_nests()}

            # Spawn for new nests
            for nid in current_nests - set(active_greenlets):
                logger.info("Discovered new nest %s — spawning player", nid)
                active_greenlets[nid] = gevent.spawn(_run_nest_player, nid)

            # Kill greenlets for removed nests
            for nid in set(active_greenlets) - current_nests:
                logger.info("Nest %s removed — killing player greenlet", nid)
                active_greenlets.pop(nid).kill()

            # Clean up dead greenlets so they can be re-spawned next cycle
            for nid in list(active_greenlets):
                if active_greenlets[nid].dead:
                    logger.warning("Player greenlet for nest %s died — will respawn", nid)
                    del active_greenlets[nid]

        except Exception:
            logger.exception("Error in master_player supervisor loop")

        gevent.sleep(poll_interval)


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

                # Count active members (prunes stale entries from MEMBERS set)
                member_count = count_active_members(nest_manager._r, nest_id)

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

    # Both loops run forever — run them as concurrent greenlets
    greenlets = [
        gevent.spawn(master_player_tick_all, nest_manager=nm),
        gevent.spawn(nest_cleanup_loop, nest_manager=nm, interval_seconds=60),
    ]
    gevent.joinall(greenlets)


if __name__ == '__main__':
    main()
