# Nests — Multi-Room Support for Andre

**Status:** Draft / RFC
**Author:** Dylan + Claude
**Date:** 2026-02-11

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
| Short URL | `echone.st/X7K2P` |
| Users in a Nest | **Listeners** (or keep existing terminology) |

### User Flow

1. Open Andre → auto-join the Main Nest (current experience, unchanged)
2. Click **"Build a Nest"** → get a 5-character code (e.g. `X7K2P`)
3. Share the code or link (`echone.st/X7K2P`)
4. Friends enter code or visit link → join the Nest
5. Nest has its own queue, voting, jams, Bender, now-playing — fully independent
6. Nest auto-deletes after configurable period of inactivity (no listeners + empty queue)
   - **Note:** With the 10-minute TTL, temporary nests will disappear quickly if everyone leaves; keep a tab open if you plan to return.

### Domain Setup

`echone.st` is the primary domain. Andre is served directly from it via Caddy.
`andre.dylanbochman.com` 301-redirects to `echone.st`. Bare nest codes
(`echone.st/X7K2P`) are caught by a Flask catch-all route and redirected to `/nest/X7K2P`.

---

## Architecture

### Core Principle: Nest-Scoped Redis Keys

Currently, all state lives under flat Redis keys like:

```
MISC|now-playing          → current song ID
MISC|priority-queue       → sorted set of queue
QUEUE|{song_id}           → hash of song metadata
QUEUE|VOTE|{song_id}      → vote tracking
FILTER|{track_uri}        → bender filter
BENDER|cache:genre        → recommendation cache
MISC|update-pubsub        → pub/sub channel
```

**Proposed:** Prefix all nest-scoped keys with `NEST:{nest_id}|`:

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

The Main Nest uses `nest_id = "main"`.

### Nest Registry

A top-level Redis hash tracks all active nests:

```
NESTS|registry            → hash { nest_id: JSON metadata }
NESTS|code:{code}         → string nest_id (lookup index)
```

Each nest's metadata:

```json
{
  "id": "X7K2P",
  "code": "X7K2P",
  "name": "Friday Vibes",
  "created_by": "dylan@example.com",
  "created_at": "2026-02-10T15:30:00",
  "last_activity": "2026-02-10T16:45:00",
  "ttl_minutes": 5,
  "is_main": false
}
```

**Decision:** For MVP, set `nest_id == code`. This keeps URLs stable and avoids an extra lookup. If we later want opaque IDs, add `NESTS|code:{code} -> nest_id` and update routes to resolve code → id via that index.

The Main Nest entry is permanent and cannot be deleted.

### Nest Membership Tracking

```
NEST:{nest_id}|MEMBERS    → set of user emails currently connected
NEST:{nest_id}|MEMBER:{email} → TTL key updated by heartbeat (optional)
```

Updated on WebSocket connect/disconnect, with an optional heartbeat TTL per user to avoid stale memberships. Used for:
- Showing "N listeners" in UI
- Determining inactivity (empty set + empty queue = candidate for cleanup)

---

## Backend Changes

### 1. DB Class — Nest-Aware Key Generation

The `DB` class currently hardcodes Redis keys. Add a `nest_id` parameter that scopes all operations.

**Approach A (recommended): Nest context on DB instance**

```python
class DB(object):
    def __init__(self, nest_id="main", init_history_to_redis=True):
        self.nest_id = nest_id
        # ...existing init...

    def _key(self, key):
        """Prefix a Redis key with the nest scope."""
        return f"NEST:{self.nest_id}|{key}"
```

Then refactor all Redis key references to use `self._key(...)`:

```python
# Before
self._r.get('MISC|now-playing')

# After
self._r.get(self._key('MISC|now-playing'))
```

The `_key()` method is the single choke point — every Redis operation goes through it. This means:
- All existing logic (queue ordering, voting, Bender, etc.) works unchanged per-nest
- No need to duplicate any business logic
- A `DB("main")` instance behaves identically to today's single-instance DB

**Global keys that should NOT be nest-scoped:**
- `MISC|spotify-rate-limited` (shared across all nests)
- `FILTER|{track_uri}` could go either way (nest-scoped means the same song can play in two nests simultaneously — probably desired)

