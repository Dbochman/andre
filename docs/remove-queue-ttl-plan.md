# Plan: Remove Queue Song TTL

> **Status:** Revised draft
> **Author:** Claude + Dylan
> **Date:** 2026-03-10

## Motivation

Queue song hashes (`QUEUE|{id}`) currently expire after 24 hours, but the queue index (`MISC|priority-queue`) does not. When the system is paused long enough, the hash expires first and the sorted-set entry survives, creating ghost queue rows and forcing `_purge_stale_queue_entries()` to repair the mismatch on read.

That is the wrong ownership model. Queue song state should live until one of these things happens:

- the song finishes playing
- the song is removed from the queue
- the queue is cleared
- the nest is deleted

Removing TTL from queue-song state is still the right direction, but the implementation has to fix the current cleanup gaps first. Today, TTL is masking some real bugs.

## Goals

- Remove TTL from queue-scoped per-song state for newly queued songs.
- Make deletion explicit and centralized.
- Preserve paused queues across deploys and across 24+ hour pauses.
- Keep a safety net for queue/hash mismatches while the new cleanup path proves itself.

## Non-Goals

- Changing the semantics of `kill_playing()` / skip.
- Changing whether `nuke_queue()` affects the currently playing song. It should continue to clear only the queued songs.
- Removing every stale-key safety net immediately. We can simplify later once the explicit lifecycle is stable.
- Sweeping adjacent `master_player()` cleanup quirks into this change. Those are tracked separately in [`docs/master-player-follow-up-plan.md`](/Users/dylanbochman/repos/EchoNest/docs/master-player-follow-up-plan.md).

## Current State

### TTL-Related Key Inventory

| Key Pattern | Type | TTL | Set At | Current Cleanup |
|---|---|---|---|---|
| `QUEUE\|{id}` | hash | 24h on create, 3h on pop to now-playing | `set_song_in_queue()` / `pop_next()` | TTL or partial explicit cleanup |
| `QUEUE\|VOTE\|{id}` | set | 24h | `_add_song()` | TTL or `master_player()` |
| `QUEUEJAM\|{id}` | sorted set | 24h | `jam()` | TTL only |
| `QUEUEJAM_TB\|{id}` | set | 24h | `benderqueue()`, `ensure_queue_depth()` | TTL only |
| `COMMENTS\|{id}` | sorted set | 24h | `add_comment()` | TTL only |
| `MISC\|priority-queue` | sorted set | none | queue add paths | `kill_song()`, `nuke_queue()`, `pop_next()` |

### Important Existing Gaps

These are the issues the TTL removal plan must address, not just document:

1. `master_player()` currently cleans up by `song['trackid']`, not by queue song ID.
   Current code sets `id = song['trackid']` and then deletes `QUEUE|{id}` and `QUEUE|VOTE|{id}`. Those keys are actually keyed by queue item ID, not Spotify URI.

2. When a stale `now-playing` song is detected, `master_player()` logs it as finished and advances, but does not explicitly delete that song's queue state before moving on.
   TTL eventually covers that today. Without TTL, those keys become permanent orphans.

3. The draft `nuke_queue()` rewrite is race-prone.
   Reading song IDs, then clearing the sorted set, then deleting per-song keys is not atomic. A concurrent add can be removed from the queue without being included in the deletion list.

### Current Defensive Workaround

`_purge_stale_queue_entries()` scans the priority queue and removes IDs whose `QUEUE|{id}` hash is missing. It is called from:

- `get_queued()`
- `ensure_queue_depth()`

That helper is still useful during rollout, but it should become a bug detector, not the primary lifecycle mechanism.

## Proposed Design

### Phase 0: Introduce Shared Per-Song Cleanup Helpers

Before removing any TTLs, centralize the key ownership model in one place.

Add two helpers in `db.py`:

```python
def _song_state_keys(self, song_id):
    sid = str(song_id)
    return [
        self._key('QUEUE|{0}'.format(sid)),
        self._key('QUEUE|VOTE|{0}'.format(sid)),
        self._key('QUEUEJAM|{0}'.format(sid)),
        self._key('QUEUEJAM_TB|{0}'.format(sid)),
        self._key('COMMENTS|{0}'.format(sid)),
    ]

def _delete_song_state(self, song_id, client=None):
    client = client or self._r
    keys = self._song_state_keys(song_id)
    if keys:
        client.delete(*keys)
```

Why this is required:

