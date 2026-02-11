# Nests MVP — Implementation Task Breakdown

Ordered list of tasks for the overnight implementation run.
Each task should result in a granular git commit.
Run tests after each task to verify no regressions.

## Test File Reference

All contract tests live in `test/test_nests.py` (from `feature/nests-tests` branch, already merged).
Tests are marked `@pytest.mark.xfail` and will pass once implementation lands.

```bash
# Run nest tests + regression suite (recommended after each task)
make test-nests

# Run just nest tests (quick check during a task)
make test-quick

# Run a specific class
SKIP_SPOTIFY_PREFETCH=1 python3 -m pytest test/test_nests.py::TestRedisKeyPrefixing -v

# Run full suite
make test-all
```

### Test Class → Task Mapping

| Test Class | File Location | Relevant Task(s) | Phase |
|---|---|---|---|
| `TestRedisKeyPrefixing` | `test/test_nests.py:641` | T1, T2 | 1 |
| `TestMigrationHelpers` | `test/test_nests.py:705` | T3 | 1 |
| `TestPubSubChannels` | `test/test_nests.py:725` | T4 | 1 |
| `TestNestCleanupLogic` | `test/test_nests.py:662` | T10 | 2 |
| `TestMembershipHeartbeat` | `test/test_nests.py:688` | T6, T9 | 2 |
| `TestMasterPlayerMultiNest` | `test/test_nests.py:740` | T10 | 2 |
| `TestNestManagerCRUD` | `test/test_nests.py:755` | T6 | 2 |
| `TestMigrationScriptBehavior` | `test/test_nests.py:786` | T3 | 1 |
| `TestNestAuthGating` | `test/test_nests.py:805` | T7, T8 | 2 |
| `TestWebSocketMembership` | `test/test_nests.py:833` | T9 | 2 |
| `TestNestsAPI` | `test/test_nests.py:16` | T7, T8 | 2 |
| `TestNestsAdminAPI` | `test/test_nests.py:241` | Phase 5 (future) |
| `TestBillingAPI` | `test/test_nests.py:333` | Phase 5 (future) |
| `TestSuperAdminAPI` | `test/test_nests.py:427` | Phase 5 (future) |
| `TestEntitlementGates` | `test/test_nests.py:479` | Phase 5 (future) |
| `TestAuditLogs` | `test/test_nests.py:537` | Phase 5 (future) |
| `TestInviteOnly` | `test/test_nests.py:567` | Phase 5 (future) |
| `TestFreeCap` | `test/test_nests.py:608` | Phase 5 (future) |

### MVP-Relevant Tests (must pass by end of overnight run)

These are the test classes that should flip from `xfail` to passing:

1. **`TestRedisKeyPrefixing`** — `DB._key()` returns correct prefixed keys
2. **`TestMigrationHelpers`** — `legacy_key_mapping` dict maps old→new keys
3. **`TestPubSubChannels`** — `pubsub_channel()` helper returns nest-scoped channel
4. **`TestNestCleanupLogic`** — `should_delete_nest()` predicate logic
5. **`TestMembershipHeartbeat`** — `member_key()` and `members_key()` helpers
6. **`TestMasterPlayerMultiNest`** — `master_player_tick_all()` callable exists
7. **`TestNestManagerCRUD`** — basic CRUD wiring exists
8. **`TestMigrationScriptBehavior`** — migration entrypoint exists
9. **`TestNestAuthGating`** — nest routes require auth
10. **`TestWebSocketMembership`** — membership helpers wired
11. **`TestNestsAPI`** — CRUD routes return correct status codes and shapes

### Future Tests (should remain xfail for now)

- `TestNestsAdminAPI` — Admin console (Phase 5)
- `TestBillingAPI` — Stripe integration (Phase 5)
- `TestSuperAdminAPI` — Internal ops (Phase 5)
- `TestEntitlementGates` — Feature gating (Phase 5)
- `TestAuditLogs` — Audit trail (Phase 5)
- `TestInviteOnly` — Private nests (Phase 5)
- `TestFreeCap` — Free tier limits (Phase 5)

