# Nests — Multi-Room Support for Andre

**Status:** Phases 1-4 Complete, Phase 5 In Progress
**Author:** Dylan + Claude
**Date:** 2026-02-11
**Last Updated:** 2026-02-11

---

## Overview

Add the ability to create temporary, independent listening sessions called **Nests** — a nod to Andre's origins at [The Echo Nest](https://en.wikipedia.org/wiki/The_Echo_Nest). Each Nest has its own queue, voting, jams, and Bender. Nests are shareable via short codes and auto-cleanup after inactivity.

The current single-queue experience becomes the persistent **Main Nest** (lobby). The domain `echone.st` serves as a short-link for sharing Nest codes.

### Branding

| Concept | Term |
|---------|------|
| A listening session | **Nest** |
| The default/permanent session | **Main Nest** |
| Creating a session | **Build a Nest** |
| Joining a session | **Join a Nest** / **Fly in** |
| The shareable code | **Nest code** |
| Short URL (code) | `echone.st/X7K2P` |
| Short URL (slug) | `echone.st/friday-vibes` |
| Users in a Nest | **Listeners** (or keep existing terminology) |

### User Flow

1. Open Andre → auto-join the Main Nest (current experience, unchanged)
2. Click **"Build a Nest"** → modal dialog with optional name and seed track
3. Share the code or link (`echone.st/X7K2P` or `echone.st/friday-vibes`)
4. Friends enter code or visit link → join the Nest
5. Nest has its own queue, voting, jams, Bender, now-playing — fully independent
6. Nest auto-deletes after configurable period of inactivity (no listeners + empty queue)
   - **Note:** With the 5-minute TTL, temporary nests will disappear quickly if everyone leaves; keep a tab open if you plan to return.

### Domain Setup

`echone.st` is the primary domain. Andre is served directly from it via Caddy.
`andre.dylanbochman.com` 301-redirects to `echone.st`. Bare nest codes
(`echone.st/X7K2P`) and slugs (`echone.st/friday-vibes`) are caught by a Flask
catch-all route and redirected to `/nest/{CODE}`.

---

## Architecture

### Core Principle: Nest-Scoped Redis Keys — DONE

All state lives under `NEST:{nest_id}|`-prefixed Redis keys:

```
NEST:main|MISC|now-playing
NEST:main|MISC|priority-queue
NEST:main|QUEUE|{song_id}
NEST:main|QUEUE|VOTE|{song_id}
NEST:main|FILTER|{track_uri}
NEST:main|BENDER|cache:genre
NEST:main|MISC|update-pubsub        ← pub/sub channel per nest

NEST:X7K2P|MISC|now-playing
NEST:X7K2P|MISC|priority-queue
...etc
```

The Main Nest uses `nest_id = "main"`. The `_key()` method on the `DB` class is the single choke point — every Redis operation goes through it. This means all existing logic (queue ordering, voting, Bender, etc.) works unchanged per-nest.

### Nest Registry — DONE

A top-level Redis hash tracks all active nests:

```
NESTS|registry            → hash { nest_id: JSON metadata }
NESTS|code:{code}         → string nest_id (lookup index)
NESTS|slug:{slug}         → string nest_id (slug lookup index)
```

Each nest's metadata:

```json
{
  "nest_id": "X7K2P",
  "code": "X7K2P",
  "name": "Friday Vibes",
  "slug": "friday-vibes",
  "creator": "dylan@example.com",
  "created_at": "2026-02-10T15:30:00",
  "last_activity": "2026-02-10T16:45:00",
  "ttl_minutes": 5,
  "is_main": false,
  "seed_uri": "spotify:track:xxx",
  "genre_hint": "jazz"
}
```

**Implementation note:** `nest_id == code` — URLs use the actual ID and no extra lookup is required. The `seed_uri` and `genre_hint` fields are optional, present only when the creator supplies a seed track.

The Main Nest entry is permanent and cannot be deleted.

### Nest Membership Tracking — DONE

```
NEST:{nest_id}|MEMBERS    → set of user emails currently connected
NEST:{nest_id}|MEMBER:{email} → TTL key updated by heartbeat (90s TTL, refreshed every 30s)
```