- It avoids duplicating the key list in `kill_song()`, `nuke_queue()`, and `master_player()`.
- It prevents the plan from fixing some cleanup paths but missing others.
- It gives migration and tests one canonical definition of queue-scoped per-song state.

### Phase 1: Remove TTL from New Writes

Once explicit cleanup exists, remove TTL from these write paths:

- `set_song_in_queue()`:
  - remove `expire(QUEUE|{id}, 24h)`
- `pop_next()`:
  - remove `expire(QUEUE|{id}, 3h)`
- `_add_song()`:
  - remove `expire(QUEUE|VOTE|{id}, 24h)`
- `jam()`:
  - remove `expire(QUEUEJAM|{id}, 24h)`
- `benderqueue()`:
  - remove `expire(QUEUEJAM_TB|{id}, 24h)`
- `ensure_queue_depth()`:
  - remove `expire(QUEUEJAM_TB|{id}, 24h)`
- `add_comment()`:
  - remove `expire(COMMENTS|{id}, 24h)`

### Phase 2: Make Cleanup Explicit and Correct

#### 2.1 `kill_song()`

After `ZREM`, explicitly delete all song-scoped state via `_delete_song_state(id)`.

That closes the current orphan-hash/orphan-comment/orphan-jam leak for manual queue removals.

#### 2.2 `master_player()` normal completion

Fix the existing key bug and use the queue song ID, not `trackid`.

Required change:

- keep `song_id = song['id']` alongside `track_id = song['trackid']`
- continue emitting progress updates with `track_id`
- run `_delete_song_state(song_id)` after the song completes

This is a prerequisite even if TTL removal were not happening, because the current cleanup path is deleting the wrong keys.

#### 2.3 `master_player()` stale `now-playing` reconciliation

When `get_now_playing()` returns a song but `MISC|current-done` is absent or expired, the code currently does this:

1. `log_finished_song(song)`
2. `song = pop_next()`

That branch also needs explicit cleanup of the old queue song before advancing:

```python
previous = song
if previous and previous.get('id'):
    self.log_finished_song(previous)
    self._delete_song_state(previous['id'])
```

This covers restart/recovery cases where the current track has already ended by the time the worker loop regains control.

### Phase 3: Make `nuke_queue()` Atomic

The previous draft proposed:

1. `ZRANGE`
2. `ZREMRANGEBYRANK`
3. delete keys for the snapshotted IDs

That is not safe under concurrent queue writes.

Recommended implementation: use `WATCH` / `MULTI` retry, matching the style already used in `_add_song()`.

Pseudo-code:

```python
def nuke_queue(self, email):
    self._check_nest_active()
    queue_key = self._key('MISC|priority-queue')
    while True:
        pipe = self._r.pipeline()
        try:
            pipe.watch(queue_key)
            song_ids = pipe.zrange(queue_key, 0, -1)

            pipe.multi()
            if song_ids:
                keys = []
                for sid in song_ids:
                    keys.extend(self._song_state_keys(sid))
                pipe.delete(*keys)
            pipe.delete(queue_key)
            pipe.execute()
            break
        except redis.WatchError:
            continue
        finally:
            pipe.reset()
    self._msg('playlist_update')
```

Properties:

- if another writer changes the queue between snapshot and delete, the transaction retries
- songs added after the clear begins are not silently dropped without cleanup
- the current behavior remains intact: queued songs are cleared, `now-playing` is not

Lua would also work, but `WATCH` / `MULTI` is simpler for this codebase and easier to test with the current Redis usage patterns.

### Phase 4: Keep `_purge_stale_queue_entries()` as a Safety Net

Do not remove `_purge_stale_queue_entries()` in the same change.

Recommended adjustment:

- keep the current behavior
- change the docstring and log message to reflect that stale queue rows are now unexpected
- optionally raise the log level from `warning` to `error`

Example:

```python
def _purge_stale_queue_entries(self):
    """Safety net for queue/hash mismatches. Should be rare once TTL is removed."""
```

This still protects the app if:

- old TTL-backed keys expire before migration runs
- an unexpected bug deletes a hash without removing the sorted-set member

### Phase 5: Run a One-Time Migration for Active Songs

The original draft's "do nothing" migration is too weak. It leaves a 24-hour window where already-queued songs can still disappear from a paused queue after deploy.

Instead, run a one-time `PERSIST` migration for active song IDs.

Migration strategy:

1. Iterate nests from the registry, or derive nests from `NEST:*|MISC|priority-queue`.
2. For each nest, collect:
   - all IDs in `MISC|priority-queue`
   - `MISC|now-playing` if present
