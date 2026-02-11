"""Nests helpers and manager.

This module provides helper functions for nest key generation, membership
tracking, and cleanup logic, plus the NestManager class for CRUD operations.
"""
import datetime
import json
import logging
import os
import random

import redis

from config import CONF

logger = logging.getLogger(__name__)

# Character set for nest codes: unambiguous uppercase + digits (no 0/O/1/I/L)
CODE_CHARS = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'


# ---------------------------------------------------------------------------
# Pure helper functions
# ---------------------------------------------------------------------------

def _nest_prefix(nest_id):
    """Return the Redis key prefix for a given nest."""
    return f"NEST:{nest_id}|"


# Legacy key mapping: maps old bare keys to their NEST:main| equivalents
# Used by migrate_keys.py and tests
legacy_key_mapping = {
    "MISC|now-playing": "NEST:main|MISC|now-playing",
    "MISC|priority-queue": "NEST:main|MISC|priority-queue",
    "MISC|current-done": "NEST:main|MISC|current-done",
    "MISC|started-on": "NEST:main|MISC|started-on",
    "MISC|paused": "NEST:main|MISC|paused",
    "MISC|force-jump": "NEST:main|MISC|force-jump",
    "MISC|master-player": "NEST:main|MISC|master-player",
    "MISC|player-now": "NEST:main|MISC|player-now",
    "MISC|playlist-plays": "NEST:main|MISC|playlist-plays",
    "MISC|last-queued": "NEST:main|MISC|last-queued",
    "MISC|last-bender-track": "NEST:main|MISC|last-bender-track",
    "MISC|bender_streak_start": "NEST:main|MISC|bender_streak_start",
    "MISC|now-playing-done": "NEST:main|MISC|now-playing-done",
    "MISC|last-played": "NEST:main|MISC|last-played",
    "MISC|volume": "NEST:main|MISC|volume",
    "MISC|update-pubsub": "NEST:main|MISC|update-pubsub",
    "MISC|backup-queue": "NEST:main|MISC|backup-queue",
    "MISC|backup-queue-data": "NEST:main|MISC|backup-queue-data",
    "MISC|guest-login": "NEST:main|MISC|guest-login",
    "MISC|guest-login-expire": "NEST:main|MISC|guest-login-expire",
    "AIRHORNS": "NEST:main|AIRHORNS",
}


def pubsub_channel(nest_id):
    """Return the pub/sub channel name for a given nest."""
    return f"NEST:{nest_id}|MISC|update-pubsub"


def members_key(nest_id):
    """Return the Redis key for the set of members in a nest."""
    return f"NEST:{nest_id}|MEMBERS"


def member_key(nest_id, email):
    """Return the Redis key for an individual member's heartbeat TTL."""
    return f"NEST:{nest_id}|MEMBER:{email}"


def deleting_key(nest_id):
    """Return the Redis key for the nest deletion-in-progress flag."""
    return f"NEST:{nest_id}|DELETING"


def is_nest_deleting(redis_client, nest_id):
    """Check whether a nest is currently being deleted."""
    return redis_client.exists(deleting_key(nest_id)) == 1


def refresh_member_ttl(redis_client, nest_id, email, ttl_seconds=90):
    """Set/refresh a member's heartbeat TTL key.

    Args:
        redis_client: Redis connection (caller provides, e.g. db._r)
        nest_id: The nest identifier
        email: Member's email address
        ttl_seconds: TTL in seconds (default 90)
    """
    key = member_key(nest_id, email)
    redis_client.setex(key, ttl_seconds, "1")


def count_active_members(redis_client, nest_id):
    """Count active members by checking heartbeat TTL keys, pruning stale ones.

    Members in the MEMBERS set whose TTL key has expired are removed
    from the set. Returns the count of still-active members.

    Args:
        redis_client: Redis connection
        nest_id: The nest identifier

    Returns:
        int: Number of active members
    """
    mkey = members_key(nest_id)
    emails = redis_client.smembers(mkey)
    stale = []
    for email in emails:
        mk = member_key(nest_id, email)
        # Use ttl() instead of exists(): a key with TTL <= 0 or missing is stale
        if redis_client.ttl(mk) <= 0:
            stale.append(email)
    for email in stale:
        redis_client.srem(mkey, email)
    return len(emails) - len(stale)