Updated on WebSocket connect/disconnect, with heartbeat TTL per user to avoid stale memberships. Used for:
- Showing "N listeners" in UI
- Determining inactivity (empty set + empty queue = candidate for cleanup)
- `count_active_members()` prunes stale members whose heartbeat key has expired

---

## Backend Changes

### 1. DB Class — Nest-Aware Key Generation — DONE

```python
class DB(object):
    def __init__(self, nest_id="main", init_history_to_redis=True):
        self.nest_id = nest_id
        # ...existing init...

    def _key(self, key):
        """Prefix a Redis key with the nest scope."""
        return f"NEST:{self.nest_id}|{key}"
```

All Redis key references use `self._key(...)`. A `DB("main")` instance behaves identically to the original single-instance DB.

**Global keys that are NOT nest-scoped:**
- `MISC|spotify-rate-limited` (shared across all nests)
- `NESTS|registry`, `NESTS|code:*`, `NESTS|slug:*` (global lookup indices)

### 2. Nest CRUD Operations — DONE

`NestManager` class in `nests.py`:

```python
class NestManager:
    def create_nest(self, creator_email, name=None, seed_track=None) -> dict
    def get_nest(self, nest_id) -> dict          # Looks up by nest_id, code, or slug
    def list_nests(self) -> list                  # Returns [(nest_id, metadata), ...]
    def delete_nest(self, nest_id)                # Deletes all NEST:{id}|* keys
    def touch_nest(self, nest_id)                 # Updates last_activity
    def join_nest(self, nest_id, email)           # Adds to MEMBERS set
    def leave_nest(self, nest_id, email)          # Removes from MEMBERS set
    def generate_code(self) -> str                # Unique 5-char code
```

**Code generation:** Character set `ABCDEFGHJKMNPQRSTUVWXYZ23456789` (30 chars, no ambiguous 0/O/1/I/L). 5 characters = 30^5 = ~24.3M possible codes. Collision check against registry.

**Queue depth limit:** Temporary nests enforce `NEST_MAX_QUEUE_DEPTH` (default 25). Main nest has no limit.

**Race-resistant deletion:** A `DELETING` flag with 30s TTL blocks writes during cleanup. All nest-scoped operations check this flag before writing.

### 3. Nest Auto-Generated Names — DONE

50 sonic/audio-themed names in `NEST_NAMES` tuple (e.g., WaveyNest, BassNest, FunkNest, etc.). When no name is provided, `_pick_random_name()` selects an unused name. If all 50 are taken, appends a numeric suffix.

### 4. Seed Track & Genre Identity — DONE

**NEST_SEED_MAP:** Each auto-generated name maps to a `(spotify_track_uri, genre_keyword)` tuple. 50 entries covering genres from funk to techno to afrobeat.

**User-supplied seed tracks:** When `seed_track` (a `spotify:track:xxx` URI) is provided at creation:
1. Validate URI format (must start with `spotify:track:`)
2. Call `_resolve_track_seed()` → Spotify API lookup for artist genres
3. Store `seed_uri` and `genre_hint` in nest metadata

**Bender seed resolution priority (most specific wins):**
1. Explicit `seed_uri` from metadata (user supplied a track)
2. `NEST_SEED_MAP` lookup by nest name (auto-generated themed name)
3. `_DEFAULT_SEED` (Billy Joel - Piano Man)

**Bender genre boosting:** `_get_nest_genre_hint()` returns the genre for this nest (explicit metadata → name-based lookup → None). When present, adds +20 flat bonus to the `genre` strategy weight.

### 5. Throwback Strategy Scoping — DONE

Throwback relies on play history which only exists for the main queue. For non-main nests, throwback is disabled at four levels:

1. **`_get_strategy_weights()`** — removes `throwback` from weight pool
2. **`_fill_strategy_cache()`** — returns 0 immediately for throwback
3. **`ensure_fill_songs()`** — skips throwback cache key check
4. **`get_fill_song()` rate-limit fallback** — throwback-only path scoped to main

### 6. Nest Cleanup Worker — DONE

