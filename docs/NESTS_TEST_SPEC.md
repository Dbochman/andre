# Nests Test Specification

> **SUPERSEDED:** This spec was written before Codex generated the actual tests.
> The canonical test file is `test/test_nests.py` — a single file with xfail
> contract tests (no fakeredis, no multi-file split). See `docs/NESTS_TASKS.md`
> for the authoritative test class → task mapping. This file is kept as a
> reference for test intent but should NOT be used to guide implementation.

This was the original test specification written before Codex generated the actual tests.
Kept as a reference for test intent and coverage ideas.

## What Actually Exists

- **Canonical tests:** `test/test_nests.py` — single file, xfail contract tests, Flask test client
- **Task mapping:** `docs/NESTS_TASKS.md` — maps test classes to implementation tasks
- **No fakeredis** in current tests (may be added during implementation for DB-level unit tests)

**Stop reading here.** Everything below is archived original design that was NOT implemented.
Use `test/test_nests.py` and `docs/NESTS_TASKS.md` as your sources of truth.

---

## Archive: Original Test Design (not implemented)

The following was the original multi-file test design. Codex instead produced
a single `test/test_nests.py` with xfail contract tests. This section is kept
for coverage reference only — do not create these files or follow these patterns.

### File: `test/test_nests_db.py` — DB Key Scoping

### Class: `TestDBKeyMethod`

Tests for the `_key()` prefix method on the DB class.

| Test | Description |
|------|-------------|
| `test_key_default_nest` | `DB()._key('MISC\|now-playing')` returns `'NEST:main\|MISC\|now-playing'` |
| `test_key_custom_nest` | `DB(nest_id='ABC12')._key('MISC\|now-playing')` returns `'NEST:ABC12\|MISC\|now-playing'` |
| `test_key_queue_prefix` | `DB(nest_id='X')._key('QUEUE\|song123')` returns `'NEST:X\|QUEUE\|song123'` |
| `test_key_bender_prefix` | `DB(nest_id='X')._key('BENDER\|cache:genre')` returns `'NEST:X\|BENDER\|cache:genre'` |
| `test_key_filter_prefix` | `DB(nest_id='X')._key('FILTER\|spotify:track:abc')` returns `'NEST:X\|FILTER\|spotify:track:abc'` |

### Class: `TestDBNestIsolation`

Tests that two DB instances with different `nest_id` values read/write to separate keys.
Use `fakeredis` for a real Redis-like environment.

| Test | Description |
|------|-------------|
| `test_separate_queues` | Add song to nest A, verify nest B's queue is empty |
| `test_separate_now_playing` | Set now-playing in nest A, verify nest B has no now-playing |
| `test_separate_volumes` | Set volume in nest A, verify nest B has default volume |
| `test_separate_votes` | Vote in nest A, verify nest B has no votes for that song |
| `test_shared_rate_limit` | Spotify rate limit set globally is visible from both nests |

### Class: `TestDBBackwardCompatibility`

Tests that `DB(nest_id="main")` produces the expected key format and that
existing operations work identically to before the refactor.

| Test | Description |
|------|-------------|
| `test_main_nest_key_format` | Keys start with `NEST:main\|` |
| `test_add_song_to_main` | `add_spotify_song` works on main nest (mock Spotify API) |
| `test_get_queued_main` | `get_queued()` returns songs from main nest |
| `test_pop_next_main` | `pop_next()` pops from main nest queue |
| `test_vote_main` | `vote()` modifies main nest queue order |

---

## File: `test/test_nests_manager.py` — NestManager CRUD

### Class: `TestNestManagerCreate`

| Test | Description |
|------|-------------|
| `test_create_nest_returns_metadata` | Returns dict with `id`, `code`, `name`, `created_by`, `created_at`, `ttl_minutes`, `is_main` |
| `test_create_nest_code_format` | Code is 5 chars, uppercase, from allowed charset `ABCDEFGHJKMNPQRSTUVWXYZ23456789` |
| `test_create_nest_stored_in_registry` | After create, `NESTS\|registry` hash contains the nest |
| `test_create_nest_with_name` | Passing `name="Friday Vibes"` stores the name in metadata |
| `test_create_nest_default_name` | Not passing name results in `None` or `""` (UI defaults to "Nest {CODE}") |
| `test_create_nest_unique_codes` | Creating 100 nests produces 100 unique codes |
| `test_create_nest_collision_retry` | If first code collides, generator retries and succeeds |