### 2. Nest CRUD Operations

New methods on a `NestManager` class (or on DB):

```python
class NestManager:
    def create_nest(self, creator_email, name=None) -> dict:
        """Build a new nest with a random 5-char code. Returns nest metadata."""

    def get_nest(self, nest_id) -> dict:
        """Get nest metadata. Returns None if nest doesn't exist."""

    def list_nests(self) -> list:
        """List all active nests (returns [(nest_id, metadata), ...])."""

    def delete_nest(self, nest_id):
        """Delete a nest and all its Redis keys."""

    def touch_nest(self, nest_id):
        """Update last_activity timestamp."""

    def join_nest(self, nest_id, email):
        """Add user to nest's member set."""

    def leave_nest(self, nest_id, email):
        """Remove user from nest's member set."""

    def generate_code(self) -> str:
        """Generate a unique 5-char alphanumeric code (uppercase, no ambiguous chars)."""
```

**Code generation:** Use uppercase alphanumeric minus ambiguous characters (`0/O`, `1/I/L`). Character set: `ABCDEFGHJKMNPQRSTUVWXYZ23456789` (30 chars). 5 characters = 30^5 = ~24.3 million possible codes. Collision check against `NESTS|registry`.

**Free tier cap:** If creator is not premium and active free nests >= `NEST_FREE_MAX_ACTIVE`, reject creation (HTTP 403/429) with a clear upgrade prompt.

**Error payload (example):**
```json
{
  "error": "nest_limit_reached",
  "message": "Free nests are currently at capacity. Upgrade to create a new nest.",
  "upgrade_url": "/billing/upgrade"
}
```

**UI copy (suggested):**
- Title: “Nests at Capacity”
- Body: “Free nests are full right now. Upgrade to build a new nest instantly.”
- CTA: “Upgrade to Pro”

### 3. Nest Cleanup Worker

Add to `master_player.py` (or a separate worker):

```python
def nest_cleanup_loop():
    """Periodically check for inactive nests and delete them."""
    while True:
        for nest_id, metadata in nest_manager.list_nests():
            if metadata['is_main']:
                continue
            last_activity = parse_iso(metadata['last_activity'])
            inactive_minutes = (now - last_activity).total_seconds() / 60
            members = r.scard(f'NEST:{nest_id}|MEMBERS')
            queue_size = r.zcard(f'NEST:{nest_id}|MISC|priority-queue')
            if inactive_minutes > metadata['ttl_minutes'] and members == 0 and queue_size == 0:
                nest_manager.delete_nest(nest_id)
        sleep(60)  # Check every minute
```

**Cleanup deletes all `NEST:{nest_id}|*` keys** using a Redis SCAN + DELETE pattern. This is safe because nest keys are fully namespaced.

### 4. WebSocket Changes

Currently, `MusicNamespace` subscribes to a single pub/sub channel (`MISC|update-pubsub`). With nests:

- Each nest gets its own channel: `NEST:{nest_id}|MISC|update-pubsub`
- On WebSocket connect, the client specifies which nest to join (via URL path or initial message)
- `MusicNamespace.__init__` takes a `nest_id` parameter
- The listener subscribes to that nest's channel
- The `DB` instance is created with the matching `nest_id`

```python
class MusicNamespace(WebSocketManager):
    def __init__(self, email, penalty, nest_id="main"):
        super().__init__()
        self.nest_id = nest_id
        self.db = DB(nest_id=nest_id, init_history_to_redis=False)
        # ...
```

### 5. App Routes

New routes:

```
POST /api/nests              → Build a nest (returns code + nest_id)
GET  /api/nests              → List active nests
GET  /api/nests/{code}       → Get nest info
PATCH /api/nests/{code}      → Update nest (name, bender toggle) — creator only
DELETE /api/nests/{code}     → Delete nest (creator only)
GET  /nest/{code}            → Serve the main UI with nest context
```

The WebSocket upgrade in `before_request` needs to extract the nest from the request path:

```
/socket              → main nest (default, backward compatible)
/socket/{nest_id}    → specific nest
```

### 6. Master Player — Per-Nest Playback

