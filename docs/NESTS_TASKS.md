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
| `TestNestCleanupLogic` | `test/test_nests.py:662` | T3, T10 | 1-2 |
| `TestMembershipHeartbeat` | `test/test_nests.py:688` | T3, T6 | 1-2 |
| `TestMasterPlayerMultiNest` | `test/test_nests.py:740` | T10 | 2 |
| `TestNestManagerCRUD` | `test/test_nests.py:755` | T6 | 2 |
| `TestMigrationScriptBehavior` | `test/test_nests.py:786` | T3 | 1 |
| `TestNestAuthGating` | `test/test_nests.py:805` | T7, T8 | 2 |
| `TestWebSocketMembership` | `test/test_nests.py:833` | T6, T9a | 2 |
| `TestNestsAPI` | `test/test_nests.py:16` | T7, T8 | 2 |
| `TestNestsAdminAPI` | `test/test_nests.py:241` | Phase 5 (future) |
| `TestBillingAPI` | `test/test_nests.py:333` | Phase 5 (future) |
| `TestSuperAdminAPI` | `test/test_nests.py:427` | Phase 5 (future) |
| `TestEntitlementGates` | `test/test_nests.py:479` | Phase 5 (future) |
| `TestAuditLogs` | `test/test_nests.py:537` | Phase 5 (future) |
| `TestInviteOnly` | `test/test_nests.py:567` | Phase 5 (future) |
| `TestFreeCap` | `test/test_nests.py:608` | Phase 5 (future) |

### MVP-Relevant Tests (must pass by end of overnight run)

These are the test classes that should flip from `xfail` to passing, grouped by when they should first pass:

**After Phase 1 (T1-T5):**
1. **`TestRedisKeyPrefixing`** — `DB._key()` returns correct prefixed keys (T1/T2)
2. **`TestMigrationHelpers`** — `legacy_key_mapping` dict maps old→new keys (T3)
3. **`TestPubSubChannels`** — `pubsub_channel()` helper returns nest-scoped channel (T3)
4. **`TestNestCleanupLogic`** — `should_delete_nest()` predicate logic (T3)
5. **`TestMembershipHeartbeat`** — `member_key()` and `members_key()` helpers (T3)
6. **`TestMigrationScriptBehavior`** — migration entrypoint exists (T3)

**After Phase 2 (T6-T10):**
7. **`TestNestManagerCRUD`** — basic CRUD wiring exists (T6)
8. **`TestWebSocketMembership`** — module-level `join_nest`/`leave_nest` wired (T6)
9. **`TestNestsAPI`** — CRUD routes return correct status codes and shapes (T7/T8)
10. **`TestNestAuthGating`** — nest routes require auth (T7/T8)
11. **`TestMasterPlayerMultiNest`** — `master_player_tick_all()` callable exists (T10)

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

### T3: Implement pure helper functions in nests.py + write migration script
**Files:** `migrate_keys.py` (new), `nests.py` (scaffold exists — replace stubs for helper functions only)
**Scope:** Helper functions and migration. Do NOT implement `NestManager` or module-level `join_nest`/`leave_nest` wrappers — those come in T6. Note: `refresh_member_ttl` may touch Redis; keep it a thin wrapper if you want T3 to stay low-risk.
**Changes:**
- `nests.py` — replace `NotImplementedError` stubs for these **pure helpers only**:
  - `legacy_key_mapping` — dict mapping old keys to `NEST:main|`-prefixed keys
  - `pubsub_channel(nest_id)` — returns `f"NEST:{nest_id}|MISC|update-pubsub"`
  - `members_key(nest_id)` — returns `f"NEST:{nest_id}|MEMBERS"`
  - `member_key(nest_id, email)` — returns `f"NEST:{nest_id}|MEMBER:{email}"`
  - `refresh_member_ttl(redis_client, nest_id, email, ttl_seconds=90)` — sets member TTL key via passed-in Redis client (no global singleton; caller provides `db._r`)
  - `should_delete_nest(metadata, members, queue_size, now)` — cleanup predicate (pure logic, no Redis)
  - Leave `NestManager` and `join_nest`/`leave_nest` stubs as `NotImplementedError` (implemented in T6)