In `master_player.py`, the cleanup loop checks every 60 seconds:
- Skip main nest
- Check `last_activity` against `ttl_minutes`
- Check member count (with stale member pruning)
- Check queue size
- Delete if inactive + empty

Cleanup uses Redis `SCAN` + `UNLINK` (non-blocking) to remove all `NEST:{id}|*` keys, plus the code and slug lookup keys.

### 7. WebSocket Changes — DONE

- Each nest has its own pub/sub channel: `NEST:{nest_id}|MISC|update-pubsub`
- WebSocket path: `/socket` (main) or `/socket/{nest_id}` (specific nest)
- `MusicNamespace` creates a `DB(nest_id=...)` instance for the connected nest
- On connect: `join_nest()` + heartbeat TTL key
- On disconnect: `leave_nest()` + delete heartbeat key
- Serve loop refreshes heartbeat TTL every 30s

### 8. App Routes — DONE

```
POST /api/nests              → Build a nest (returns code, slug, metadata)
GET  /api/nests              → List active nests (with now-playing, member count)
GET  /api/nests/{code}       → Get nest info
PATCH /api/nests/{code}      → Update nest (name) — creator only
DELETE /api/nests/{code}     → Delete nest (creator only)
GET  /nest/{code}            → Serve main UI with nest context
GET  /{slug}                 → Catch-all resolves slug → redirect to /nest/{code}
GET  /{CODE}                 → Catch-all resolves 5-char code → redirect to /nest/{CODE}
```

### 9. Slug URLs — DONE

Custom-named nests generate URL slugs via `slugify()`:
- Lowercase, replace non-alphanumeric with hyphens, strip leading/trailing hyphens
- Stored in metadata as `slug` field
- Redis lookup: `NESTS|slug:{slug}` → nest_id
- Catch-all route resolves slugs: `echone.st/friday-vibes` → `/nest/{CODE}`
- Slug lookup cleaned up on nest deletion
- `get_nest()` resolves by nest_id, code, or slug

### 10. Master Player — Per-Nest Playback — DONE

Single worker iterates over all active nests (Option A from original plan):

```python
for nest_id in nest_manager.get_active_nest_ids():
    db = DB(nest_id=nest_id)
    db._master_player_tick()
```

---

## Frontend Changes

### 1. Nest Bar UI — DONE

- Top bar shows nest name + code + "Copy Link" button
- Listener count badge
- "Back to Main Nest" link (when in a temporary nest)
- "Build a Nest" and "Join a Nest" buttons

### 2. Create Nest Dialog — DONE

Modal dialog (replaces browser `prompt()`) with:
- **Name field** (optional) — leave blank for auto-generated sonic name
- **Seed Track field** (optional, visible only when custom name entered):
  - Paste `spotify:track:...` URI directly, OR
  - Type to search — debounced Spotify search (300ms) shows top 5 results
  - Click a result to fill the URI
  - Sets genre vibe for Bender auto-fills
- Dark backdrop overlay prevents background scroll/interaction
- Centered with `max-height: 80vh` and scrollable content
- Click backdrop or Cancel to dismiss

### 3. Join Nest Dialog — DONE

Modal dialog with:
- **Active nests list** — shows name, now-playing track, member count for each nest (excluding current)
- **Scrollable list** with independent scroll (not page scroll)
- **Manual code entry** — 5-char code input pinned at bottom
- Dark backdrop overlay, centered, `max-height: 80vh`
- Click backdrop or Close to dismiss
- Click any nest in list to join directly

### 4. WebSocket Connection — DONE

```javascript
var socket = new Socket('/socket/' + nestId);  // nestId from template context
```

### 5. URL Routing — DONE

```
/                    → Main Nest (current behavior)
/nest/{code}         → Specific nest (same UI, different data)
/{slug}              → Redirect to /nest/{code} via slug lookup
/{CODE}              → Redirect to /nest/{CODE} via code match
```

After creating a nest with a custom name, the browser redirects to `/{slug}`. Random-named nests redirect to `/nest/{CODE}`.

### 6. Airhorn Sync — DONE

Airhorn sound plays locally as confirmation when `sync-audio` event is received.

