# Plan: Remove Queue Song TTL

> **Status:** Draft
> **Author:** Claude + Dylan
> **Date:** 2026-03-08

## Motivation

Queue song hashes (`QUEUE|{id}`) currently have a 24-hour TTL. This creates a fundamental architectural mismatch: the `MISC|priority-queue` sorted set has no TTL, so when the system is paused for >24 hours, hashes expire while their IDs remain — creating "ghost entries." The existing fix (`_purge_stale_queue_entries()`) is a defensive workaround, not a solution.

Removing the TTL eliminates the mismatch entirely. Songs stay in the queue until they are played, removed, or the nest is deleted — which is the correct semantic.

### Why TTL Existed

The 24-hour TTL was a Redis hygiene habit to prevent unbounded key growth, not an intentional feature. In practice:

- Each `QUEUE|{id}` hash is ~500 bytes. Even 10,000 orphaned songs = ~5MB — negligible for Redis.
- The actual song lifecycle (play, kill, nuke, nest cleanup) already covers all real removal cases.
- The TTL causes more bugs than it prevents (ghost entries, stale purge overhead, songs vanishing from paused queues).

## Current State

### TTL-Related Code Inventory

| Key Pattern | Type | TTL | Set At | Cleanup |
|---|---|---|---|---|
| `QUEUE\|{id}` | hash | 24h | `set_song_in_queue()` db.py:1566 | `master_player()` db.py:1011 or TTL expiry |
| `QUEUE\|VOTE\|{id}` | sorted set | 24h | `_add_song()` db.py:1135 | `master_player()` db.py:1010 or TTL expiry |
| `QUEUEJAM\|{id}` | sorted set | 24h | `jam()` db.py:1449, `ensure_queue_depth()` db.py:762 | TTL expiry only |
| `QUEUEJAM_TB\|{id}` | set | 24h | `benderqueue()` db.py:1507, `ensure_queue_depth()` db.py:762 | TTL expiry only |
| `COMMENTS\|{id}` | sorted set | 24h | `add_comment()` db.py:1465 | TTL expiry only |
| `MISC\|priority-queue` | sorted set | None | Various add methods | `kill_song()`, `nuke_queue()`, `pop_next()` |

### Current Song Lifecycle

```
add_spotify_song() → _add_song() → set_song_in_queue() [creates hash, 24h TTL]
                                  → zadd priority-queue [adds to sorted set]
                                  → sadd VOTE key [24h TTL]

pop_next()          → zrange + zrem priority-queue [removes from sorted set]
                    → expire QUEUE hash to 3h [extends for playback]
                    → sets now-playing state

master_player()     → delete QUEUE|{id} [explicit cleanup after song finishes]
                    → delete QUEUE|VOTE|{id}

kill_song()         → zrem priority-queue [removes from sorted set only]
                    → hash left to TTL-expire ← BUG: orphaned hash

nuke_queue()        → zremrangebyrank priority-queue [clears sorted set only]
                    → hashes left to TTL-expire ← BUG: orphaned hashes

nest delete_nest()  → SCAN + UNLINK all NEST:{id}|* keys [nuclear cleanup]
```

### Defensive Workaround

`_purge_stale_queue_entries()` scans the entire sorted set and checks each hash for existence. Called in:
- `get_queued()` (db.py:1638) — before rendering queue
- `ensure_queue_depth()` (db.py:742) — before Bender backfill

This is O(n) per call with n Redis `EXISTS` commands. Works, but unnecessary if hashes never expire.

## Proposed Changes

### Phase 1: Remove TTL from Queue Hashes

#### 1.1 — Remove TTL on song creation

**File:** `db.py` — `set_song_in_queue()` (line 1566)

```python
# REMOVE this line:
client.expire(key, 24*60*60)
```

#### 1.2 — Remove TTL refresh on now-playing

**File:** `db.py` — `pop_next()` (line 1676)

