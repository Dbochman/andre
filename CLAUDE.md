# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

EchoNest is a collaborative music queue system for offices and parties. Users share a queue where they can search for songs (Spotify), add them, vote to reorder, and trigger airhorns. The app uses WebSockets for real-time updates. "Bender mode" auto-fills the queue with recommendations when it runs low.

## Commands

### Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run locally (requires Redis on localhost:6379)
python run.py

# Run with Docker (all services)
docker-compose up --build
```

### Testing

```bash
# Run all tests (skip Spotify prefetch for CI/faster runs)
SKIP_SPOTIFY_PREFETCH=1 python3 -m pytest

# Run specific test file
SKIP_SPOTIFY_PREFETCH=1 python3 -m pytest test/test_auth.py

# Run single test
SKIP_SPOTIFY_PREFETCH=1 python3 -m pytest test/test_auth.py::TestAuthGate::test_health_endpoint_public
```

### Deployment

```bash
# Deploy to production (rsync + rebuild containers)
make deploy
```

This rsyncs the repo to `deploy@echone.st:/opt/echonest/`, then runs `docker compose up -d --build echonest player`. A Slack notification fires automatically on container start.

### Configuration

Copy `config.example.yaml` to `local_config.yaml` and fill in OAuth credentials. Environment variables override YAML config (e.g., `REDIS_HOST`, `DEBUG`, `DEV_AUTH_EMAIL`).

## Architecture

### Core Components

- **app.py** - Flask application with all routes, WebSocket handling, OAuth flows. Key classes: `WebSocketManager`, `MusicNamespace`, `VolumeNamespace`.
- **db.py** - Redis interface (`DB` class) and Bender recommendation engine. All queue operations, voting, and song filtering logic lives here.
- **history.py** - `PlayHistory` class for tracking played songs (powers Throwback feature).
- **run.py** - Entry point; starts gevent WSGI server on port 5000.
- **master_player.py** - Background worker that tracks playback timing, broadcasts queue updates, pre-warms Bender preview after song transitions, and runs nest cleanup loop.
- **config.py** - Loads YAML config with environment variable overrides.
- **analytics.py** - Fire-and-forget Redis-native event tracking (user activity, Spotify API calls, OAuth health).
- **slack.py** - Fire-and-forget Slack webhook notifications (deploy alerts, now-playing feed, airhorn events, nest creation). Only posts for the main nest; no-op when `SLACK_WEBHOOK_URL` is unset. Deploy notification rate-limited to once per 5 minutes via Redis (`SLACK|deploy_cooldown`) to prevent Slack spam during crash loops.
- **nests.py** - `NestManager` class, nest lifecycle helpers (`should_delete_nest`, `pubsub_channel`, etc.)
- **templates/spotify_prompt.html** - Spotify connect interstitial shown to new users after Google sign-in.
- **templates/stats.html** - Public analytics dashboard at `/stats`.
- **templates/help.html** - Help page at `/help` with Slack invite and rendered `GETTING_STARTED.md`. Opened in new tab from Other menu; close button uses `window.close()`.

### Services (Docker Compose)

```
echonest (Flask app) → Redis ← player (master_player.py)
                      ↓
                  PostgreSQL (optional, user data)