---

## Migration Strategy

### Phase 1: Backend Key Migration — DONE

1. Added `_key()` method to DB class
2. Refactored all Redis key references to use `_key()`
3. Default `nest_id="main"`
4. Migration script (`migrate_keys.py`) renames existing keys using `DUMP`+`RESTORE`+`DEL`
   - Covers all 9 Redis key prefix families
   - Idempotent: skips keys with `NEST:` prefix; skips if destination exists
5. `SKIP_SPOTIFY_PREFETCH` env var guards module-level Spotify auth for test environments

### Phase 2: Nest Backend — DONE

1. `NestManager` class in `nests.py` with full CRUD
2. Helper functions (pure) + NestManager (Redis CRUD) + module-level wrappers
3. Nest CRUD API routes
4. WebSocket accepts `nest_id`, per-nest DB instances
5. Nest cleanup in master_player
6. Creator-only update endpoint (PATCH)
7. Queue depth limit (25 songs for temp nests)
8. Race-resistant deletion (DELETING flag)

### Phase 3: Nest Frontend — DONE

1. Nest bar UI with name, code, listener count, copy link
2. Create Nest modal with name + seed track picker
3. Join Nest modal with active nests list + manual code entry
4. `/nest/{code}` route serves UI with nest context
5. Backdrop overlays and scrollable dialogs

### Phase 4: echone.st Domain — DONE

Domain registered (Netim, Lite Hosting, expires 2027-02-11) and configured on Cloudflare.
echone.st is the **primary domain** — served directly by Caddy on the DigitalOcean droplet.

**Cloudflare Zone:**
- Zone ID: `583f76bbb1bd8c655b86958885fdef76`
- Account: `324caf800a82364b608b3e82d9a1debd` (dylanbochman@gmail.com)
- Nameservers: `eric.ns.cloudflare.com`, `monika.ns.cloudflare.com` (set at Netim)

**DNS Records:**
- `echone.st` → A `192.81.213.152` (proxied)
- `www.echone.st` → A `192.0.2.1` (proxied, Caddy handles redirect)

**Caddy (see `/Caddyfile` in repo):**
- `echone.st` → reverse proxy to localhost:5001 (primary)
- `www.echone.st` → 301 redirect to `echone.st`
- `andre.dylanbochman.com` → 301 redirect to `echone.st`

**Routing:** Flask catch-all resolves both bare 5-char codes and slug URLs.

### Phase 5: Polish — IN PROGRESS

Completed:
- [x] Auto-generated sonic nest names (50 themed names)
- [x] NEST_SEED_MAP with genre-specific Bender seeding per nest name
- [x] User-supplied seed track at creation (Spotify URI → genre resolution)
- [x] Throwback disabled for non-main nests
- [x] Slug URLs for custom-named nests (`echone.st/friday-vibes`)
- [x] Modal dialogs with backdrop overlay and scrollable lists
- [x] Seed track search UI with Spotify lookup
- [x] Dead Spotify URI audit and replacement (15 of 50 fixed)
- [x] Active nests with now-playing shown in Join dialog
- [x] Queue depth limit (25 songs) for temporary nests

Remaining:
- [ ] Nest history (what played in this nest)
- [ ] Nest-specific Bender weight sliders (creator controls)
- [ ] Nest creator controls (kick listener, lock nest)
- [ ] Nest-specific branding/emoji in share links
- [ ] **Paid Admin Console** (see below)

---

## Bender Strategy Architecture (per-nest)

### Strategy Weights

Default weights (from config or `STRATEGY_WEIGHTS_DEFAULT`):

| Strategy | Weight | Notes |
|----------|--------|-------|
| genre | 35 (+20 if genre hint) | Searches Spotify by genre keyword |
| throwback | 30 | **Main nest only** — disabled for temp nests |
| artist_search | 25 | Searches for artist collaborations |
| top_tracks | 5 | Top tracks from seed artist |
| album | 5 | Other tracks from same album |

### Seed Resolution Chain

For each Bender fill, the seed is resolved in order:
1. Last user-queued track URI
2. Last Bender-added track URI
3. Currently playing track
4. Fallback seed (see below)

