"""Shared test fixtures."""
import os

import pytest
import redis


@pytest.fixture
def flush_redis():
    """Connect to a dedicated Redis test DB and flush before/after test.

    Uses DB index 15 by default (configurable via TEST_REDIS_DB env var).
    Not autouse — only activates when explicitly requested by a test.

    Yields the Redis connection for direct use.
    """
    db_index = int(os.environ.get("TEST_REDIS_DB", 15))
    r = redis.StrictRedis(
        host=os.environ.get("REDIS_HOST", "localhost"),
        port=int(os.environ.get("REDIS_PORT", 6379)),
        db=db_index,
        decode_responses=True,
    )
    r.flushdb()
    yield r
    r.flushdb()