The `master_player()` loop currently manages one queue. With nests, it needs to manage all active nests:

**Option A: Single worker, iterate over nests**
```python
def master_player(self):
    while True:
        for nest_id in nest_manager.get_active_nest_ids():
            db = DB(nest_id=nest_id)
            # Run one iteration of playback logic for this nest
            db._master_player_tick()
        sleep(1)
```

**Option B: Spawn a greenlet per nest**
Each nest gets its own master_player greenlet, spawned on nest creation, killed on nest deletion. More responsive but more complex.

**Recommendation:** Start with Option A. The master_player loop is already polling-based. Iterating over a handful of nests adds negligible overhead. Move to Option B only if latency becomes noticeable with many concurrent nests.

---

## Frontend Changes

### 1. Nest UI Components

- **Nest bar** at the top of the page showing current nest name + code + "Copy Link" button
- **"Build a Nest"** button (opens modal: nest name, creates nest, shows code)
- **"Join a Nest"** input field (enter code → navigate to `/nest/{code}`)
- **Listener count** badge
- **"Back to Main Nest"** link (when in a temporary nest)

### 2. WebSocket Connection

Currently connects to `/socket`. With nests:

```javascript
// In Main Nest (default)
var socket = new Socket('/socket');

// In a nest
var socket = new Socket('/socket/' + nestId);
```

The nest ID comes from:
- URL path: `/nest/X7K2P` → extract code, resolve to nest_id
- Or passed via the template context from Flask

### 3. URL Routing

```
/                    → Main Nest (current behavior)
/nest/{code}         → specific nest (same UI, different data)
```

External short URL:
```
echone.st/X7K2P      → Flask catch-all redirects to /nest/X7K2P
```

Since the frontend is Backbone.js with no client-side routing, the simplest approach is to pass the `nest_id` into the template context and have `app.js` use it for the WebSocket connection and API calls.

### 4. Nest Indicator

When in a nest (not Main Nest), show:
- Nest name and code prominently
- A **"Share Nest"** button that copies `echone.st/X7K2P` to clipboard
- Listener count
- If creator: inline edit for the nest name (or modal)
- "Back to Main Nest" link