```python
# REMOVE this line:
self._r.expire(self._key('QUEUE|{0}'.format(song)), 3*60*60)
```

The hash no longer needs a TTL refresh since it won't expire.

### Phase 2: Add Explicit Cleanup to kill_song() and nuke_queue()

These methods currently only remove the sorted set entry, leaving hashes to TTL-expire. Without TTL, we must clean up explicitly.

#### 2.1 — kill_song() cleanup

**File:** `db.py` — `kill_song()` (lines 1573-1576)

```python
def kill_song(self, id, email):
    self._check_nest_active()
    self._r.zrem(self._key('MISC|priority-queue'), id)
    # Explicitly delete the song hash and associated keys
    self._r.delete(
        self._key('QUEUE|{0}'.format(id)),
        self._key('QUEUE|VOTE|{0}'.format(id)),
        self._key('QUEUEJAM|{0}'.format(id)),
        self._key('QUEUEJAM_TB|{0}'.format(id)),
        self._key('COMMENTS|{0}'.format(id)),
    )
    self._msg('playlist_update')
```

#### 2.2 — nuke_queue() cleanup

**File:** `db.py` — `nuke_queue()` (lines 1568-1571)

```python
def nuke_queue(self, email):
    self._check_nest_active()
    # Get all song IDs before clearing the sorted set
    song_ids = self._r.zrange(self._key('MISC|priority-queue'), 0, -1)
    self._r.zremrangebyrank(self._key('MISC|priority-queue'), 0, -1)
    # Delete all associated keys for each song
    if song_ids:
        keys_to_delete = []
        for sid in song_ids:
            keys_to_delete.extend([
                self._key('QUEUE|{0}'.format(sid)),
                self._key('QUEUE|VOTE|{0}'.format(sid)),
                self._key('QUEUEJAM|{0}'.format(sid)),
                self._key('QUEUEJAM_TB|{0}'.format(sid)),
                self._key('COMMENTS|{0}'.format(sid)),
            ])
        self._r.delete(*keys_to_delete)
    self._msg('playlist_update')
```

#### 2.3 — master_player() cleanup (already correct)

The `master_player()` method at db.py:1009-1011 already explicitly deletes `QUEUE|{id}` and `QUEUE|VOTE|{id}` after a song finishes. Extend it to also clean up jam/throwback/comment keys:

```python
# After song finishes (db.py ~line 1009-1011):
self._r.delete(self._key('MISC|current-done'))
self._r.delete(self._key('QUEUE|VOTE|{0}'.format(id)))
self._r.delete(self._key('QUEUE|{0}'.format(id)))
# ADD:
self._r.delete(self._key('QUEUEJAM|{0}'.format(id)))
self._r.delete(self._key('QUEUEJAM_TB|{0}'.format(id)))
self._r.delete(self._key('COMMENTS|{0}'.format(id)))
```

### Phase 3: Remove TTL from Associated Keys

Vote, jam, throwback, and comment keys also have 24-hour TTLs. Since these are tied to the song lifecycle, they should follow the same pattern: explicit cleanup, no TTL.

#### 3.1 — Vote key TTL

**File:** `db.py` — `_add_song()` (line 1135)

```python
# REMOVE this line:
pipe.expire(vote_key, 24*60*60)
```

#### 3.2 — Jam key TTL

**File:** `db.py` — `jam()` (line 1449)

```python
# REMOVE this line:
self._r.expire(queued_song_jams_key, 24*60*60)
```

#### 3.3 — Throwback jam key TTL

**File:** `db.py` — `benderqueue()` (line 1507) and `ensure_queue_depth()` (line 762)

```python
# REMOVE these lines:
self._r.expire(tb_key, 24*60*60)
```

#### 3.4 — Comment key TTL

**File:** `db.py` — `add_comment()` (line 1465)

```python
# REMOVE this line:
self._r.expire(comments_key, 24*60*60)
```

### Phase 4: Simplify _purge_stale_queue_entries()