### Fallback Seed Priority

1. **Explicit `seed_uri`** from nest metadata (user supplied a seed track at creation)
2. **`NEST_SEED_MAP`** lookup by nest name (auto-generated themed names)
3. **`_DEFAULT_SEED`** — Billy Joel "Piano Man" (main nest, unknown names)

### Genre Hint Injection

When a nest has a genre hint (explicit or name-derived), the genre is injected into `_fetch_genre_tracks()` with double weight (~50% selection chance alongside artist genres). This ensures genre-themed nests stay on-genre even when the seed artist has diverse genres.

---

## Configuration — DONE

Active config options in `config.yaml`:

```yaml
# Nests
NESTS_ENABLED: true
NEST_MAX_INACTIVE_MINUTES: 5      # Auto-delete after 5 minutes of inactivity
NEST_MAX_ACTIVE: 20               # Max concurrent nests (prevents resource abuse)
NEST_CODE_LENGTH: 5               # Characters in nest code
NEST_BENDER_DEFAULT: true         # Whether Bender runs in new nests by default
NEST_MAX_QUEUE_DEPTH: 25          # Max songs in temp nest queue
ECHONEST_DOMAIN: echone.st        # Short-link domain for sharing
```

Future config options (not yet implemented):
```yaml
NEST_ALLOW_VANITY: true           # Allow custom nest names
NEST_VANITY_MAX_LEN: 40           # Max length for display name
NEST_VANITY_ALLOW_RENAME: true    # Allow creator to rename after creation
NEST_VANITY_RATE_LIMIT_MIN: 1     # Minimum minutes between renames
NEST_ADMIN_ENABLED: false         # Enable paid admin console features
NEST_ADMIN_PLAN: "pro"            # Plan tier required for admin features
NEST_FREE_MAX_ACTIVE: 50          # Max concurrent free nests (block create when exceeded)
```

---

## Redis Key Reference (Complete)

### Global Keys (not nest-scoped)
```
NESTS|registry                          → hash of all nests
NESTS|code:{code}                       → string nest_id (code lookup)
NESTS|slug:{slug}                       → string nest_id (slug lookup)
MISC|spotify-rate-limited               → rate limit flag
```

### Per-Nest Keys (prefixed with NEST:{nest_id}|)
```
NEST:{id}|MISC|now-playing              → current song ID
NEST:{id}|MISC|now-playing-done         → TTL marker for song end
NEST:{id}|MISC|priority-queue           → sorted set (the queue)
NEST:{id}|MISC|backup-queue             → list (backup songs)
NEST:{id}|MISC|backup-queue-data        → hash (backup metadata)
NEST:{id}|MISC|master-player            → master player lock
NEST:{id}|MISC|last-queued              → last user-queued track URI
NEST:{id}|MISC|last-bender-track        → last bender-added track URI
NEST:{id}|MISC|bender_streak_start      → bender streak timestamp
NEST:{id}|MISC|update-pubsub            → pub/sub channel
NEST:{id}|MISC|volume                   → volume level
NEST:{id}|MISC|paused                   → pause state
NEST:{id}|MISC|DELETING                 → flag during nest deletion (30s TTL)
NEST:{id}|QUEUE|{song_id}              → hash (song metadata)
NEST:{id}|QUEUE|VOTE|{song_id}         → vote data
NEST:{id}|FILTER|{track_uri}           → bender recently-played filter
NEST:{id}|BENDER|seed-info             → hash (current seed artist)
NEST:{id}|BENDER|cache:genre           → list (cached recommendations)
NEST:{id}|BENDER|cache:throwback       → list (main nest only)
NEST:{id}|BENDER|cache:artist-search   → list
NEST:{id}|BENDER|cache:top-tracks      → list
NEST:{id}|BENDER|cache:album           → list
NEST:{id}|BENDER|throwback-users       → hash (user attribution, main nest only)
NEST:{id}|BENDER|next-preview          → hash (next bender song preview)
NEST:{id}|MEMBERS                      → set of connected user emails
NEST:{id}|MEMBER:{email}              → heartbeat TTL key (90s, per-member liveness)
NEST:{id}|QUEUEJAM|{song_id}         → sorted set of jams
NEST:{id}|COMMENTS|{song_id}          → sorted set of comments
NEST:{id}|FILL-INFO|{trackid}         → hash (cached Spotify metadata for auto-fill)
NEST:{id}|AIRHORNS                     → list of airhorn events
NEST:{id}|FREEHORN_{userid}            → set of free airhorn eligible songs
```