def should_delete_nest(metadata, members, queue_size, now):
    """Determine whether a nest should be cleaned up.

    Args:
        metadata: dict with keys 'is_main', 'last_activity' (ISO string),
                  'ttl_minutes' (int)
        members: int count of active members
        queue_size: int count of songs in queue
        now: datetime.datetime representing current time

    Returns:
        True if the nest should be deleted, False otherwise.
    """
    # Never delete the main nest
    if metadata.get("is_main"):
        return False

    # Don't delete if there are active members
    if members > 0:
        return False

    # Don't delete if there are songs in the queue
    if queue_size > 0:
        return False

    # Check inactivity timeout
    last_activity_str = metadata.get("last_activity")
    ttl_minutes = metadata.get("ttl_minutes", getattr(CONF, 'NEST_MAX_INACTIVE_MINUTES', 5))

    if last_activity_str:
        last_activity = datetime.datetime.fromisoformat(last_activity_str)
        elapsed = (now - last_activity).total_seconds() / 60.0
        if elapsed >= ttl_minutes:
            return True

    return False


# ---------------------------------------------------------------------------
# NestManager class
# ---------------------------------------------------------------------------

# Global registry key (NOT nest-scoped)
_REGISTRY_KEY = 'NESTS|registry'


def _code_key(code):
    """Return the Redis key for a nest code lookup (global, NOT nest-scoped)."""
    return f'NESTS|code:{code}'