- **Redis client convention:** All helpers that need Redis take an explicit `redis_client` parameter. No global singletons. The caller (WebSocket serve loop, NestManager, etc.) already has a Redis connection and passes it through. This matches how `db.py` works.
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
**Commit:** `feat(nests): add nests helpers and key migration script`
**Verify:**
- `SKIP_SPOTIFY_PREFETCH=1 python3 -m pytest test/test_nests.py::TestMigrationHelpers -v`
- `SKIP_SPOTIFY_PREFETCH=1 python3 -m pytest test/test_nests.py::TestPubSubChannels -v`
- `SKIP_SPOTIFY_PREFETCH=1 python3 -m pytest test/test_nests.py::TestMembershipHeartbeat -v`
- `SKIP_SPOTIFY_PREFETCH=1 python3 -m pytest test/test_nests.py::TestNestCleanupLogic -v`
**Done when:** helper functions work in `nests.py`, `migrate()` exists, and the four helper tests pass. `NestManager` stubs still raise `NotImplementedError`.

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
  NEST_MAX_INACTIVE_MINUTES: 5
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

### T6: Implement NestManager class + module-level wrappers
**File:** `nests.py` (replace NestManager + join/leave stubs — scaffold already has the class shape)
**Depends on:** T3 (pure helpers must be implemented first)
**Changes:**
- `NestManager` class with Redis connection — replace `NotImplementedError` with real logic:
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
- **Module-level wrappers:** Replace `join_nest` and `leave_nest` stubs at module level in `nests.py` with real implementations that delegate to a default NestManager instance. Tests import them directly: `getattr(nests, "join_nest")`, `getattr(nests, "leave_nest")`, `getattr(nests, "refresh_member_ttl")`
**Commit:** `feat(nests): implement NestManager class with CRUD operations`
**Verify:**
- `TestMembershipHeartbeat` should already pass (uses pure helpers from T3)
- `TestNestManagerCRUD` should pass (imports `nests.NestManager`)
- `TestWebSocketMembership` should pass (imports `nests.join_nest`/`nests.leave_nest`)
**Done when:** `nests.NestManager` CRUD works, module-level wrappers work, and all three test classes pass.

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

### T9a: WebSocket nest routing + per-nest DB instance
**File:** `app.py`
**Depends on:** T6 (NestManager must exist for join/leave calls)
**Changes:**
- Modify `before_request` WebSocket handling to extract nest_id from path:
  - `/socket` → `nest_id="main"` (backward compatible)
  - `/socket/<nest_id>` → use that nest_id (validate it exists via NestManager)
- Pass `nest_id` to `MusicNamespace.__init__`
- `MusicNamespace` creates its own `DB(nest_id=...)` instance
- On connect: `nest_manager.join_nest(nest_id, email)`
- On disconnect (in `serve()` finally block): `nest_manager.leave_nest(nest_id, email)`
- Update `nest_manager.touch_nest(nest_id)` on queue operations (add, vote, skip)
**Commit:** `feat(nests): route WebSocket connections to specific nests`
**Verify:** Hard to test via pytest (WebSocket mocking). `TestWebSocketMembership` tests the helper imports exist. Manually verify `/socket` still works for main nest.
**Done when:** WebSocket connections route to the correct nest, DB is scoped per-nest, and join/leave fire on connect/disconnect.

### T9b: Membership heartbeat TTL in WebSocket serve loop
**File:** `app.py`
**Depends on:** T9a (WebSocket routing must be in place)
**Changes:**
- Add heartbeat refresh in `MusicNamespace.serve()` loop:
  - On connect: `refresh_member_ttl(self.db._r, nest_id, email, ttl_seconds=90)` — pass Redis client from DB instance
  - Every 30s in serve loop: call `refresh_member_ttl()` again with same client
  - Use `member_key(nest_id, email)` from `nests.py` for key format: `SET NEST:{id}|MEMBER:{email} 1 EX 90`
- On disconnect (in `serve()` finally block): delete the member TTL key AND SREM from MEMBERS set
- **Design:** The MEMBERS set tracks who's in the nest; the `MEMBER:{email}` TTL keys track liveness. Cleanup (T10) checks member TTL keys — if all are expired, the MEMBERS set is stale and the nest can be deleted.
**Commit:** `feat(nests): add membership heartbeat TTL to WebSocket serve loop`
**Verify:** `TestMembershipHeartbeat` tests the key format helpers. Manual verification: connect, wait >90s idle, member key should expire.
**Done when:** `refresh_member_ttl()` is called every 30s in serve loop, member keys have 90s TTL, and disconnect cleans up both TTL key and MEMBERS set.