---

## Implementation Notes

### Decisions Made (see `docs/NESTS_DECISION_LOG.md` for full details)

| # | Decision | Rationale |
|---|----------|-----------|
| D001 | Migration uses DUMP+RESTORE+DEL | Idempotent, safe for partial re-runs |
| D002 | GET /api/nests requires auth | Prevents leaking nest names/codes/creators |
| D003 | Migration covers all 9 key families | Prevents orphaned data |
| D004 | Heartbeat TTL for stale members | Prevents stale memberships blocking cleanup |
| D005 | Spotify rate limit key stays global | Rate limiting is per-app, not per-nest |
| D006 | No hold period on vanity release | Simplicity for MVP |
| D007 | POST /api/nests returns 200 | Matches existing contract tests |
| D008 | Single test file with xfail contracts | Contract tests as primary suite |
| D009 | Admin access is creator-only | No admin role system for MVP |
| D010 | /nest/{code} pages require auth | Consistent with app-wide OAuth gate |
| D016 | SKIP_SPOTIFY_PREFETCH guard | Allows clean imports in test environments |
| D017 | echone.st as primary domain | Cleaner than redirect chain |

### Resolved Open Questions

1. ~~Vanity limit~~ → 1 vanity per paid nest, no hold period (D006)
2. ~~Admin eligibility~~ → Creator-only by `created_by` email (D009)
3. ~~Font whitelist~~ → Not yet needed (future Phase 5)
4. ~~Should Bender run in temporary nests?~~ → **Yes**, with genre-aware seeding per nest name/seed track. Throwback disabled for non-main nests.
5. ~~Multiple nests simultaneously?~~ → No, one nest at a time per WebSocket
6. ~~Nest persistence across deploys?~~ → Yes, Redis persists (RDB/AOF)
7. ~~Private nests?~~ → Not for MVP, future Phase 5
8. ~~Throwback data shared or per-nest?~~ → **Shared play history, but throwback strategy disabled for non-main nests.** Play history is global; throwback caches are nest-scoped but only populated for main.
9. ~~Main vs temporary feature parity?~~ → Yes, except throwback (main only)
10. ~~echone.st domain~~ → **DONE.** Registered and configured.

### Remaining Open Questions

1. **Slug collision handling:** What happens when two nests produce the same slug? Currently last-write-wins. Should we enforce uniqueness? (Low priority — nests are ephemeral.)
2. **Seed track validation:** Should we verify the Spotify track exists before storing? Currently we store the URI even if Spotify lookup fails (graceful degradation).

---

## Test Suite

### Running Tests

```bash
# All nest tests
SKIP_SPOTIFY_PREFETCH=1 python3 -m pytest test/test_nests.py -v

# All tests (ensure no regressions)
SKIP_SPOTIFY_PREFETCH=1 python3 -m pytest -v
```

### Test Coverage (78 tests in test/test_nests.py)

| Category | Tests | Status |
|----------|-------|--------|
| API contract (xfail) | 12 | Skipped (future billing/admin) |
| Admin API (xfail) | 5 | Skipped |
| Billing API (xfail) | 7 | Skipped |
| Super Admin (xfail) | 3 | Skipped |
| Entitlement gates (xfail) | 3 | Skipped |
| Audit logs (xfail) | 1 | Skipped |
| Invite-only (xfail) | 2 | Skipped |
| Free cap (xfail) | 1 | Skipped |
| Auth gating (xfail) | 2 | Skipped |
| Redis key prefixing | 1 | xpass |
| Cleanup logic | 1 | xpass |
| Membership heartbeat | 1 | xpass |
| Migration helpers | 2 | xpass |
| PubSub channels | 1 | xpass |
| Master player multi-nest | 1 | xpass |
| WebSocket membership | 2 | xpass |
| Migration script behavior | 2 | xpass |
| NestManager CRUD | 6 | Passing |
| Count active members | 3 | Passing |
| Delete main guard | 1 | Passing |
| Cross-nest isolation | 5 | Passing |
| Queue depth limit | 2 | Passing |
| Race-resistant deletion | 5 | Passing |
| Nest seed map | 5 | Passing |
| Seed track metadata | 5 | Passing |

