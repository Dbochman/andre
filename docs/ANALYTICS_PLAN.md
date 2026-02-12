# EchoNest Analytics — Redis-Native Tracking + Admin Dashboard

## Context

EchoNest has no analytics. We just manually queried Redis to count 8 users. We need lightweight, Redis-native event tracking with a simple admin stats page so Dylan can see who's using the app and how.

## Architecture

### Core: `analytics.py` — New module

A thin tracking layer using Redis sorted sets and hashes with daily key bucketing. No new dependencies.

**Key pattern:** `ANALYTICS|{event_type}|{YYYY-MM-DD}`

**Event types to track:**

| Event | Trigger Location | Data Captured |
|-------|-----------------|---------------|
| `login` | `app.py:auth_callback()` (line ~871) | email, method=google |
| `signup` | `app.py:signup()` (line ~1024) | email, ip |
| `ws_connect` | `app.py:MusicNamespace.__init__()` (line ~338) | email, nest_id |
| `ws_disconnect` | `app.py:MusicNamespace._on_disconnect()` (line ~344) | email, nest_id |
| `song_add` | `app.py:on_add_song()` (lines ~492/495/499) | email, song_id, src |
| `vote` | `app.py:on_vote()` (line ~541) | email, song_id, direction |
| `jam` | `app.py:on_jam()` (line ~573) | email, song_id |
| `airhorn` | `app.py:on_airhorn()` (line ~557) | email, airhorn_name |
| `bender_fill` | `db.py:ensure_queue_depth()` (line ~691) | strategy, track_uri |
| `song_finish` | `db.py:log_finished_song()` (line ~1863) | song_id, duration |

**Redis storage strategy:**

```
# Daily event counters (sorted set: member=email, score=count)
ANALYTICS|login|2026-02-12         → {dylan@gmail.com: 3, bob@bob.com: 1}
ANALYTICS|song_add|2026-02-12      → {dylan@gmail.com: 15, kurt@gmail.com: 2}

# Daily totals (hash: field=event_type, value=count)
ANALYTICS|totals|2026-02-12        → {login: 4, signup: 1, song_add: 17, vote: 23, ...}

# Global unique users (set, no TTL)
ANALYTICS|known_users              → {dylan@gmail.com, bob@bob.com, ...}

# All daily keys get 90-day TTL for auto-cleanup
```

**Module API:**
```python
# analytics.py
def track(redis_client, event_type, email=None, metadata=None):
    """Record an event. One-liner to call from any route/handler."""

def get_daily_stats(redis_client, date=None):
    """Return dict of event counts for a given day."""

def get_user_stats(redis_client, days=30):
    """Return per-user activity summary over N days."""

def get_daily_active_users(redis_client, date=None):
    """Return set of unique emails active on a given day."""
```

### Files to Modify

#### 1. `analytics.py` (NEW) — Tracking module

- `track(r, event_type, email=None, metadata=None)` — core function
  - Increments `ANALYTICS|{event}|{date}` sorted set (score += 1 for email)
  - Increments `ANALYTICS|totals|{date}` hash field
  - Adds email to `ANALYTICS|known_users` set
  - Adds email to `ANALYTICS|dau|{date}` set (daily active users)
  - Sets 90-day TTL on daily keys (idempotent via `EXPIRE`)
  - All operations pipelined for single round-trip
- `get_daily_stats(r, date=None)` — returns `{event: count}` for a date
- `get_user_stats(r, days=30)` — returns per-user totals across N days
- `get_daily_active_users(r, date=None)` — returns set of emails
- `get_top_users(r, event_type, days=7)` — leaderboard for an event type

#### 2. `app.py` — Add tracking calls + admin route

**Add tracking calls** (one-liners, minimal footprint):
- `auth_callback()` after successful login → `track(r, 'login', email)`
- `signup()` after successful creation → `track(r, 'signup', email)`
- `MusicNamespace.__init__()` → `track(r, 'ws_connect', self.email)`
- `MusicNamespace._on_disconnect()` → `track(r, 'ws_disconnect', self.email)`
- `on_add_song()` → `track(r, 'song_add', self.email)`
- `on_vote()` → `track(r, 'vote', self.email)`
- `on_jam()` → `track(r, 'jam', self.email)`
- `on_airhorn()` → `track(r, 'airhorn', self.email)`

**Add admin route:**
- `GET /admin/stats` — protected by email check (only `dylanbochman@gmail.com` or configurable `CONF.ADMIN_EMAILS`)
- Renders `templates/admin_stats.html`
- Passes: today's stats, 7-day DAU trend, top users, signup count, total known users

#### 3. `db.py` — Add tracking for Bender and song finish

- `ensure_queue_depth()` after fill → `track(r, 'bender_fill')`
- `log_finished_song()` → `track(r, 'song_finish')`

#### 4. `templates/admin_stats.html` (NEW) — Dashboard

Simple, single-page dashboard with:
- **Today at a Glance**: DAU count, songs queued, votes, airhorns, signups
- **7-Day DAU Chart**: Simple bar chart (CSS-only, no JS charting library)
- **Top Users (7 days)**: Table of most active users by songs added, votes, jams
- **Recent Signups**: List of guest signups with dates
- Styled consistently with existing templates (dark theme, Bootstrap 3)

#### 5. `config.py` — Add `ADMIN_EMAILS` to `ENV_OVERRIDES`

- Add `ECHONEST_ADMIN_EMAILS` to `ENV_OVERRIDES` list
- Maps to `ADMIN_EMAILS` config key

## Security

- Admin page gated by email check — only configured admin emails can access
- No PII beyond email (already stored in Redis for queue operations)
- 90-day TTL on all daily keys — auto-cleanup, no unbounded growth
- Tracking is fire-and-forget — failures don't affect the main app

## Verification

```bash
# Run tests
SKIP_SPOTIFY_PREFETCH=1 python3 -m pytest -v

# Manual verification
# 1. Log in → check ANALYTICS|login|{today} key in Redis
# 2. Add a song → check ANALYTICS|song_add|{today}
# 3. Visit /admin/stats → see dashboard with today's activity
# 4. Verify non-admin gets redirected away from /admin/stats
```
