"""One-time migration script to prefix existing Redis keys with NEST:main|.

Usage:
    python migrate_keys.py              # Dry-run (default)
    python migrate_keys.py --execute    # Actually perform migration

The script uses SCAN to find keys matching known prefixes, then copies them
to their NEST:main| equivalents using DUMP+RESTORE+DEL (safe if destination
already exists -- it will skip with a warning rather than overwrite).
"""
import argparse
import logging
import os

import redis

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

# All known key prefix patterns that need migration
SCAN_PATTERNS = [
    'MISC|*',
    'QUEUE|*',
    'FILTER|*',
    'BENDER|*',
    'QUEUEJAM|*',
    'COMMENTS|*',
    'FILL-INFO|*',
    'AIRHORNS',
    'FREEHORN_*',
]

# Keys that must NOT be migrated (global, not nest-scoped)
GLOBAL_KEYS = {
    'MISC|spotify-rate-limited',
}

# Keys managed by NestManager (also global)
NEST_MANAGER_PREFIXES = ('NESTS|',)

DEST_PREFIX = 'NEST:main|'


def _should_skip(key):
    """Return True if the key should NOT be migrated."""
    if key in GLOBAL_KEYS:
        return True
    if key.startswith('NEST:'):
        return True
    for prefix in NEST_MANAGER_PREFIXES:
        if key.startswith(prefix):
            return True
    return False


def migrate(redis_client=None, dry_run=True):
    """Migrate all legacy Redis keys to NEST:main| prefix.

    Args:
        redis_client: Optional Redis connection. If None, connects using
                      environment variables or defaults.
        dry_run: If True, log what would be done without making changes.

    Returns:
        dict with counts: {'migrated': N, 'skipped': N, 'already_exists': N}
    """
    if redis_client is None:
        host = os.environ.get('REDIS_HOST', 'localhost')
        port = int(os.environ.get('REDIS_PORT', 6379))
        password = os.environ.get('REDIS_PASSWORD') or None
        redis_client = redis.StrictRedis(
            host=host, port=port, password=password, decode_responses=False
        )

    stats = {'migrated': 0, 'skipped': 0, 'already_exists': 0}

    # Collect all keys matching our patterns
    keys_to_migrate = set()
    for pattern in SCAN_PATTERNS:
        cursor = 0
        while True:
            cursor, found_keys = redis_client.scan(cursor, match=pattern, count=200)
            for k in found_keys:
                if isinstance(k, bytes):
                    k = k.decode('utf-8', errors='replace')
                keys_to_migrate.add(k)
            if cursor == 0:
                break

    logger.info("Found %d candidate keys to migrate", len(keys_to_migrate))

    for key in sorted(keys_to_migrate):
        if _should_skip(key):
            logger.debug("SKIP (global/nested): %s", key)
            stats['skipped'] += 1
            continue

        dest_key = DEST_PREFIX + key

        # Check if destination already exists
        if redis_client.exists(dest_key):
            logger.warning("SKIP (destination exists): %s -> %s", key, dest_key)
            stats['already_exists'] += 1
            continue

        if dry_run:
            logger.info("DRY-RUN: would migrate %s -> %s", key, dest_key)
            stats['migrated'] += 1
            continue

        # Use DUMP+RESTORE+DEL for safe copy-then-delete
        try:
            # Encode key for raw Redis commands
            raw_key = key.encode('utf-8') if isinstance(key, str) else key
            raw_dest = dest_key.encode('utf-8') if isinstance(dest_key, str) else dest_key

            dump_data = redis_client.dump(raw_key)
            if dump_data is None:
                logger.debug("SKIP (expired/gone): %s", key)
                stats['skipped'] += 1
                continue

            ttl_ms = redis_client.pttl(raw_key)
            if ttl_ms is None or ttl_ms < 0:
                ttl_ms = 0  # No expiry

            redis_client.restore(raw_dest, ttl_ms, dump_data)
            redis_client.delete(raw_key)
            logger.info("MIGRATED: %s -> %s (ttl=%dms)", key, dest_key, ttl_ms)
            stats['migrated'] += 1
        except redis.exceptions.ResponseError as e:
            if 'BUSYKEY' in str(e):
                logger.warning("SKIP (destination appeared): %s -> %s", key, dest_key)
                stats['already_exists'] += 1
            else:
                logger.error("ERROR migrating %s: %s", key, e)
                stats['skipped'] += 1
        except Exception as e:
            logger.error("ERROR migrating %s: %s", key, e)
            stats['skipped'] += 1

    logger.info(
        "Migration complete: migrated=%d, skipped=%d, already_exists=%d",
        stats['migrated'], stats['skipped'], stats['already_exists']
    )
    return stats


def main():
    parser = argparse.ArgumentParser(description='Migrate Redis keys to NEST:main| prefix')
    parser.add_argument('--execute', action='store_true',
                        help='Actually perform migration (default is dry-run)')
    parser.add_argument('--redis-host', default=os.environ.get('REDIS_HOST', 'localhost'))
    parser.add_argument('--redis-port', type=int, default=int(os.environ.get('REDIS_PORT', 6379)))
    parser.add_argument('--redis-password', default=os.environ.get('REDIS_PASSWORD'))
    args = parser.parse_args()

    r = redis.StrictRedis(
        host=args.redis_host,
        port=args.redis_port,
        password=args.redis_password or None,
        decode_responses=False
    )

    dry_run = not args.execute
    if dry_run:
        logger.info("DRY-RUN mode (use --execute to actually migrate)")
    else:
        logger.info("EXECUTE mode -- keys will be migrated!")

    migrate(redis_client=r, dry_run=dry_run)


if __name__ == '__main__':
    main()