```

- `echonest` - Web server on port 5001 (maps to 5000 internally)
- `player` - Runs `master_player.py` for playback timing
- `redis` - Primary data store for queue, votes, sessions
- `db` - PostgreSQL (optional)

### Real-time Communication

WebSocket via gevent-websocket. The `before_request` hook intercepts WebSocket upgrades before Flask routing. Redis pub/sub coordinates between containers.

**SSE event stream** (`GET /api/events`): Token-authenticated Server-Sent Events endpoint for API clients. Subscribes to the same Redis pubsub channel as the WebSocket and emits `queue_update`, `now_playing`, `player_position`, and `volume` events. Keepalive comments sent every 15 seconds.

### Bender (Auto-fill) Engine

Spotify deprecated `/recommendations` and `/artists/{id}/related-artists` (Nov 2024), then `/artists/{id}/top-tracks` and batch `GET /tracks` (Feb 2026). Search limit reduced from 50 to 10. The current approach uses:
1. `artist_album_tracks()` + `album_tracks()` - Get tracks from seed artist's albums
2. `album_tracks()` - Get other tracks from same album
3. `search()` - Find artist collaborations (paginated, 2x10)

Seeds from: last-queued track → last-bender-track → now-playing → fallback.

**Strategy weights** (default): genre 35, throwback 30, artist_search 25, artist_album_tracks 5, album 5. Bender search strategies paginate (2 pages of 10) since Spotify's search limit max is now 10.

After song transitions, master_player pre-warms `BENDER|next-preview` via `_peek_next_fill_song()` and sends an explicit `playlist_update` message so clients always have fresh Bender preview data.

### Analytics

**Module**: `analytics.py` — fire-and-forget Redis tracking, 90-day TTL. All events use `analytics.track(r, event_type, email)`.

**User activity events**: `login`, `signup`, `song_add`, `vote`, `jam`, `airhorn`, `ws_connect`, `ws_disconnect`, `bender_fill`, `song_finish`

**Spotify API tracking** (12 event types): `spotify_api_search`, `spotify_api_track`, `spotify_api_artist`, `spotify_api_artist_album_tracks`, `spotify_api_album_tracks`, `spotify_api_get_track`, `spotify_api_get_episode`, `spotify_api_devices`, `spotify_api_transfer`, `spotify_api_status`, `spotify_api_rate_limited`, `spotify_api_error`. Instrumented at every Spotify API call site in `db.py` and `app.py`.

**Spotify OAuth tracking** (3 event types): `spotify_oauth_reconnect` (user clicked reconnect button), `spotify_oauth_refresh` (OAuth callback completed), `spotify_oauth_stale` (cached token missing/expired). Per-user breakdown available via sorted sets.

**Dashboard**: `/stats` — public (no auth required). Shows aggregate metrics, Spotify API call counts, OAuth health, DAU trend.

**API endpoint**: `GET /api/stats?days=N` — returns JSON with `today`, `dau`, `dau_trend`, `known_users`, `spotify_api` (call counts + daily trend), and `spotify_oauth` (reconnect/refresh/stale counts + stale_users breakdown).

### Frontend

Backbone.js + jQuery served as static files. Main logic in `static/js/app.js`. Nine color themes rotate.

## Key Patterns

### Authentication
- Google OAuth for login, Spotify OAuth per-user for playback
- New users see a Spotify connect interstitial after Google sign-in (`templates/spotify_prompt.html`); returning users with cached tokens skip straight to the app
- `DEV_AUTH_EMAIL` bypasses OAuth when `DEBUG=true` on localhost
- Public endpoints defined in `SAFE_PATHS` and `SAFE_PARAM_PATHS` lists in `app.py`
- Legacy REST routes (`/add_song`, `/blast_airhorn`, `/jam`) use `@require_session_or_api_token` — accepts browser sessions or API tokens, uses `g.auth_email` (not client-supplied email)
- REST API endpoints under `/api/` use `@require_api_token` decorator with `secrets.compare_digest` for constant-time token comparison
- `/api/` is in `SAFE_PARAM_PATHS` (bypasses session auth); token auth handled by decorator
- Config: set `ECHONEST_API_TOKEN` via environment variable or yaml config
- Spotify Connect endpoints (`/api/spotify/*`) use the same Bearer token auth; require `ECHONEST_SPOTIFY_EMAIL` to be set and the corresponding user to have completed Spotify OAuth via the browser
- Read endpoints: `GET /api/queue` (full metadata including vote, jam, comments, duration, score), `GET /api/playing` (now-playing with server timestamp), `GET /api/events` (SSE stream), `GET /api/stats?days=N` (analytics with Spotify API/OAuth breakdowns)
- CORS: allowlist-based origin validation (production hostname + localhost in debug). See `_ALLOWED_ORIGINS` in `app.py`
- Audit logging: `_log_action()` writes structured `AUDIT` lines to container stdout (login, ws_connect, api_auth_ok/fail, etc.)
- Per-user rate limits on WebSocket actions: `_check_rate_limit()` with Redis INCR/EXPIRE (50 songs/hr, 20 airhorns/hr, 30 comments/hr)

### Redis Data
- Strings decoded automatically (`decode_responses=True`)
- Binary objects (datetimes) stored via base64-wrapped pickle (`pickle_dump_b64`/`pickle_load_b64` in `db.py`)
- `QUEUE|{id}` hashes have a 24-hour TTL; the priority queue sorted set does not. `_purge_stale_queue_entries()` removes song IDs from the sorted set when their hash has expired — called by `get_queued()` and `backfill_queue()` so `zcard`-based depth checks reflect real songs. `pop_next()` also skips entries with missing `src` field. Without this, pausing >24h leaves ghost IDs that block Bender backfill.

### Spotify Token Handling
Newer spotipy versions return dict from `get_access_token()`. Code handles both string and dict formats.

### Spotify Connect (Device Control)
Server-side Spotify playback control via REST API. The `_get_spotify_client()` helper loads a cached OAuth token for `ECHONEST_SPOTIFY_EMAIL` and returns a spotipy client. Endpoints: `/api/spotify/devices`, `/api/spotify/transfer`, `/api/spotify/status`. Requires OAuth scope `user-read-playback-state user-modify-playback-state` (added to all SpotifyOAuth constructors).

## Nests Feature (In Progress)

**Plan:** See `docs/nests/plan.md` for full spec.
**Decision Log:** See `docs/nests/decision-log.md` — append every judgment call here.
**API Errors:** See `docs/nests/api-errors.md` — canonical error response shapes.
**Test Spec:** See `docs/nests/test-spec.md` (superseded — kept as reference). Canonical tests: `test/test_nests.py`.
**Branch:** `feature/nests`

### What Are Nests?

Nests are independent listening sessions (rooms) with shareable 5-character codes. The current single-queue becomes the permanent "Main Nest" (`nest_id="main"`). Temporary nests auto-cleanup after inactivity (checked every 60s by `nest_cleanup_loop()` in master_player). Cleanup is based on member count and `last_activity` TTL — orphaned queue songs from Bender do NOT prevent cleanup. Domain `echone.st` is registered for short links.

### Architecture Summary

**Core change:** All Redis keys are prefixed with `NEST:{nest_id}|` via a `_key()` method on the DB class. This means all existing business logic (queue, voting, Bender, etc.) works identically per-nest with no duplication.

**Key files being modified:**
- `db.py` — Add `nest_id` param, `_key()` method, refactor all Redis key references
- `app.py` — Add nest API routes, modify WebSocket routing to accept `nest_id`
- `master_player.py` — Iterate over all active nests instead of one queue
- `config.py` — Add nest-related config options to `ENV_OVERRIDES`
- `config.yaml` — Add default nest config values
- `templates/main.html` — Pass `nest_id` to frontend
- `static/js/app.js` — Use `nest_id` for WebSocket connection and API calls

**New files:**
- `nests.py` — Helper functions (`pubsub_channel`, `member_key`, `should_delete_nest`, etc.) + `NestManager` class
- `migrate_keys.py` — One-time migration script for existing Redis keys
- `test/test_nests.py` — Contract test suite (written by Codex, xfail until implemented)

### Redis Key Pattern

```
NEST:{nest_id}|MISC|now-playing
NEST:{nest_id}|MISC|priority-queue
NEST:{nest_id}|QUEUE|{song_id}
NEST:{nest_id}|MEMBERS
...etc (see docs/nests/plan.md for complete reference)
```

**Global keys (NOT nest-scoped):**
- `MISC|spotify-rate-limited`
- `NESTS|registry`

### Implementation Phases

1. **Phase 1 — Key Migration:** Add `_key()` to DB, refactor all key refs, migration script
2. **Phase 2 — Nest Backend:** NestManager, API routes, WebSocket nest routing, cleanup worker
3. **Phase 3 — Nest Frontend:** Nest bar UI, create/join flows, `/nest/{code}` route

### Testing

```bash
# Run nest tests (single file with xfail contract tests)
SKIP_SPOTIFY_PREFETCH=1 python3 -m pytest test/test_nests.py -v

# Run all tests (ensure no regressions)
SKIP_SPOTIFY_PREFETCH=1 python3 -m pytest -v
```

Tests are xfail contract tests using Flask test client (no fakeredis). Implementation should add `redis_client` param to `DB.__init__` (T1) and `fakeredis` to requirements (T0.1) for future unit tests, but the existing Codex tests don't require them.

### Decision Protocol

When a judgment call is needed during implementation:
1. Pick the simplest option that aligns with the plan
2. Append the decision to `docs/nests/decision-log.md` with rationale
3. Continue implementing

## echonest-sync (Desktop Sync Client)

A standalone Python package in `echonest-sync/` that syncs local Spotify playback to an EchoNest server. Two entry points: `echonest-sync` (CLI) and `echonest-sync-app` (desktop tray app with onboarding).

### Commands

```bash
# Install via Homebrew (macOS)
brew tap dbochman/echonest && brew install echonest-sync

# Install in dev mode (macOS)
cd echonest-sync && pip install -e ".[mac]"

# Run CLI
echonest-sync --server https://echone.st --token YOUR_TOKEN

# Run desktop app (tray icon + onboarding)
echonest-sync-app

# Run tests
cd echonest-sync && SKIP_SPOTIFY_PREFETCH=1 python3 -m pytest tests/ -v
```

### Architecture

- **`sync.py`** — Core sync engine: SSE listener, plays/seeks/pauses local Spotify via AppleScript (macOS), playerctl (Linux), or os.startfile (Windows). Override detection pauses sync when user manually changes tracks (15s grace period after track changes).
- **`app.py`** — Desktop launcher: checks keyring → spawns onboarding subprocess if no token → starts engine thread → starts tray on main thread.
- **`tray_mac.py`** — rumps menu bar app. Polls IPC events every 1s. Icon states: 🪺 green (synced), 🪹 yellow (paused/override), 🪹 grey (disconnected). Custom `NSAlert` with nest icon for dialogs. Link Account uses native NSAlert with text field (tkinter crashes when rumps owns main thread).
- **`tray_win.py`** — pystray equivalent for Windows/Linux. Dynamic submenus via callables.
- **`updater.py`** — GitHub Releases API update checker. Finds latest `sync-v*` tag, compares versions, returns platform-appropriate download URL.
- **`onboarding.py`** — tkinter dialog (runs as subprocess to avoid event loop conflicts). Invite code → `POST /api/sync-token` → stores token in keyring + server URL in config.
- **`config.py`** — OS-appropriate config dirs, keyring integration (macOS Keychain / Windows DPAPI), `save_config()` strips secrets before writing to disk. `DEFAULTS` dict must include any key that `load_config()` should read from the config file.
- **`ipc.py`** — Thread-safe command/event queues between tray GUI and sync engine.
- **`autostart.py`** — LaunchAgent plist (macOS) / Startup folder shortcut (Windows).
- **`link.py`** — Account linking dialog. On macOS uses NSAlert (via tray_mac); on Windows/Linux uses tkinter. Exchanges 6-char code for per-user HMAC token.
- **`search.py`** — Tkinter search dialog for finding and adding songs to the queue.
- **`audio.py`** — Cross-platform audio caching and playback for airhorn sounds.

### Server-Side Endpoints

- `POST /api/sync-token` in `app.py` — exchanges invite code for API token. Rate limited (10 attempts/IP/hour via Redis). Config: `SYNC_INVITE_CODES` list in `local_config.yaml`.
- `GET /sync/link` — session-auth page that generates a 6-char linking code (stored in Redis with 5min TTL).
- `POST /api/sync-link` — exchanges linking code for per-user HMAC token. Rate limited. Adds email to `SYNC_LINKED_USERS` Redis set.

### Account Linking

Optional feature: users link their Google account so songs added via the API use their real email (and Gravatar) instead of `openclaw@api`. Per-user tokens are `HMAC-SHA256(SECRET_KEY, "sync:" + email)` — deterministic, no DB lookup. The `require_api_token` decorator checks the shared token first, then iterates linked users (cached 60s). Search & Add is disabled in the tray until the user links their account.

### Key Gotchas

- Server `trackid` field is already a full Spotify URI (`spotify:track:...`) — don't double-prefix.
- Server `starttime` can be stale (hours old) — always clamp elapsed to track `duration` before seeking.
- macOS port 5000 is used by AirPlay Receiver — use port 5001 for local dev.
- rumps adds a default Quit menu item — use `quit_button=None` to provide your own.
- `template=True` in rumps silhouettes colored icons — use `template=False` for the nest artwork.
- `rumps.alert()` uses the Python rocket icon by default — use `NSAlert` directly with `setIcon_()` for custom dialog icons.
- `rumps.notification()` doesn't work reliably from background threads — use `NSAlert` (synchronous, main thread) or menu item text changes instead.
- macOS dock icon shows "Python" for pip-installed scripts — use `NSApplicationActivationPolicyAccessory` to hide it (`.app` bundles use `LSUIElement` in Info.plist instead).
- Tests must mock `get_token`/`get_config_dir` to isolate from real keyring, or CLI tests will connect to live servers.
- PyInstaller bundle must be codesigned or macOS Keychain rejects `keyring.set_password()` with `-67030` (SecAuthFailure). The build script signs with Developer ID by default (`--adhoc` for local dev).
- `sys.executable` in a frozen PyInstaller bundle points to the binary, not a Python interpreter — never pass `-m module` args to it. Use `getattr(sys, 'frozen', False)` to detect.
- SSE streaming response blocks the engine thread indefinitely. On quit, `_sse_response.close()` must be called to unblock the iterator.
- tkinter `Tk()` cannot be created on a background thread when rumps owns the main thread on macOS — use `NSAlert` with `setAccessoryView_()` for input dialogs instead.
- `load_config()` only reads keys present in the `DEFAULTS` dict — any new config key (like `email`) must be added there or it will be silently dropped.
- `Path | None` type hint syntax requires Python 3.10+ — use `from __future__ import annotations` for 3.9 compat.

### Packaging

- `build/macos/build_app.py` — PyInstaller `.app` bundle, Developer ID signed + notarized. Run with `/usr/local/bin/python3` (not Xcode python). Pass `--adhoc` for local dev.
- `build/windows/build_exe.py` — PyInstaller `.exe` (onefile, `icon.ico`)
- `.github/workflows/echonest-sync.yml` — CI test matrix + build/release on `sync-v*` tags

## Known Limitations

1. Spotify recommendations API deprecated - workaround uses top tracks + album tracks
2. HOSTNAME in config must exactly match Google OAuth redirect URI registration
3. `handle_spotify_exception()` is a module-level function in `db.py` — uses `_get_rate_limit_redis()` for analytics tracking since it has no `self._r`