3. For each collected song ID, call `PERSIST` on every key returned by `_song_state_keys(song_id)`.

Why this shape:

- it covers active queued songs
- it also covers the currently playing song, which is no longer in the queue sorted set
- it avoids scanning and persisting unrelated historical/orphan keys

Pseudo-code:

```python
for nest_id in all_nest_ids():
    db = DB(nest_id=nest_id)
    song_ids = set(db._r.zrange(db._key('MISC|priority-queue'), 0, -1))
    now_playing = db._r.get(db._key('MISC|now-playing'))
    if now_playing:
        song_ids.add(now_playing)

    for sid in song_ids:
        for key in db._song_state_keys(sid):
            if db._r.ttl(key) > 0:
                db._r.persist(key)
```

Recommendation:

- add a temporary script under `scripts/`
- run it once during deploy, before or immediately after the application rollout
- remove the script later if it is truly one-off

### Phase 6: Documentation Updates

Update:

- `CLAUDE.md`
- `docs/bender-queue-logic.md`
- `docs/changelog.md`

Do not reference `MEMORY.md`; there is no such file in this repo.

The docs should explicitly say:

- queue-scoped per-song keys have no TTL
- cleanup is explicit
- `_purge_stale_queue_entries()` remains as a safety net during rollout

## Testing Plan

### Automated Tests

Add or update tests for these cases:

1. `set_song_in_queue()` creates `QUEUE|{id}` with no TTL.
2. `_add_song()` creates `QUEUE|VOTE|{id}` with no TTL.
3. `jam()` / `add_comment()` / throwback jam paths create keys with no TTL.
4. `kill_song()` deletes all five per-song key families.
5. `nuke_queue()` deletes all per-song state for queued songs.
6. `master_player()` cleanup deletes by queue song ID, not `trackid`.
7. stale `now-playing` reconciliation deletes prior song state before advancing.
8. migration script persists active queue song keys and active now-playing song keys.

### Manual Smoke Test

1. Add a song to the queue.
2. Verify `TTL NEST:main|QUEUE|{id}` returns `-1`.
3. Pause the system, leave it paused longer than the old 24-hour TTL window.
4. Verify the queued song is still present after unpause.
5. Remove a queued song and verify `QUEUE|`, `QUEUE|VOTE|`, `QUEUEJAM|`, `QUEUEJAM_TB|`, and `COMMENTS|` are gone.
6. Clear the queue and verify queued-song state is removed while the current song, if any, is unaffected.
7. Let a song finish and verify all per-song state is removed.
8. Simulate stale `now-playing` recovery and verify the old song state is cleaned before the next track starts.

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Missed cleanup path leaves orphaned song keys | Medium | Low | Shared `_delete_song_state()` helper + targeted tests |
| `nuke_queue()` races with add/remove operations | Medium | High | `WATCH` / `MULTI` retry instead of snapshot + blind delete |
| Existing TTL-backed songs still expire after deploy | High without migration | Medium | Required one-time `PERSIST` migration for active songs |
| Recovery path after interrupted playback leaks keys | Medium | Medium | Explicit cleanup in stale `now-playing` branch |
| `_purge_stale_queue_entries()` still fires after rollout | Low | Low | Keep as safety net and treat logs as bug reports |

## Summary of Changes

| File | Changes |
|---|---|
| `db.py` | Add `_song_state_keys()` and `_delete_song_state()`, remove queue-song TTL calls, fix `master_player()` cleanup, add explicit stale-`now-playing` cleanup, make `kill_song()` explicit, rework `nuke_queue()` with `WATCH` / `MULTI` |
| `scripts/*` | Add one-time migration script to `PERSIST` active queue-song keys |
| `CLAUDE.md` | Update Redis lifecycle documentation |
| `docs/bender-queue-logic.md` | Replace TTL-mismatch explanation with explicit lifecycle description |
| `docs/changelog.md` | Add rollout note and rationale |

**Deployment:** deploy code + run one-time migration script. Do not rely on “old keys will expire naturally.”

## Related Follow-Up

Additional `master_player()` cleanup and recovery work discovered during this plan review is tracked separately in [`docs/master-player-follow-up-plan.md`](/Users/dylanbochman/repos/EchoNest/docs/master-player-follow-up-plan.md). That follow-up covers shared player-state cleanup, explicit short-track handling, empty-queue Bender retry backoff, resolving `MISC|now-playing-done`, and improving nest cleanup queue counting.