With no TTL, hashes should never go missing unless there's a bug. Two options:

#### Option A: Keep as safety net (recommended for now)

Downgrade from "expected behavior" to "bug detector." Change the log level from `warning` to `error` so it's noticeable if it ever fires:

```python
def _purge_stale_queue_entries(self):
    """Safety net: detect queue/hash inconsistencies (should never happen without TTL)."""
    queue_key = self._key('MISC|priority-queue')
    song_ids = self._r.zrange(queue_key, 0, -1)
    stale = [sid for sid in song_ids if not self._r.exists(self._key('QUEUE|{0}'.format(sid)))]
    if stale:
        logger.error("BUG: Found %d orphaned queue entries (no TTL — this shouldn't happen): %s",
                      len(stale), stale)
        self._r.zrem(queue_key, *stale)
    return len(song_ids) - len(stale)
```

#### Option B: Remove entirely

Delete `_purge_stale_queue_entries()` and its two call sites. Replace with direct `zrange` calls. Simpler but loses the safety net.

### Phase 5: Update Documentation

#### 5.1 — CLAUDE.md

Update the "Redis Data" section (line ~137):

```
- `QUEUE|{id}` hashes have no TTL — they are explicitly deleted when a song
  finishes playing (`master_player`), is removed (`kill_song`), queue is cleared
  (`nuke_queue`), or nest is deleted. `_purge_stale_queue_entries()` remains as
  a bug-detection safety net.
```

#### 5.2 — docs/bender-queue-logic.md

Remove or update the section about the TTL mismatch (lines 80-84).

#### 5.3 — docs/changelog.md

Add entry documenting the change and rationale.

#### 5.4 — MEMORY.md

Update the "Redis TTL mismatch" known issue to reflect the fix.

## Migration

### Existing Songs in Redis

Songs already in the queue will have TTLs set. Two options:

1. **Do nothing.** They'll either get played (explicit delete) or expire naturally (24h). The purge safety net handles any edge case. This is the simplest approach.

2. **One-time PERSIST.** Run a script to remove TTL from all existing `QUEUE|*` keys:
   ```python
   for key in r.scan_iter("NEST:*|QUEUE|*"):
       if r.ttl(key) > 0:
           r.persist(key)
   ```

**Recommendation:** Option 1 (do nothing). Within 24 hours of deploy, all old keys will have expired naturally or been played. No migration needed.

## Testing

### Manual Smoke Test

1. Add a song to the queue
2. Verify `redis-cli TTL NEST:main|QUEUE|{id}` returns `-1` (no TTL)
3. Pause the system for a few minutes
4. Unpause — song should still be in queue
5. Kill a song — verify the hash is deleted (`EXISTS` returns 0)
6. Nuke queue — verify all hashes are deleted
7. Let a song play through — verify cleanup after completion

### Automated Tests

- Existing tests in `test/test_nests.py` create queue hashes directly and should still pass
- Add a test verifying `kill_song()` deletes associated keys
- Add a test verifying `nuke_queue()` deletes associated keys

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Orphaned hashes accumulate | Low | Low (~500B each) | Safety net purge + nest cleanup |
| Bug in explicit cleanup misses keys | Low | Low (memory only) | Nest `SCAN + UNLINK` catches all |
| Regression in Bender backfill logic | Low | Medium | `_purge_stale_queue_entries()` stays as safety net |

## Summary of Changes

| File | Changes |
|---|---|
| `db.py` | Remove 6 `expire()` calls, add explicit `delete()` in `kill_song()`, `nuke_queue()`, `master_player()`, update `_purge_stale_queue_entries()` log level |
| `CLAUDE.md` | Update Redis Data section |
| `docs/bender-queue-logic.md` | Update TTL mismatch section |
| `docs/changelog.md` | Add entry |

**Lines changed (estimated):** ~30 modified, ~10 added, ~6 removed

**Deployment:** Standard `make deploy`. No migration script needed.