### T10: Add nest cleanup to master_player
**Files:** `master_player.py`, `db.py`
**Changes:**
- **Strategy:** Dedicated supervisor + per‑nest worker greenlets that run bounded ticks (not infinite loops).
- Extract single-iteration logic into `DB._master_player_tick()` (one nest, one cycle)
- Implement `_run_nest_player(nest_id)` as a loop:
  - `db = DB(nest_id=nest_id)` once
  - `while True: db._master_player_tick(); gevent.sleep(0.25–1.0)`
- `master_player_tick_all()` becomes the **supervisor**:
  - Poll `list_nests()` every few seconds
  - Spawn a worker greenlet per new nest (including `main`)
  - Kill workers for removed nests
  - Respawn workers that die (log exception)
- Add `nest_cleanup_loop()` that runs alongside the supervisor
- Cleanup uses `should_delete_nest()` from `nests.py` module
- Skip main nest
- **IMPORTANT: Global keys stay global.** `MISC|spotify-rate-limited` is checked in module-level functions (not on DB class) and must NOT be nest-scoped. Verify T2 didn't wrap it. The rate limit is a Spotify API concern shared across all nests.
- **Spotify overhead control:** Keep OAuth refresh/token cache global or shared so per‑nest workers do not all refresh at once.
**Commit:** `feat(nests): add multi-nest master player and cleanup worker`
**Verify:**
- `SKIP_SPOTIFY_PREFETCH=1 python3 -m pytest test/test_nests.py::TestNestCleanupLogic -v`
- `SKIP_SPOTIFY_PREFETCH=1 python3 -m pytest test/test_nests.py::TestMasterPlayerMultiNest -v`
  - `test_master_player_iterates_nests` — asserts `master_player_tick_all` is callable
**Done when:** supervisor spawns/cleans per‑nest workers, `_master_player_tick()` runs per nest, and cleanup deletes only inactive empty nests.

---

## Phase 3: Nest Frontend

> **Note:** No Codex contract tests exist for frontend tasks. Verification is manual/visual. Each task has explicit acceptance criteria to keep scope clear.

### T11: Pass nest_id to frontend template
**Files:** `templates/main.html`, `app.py`
**Depends on:** T8 (`/nest/<code>` route must exist)
**Changes:**
- In `app.py`, pass `nest_id`, `nest_code`, `nest_name`, and `is_main_nest` to the template context for both `/` (main nest) and `/nest/<code>` routes
- In `templates/main.html`, emit these as JS globals:
  ```html
  <script>
    window.NEST_ID = "{{ nest_id }}";
    window.NEST_CODE = "{{ nest_code }}";
    window.NEST_NAME = "{{ nest_name }}";
    window.IS_MAIN_NEST = {{ is_main_nest|tojson }};
  </script>
  ```
**Commit:** `feat(nests): pass nest context to frontend templates`
**Acceptance criteria:**
- `/` sets `window.NEST_ID = "main"`, `window.IS_MAIN_NEST = true`
- `/nest/X7K2P` sets `window.NEST_ID` to the nest's id, `window.NEST_CODE = "X7K2P"`, `window.IS_MAIN_NEST = false`
- Existing page renders identically (no visible change)

### T12: Update WebSocket connection to use nest_id
**File:** `static/js/app.js`
**Depends on:** T11 (nest context must be in window globals), T9a (WebSocket routing must accept nest_id)
**Changes:**
- Read `window.NEST_ID` (default `"main"`)
- Connect to `/socket/{nest_id}` instead of `/socket`
- Backward compatible: if `NEST_ID` is `"main"` or undefined, connect to `/socket` (no path change)
**Commit:** `feat(nests): connect WebSocket to nest-specific endpoint`
**Acceptance criteria:**
- Main nest: WebSocket connects to `/socket` (or `/socket/main`) — queue updates work
- Temporary nest: WebSocket connects to `/socket/{nest_id}` — queue updates scoped to that nest
- No JavaScript errors in browser console

### T13a: Add nest bar HTML/CSS
**Files:** `templates/main.html`, `static/css/app.css`
**Depends on:** T11 (nest context must be available)
**Changes:**
- Add a `#nest-bar` div above the main content area in `main.html`
- Two states controlled by `IS_MAIN_NEST`:
  - **Main Nest:** Subtle bar with "Build a Nest" button and "Join a Nest" code input (5-char text field)
  - **Temporary Nest:** Bar showing nest name, 5-char code badge, "Share Nest" button, listener count placeholder (`--`), and "Back to Main Nest" link
