# Nests MVP — Implementation Task Breakdown

Ordered list of tasks for the overnight implementation run.
Each task should result in a granular git commit.
Run tests after each task to verify no regressions.

---

## Pre-flight

- [ ] **T0: Merge Codex test branch** — Cherry-pick or merge the test files from Codex's branch into `feature/nests`. Verify tests exist and fail (since implementation doesn't exist yet).
- [ ] **T0.1: Add fakeredis to requirements.txt** — `fakeredis>=2.0`

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
**Tests:** `test_nests_db.py::TestDBKeyMethod`

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
**Tests:** `test_nests_db.py::TestDBNestIsolation`, `test_nests_db.py::TestDBBackwardCompatibility`

### T3: Write key migration script
**File:** `migrate_keys.py` (new)
**Changes:**
- Script that connects to Redis and renames all existing keys to `NEST:main|` prefix
- Handle different key types: strings, hashes, sorted sets, lists, sets
- Use `SCAN` to find all keys matching known prefixes (`MISC|*`, `QUEUE|*`, `FILTER|*`, `BENDER|*`)
- Use `RENAME` for each key
- Idempotent: skip keys that already have `NEST:` prefix
- Dry-run mode (print what would be renamed)
- Log output for verification
**Commit:** `feat(nests): add key migration script for existing Redis data`
**Tests:** `test_nests_migration.py::TestKeyMigration`

### T4: Update pub/sub subscription in app.py
**File:** `app.py`
**Changes:**
- `MusicNamespace.listener()` should subscribe to `NEST:{nest_id}|MISC|update-pubsub` instead of hardcoded `MISC|update-pubsub`
- `VolumeNamespace.listener()` same change
- SSE endpoint `/api/events` same change
- For now, all use "main" as nest_id (nest routing comes in Phase 2)
**Commit:** `feat(nests): scope pub/sub channels to nest_id`
**Tests:** Run existing tests to verify no regressions

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
**Tests:** Verify config loads correctly

---

## Phase 2: Nest Backend

### T6: Create NestManager class
**File:** `nest_manager.py` (new)
**Changes:**
- `NestManager` class with Redis connection
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
**Commit:** `feat(nests): add NestManager class with CRUD operations`
**Tests:** `test_nests_manager.py` (all classes)

### T7: Add nest API routes
**File:** `app.py`
**Changes:**
- Import `NestManager`, instantiate alongside DB
- `POST /api/nests` — create nest (requires authenticated session)
- `GET /api/nests` — list active nests (public or authenticated, TBD)
- `GET /api/nests/<code>` — get nest info
- `PATCH /api/nests/<code>` — update nest (creator only)
- `DELETE /api/nests/<code>` — delete nest (creator only)
- Add `/api/nests` to `SAFE_PARAM_PATHS` (token auth or session auth)
- Return proper JSON responses with status codes
**Commit:** `feat(nests): add REST API routes for nest CRUD`
**Tests:** `test_nests_api.py`

### T8: Add `/nest/<code>` page route
**File:** `app.py`
**Changes:**
- `GET /nest/<code>` — look up nest, render `main.html` with `nest_id` in template context
- Return 404 if nest doesn't exist
- Add `/nest/` to `SAFE_PARAM_PATHS` (auth still required via session)
**Commit:** `feat(nests): add /nest/<code> page route`
**Tests:** `test_nests_api.py::TestNestRoute`

### T9: WebSocket nest routing
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
**Commit:** `feat(nests): route WebSocket connections to specific nests`
**Tests:** `test_nests_websocket.py`

### T10: Add nest cleanup to master_player
**File:** `master_player.py`, `db.py`
**Changes:**
- Refactor `master_player()` loop to iterate over all active nests
- Extract single-iteration logic into `_master_player_tick()` method
- Add `nest_cleanup_loop()` that runs alongside master_player
- Cleanup checks: `last_activity` past TTL + no members + empty queue → delete
- Skip main nest
**Commit:** `feat(nests): add multi-nest master player and cleanup worker`
**Tests:** `test_nests_cleanup.py`

---

## Phase 3: Nest Frontend

### T11: Pass nest_id to frontend template
**File:** `templates/main.html`, `templates/config.js` (if exists), `app.py`
**Changes:**
- Pass `nest_id` and `nest_info` (name, code, is_main) to template context
- Make it available to JavaScript (e.g., `window.NEST_ID`, `window.NEST_INFO`)
**Commit:** `feat(nests): pass nest context to frontend templates`

### T12: Update WebSocket connection to use nest_id
**File:** `static/js/app.js`
**Changes:**
- Read `window.NEST_ID` (default "main")
- Connect to `/socket/{nest_id}` instead of `/socket`
- Keep backward compatible: if `NEST_ID` is "main" or undefined, connect to `/socket`
**Commit:** `feat(nests): connect WebSocket to nest-specific endpoint`

### T13: Add nest bar UI
**File:** `templates/main.html`, `static/css/app.css`, `static/js/app.js`
**Changes:**
- Add a nest bar above the main content area
- When in Main Nest: show subtle "Build a Nest" button + "Join a Nest" input
- When in a temporary nest: show nest name, code, "Share Nest" button, listener count, "Back to Main Nest" link
- "Build a Nest" opens a modal with name input → POST /api/nests → show code + share link
- "Join a Nest" input: enter 5-char code → navigate to `/nest/{code}`
- "Share Nest" copies `echone.st/{code}` (or full URL if domain not configured) to clipboard
- Style it to work with the existing 9-theme system
**Commit:** `feat(nests): add nest bar UI with create/join flows`

### T14: Show listener count
**File:** `static/js/app.js`, `app.py` (or via WebSocket)
**Changes:**
- Display number of listeners in the nest bar
- Option A: Fetch from `GET /api/nests/{code}` periodically
- Option B: Broadcast listener count changes via pub/sub (preferred for real-time)
- Add a `member_update` pub/sub message type when membership changes
**Commit:** `feat(nests): show real-time listener count in nest bar`

---

## Post-Implementation

- [ ] **T15: Run full test suite** — `SKIP_SPOTIFY_PREFETCH=1 python3 -m pytest -v`
- [ ] **T16: Test manually** (if possible — start dev server, create/join nests)
- [ ] **T17: Update CHANGELOG.md** — Add Nests feature entry
- [ ] **T18: Review decision log** — Ensure all decisions are documented

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

1. **db.py refactor (T2)** — Most error-prone task. Every Redis key must be wrapped. Missing one means silent data corruption (writing to wrong key). Be exhaustive.
2. **pub/sub channel scoping (T4)** — If the channel name doesn't match between publisher (db.py) and subscriber (app.py), real-time updates break silently.
3. **WebSocket disconnect handling (T9)** — Must reliably call `leave_nest` even on abnormal disconnects. The `finally` block in `serve()` is the right place.
4. **master_player multi-nest (T10)** — The lock mechanism (`MISC|master-player` via `setnx`) needs to be per-nest: `NEST:{id}|MISC|master-player`.