**Total: 32 passed, 36 skipped, 10 xpassed**

---

## Paid Admin Console (Feature Gate) — NOT STARTED

**Goal:** Monetize advanced nest controls and vanity URLs with a paid admin interface.

### Admin Capabilities (paid)

- **Vanity URLs:** allow custom short codes/URLs (e.g., `echone.st/jazznight`). Reserved words and collisions enforced.
- **Nest theming:** per-nest colors, fonts, and accent style.
- **Bender controls:** per-nest toggles + weight sliders (genre bias, throwback ratio, max streak).
- **Moderation:** kick/ban users; ban list scoped to the nest.
- **Privacy:** invite-only toggle and invite link rotation.

### Admin UX Flow (minimal)

1. **Admin entry point**: "Nest Settings" link visible only to the creator in the nest bar.
2. **Plan gate**: If unpaid, show a paywall screen with feature list + upgrade CTA.
3. **Settings tabs**:
   - **General**: name, vanity URL, invite-only toggle, rotate invite link.
   - **Theme**: colors, font picker, preview.
   - **Bender**: enable toggle, sliders for weights/limits.
   - **Moderation**: kick/ban list, ban search, recent actions.
4. **Save model**: changes are explicit Save/Cancel (avoid live changes) and publish to pub/sub on save.
5. **Audit**: show "Last updated by {user} at {timestamp}" per section.

### Vanity URL Policy (robust defaults)

- **Charset**: lowercase a–z, 0–9, hyphen; must start with a letter.
- **Length**: 3–24 characters.
- **Reserved words**: `admin`, `api`, `socket`, `nest`, `login`, `signup`, `static`, `assets`, `health`, `status`, `metrics`, `terms`, `privacy`.
- **Collision**: case-insensitive; `jazznight` conflicts with `JazzNight`.
- **Immutability**: once claimed, only creator can release/change it; old vanity code is released immediately on change (no hold period — D006).
- **Abuse**: block obvious impersonation (configurable denylist).

### Admin Routes (paid)

```
GET  /api/nests/{code}/admin            → fetch admin settings (auth required)
PATCH /api/nests/{code}/admin           → update admin settings
POST /api/nests/{code}/kick             → kick user
POST /api/nests/{code}/ban              → ban user
POST /api/nests/{code}/unban            → unban user
POST /api/nests/{code}/invites/rotate   → rotate invite token
```

### Gating & Billing Notes

- Gate admin routes via plan checks (`NEST_ADMIN_PLAN`) and a verified billing status.
- Consider soft-gating: allow UI preview but enforce on save.
- Vanity URLs can be changed or released by the creator at any time (no hold period, immediate release — D006).
- If a plan lapses, keep current settings but block edits until upgraded.
- Tier split confirmed:
  - **Tier A:** Vanity URL + Theme
  - **Tier B:** Moderation + Invite-only + Bender controls

---

## Billing Integration (Plan Enforcement) — NOT STARTED

### Billing Product Model (confirmed)

- **Products/Prices**
  - Tier A (Vanity + Theme): **$5/month**
  - Tier B (Moderation + Invite-only + Bender controls): **$30/month** or **$300/year**
- **Billing cadence:** monthly + annual for Tier B.
- **Trials:** none.
- **Upgrades/Downgrades:** proration on upgrade; downgrade effective at period end.

### Billing Endpoints (minimal)

```
POST /api/billing/checkout          → create hosted checkout session
POST /api/billing/portal            → create billing portal session
POST /api/billing/webhook           → receive provider events
GET  /api/billing/status            → current plan + entitlements
```