class NestManager:
    """Manages nest lifecycle: create, read, update, delete.

    Uses Redis hash at NESTS|registry for nest metadata and
    NESTS|code:{code} for code-to-nest_id lookup.
    """

    def __init__(self, redis_client=None):
        if redis_client is not None:
            self._r = redis_client
        else:
            redis_host = os.environ.get('REDIS_HOST', 'localhost')
            redis_port = int(os.environ.get('REDIS_PORT', 6379))
            redis_password = os.environ.get('REDIS_PASSWORD') or None
            self._r = redis.StrictRedis(
                host=redis_host, port=redis_port,
                password=redis_password, decode_responses=True
            )
        # Ensure main nest exists in registry
        self._ensure_main_nest()

    def _ensure_main_nest(self):
        """Initialize the main nest in the registry if not present."""
        existing = self._r.hget(_REGISTRY_KEY, 'main')
        if not existing:
            metadata = {
                'nest_id': 'main',
                'code': 'main',
                'name': 'Home Nest',
                'creator': 'system',
                'is_main': True,
                'created_at': datetime.datetime.now().isoformat(),
                'last_activity': datetime.datetime.now().isoformat(),
                'ttl_minutes': 0,  # Never expires
            }
            self._r.hset(_REGISTRY_KEY, 'main', json.dumps(metadata))

    def generate_code(self, length=5):
        """Generate a unique 5-character nest code.

        Uses CODE_CHARS (unambiguous chars) and checks for collisions.
        """
        for _ in range(100):  # Max attempts to avoid infinite loop
            code = ''.join(random.choice(CODE_CHARS) for _ in range(length))
            # Check if code is already in use
            if not self._r.exists(_code_key(code)):
                return code
        raise RuntimeError("Could not generate unique nest code after 100 attempts")

    def create_nest(self, creator_email, name=None):
        """Create a new nest.

        Args:
            creator_email: Email of the creator
            name: Optional name for the nest

        Returns:
            dict with nest metadata including 'code'
        """
        code = self.generate_code()
        nest_id = code  # Use code as nest_id for simplicity

        now = datetime.datetime.now().isoformat()
        metadata = {
            'nest_id': nest_id,
            'code': code,
            'name': name or f'Nest {code}',
            'creator': creator_email,
            'is_main': False,
            'created_at': now,
            'last_activity': now,
            'ttl_minutes': getattr(CONF, 'NEST_MAX_INACTIVE_MINUTES', 5),
        }

        # Store in registry hash (nest_id -> JSON metadata)
        self._r.hset(_REGISTRY_KEY, nest_id, json.dumps(metadata))
        # Store code lookup (code -> nest_id)
        self._r.set(_code_key(code), nest_id)

        return metadata

    def get_nest(self, nest_id):
        """Get nest metadata by nest_id (which is also the code).

        Returns dict or None if not found.
        """
        raw = self._r.hget(_REGISTRY_KEY, nest_id)
        if raw:
            return json.loads(raw)

        # Try looking up by code
        looked_up_id = self._r.get(_code_key(nest_id))
        if looked_up_id:
            raw = self._r.hget(_REGISTRY_KEY, looked_up_id)
            if raw:
                return json.loads(raw)

        return None

    def list_nests(self):
        """List all registered nests.

        Returns list of (nest_id, metadata_dict) tuples.
        """
        all_data = self._r.hgetall(_REGISTRY_KEY)
        result = []
        for nest_id, raw_meta in all_data.items():
            try:
                meta = json.loads(raw_meta)
                # Add member count
                mkey = members_key(nest_id)
                meta['member_count'] = self._r.scard(mkey)
                result.append((nest_id, meta))
            except (json.JSONDecodeError, TypeError):
                logger.warning("Invalid metadata for nest %s", nest_id)
                continue
        return result

    def delete_nest(self, nest_id):
        """Delete a nest and all its Redis keys.

        Sets a DELETING flag (30s TTL) to prevent writes during cleanup,
        then removes all nest keys using non-blocking unlink().

        Args:
            nest_id: The nest to delete
        """
        if nest_id == "main":
            logger.warning("Attempted to delete main nest — ignoring")
            return

        # Set DELETING flag with 30s TTL (auto-expires on crash)
        self._r.setex(deleting_key(nest_id), 30, "1")

        # Get metadata to find the code
        raw = self._r.hget(_REGISTRY_KEY, nest_id)
        if raw:
            try:
                meta = json.loads(raw)
                code = meta.get('code', nest_id)
                self._r.delete(_code_key(code))
            except (json.JSONDecodeError, TypeError):
                pass

        # Remove from registry
        self._r.hdel(_REGISTRY_KEY, nest_id)

        # SCAN and unlink all NEST:{nest_id}|* keys (non-blocking)
        prefix = _nest_prefix(nest_id)
        cursor = 0
        while True:
            cursor, keys = self._r.scan(cursor, match=f"{prefix}*", count=200)
            if keys:
                self._r.unlink(*keys)
            if cursor == 0:
                break

        # Clean up the DELETING flag itself
        self._r.delete(deleting_key(nest_id))

    def touch_nest(self, nest_id):
        """Update the last_activity timestamp for a nest."""
        raw = self._r.hget(_REGISTRY_KEY, nest_id)
        if raw:
            try:
                meta = json.loads(raw)
                meta['last_activity'] = datetime.datetime.now().isoformat()
                self._r.hset(_REGISTRY_KEY, nest_id, json.dumps(meta))
            except (json.JSONDecodeError, TypeError):
                pass

    def join_nest(self, nest_id, email):
        """Add a member to a nest's MEMBERS set and broadcast update."""
        mkey = members_key(nest_id)
        self._r.sadd(mkey, email)
        self.touch_nest(nest_id)
        self._broadcast_member_update(nest_id)

    def leave_nest(self, nest_id, email):
        """Remove a member from a nest's MEMBERS set and delete TTL key."""
        mkey = members_key(nest_id)
        self._r.srem(mkey, email)
        # Also delete the member TTL key
        mk = member_key(nest_id, email)
        self._r.delete(mk)
        self._broadcast_member_update(nest_id)

    def _broadcast_member_update(self, nest_id):
        """Publish member_update event with current count on the nest's pubsub channel."""
        try:
            mkey = members_key(nest_id)
            count = self._r.scard(mkey)
            channel = pubsub_channel(nest_id)
            self._r.publish(channel, f"member_update|{count}")
        except Exception:
            logger.exception("Failed to broadcast member_update for nest %s", nest_id)


# ---------------------------------------------------------------------------
# Default NestManager instance (lazy-initialized)
# ---------------------------------------------------------------------------

_default_manager = None


def _get_default_manager():
    """Get or create the default NestManager instance."""
    global _default_manager
    if _default_manager is None:
        _default_manager = NestManager()
    return _default_manager


# ---------------------------------------------------------------------------
# Module-level join/leave wrappers
# ---------------------------------------------------------------------------

def join_nest(nest_id, email):
    """Add a member to a nest. Delegates to default NestManager."""
    return _get_default_manager().join_nest(nest_id, email)


def leave_nest(nest_id, email):
    """Remove a member from a nest. Delegates to default NestManager."""
    return _get_default_manager().leave_nest(nest_id, email)