---

## Pre-flight

- [x] **T0: Merge Codex test branch** — `test/test_nests.py` already on `feature/nests` (shared history with `feature/nests-tests`).
- [x] **T0.0: nests.py scaffold exists** — Codex created `nests.py` with `NotImplementedError` stubs for all helpers + `NestManager`. Tests can import without `ModuleNotFoundError`. Implementation replaces stubs with real logic.
- [ ] **T0.1: Add fakeredis to requirements.txt** — `fakeredis>=2.0` (if not already present). Note: existing Codex contract tests in `test/test_nests.py` use Flask test client, not fakeredis. But `fakeredis` is needed for DB-level unit tests added during implementation.
- [x] **T0.2: CI + Makefile** — `make test-nests` runs nest tests + regression suite. GitHub Actions on push to `feature/nests`.

---

## Phase 1: Backend Key Migration

### T1: Add `_key()` method and `nest_id` param to DB class
**File:** `db.py`
**Changes:**
- Add `nest_id="main"` parameter to `DB.__init__`
- Add optional `redis_client` parameter to `DB.__init__` (for test injection via fakeredis)
- Add `_key(self, key)` method that returns `f"NEST:{self.nest_id}|{key}"`
- Store `self.nest_id` as instance attribute
**Commit:** `feat(nests): add _key() method and nest_id to DB class`
**Verify:** `SKIP_SPOTIFY_PREFETCH=1 python3 -m pytest test/test_nests.py::TestRedisKeyPrefixing -v`
- `test_db_key_prefixing` — asserts `DB(nest_id="X7K2P")._key("MISC|now-playing") == "NEST:X7K2P|MISC|now-playing"`
**Done when:** `DB.__init__` accepts `nest_id`, `_key()` exists, and `TestRedisKeyPrefixing` passes.

### T2: Refactor all Redis key references in DB class to use `_key()`
**File:** `db.py`
**Changes:**
- Find every hardcoded Redis key string and wrap with `self._key(...)`
- **EXCEPTIONS (global, do NOT wrap):**
  - `MISC|spotify-rate-limited` (in module-level functions, not on DB class)
  - `NESTS|registry` and `NESTS|code:*` (managed by NestManager, not DB)
- Be methodical: search for all `self._r.get(`, `self._r.set(`, `self._r.hget(`, `self._r.hset(`, `self._r.zadd(`, `self._r.zrem(`, `self._r.delete(`, `self._r.setnx(`, `self._r.expire(`, `self._r.publish(`, etc.
- The pub/sub channel `MISC|update-pubsub` MUST be wrapped so each nest gets its own channel
**Commit:** `feat(nests): scope all DB Redis keys to nest_id via _key()`
**Verify:** `TestRedisKeyPrefixing` should still pass. Also run existing tests to check for regressions.
**Done when:** all DB Redis ops are scoped via `_key()` (except global keys) and main-nest behavior remains unchanged.

### T3: Implement helpers in nests.py + write migration script
**Files:** `migrate_keys.py` (new), `nests.py` (scaffold exists — replace stubs with real implementations)
**Changes:**
- `nests.py` — replace `NotImplementedError` stubs with real implementations:
  - `legacy_key_mapping` — dict mapping old keys to `NEST:main|`-prefixed keys
  - `pubsub_channel(nest_id)` — returns `f"NEST:{nest_id}|MISC|update-pubsub"`
  - `members_key(nest_id)` — returns `f"NEST:{nest_id}|MEMBERS"`
  - `member_key(nest_id, email)` — returns `f"NEST:{nest_id}|MEMBER:{email}"`
  - `refresh_member_ttl(nest_id, email, ttl_seconds=90)` — sets member TTL key
  - `should_delete_nest(metadata, members, queue_size, now)` — cleanup predicate
  - `NestManager` should be importable from `nests.py` (tests import `nests.NestManager`)