### Stripe Config

```yaml
STRIPE_SECRET_KEY: sk_live_...
STRIPE_WEBHOOK_SECRET: whsec_...
STRIPE_PRICE_TIER_A_MONTHLY: price_tier_a_monthly
STRIPE_PRICE_TIER_B_MONTHLY: price_tier_b_monthly
STRIPE_PRICE_TIER_B_ANNUAL: price_tier_b_annual
```

---

## Metrics, Monitoring & Alerts — NOT STARTED

### Core Metrics

- `nests.active_total`, `nests.active_free`, `nests.active_paid`
- `nests.created_total`, `nests.deleted_total`
- `nests.cleanup_runs`, `nests.cleanup_deleted`
- `nests.code_collisions`
- `ws.connections_total`, `ws.connections_by_nest`, `ws.reconnects`
- `queue.ops_per_sec`, `queue.size_p95`, `queue.size_max`
- `bender.ops_per_sec`, `bender.failures`
- `pubsub.msgs_per_sec`, `pubsub.bytes_per_sec`

### Alerts (initial)

- Cleanup loop stalled (no run > 5 min).
- Redis latency p95 > 5–10 ms sustained.
- WebSocket disconnect rate spike.
- Active nests within 90% of free cap for > 10 min.

---

## Scaling & Redis Strategy (future-proofing) — NOT STARTED

### When to Consider Sharding

- Sustained Redis ops > 30k/sec with p95 latency > 10ms.
- Active nests consistently > 500 with high activity.
- Pub/Sub fan-out saturating the app server CPU/network.

### Sharding Approach (incremental)

- **Phase 1:** Separate Redis for pub/sub vs data (split hot channels).
- **Phase 2:** Hash-shard nests by `nest_id` across multiple Redis instances.
- **Phase 3:** Redis Cluster or managed shard service.

### Keying Guideline

- Always keep the `NEST:{id}|` prefix; shard routing uses `{id}` hash.

---

## Abuse Protections — NOT STARTED

### Rate Limits

- Create nest: free = 3/hour per user, 10/hour per IP; paid = 30/hour per user.
- Join nest: 30/min per IP, 10/min per user (to discourage code guessing).
- Rename nest: existing rate limit (`NEST_VANITY_RATE_LIMIT_MIN`).
- Admin actions: 20/min per user for kick/ban; invite rotate 5/hour per nest.
- Vanity claim: 3/day per nest, 10/day per creator.

### Validation & Sanitization

- Validate vanity codes against policy (see above).
- Sanitize display names (strip control chars, collapse whitespace).
- Enforce size limits on comments/jams to avoid key bloat.

---

## Super Admin Interfaces (internal) — NOT STARTED

**Purpose:** Operational oversight, billing support, and safety.

### Super Admin Capabilities

- View/search all nests (by code, creator email, vanity URL).
- Force-delete a nest (with reason + audit).
- Release/transfer a vanity URL.
- Override invite-only and rotate invite token.
- View ban list and unban globally.
- View billing status + entitlements and force refresh.
- Throttle/lock a nest temporarily (rate limit abuse).

### Super Admin Permission Model

- Super admin access only via a separate allowlist (`SUPER_ADMIN_EMAILS`).
- MFA required for super admin actions.
- All super admin actions must write to a global audit log.

---

## Effort Estimate

| Phase | Scope | Status |
|-------|-------|--------|
| Phase 1: Key migration | DB refactor + migration script | **DONE** |
| Phase 2: Nest backend | NestManager, API routes, WebSocket, cleanup | **DONE** |
| Phase 3: Nest frontend | UI components, routing, nest bar | **DONE** |
| Phase 4: echone.st | Domain registration + config | **DONE** |
| Phase 5: Polish | Names, seeds, slugs, throwback scoping, dialogs | **Partially done** |
| Phase 6: Admin console | Paid features, billing, moderation | Not started |
| Phase 7: Monitoring | Metrics, alerts, scaling | Not started |

**MVP (Phases 1-4): COMPLETE.** The core nests feature is fully functional with genre-aware Bender, slug URLs, modal dialogs, and scrollable nest discovery.