When in the Main Nest, show a subtle "Build a Nest" button (doesn't clutter the existing UI).

---

## Migration Strategy

### Phase 1: Backend Key Migration (Zero Downtime)

1. Add `_key()` method to DB class
2. Refactor all Redis key references to use `_key()`
3. Default `nest_id="main"`
4. Deploy a compatibility build that reads both `MISC|*` and `NEST:main|MISC|*` (write to both if needed)
5. Run a one-time migration script (`migrate_keys.py`) that renames existing keys using `DUMP`+`RESTORE`+`DEL`:
   ```
   MISC|now-playing → NEST:main|MISC|now-playing
   ```
   - Must expose a `migrate()` function (contract tests verify this)
   - Uses `SCAN` to cover ALL 9 Redis key prefix families (see Redis Key Reference below)
   - Idempotent: skips keys that already have `NEST:` prefix; skips if destination exists
6. Deploy a cleanup build that stops reading legacy keys — behavior is identical, all data now lives under `NEST:main|*`

### Phase 2: Nest Backend

1. Add `NestManager` class in `nests.py` (module at project root — tests import via `importlib.import_module("nests")`)
   - Scaffold already exists with `NotImplementedError` stubs; implementation replaces stubs
   - Helper functions (pure) + `NestManager` (Redis CRUD) + module-level `join_nest`/`leave_nest` wrappers all live in this one file
   - Helpers that need Redis take an explicit `redis_client` parameter (no global singleton)
2. Add nest CRUD API routes
3. Make WebSocket accept nest_id
4. Add nest cleanup to master_player
5. Deploy — nests work but there's no UI for them yet (API-only)
6. Add creator-only update endpoint (vanity name + optional bender toggle)

### Phase 3: Nest Frontend

1. Add nest bar UI
2. Add "Build a Nest" / "Join a Nest" flows
3. Add `/nest/{code}` route
4. Deploy — full feature live

### Phase 4: echone.st Domain — DONE

Domain is registered (Netim, Lite Hosting, expires 2027-02-11) and configured on Cloudflare.
echone.st is now the **primary domain** — served directly by Caddy on the DigitalOcean droplet.

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

**Page Rules:** Cloudflare page rules removed — Caddy and Flask handle all routing.

**Nest code routing:** Flask catch-all route matches bare 5-char nest codes
(`echone.st/X7K2P`) and redirects to `/nest/X7K2P`.

**Remaining TODO:**
- Update "Share Nest" button to use `echone.st/{code}` short URL

### Phase 5: Polish

1. Nest names / theming per nest
2. Nest history (what played in this nest)
3. Nest-specific Bender settings (genre weights, on/off toggle)
4. "Active Nests" discovery on landing page
5. Nest creator controls (kick listener, lock nest)
6. Nest-specific branding/emoji in share links
7. **Paid Admin Console** (see below)

---

## Configuration

New config options:

```yaml
# Nests
NESTS_ENABLED: true
NEST_MAX_INACTIVE_MINUTES: 5      # Auto-delete after 5 minutes of inactivity
NEST_MAX_ACTIVE: 20               # Max concurrent nests (prevents resource abuse)
NEST_CODE_LENGTH: 5               # Characters in nest code
NEST_BENDER_DEFAULT: true         # Whether Bender runs in new nests by default
ECHONEST_DOMAIN: echone.st        # Short-link domain for sharing
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
NEST:{id}|QUEUE|{song_id}              → hash (song metadata)
NEST:{id}|QUEUE|VOTE|{song_id}         → vote data
NEST:{id}|FILTER|{track_uri}           → bender recently-played filter
NEST:{id}|BENDER|seed-info             → hash (current seed artist)
NEST:{id}|BENDER|cache:genre           → list (cached recommendations)
NEST:{id}|BENDER|cache:throwback       → list
NEST:{id}|BENDER|cache:artist-search   → list
NEST:{id}|BENDER|cache:top-tracks      → list
NEST:{id}|BENDER|cache:album           → list
NEST:{id}|BENDER|throwback-users       → hash (user attribution)
NEST:{id}|BENDER|next-preview          → hash (next bender song preview)
NEST:{id}|MEMBERS                      → set of connected user emails
NEST:{id}|MEMBER:{email}              → heartbeat TTL key (per-member liveness)
NEST:{id}|QUEUEJAM|{song_id}         → sorted set of jams (actual key in db.py)
NEST:{id}|COMMENTS|{song_id}          → sorted set of comments
NEST:{id}|FILL-INFO|{trackid}         → hash (cached Spotify metadata for auto-fill)
NEST:{id}|AIRHORNS                     → list of airhorn events (actual key in db.py)
NEST:{id}|FREEHORN_{userid}            → set of free airhorn eligible songs
```

---

## Implementation Notes

### Code → ID Mapping

- **MVP decision:** `nest_id == code`, so URLs use the actual ID and no extra lookup is required.
- **If we later decouple:** add `NESTS|code:{code} -> nest_id` and resolve all inbound routes via that index. Keep `code` in metadata for display.

### Membership Heartbeats (avoid stale listeners)

- On WebSocket connect, add email to `NEST:{id}|MEMBERS` and set `NEST:{id}|MEMBER:{email}` with a short TTL (e.g., 60–120s).
- On client heartbeat (e.g., every 30s), refresh the TTL.
- Cleanup uses `MEMBERS` but can optionally prune any members whose `MEMBER:{email}` key is missing before counting.

### Vanity Nests (curated names)

- **Supported for MVP:** allow creators to set a display name on creation; allow editing only by the creator.
- **Storage:** `name` in nest metadata (already present); keep it sanitized and length-limited.
- **Validation:** strip leading/trailing whitespace, collapse internal whitespace, reject empty or all-symbol names, limit length (`NEST_VANITY_MAX_LEN`).
- **Display:** show `name` in UI; if absent, default to `Nest {CODE}`.
- **Abuse control:** rate-limit renames (`NEST_VANITY_RATE_LIMIT_MIN`) and apply auth checks (creator only).

### Update Endpoint (PATCH /api/nests/{code})

- **Request body (JSON):** `{ "name": "Friday Vibes", "bender_enabled": true }` (fields optional)
- **Auth:** creator-only (match `created_by`); return 403 otherwise.
- **Validation:** apply the same name rules as create; ignore no-op updates; return 400 for invalid.
- **Side effects:** update `last_activity`, publish an update on the nest pub/sub channel so clients refresh the nest bar.

---

## Paid Admin Console (Feature Gate)

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
5. **Audit**: show “Last updated by {user} at {timestamp}” per section.

### Vanity URL Policy (robust defaults)

- **Charset**: lowercase a–z, 0–9, hyphen; must start with a letter.
- **Length**: 3–24 characters.
- **Reserved words**: `admin`, `api`, `socket`, `nest`, `login`, `signup`, `static`, `assets`, `health`, `status`, `metrics`, `terms`, `privacy`.
- **Collision**: case-insensitive; `jazznight` conflicts with `JazzNight`.
- **Immutability**: once claimed, only creator can release/change it; old vanity code is released immediately on change (no hold period — confirmed in Open Questions).
- **Abuse**: block obvious impersonation (configurable denylist).

### Suggested Data Additions

- Nest metadata fields:
  - `admin_enabled` (bool), `plan` (string), `is_private` (bool)
  - `theme` (object: colors, font, accent)
  - `bender` (object: enabled, weights, limits)
  - `banlist` (set of user email addresses)
  - `vanity_code` (string) with `NESTS|vanity:{code} -> nest_id`
  - `invite_token` (string) and `invite_token_rotated_at`
- Audit trail (optional): `NEST:{id}|AUDIT` list for admin actions (kick/ban/rename/visibility)

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
- Vanity URLs can be changed or released by the creator at any time (no hold period, immediate release — see D006).
- If a plan lapses, keep current settings but block edits until upgraded.
- Tier split confirmed:
  - **Tier A:** Vanity URL + Theme
  - **Tier B:** Moderation + Invite-only + Bender controls

---

## Billing Integration (Plan Enforcement)

### Sources of Truth

- Billing provider (e.g., Stripe) is authoritative for plan tier + active status.
- Cache the entitlements in app DB with a short TTL to reduce API calls.

### Billing Product Model (confirmed)

- **Products/Prices**
  - Tier A (Vanity + Theme): **$5/month**
  - Tier B (Moderation + Invite-only + Bender controls): **$30/month** or **$300/year**
- **Billing cadence:** monthly + annual for Tier B.
- **Trials:** none.
- **Upgrades/Downgrades:** proration on upgrade; downgrade effective at period end.

### Entitlements Model

- `plan_tier`: `free`, `tier_a`, `tier_b`
- `status`: `active`, `past_due`, `canceled`
- `features`: derived booleans (`vanity`, `theme`, `moderation`, `invite_only`, `bender_controls`)

### Entitlements Data Schema (minimal)

```
ENTITLEMENTS|{email} -> hash
  plan_tier: "free" | "tier_a" | "tier_b"
  status: "active" | "past_due" | "canceled"
  period_end: "2026-03-01T00:00:00Z"
  updated_at: "2026-02-11T12:34:56Z"
  features: JSON string {"vanity":true,"theme":true,"moderation":false,"invite_only":false,"bender_controls":false}
```

**Cache TTL:** 5–15 minutes (refresh on webhook events).

### Enforcement Points

- **Create nest**: block if free + cap reached (existing rule).
- **Admin routes**: hard‑block if entitlements don’t include the feature.
- **UI**: show “Upgrade” state when feature not allowed.

### Lapse Behavior

- Keep existing premium settings in effect, but block changes (read‑only).
- If the plan is canceled, **release vanity URL immediately**.

### Webhooks / Events

- On payment success: refresh entitlements.
- On plan change: re-evaluate feature gates immediately.
- On cancel: lock admin edit routes; optionally queue vanity release.

**Stripe events (minimum set):**
- `checkout.session.completed`
- `customer.subscription.created`
- `customer.subscription.updated`
- `customer.subscription.deleted`
- `invoice.payment_succeeded`
- `invoice.payment_failed`

**Subscription status mapping:**
| Stripe status | App status | Behavior |
|---|---|---|
| `trialing` | `active` | (unused; no trials) |
| `active` | `active` | Full access per tier |
| `past_due` | `past_due` | Read-only admin, no new changes |
| `canceled` | `canceled` | Revoke admin edits, release vanity |

### Webhook Ops (setup + reliability)

- **Signing secret:** store in `STRIPE_WEBHOOK_SECRET`.
- **Idempotency:** store processed event IDs (`STRIPE_EVENT|{id}`) with TTL 30 days.
- **Retries:** Stripe retries for up to ~3 days; ensure handlers are idempotent.
- **Out-of-order events:** trust event timestamps; prefer subscription object state on `customer.subscription.updated`.
- **Alerting:** notify on repeated webhook failures or signature mismatch.

### Payments & Compliance Notes

- Use hosted checkout (PCI reduction). Do not store card data.
- Webhook verification + idempotency keys on all billing callbacks.
- Tax/VAT: use Stripe Tax (automatic tax) where available.
- Billing emails: use Stripe’s customer email + configure receipt/invoice emails.
- Proration: enable prorations on upgrade; for annual, prorate remaining time and charge immediately.
- Refunds/chargebacks: 7‑day no‑questions‑asked window; add a manual override path for super admins.

### Billing Data Schema (minimal)

```
CUSTOMER|{email} -> hash
  billing_customer_id: "cus_123"
  subscription_id: "sub_123"
  price_id: "price_123"
  plan_tier: "free" | "tier_a" | "tier_b"
  status: "active" | "past_due" | "canceled"
  current_period_end: "2026-03-01T00:00:00Z"
  cancel_at_period_end: "false"
```

### Billing Endpoints (minimal)

```
POST /api/billing/checkout          → create hosted checkout session
POST /api/billing/portal            → create billing portal session
POST /api/billing/webhook           → receive provider events
GET  /api/billing/status            → current plan + entitlements
```

### Stripe IDs (config)

```yaml
STRIPE_SECRET_KEY: sk_live_...
STRIPE_WEBHOOK_SECRET: whsec_...
STRIPE_PRICE_TIER_A_MONTHLY: price_tier_a_monthly
STRIPE_PRICE_TIER_B_MONTHLY: price_tier_b_monthly
STRIPE_PRICE_TIER_B_ANNUAL: price_tier_b_annual
```

---

## Metrics, Monitoring & Alerts

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

## Scaling & Redis Strategy (future‑proofing)

### When to Consider Sharding

- Sustained Redis ops > 30k/sec with p95 latency > 10ms.
- Active nests consistently > 500 with high activity.
- Pub/Sub fan‑out saturating the app server CPU/network.

### Sharding Approach (incremental)

- **Phase 1:** Separate Redis for pub/sub vs data (split hot channels).
- **Phase 2:** Hash‑shard nests by `nest_id` across multiple Redis instances.
- **Phase 3:** Redis Cluster or managed shard service.

### Keying Guideline

- Always keep the `NEST:{id}|` prefix; shard routing uses `{id}` hash.

---

## Abuse Protections

### Rate Limits

- Create nest: free = 3/hour per user, 10/hour per IP; paid = 30/hour per user.
- Join nest: 30/min per IP, 10/min per user (to discourage code guessing).
- Rename nest: existing rate limit (`NEST_VANITY_RATE_LIMIT_MIN`).
- Admin actions: 20/min per user for kick/ban; invite rotate 5/hour per nest.
- Vanity claim: 3/day per nest, 10/day per creator.

**Storage & keys (Redis):**
- `RL|create_nest|user:{email}|{minute}` -> count (TTL 2h)
- `RL|create_nest|ip:{ip}|{minute}` -> count (TTL 2h)
- `RL|join_nest|user:{email}|{minute}` -> count (TTL 1h)
- `RL|join_nest|ip:{ip}|{minute}` -> count (TTL 1h)
- `RL|admin_action|user:{email}|{minute}` -> count (TTL 1h)
- `RL|invite_rotate|nest:{id}|{hour}` -> count (TTL 48h)
- `RL|vanity_claim|nest:{id}|{day}` -> count (TTL 7d)
- `RL|vanity_claim|user:{email}|{day}` -> count (TTL 7d)

**Proxy/IP handling:** trust `X-Forwarded-For` only if requests are from known reverse proxies; otherwise use `remote_addr`. Keep a `TRUSTED_PROXY_IPS` allowlist.

### Validation & Sanitization

- Validate vanity codes against policy (see above).
- Sanitize display names (strip control chars, collapse whitespace).
- Enforce size limits on comments/jams to avoid key bloat.

### Moderation Safety

- Audit all admin actions to `NEST:{id}|AUDIT`.
- Shadow‑ban option (optional) for abuse mitigation without escalation.

---

## Super Admin Interfaces (internal)

**Purpose:** Operational oversight, billing support, and safety.

### Super Admin Capabilities

- View/search all nests (by code, creator email, vanity URL).
- Force‑delete a nest (with reason + audit).
- Release/transfer a vanity URL.
- Override invite‑only and rotate invite token.
- View ban list and unban globally.
- View billing status + entitlements and force refresh.
- Throttle/lock a nest temporarily (rate limit abuse).

### Super Admin Permission Model

- Super admin access only via a separate allowlist (`SUPER_ADMIN_EMAILS`).
- MFA required for super admin actions.
- All super admin actions must write to a global audit log:
  - `AUDIT|super_admin` list of JSON events.
- Sensitive actions (force delete, vanity transfer, ban override) require a reason string.

### Super Admin UI (minimal)

- **Nests table:** code, name, creator, plan, active listeners, status.
- **Nest detail:** metadata, live status, recent actions, admin overrides.
- **Billing panel:** subscription state, last invoice, plan changes.
- **Safety panel:** abuse reports, blocked codes, global denylist.

---

## Audit Log Schema (minimal)

```
NEST:{id}|AUDIT -> list of JSON lines
{
  "ts": "2026-02-11T12:34:56Z",
  "actor": "creator@example.com",
  "action": "ban_user",
  "target": "user@example.com",
  "meta": {"reason":"spam"}
}
```

---

## Open Questions

1. **Vanity limit:** You want 1 vanity per paid nest and no hold period on old vanity codes (confirmed).

2. **Admin eligibility:** Creator-only and defined strictly by `created_by` email (confirmed).

3. **Font whitelist:** Proposed initial list (Winamp-inspired, readable on web): `Tahoma`, `Trebuchet MS`, `Verdana`, `Arial Black`, `Impact`, `Lucida Sans`, `MS Sans Serif` (fallback to `sans-serif`).

4. **Should Bender run in temporary nests?** It's nice for keeping music going, but adds load. Could default to off in temporary nests and let the creator toggle it.

5. **Should users be in multiple nests simultaneously?** Probably not for MVP — you're in one nest at a time. The WebSocket is per-nest. (If we add this later, membership tracking should use session IDs rather than emails.)

6. **Nest persistence across deploys?** Since nests are in Redis and Redis persists (RDB/AOF), nests survive container restarts. But should they survive intentional deploys? Probably yes for short-lived nests.

7. **Private nests?** For MVP, all nests are open (anyone with the code can join). Later: optional password or invite-only.

8. **Should play history (throwback data) be shared across nests or per-nest?** Probably shared — throwback data is historical and global.

9. **Main Nest vs. temporary nest feature parity?** The Main Nest should have every feature temporary nests have. Nests are just isolated instances of the same experience.

10. ~~**echone.st — register now or later?**~~ **DONE.** Domain registered 2026-02-11 via Netim ($21.50/yr). Includes free Lite Hosting for 12 months. Ready to configure.

---

## Effort Estimate

| Phase | Scope | Estimate |
|-------|-------|----------|
| Phase 1: Key migration | DB refactor + migration script | Small-Medium |
| Phase 2: Nest backend | NestManager, API routes, WebSocket, cleanup | Medium |
| Phase 3: Nest frontend | UI components, routing, nest bar | Medium |
| Phase 4: echone.st | ~~Domain registration~~ + redirect config | Small (domain secured) |
| Phase 5: Polish | Optional enhancements | Ongoing |

**MVP (Phases 1-3):** Medium-sized project. The key insight is that the `_key()` prefix method means zero business logic changes — the queue algorithm, voting, Bender, etc. all work identically per-nest without modification.