### Class: `TestNestManagerGet`

| Test | Description |
|------|-------------|
| `test_get_existing_nest` | Returns metadata for a created nest |
| `test_get_nonexistent_nest` | Returns `None` |
| `test_get_main_nest` | Returns the main nest metadata with `is_main=True` |

### Class: `TestNestManagerList`

| Test | Description |
|------|-------------|
| `test_list_empty` | Returns only main nest when no others exist |
| `test_list_multiple` | Returns all created nests + main |
| `test_list_includes_member_count` | Each entry includes current listener count |

### Class: `TestNestManagerDelete`

| Test | Description |
|------|-------------|
| `test_delete_nest` | Nest removed from registry after delete |
| `test_delete_cleans_redis_keys` | All `NEST:{id}\|*` keys are removed |
| `test_delete_main_nest_fails` | Cannot delete the main nest (raises error or returns False) |
| `test_delete_nonexistent_nest` | No error on deleting nonexistent nest |

### Class: `TestNestManagerMembership`

| Test | Description |
|------|-------------|
| `test_join_adds_member` | `join_nest` adds email to MEMBERS set |
| `test_leave_removes_member` | `leave_nest` removes email from MEMBERS set |
| `test_join_idempotent` | Joining twice doesn't duplicate the member |
| `test_member_count` | After 3 joins and 1 leave, count is 2 |

### Class: `TestNestManagerTouch`

| Test | Description |
|------|-------------|
| `test_touch_updates_last_activity` | `touch_nest` updates `last_activity` in metadata |
| `test_touch_nonexistent` | No error on touching nonexistent nest |

### Class: `TestNestManagerCodeGeneration`

| Test | Description |
|------|-------------|
| `test_code_length` | Generated code is exactly `NEST_CODE_LENGTH` (5) chars |
| `test_code_charset` | All characters are from `ABCDEFGHJKMNPQRSTUVWXYZ23456789` |
| `test_no_ambiguous_chars` | Code never contains `0`, `O`, `1`, `I`, `L` |
| `test_codes_are_random` | Two consecutive codes are different (probabilistic) |

---

## File: `test/test_nests_cleanup.py` — Cleanup Worker

### Class: `TestNestCleanup`

| Test | Description |
|------|-------------|
| `test_inactive_empty_nest_deleted` | Nest with no members, empty queue, past TTL → deleted |
| `test_active_nest_not_deleted` | Nest with members → not deleted regardless of TTL |
| `test_nest_with_queue_not_deleted` | Nest with empty members but songs in queue → not deleted |
| `test_main_nest_never_deleted` | Main nest is never deleted regardless of inactivity |
| `test_recently_active_not_deleted` | Nest within TTL → not deleted even if empty |

---

## File: `test/test_nests_api.py` — REST API Routes

### Class: `TestNestAPICreate`

| Test | Description |
|------|-------------|
| `test_create_nest_authenticated` | `POST /api/nests` with valid session → 201 + nest metadata |
| `test_create_nest_unauthenticated` | `POST /api/nests` without auth → 401 or 302 |
| `test_create_nest_with_name` | `POST /api/nests` with `{"name": "My Nest"}` → name in response |
| `test_create_nest_response_format` | Response includes `code`, `id`, `name`, `created_by` |

### Class: `TestNestAPIList`

| Test | Description |
|------|-------------|
| `test_list_nests` | `GET /api/nests` returns array of active nests |
| `test_list_includes_main` | Response includes main nest |
| `test_list_includes_listener_count` | Each nest has `listener_count` field |

### Class: `TestNestAPIGet`