- CSS should:
  - Use CSS variables from the existing theme system so it adapts to all 9 themes
  - Be a compact horizontal bar (not modal, not full-width banner)
  - Not displace existing UI significantly (absolute or fixed position, or slim inline bar)
**Commit:** `feat(nests): add nest bar HTML and CSS`
**Acceptance criteria:**
- Bar visible at top of page in both main and nest views
- Bar adapts to all 9 color themes (uses existing CSS variables)
- No layout breakage to existing queue/player UI
- Static only — buttons don't need to work yet

### T13b: Wire nest bar interactions (create/join/share)
**Files:** `static/js/app.js`
**Depends on:** T13a (bar HTML must exist), T7 (API routes must exist)
**Changes:**
- "Build a Nest" button: opens inline form (or small modal) with name input → `POST /api/nests` → on success, display code + `echone.st/{code}` share link, then navigate to `/nest/{code}`
- "Join a Nest" input: on submit (Enter or button), validate 5-char code → navigate to `/nest/{code}` (server returns 404 if invalid)
- "Share Nest" button: copy `echone.st/{code}` (or `window.location.origin + /nest/{code}` if `ECHONEST_DOMAIN` not configured) to clipboard via `navigator.clipboard.writeText()`
- "Back to Main Nest" link: navigate to `/`
- Error handling: show inline error if API returns error (use shapes from `docs/NESTS_API_ERRORS.md`)
**Commit:** `feat(nests): wire nest bar create/join/share interactions`
**Acceptance criteria:**
- "Build a Nest" calls API, gets code, navigates to new nest
- "Join a Nest" navigates to `/nest/{code}` on valid input
- "Share Nest" copies link to clipboard (verify via paste)
- Errors display inline (not alert boxes)

### T14: Show real-time listener count in nest bar
**Files:** `static/js/app.js`, `app.py`
**Depends on:** T13a (nest bar must exist), T9b (heartbeat must be wired)
**Changes:**
- Backend: broadcast a `member_update` event via pub/sub when `join_nest` or `leave_nest` is called (include `count` field)
- Frontend: listen for `member_update` WebSocket message and update the listener count in `#nest-bar`
- Fallback: on initial page load, fetch count from `GET /api/nests/{code}` response
**Commit:** `feat(nests): show real-time listener count in nest bar`
**Acceptance criteria:**
- Listener count updates within 2s of someone joining/leaving
- Count shows `--` before first update (not `0` or empty)
- Count is accurate after page reload (fetched from API)

---

## Post-Implementation

- [ ] **T15: Run full test suite** — `SKIP_SPOTIFY_PREFETCH=1 python3 -m pytest -v`
- [ ] **T16: Test manually** (if possible — start dev server, create/join nests)
- [ ] **T17: Update CHANGELOG.md** — Add Nests feature entry
- [ ] **T18: Review decision log** — Ensure all decisions are documented
- [x] **T19: Make echone.st the primary domain** — echone.st now served directly by Caddy. `andre.dylanbochman.com` 301-redirects to `echone.st`. Bare nest codes handled by Flask catch-all route. Cloudflare page rules removed.

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
3. **WebSocket disconnect handling (T9a/T9b)** — Must reliably call `leave_nest` even on abnormal disconnects. The `finally` block in `serve()` is the right place (T9a). Must also refresh heartbeat TTL key every 30s to prevent stale members blocking cleanup (T9b).
4. **master_player multi-nest (T10)** — The lock mechanism (`MISC|master-player` via `setnx`) needs to be per-nest: `NEST:{id}|MISC|master-player`. Keep `MISC|spotify-rate-limited` global (not nest-scoped).
5. **nests.py module name (T3/T6)** — `nests.py` scaffold already exists at project root with `NotImplementedError` stubs. Tests import via `importlib.import_module("nests")`. T3 replaces pure helper stubs; T6 replaces `NestManager` + `join_nest`/`leave_nest` stubs. Do NOT rename to `nest_manager.py` — that breaks test imports.
6. **Migration safety (T3)** — Use `DUMP`+`RESTORE`+`DEL` (not `RENAME`) to avoid clobbering if destination key already exists from a partial migration. Skip with warning if destination exists. Cover ALL 9 prefix families, not just the 4 main ones.