- `migrate_keys.py` script that:
  - Connects to Redis and renames all existing keys to `NEST:main|` prefix
  - Uses `SCAN` to find keys matching ALL known prefixes:
    - `MISC|*`, `QUEUE|*`, `FILTER|*`, `BENDER|*`
    - `QUEUEJAM|*`, `COMMENTS|*`, `FILL-INFO|*`
    - `AIRHORNS`, `FREEHORN_*`
  - Uses `DUMP`+`RESTORE`+`DEL` (copy-then-delete) instead of `RENAME` — safe if destination already exists (won't clobber)
  - Idempotent: skip keys that already have `NEST:` prefix
  - Dry-run mode flag
  - **Safety:** If `NEST:main|{key}` already exists, log a warning and skip (don't overwrite)
  - Provide a `migrate()` function in `migrate_keys.py` (tests check for it)
**Commit:** `feat(nests): add nests helpers module and key migration script`
**Verify:**
- `SKIP_SPOTIFY_PREFETCH=1 python3 -m pytest test/test_nests.py::TestMigrationHelpers -v`
- `SKIP_SPOTIFY_PREFETCH=1 python3 -m pytest test/test_nests.py::TestPubSubChannels -v`
- `SKIP_SPOTIFY_PREFETCH=1 python3 -m pytest test/test_nests.py::TestMembershipHeartbeat -v`
- `SKIP_SPOTIFY_PREFETCH=1 python3 -m pytest test/test_nests.py::TestNestCleanupLogic -v`
**Done when:** helper functions exist in `nests.py`, `migrate()` exists, and the four helper tests pass.

### T4: Update pub/sub subscription in app.py
**File:** `app.py`
**Changes:**
- `MusicNamespace.listener()` should subscribe to `NEST:{nest_id}|MISC|update-pubsub` instead of hardcoded `MISC|update-pubsub`
- `VolumeNamespace.listener()` same change
- SSE endpoint `/api/events` same change
- For now, all use "main" as nest_id (nest routing comes in Phase 2)
- Can import `pubsub_channel` from `nests.py` module
**Commit:** `feat(nests): scope pub/sub channels to nest_id`
**Verify:** Run existing tests to verify no regressions
**Done when:** SSE and WebSocket subscribe to `pubsub_channel(nest_id)` without breaking updates.

### T5: Add nest config options
**Files:** `config.yaml`, `config.py`
**Changes:**
- Add to `config.yaml`:
  ```yaml
  NESTS_ENABLED: true
  NEST_MAX_INACTIVE_MINUTES: 120
  NEST_MAX_ACTIVE: 20
  NEST_CODE_LENGTH: 5
  NEST_BENDER_DEFAULT: true
  ECHONEST_DOMAIN: echone.st
  ```
- Add to `ENV_OVERRIDES` in `config.py`: `'NESTS_ENABLED'`
**Commit:** `feat(nests): add nest configuration options`
**Verify:** Verify config loads correctly
**Done when:** new config values are available via `CONF.*` with defaults matching the plan.

---

## Phase 2: Nest Backend

### T6: Implement NestManager class
**File:** `nests.py` (replace NestManager stub — scaffold already has the class shape)
**Changes:**
- `NestManager` class with Redis connection — already stubbed in `nests.py`, replace `NotImplementedError` with real logic
- `create_nest(creator_email, name=None)` → generates code, stores in `NESTS|registry`
- `get_nest(nest_id)` → reads from registry
- `list_nests()` → returns all nests with member counts
- `delete_nest(nest_id)` → removes from registry + SCAN/DELETE all `NEST:{id}|*` keys
- `touch_nest(nest_id)` → updates `last_activity`
- `join_nest(nest_id, email)` → SADD to `NEST:{id}|MEMBERS`
- `leave_nest(nest_id, email)` → SREM from `NEST:{id}|MEMBERS`
- `generate_code()` → random 5-char from `ABCDEFGHJKMNPQRSTUVWXYZ23456789`, collision check
- Initialize main nest in registry on first run if not present
- Accept optional `redis_client` for test injection
- **Module-level wrappers:** Also expose `join_nest(nest_id, email)` and `leave_nest(nest_id, email)` as module-level functions in `nests.py` (tests import them directly: `getattr(nests, "join_nest")`)
**Commit:** `feat(nests): add NestManager class with CRUD operations`
**Verify:**
- `TestMembershipHeartbeat` should pass (uses `members_key`/`member_key` from `nests.py`)
- `TestNestManagerCRUD` should pass (imports `nests.NestManager`)
- `TestWebSocketMembership` should pass (imports `nests.join_nest`/`nests.leave_nest`)
**Done when:** `nests.NestManager` CRUD works and `TestNestManagerCRUD` passes.

### T7: Add nest API routes
**File:** `app.py`
**Changes:**
- Import `NestManager`, instantiate alongside DB
- `POST /api/nests` — create nest (requires authenticated session or API token)
- `GET /api/nests` — list active nests (**authenticated only** — don't leak nest list to anonymous users)
- `GET /api/nests/<code>` — get nest info (**authenticated only**)
- `PATCH /api/nests/<code>` — update nest (creator only)
- `DELETE /api/nests/<code>` — delete nest (creator only)
- **Auth:** These routes use session auth (standard `before_request` gate) OR `@require_api_token` for API clients. Do NOT add `/api/nests` to `SAFE_PARAM_PATHS` — that would bypass session auth and make them public
- Return proper JSON responses with status codes
- Use error shapes from `docs/NESTS_API_ERRORS.md`
**Commit:** `feat(nests): add REST API routes for nest CRUD`
**Verify:** `SKIP_SPOTIFY_PREFETCH=1 python3 -m pytest test/test_nests.py::TestNestsAPI -v`
- `test_create_nest_returns_code` — POST /api/nests → 200 with `code` (5 chars)
- `test_get_nest_info` — GET /api/nests/{code} → 200 or 404
- `test_patch_nest_name` — PATCH /api/nests/{code} → 200/403/404
- `test_create_nest_free_cap_error_shape` — if 403/429, error body has `nest_limit_reached`
- `test_rate_limit_shape` — if 429, error has correct shape
**Done when:** `TestNestsAPI` and `TestNestAuthGating` pass and error payloads match the doc.

### T8: Add `/nest/<code>` page route
**File:** `app.py`
**Changes:**
- `GET /nest/<code>` — look up nest, render `main.html` with `nest_id` in template context
- Return 404 if nest doesn't exist
- **Auth:** Do NOT add `/nest/` to `SAFE_PARAM_PATHS`. Nest pages require Google auth like everything else. The flow is: visit `echone.st/X7K2P` → redirect to `/nest/X7K2P` → Google login gate → render nest page. This is consistent with the existing app model where all pages require authentication.
**Commit:** `feat(nests): add /nest/<code> page route`
**Verify:** Part of `TestNestsAPI` tests
**Done when:** `/nest/<code>` requires auth and renders nest context on success.

### T9: WebSocket nest routing + membership heartbeat
**File:** `app.py`
**Changes:**
- Modify `before_request` WebSocket handling to extract nest_id from path:
  - `/socket` → `nest_id="main"` (backward compatible)
  - `/socket/<nest_id>` → use that nest_id (validate it exists)
- Pass `nest_id` to `MusicNamespace.__init__`
- `MusicNamespace` creates its own `DB(nest_id=...)` instance
- On connect: `nest_manager.join_nest(nest_id, email)`
- On disconnect (in `serve()` finally block): `nest_manager.leave_nest(nest_id, email)`
- Update `nest_manager.touch_nest(nest_id)` on queue operations
- **Heartbeat TTL:** Use per-member keys with TTL to handle stale members:
  - On connect and periodically (every 30s in `serve()` loop): `SET NEST:{id}|MEMBER:{email} 1 EX 90`
  - Use `member_key(nest_id, email)` from `nests.py` for key format
  - The MEMBERS set tracks who's in the nest; the MEMBER:{email} TTL keys track liveness
  - `should_delete_nest()` in cleanup should check MEMBER TTL keys, not just the MEMBERS set — if all member keys are expired, the set is stale
  - On disconnect: delete the member key AND SREM from MEMBERS set
**Commit:** `feat(nests): route WebSocket connections to specific nests with heartbeat`
**Verify:** Hard to test via pytest (WebSocket mocking). Verify manually if possible. `TestMembershipHeartbeat` tests the key format helpers.
**Done when:** `refresh_member_ttl()` is called periodically and stale members no longer block cleanup.

### T10: Add nest cleanup to master_player
**Files:** `master_player.py`, `db.py`
**Changes:**
- Refactor `master_player()` loop to iterate over all active nests
- Extract single-iteration logic into `_master_player_tick()` method
- Add `master_player_tick_all()` function (the test expects this to be callable)
- Add `nest_cleanup_loop()` that runs alongside master_player
- Cleanup uses `should_delete_nest()` from `nests.py` module
- Skip main nest
- **IMPORTANT: Global keys stay global.** `MISC|spotify-rate-limited` is checked in module-level functions (not on DB class) and must NOT be nest-scoped. Verify T2 didn't wrap it. The rate limit is a Spotify API concern shared across all nests.
- **Auth refresh storms:** When iterating nests, reuse the same Spotify client/token across nests in a single tick cycle rather than refreshing per-nest
**Commit:** `feat(nests): add multi-nest master player and cleanup worker`
**Verify:**
- `SKIP_SPOTIFY_PREFETCH=1 python3 -m pytest test/test_nests.py::TestNestCleanupLogic -v`
- `SKIP_SPOTIFY_PREFETCH=1 python3 -m pytest test/test_nests.py::TestMasterPlayerMultiNest -v`
  - `test_master_player_iterates_nests` — asserts `master_player_tick_all` is callable
**Done when:** `master_player_tick_all()` exists and cleanup deletes only inactive empty nests.

---

## Phase 3: Nest Frontend

### T11: Pass nest_id to frontend template
**Files:** `templates/main.html`, `templates/config.js` (if exists), `app.py`
**Changes:**
- Pass `nest_id` and `nest_info` (name, code, is_main) to template context
- Make it available to JavaScript (e.g., `window.NEST_ID`, `window.NEST_INFO`)
**Commit:** `feat(nests): pass nest context to frontend templates`
**Verify:** No specific Codex test. Verify template renders correctly.

### T12: Update WebSocket connection to use nest_id
**File:** `static/js/app.js`
**Changes:**
- Read `window.NEST_ID` (default "main")
- Connect to `/socket/{nest_id}` instead of `/socket`
- Keep backward compatible: if `NEST_ID` is "main" or undefined, connect to `/socket`
**Commit:** `feat(nests): connect WebSocket to nest-specific endpoint`
**Verify:** No specific Codex test. Verify WebSocket connects.

### T13: Add nest bar UI
**Files:** `templates/main.html`, `static/css/app.css`, `static/js/app.js`
**Changes:**
- Add a nest bar above the main content area
- When in Main Nest: show subtle "Build a Nest" button + "Join a Nest" input
- When in a temporary nest: show nest name, code, "Share Nest" button, listener count, "Back to Main Nest" link
- "Build a Nest" opens a modal with name input → POST /api/nests → show code + share link
- "Join a Nest" input: enter 5-char code → navigate to `/nest/{code}`
- "Share Nest" copies `echone.st/{code}` (or full URL if domain not configured) to clipboard
- Style it to work with the existing 9-theme system
**Commit:** `feat(nests): add nest bar UI with create/join flows`
**Verify:** No specific Codex test. Visual inspection needed.

### T14: Show listener count
**Files:** `static/js/app.js`, `app.py` (or via WebSocket)
**Changes:**
- Display number of listeners in the nest bar
- Option A: Fetch from `GET /api/nests/{code}` periodically
- Option B: Broadcast listener count changes via pub/sub (preferred for real-time)
- Add a `member_update` pub/sub message type when membership changes
**Commit:** `feat(nests): show real-time listener count in nest bar`
**Verify:** No specific Codex test. Verify count updates.

---

## Post-Implementation

- [ ] **T15: Run full test suite** — `SKIP_SPOTIFY_PREFETCH=1 python3 -m pytest -v`
- [ ] **T16: Test manually** (if possible — start dev server, create/join nests)
- [ ] **T17: Update CHANGELOG.md** — Add Nests feature entry
- [ ] **T18: Review decision log** — Ensure all decisions are documented

---

## Expected Test Results After Full MVP

```bash
SKIP_SPOTIFY_PREFETCH=1 python3 -m pytest test/test_nests.py -v
```

**Should PASS (no longer xfail):**
- `TestRedisKeyPrefixing::test_db_key_prefixing`
- `TestMigrationHelpers::test_legacy_key_rename_map`
- `TestPubSubChannels::test_pubsub_channel_key`
- `TestNestCleanupLogic::test_should_delete_nest_predicate`
- `TestMembershipHeartbeat::test_member_key_helpers`
- `TestMasterPlayerMultiNest::test_master_player_iterates_nests`
- `TestNestManagerCRUD::test_create_get_list_delete`
- `TestMigrationScriptBehavior::test_migration_script_idempotent`
- `TestMigrationScriptBehavior::test_migration_skips_existing_dest`
- `TestNestAuthGating::test_api_nests_requires_auth`
- `TestNestAuthGating::test_nest_page_requires_auth`
- `TestWebSocketMembership::test_membership_join_leave`
- `TestWebSocketMembership::test_heartbeat_ttl_refresh`
- `TestNestsAPI::*` (all API contract tests)

**Should remain XFAIL (future phases):**
- `TestNestsAdminAPI::*`
- `TestBillingAPI::*`
- `TestSuperAdminAPI::*`
- `TestEntitlementGates::*`
- `TestAuditLogs::*`
- `TestInviteOnly::*`
- `TestFreeCap::*`

**Important:** When a test class is implemented and should pass, remove the `@pytest.mark.xfail` decorator from that class. Leave xfail on future-phase classes.

---

## Commit Message Convention

```
feat(nests): <description>
```

All commits should end with:
```
Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

---

## Risk Areas (pay extra attention)

1. **db.py refactor (T2)** — Most error-prone task. Every Redis key must be wrapped. Missing one means silent data corruption (writing to wrong key). Be exhaustive. The complete list of key prefixes in db.py: `MISC|*`, `QUEUE|*`, `QUEUE|VOTE|*`, `FILTER|*`, `BENDER|*`, `QUEUEJAM|*`, `COMMENTS|*`, `FILL-INFO|*`, `AIRHORNS`, `FREEHORN_*`.
2. **pub/sub channel scoping (T4)** — If the channel name doesn't match between publisher (db.py) and subscriber (app.py), real-time updates break silently.
3. **WebSocket disconnect handling (T9)** — Must reliably call `leave_nest` even on abnormal disconnects. The `finally` block in `serve()` is the right place. Must also refresh heartbeat TTL key periodically to prevent stale members blocking cleanup.
4. **master_player multi-nest (T10)** — The lock mechanism (`MISC|master-player` via `setnx`) needs to be per-nest: `NEST:{id}|MISC|master-player`. Keep `MISC|spotify-rate-limited` global (not nest-scoped).
5. **nests.py module name (T3)** — Tests import `nests` module via `importlib.import_module("nests")`. The file MUST be named `nests.py` at the project root, not `nest_manager.py`. Either name the file `nests.py` or ensure `nest_manager.py` exports the expected helpers AND update the import in tests. **Recommended:** Create `nests.py` with the helper functions and keep `nest_manager.py` for the NestManager class, OR put everything in `nests.py`.
6. **Migration safety (T3)** — Use `DUMP`+`RESTORE`+`DEL` (not `RENAME`) to avoid clobbering if destination key already exists from a partial migration. Skip with warning if destination exists. Cover ALL 9 prefix families, not just the 4 main ones.