| Test | Description |
|------|-------------|
| `test_get_nest_by_code` | `GET /api/nests/{code}` returns nest metadata |
| `test_get_nonexistent_nest` | `GET /api/nests/ZZZZZ` returns 404 |

### Class: `TestNestAPIDelete`

| Test | Description |
|------|-------------|
| `test_delete_nest_by_creator` | `DELETE /api/nests/{code}` by creator → 200 |
| `test_delete_nest_by_non_creator` | `DELETE /api/nests/{code}` by other user → 403 |
| `test_delete_main_nest` | `DELETE /api/nests/main` → 403 or 400 |

### Class: `TestNestAPIUpdate`

| Test | Description |
|------|-------------|
| `test_update_nest_name` | `PATCH /api/nests/{code}` with `{"name": "New Name"}` → 200 |
| `test_update_nest_bender` | `PATCH /api/nests/{code}` with `{"bender_enabled": false}` → 200 |
| `test_update_nest_non_creator` | `PATCH /api/nests/{code}` by other user → 403 |
| `test_update_nest_invalid_name` | Empty or too-long name → 400 |

### Class: `TestNestRoute`

| Test | Description |
|------|-------------|
| `test_nest_page_renders` | `GET /nest/{code}` for valid nest → 200 with HTML |
| `test_nest_page_invalid_code` | `GET /nest/ZZZZZ` → 404 |
| `test_nest_page_includes_nest_id` | Response HTML/JS includes the nest_id for WebSocket |

---

## File: `test/test_nests_websocket.py` — WebSocket Nest Routing

These tests verify that WebSocket connections are routed to the correct nest.
May need to mock or simulate WebSocket at the `before_request` level.

### Class: `TestWebSocketNestRouting`

| Test | Description |
|------|-------------|
| `test_socket_default_is_main` | `/socket` WebSocket connects to main nest |
| `test_socket_with_nest_id` | `/socket/{nest_id}` connects to the specified nest |
| `test_socket_invalid_nest` | `/socket/ZZZZZ` for nonexistent nest → appropriate error |
| `test_socket_membership_on_connect` | Connecting adds user to `NEST:{id}\|MEMBERS` |
| `test_socket_membership_on_disconnect` | Disconnecting removes user from MEMBERS |

---

## File: `test/test_nests_migration.py` — Key Migration Script

### Class: `TestKeyMigration`

| Test | Description |
|------|-------------|
| `test_migrate_renames_keys` | Old `MISC\|now-playing` becomes `NEST:main\|MISC\|now-playing` |
| `test_migrate_preserves_values` | Values are identical after migration |
| `test_migrate_handles_empty_redis` | No error when Redis is empty |
| `test_migrate_idempotent` | Running migration twice doesn't break anything |
| `test_migrate_queue_sorted_set` | `MISC\|priority-queue` sorted set migrated with scores intact |
| `test_migrate_hash_data` | `QUEUE\|{id}` hash migrated with all fields |

---

## Test Priorities for Codex

**Must have (blocks implementation):**
1. `test_nests_db.py` — needed for Phase 1
2. `test_nests_manager.py` — needed for Phase 2
3. `test_nests_migration.py` — needed for Phase 1

**Should have (needed for full MVP):**
4. `test_nests_api.py` — needed for Phase 2
5. `test_nests_cleanup.py` — needed for Phase 2

**Nice to have (can write during implementation):**
6. `test_nests_websocket.py` — harder to test, may need mocking
7. `test_nests_route.py` — frontend integration

---

## Dependencies to Add

```
# requirements.txt additions
fakeredis>=2.0     # For Redis test isolation
```

---

## Running Tests

```bash
# All nest tests
SKIP_SPOTIFY_PREFETCH=1 python3 -m pytest test/test_nests_*.py -v

# Specific phase
SKIP_SPOTIFY_PREFETCH=1 python3 -m pytest test/test_nests_db.py test/test_nests_migration.py -v   # Phase 1
SKIP_SPOTIFY_PREFETCH=1 python3 -m pytest test/test_nests_manager.py test/test_nests_api.py -v     # Phase 2
```
