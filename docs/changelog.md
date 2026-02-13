# Changelog

All notable changes to EchoNest are documented in this file.

---

## 2026-02-06

### Features

- **Spotify Playlist & Album URL Support** - Paste open.spotify.com URLs directly into search
  - Supports playlist, album, and track URLs (e.g. `https://open.spotify.com/playlist/...`)
  - Shows up to 20 tracks with an "Add All" button to bulk-queue them
  - Existing `spotify:album:` and `spotify:artist:` URIs now also show track lists with Add All
  - Private/invalid playlists show a friendly error message
  - **Files Changed**: `static/js/app.js`, `static/css/app.css`

- **YouTube Playlist URL Support** - Paste YouTube playlist URLs to see all videos
  - Supports `youtube.com/watch?v=...&list=...` and `youtube.com/playlist?list=...` formats
  - Shows up to 20 videos with an "Add All" button to bulk-queue them
  - Single video URLs (without `list=`) still work as before
  - **Files Changed**: `app.py`, `static/js/app.js`

- **Sync Audio Button** - Improved UX for audio sync
  - Added prominent "sync audio" button at top of Airhorn tab
  - Airhorn button now hidden until user syncs audio (encourages connection)
  - Button disappears after sync, airhorn button appears
  - Removed free airhorn button (UI declutter)
  - Commit: `c6df2a7`

### Cleanup

- **Airhorn Code Simplification** - Removed redundant logic from airhorn flow
  - Removed `make_player()`/`resume_spotify_if_needed()` calls (audio sync is now a prerequisite)
  - Removed dead `do_free_airhorn()` function and event binding (button already removed from HTML)
  - Removed dead `free_horns` socket handler
  - Confirmation dialog and airhorn picker dropdown preserved
  - **Files Changed**: `static/js/app.js`

- **Hide Shame Mixed Content Fix** - Replaced broken external placeholder image sites with inline SVG
  - 4 of 6 placeholder sites (lorempixel, fillmurray, placecage, placekitten) are now dead
  - Switched to self-contained SVG data URIs with random colored blocks
  - Eliminates mixed content warnings and broken images
  - **Files Changed**: `static/js/app.js`

- **Pause Button Guard** - Only pause Spotify when a Spotify track is playing
  - Prevents 403 errors from Spotify API when pausing during YouTube/SoundCloud playback
  - **Files Changed**: `static/js/app.js`

### Bug Fixes

- **YouTube Duration Parsing** - Fixed ISO 8601 duration parsing (PT1H9M9S, PT5M30S, etc.)
  - Hours now display correctly for long videos
  - Fixed regex to handle all YouTube duration formats

- **Search Token Refresh Loop** - Fixed infinite loop when Spotify rate limits search token refresh
  - Only schedule refresh if `time_left > 0`

- **Local Volume Decoupling** - Local playback volume now independent of server volume
  - Users can mute/adjust their own playback without affecting others
  - Spotify device volume preserved instead of being overwritten by server

- **SoundCloud OAuth Integration** - Fully reactivated SoundCloud support with server-side OAuth
  - SoundCloud deprecated simple client_id API authentication; now requires OAuth tokens
  - Implemented `client_credentials` OAuth flow (server-side only, no user popup required)
  - Backend fetches and caches OAuth tokens with automatic refresh
  - Stream URLs are resolved server-side to get direct CDN URLs for HTML5 Audio playback
  - Replaced SoundCloud SDK with lightweight HTML5 Audio player
  - Added WebSocket events: `resolve_soundcloud`, `get_soundcloud_stream`
  - Configuration: Add `SOUNDCLOUD_CLIENT_SECRET` to config alongside existing `SOUNDCLOUD_CLIENT_ID`

**Files Changed**:
- `app.py` - Added `get_soundcloud_token()`, `on_resolve_soundcloud()`, `on_get_soundcloud_stream()` handlers
- `db.py` - Updated `add_soundcloud_song()` to use OAuth, added `permalink_url` to track data
- `config.py` - Added `SOUNDCLOUD_CLIENT_SECRET` to env overrides
- `config.example.yaml` - Added `SOUNDCLOUD_CLIENT_SECRET` placeholder
- `static/js/app.js` - Updated `soundcloud_url_search()` to use WebSocket, updated `cloud()` function
- `static/js/sc.js` - Rewrote to use HTML5 Audio with server-provided stream URLs
- `templates/base.html` - Removed SoundCloud SDK, changed to `SOUNDCLOUD_ENABLED` boolean flag

---

## 2026-02-05

### Features

- **Podcast Support** - Added ability to search for and play Spotify podcast episodes
  - Separate podcast search input in the Search tab
  - Episode metadata display (show name, cover art)
  - Dynamic skip button text ("skip playing song" vs "skip playing podcast")
  - 9 new tests for episode handling
  - PR #5, Commit: `411b568`

### Bug Fixes

- **WebSocket Message Blocking Fix** - Fixed critical issue where WebSocket messages (airhorn, add_song, vote, etc.) would never reach the server
  - Root cause: Synchronous Spotify API calls in the `fetch_playlist` handler blocked the entire WebSocket receive loop
  - When rate limited, spotipy's internal retry logic would block for hours, preventing any messages from being processed
  - Added rate limit checks before ALL Spotify API calls in the request path (`get_additional_src`, `get_fill_info`)
  - Changed rate limit state storage from Python global variable to Redis for persistence across container restarts
  - Added `_parse_session_cookie()` to properly parse Flask session cookies for WebSocket authentication (Flask's session isn't initialized during WebSocket upgrade)
  - Simplified Socket.emit() in app.js - removed unnecessary setTimeout wrapper

- **Visual Duplicate Fix** - Fixed issue where now-playing track appeared in both Now Playing section and queue due to WebSocket timing
  - Added client-side filtering in `PlaylistView.render()`
  - Commit: `7f97604`

- **Spotify Unpause Fix** - Fixed issue where Spotify playback wouldn't resume when unpausing Andre
  - Added state transition detection to call `resume_spotify_if_needed()` when going from paused to unpaused
  - Commit: `1ef478f`

- **Spotify 403 Error Fix** - Fixed 403 Forbidden errors when resuming Spotify without an active device
  - Changed `resume_spotify_if_needed()` to use `spotify_play()` with track URI instead of bare play endpoint
  - Commit: `f17cccf`

- **Missing Audio File Fix** - Fixed 404 error and console warnings for missing `wow.wav` airhorn file
  - Removed reference to non-existent audio file from `app.js`

- **Form Accessibility Fix** - Added missing `id` and `name` attributes to search input fields
  - Fixed 3 form fields in `main.html` that triggered browser accessibility warnings

- **Queue Profile Image Clipping** - Fixed profile images being clipped in queue items
  - Changed person-image from 43x65px to 65x65px square to match Gravatar aspect ratio
  - Adjusted controls and jammers positioning to accommodate wider images

- **Volume Override on Sync** - Fixed issue where syncing Spotify would set volume to 1 instead of user's local volume
  - Changed `fix_player()` to use `volumeBeforeMute` (user's local Spotify device volume) instead of server's global `volume`
  - Applies to Spotify, SoundCloud, and YouTube players
  - Commit: `f46c4bf`

- **Local Volume Independence** - Server volume broadcasts no longer override local playback volume
  - Server volume only updates the UI slider, not actual playback
  - Airhorns now use local volume (`volumeBeforeMute`) instead of server volume
  - Fixes issue where airhorns were nearly silent when server volume was set low

- **Search Token Refresh Loop Fix** - Fixed infinite loop when Spotify is rate limited
  - When rate limited, server returns `time_left=0` which caused client to immediately re-request token
  - Now only schedules token refresh when `time_left > 0`

- **Bender Empty Queue During Podcasts** - Fixed Bender not generating song recommendations while a podcast episode is playing
  - Added `is_valid_track_seed()` helper to skip episode URIs when selecting seeds
  - Falls back to last valid track or Billy Joel when only episodes are available
  - Commit: `93aa72b`

- **YouTube URL Lookup Restored** - Fixed YouTube video adding with backend proxy and expanded URL support
  - Created `/youtube/lookup` backend endpoint to hide API key from frontend
  - Added support for `youtu.be` short URLs and `m.youtube.com` mobile URLs
  - Added proper error handling to `add_youtube_song()` with logging
  - Removed debug print statement that was logging to console
  - Commit: `932285c`

- **Spotify Rate Limit Handling** - Added global rate limit tracking to stop hammering the API when rate limited
  - `is_spotify_rate_limited()` checks if we're currently rate limited
  - `handle_spotify_exception()` detects 429 errors and sets the rate limit expiry
  - Bender, search endpoints, and search token all check before making API calls
  - Rate limit automatically clears when the retry-after period expires
  - Stopped `andre_player` container during active rate limit to prevent spotipy's internal retry logic from making requests
  - Added cron job to restart player at 1:00 AM UTC daily
  - Commits: `653cd5c`, `29d4a05`

### Features

- **Local Mute** - Added local mute button that only affects the current user's playback
  - Re-enabled Spotify Web API volume control with proper error handling (403, 429)
  - Reads actual Spotify device volume on sync and mute for accurate restore
  - Mute state persists through server volume updates and track changes
  - Replaced global "mute all" with per-user "mute" toggle
  - Added double-click protection and volume 0 edge case handling
  - Added `.cache` to `.gitignore` to prevent token leakage

### Security

- **Redis Authentication** - Added password authentication and protected mode in response to DigitalOcean security notice
  - `--requirepass` and `--protected-mode yes` flags
  - All Python Redis connections updated to use password
  - Commit: `895b62d`

- **Redis Security Documentation** - Added comprehensive best practices checklist with references
  - Commit: `a51d027`

---

## 2026-02-04

### Features

- **Enhanced Paused State Display** - Added visual indicator when playback is paused
  - Pause icon overlay on album art with Bender theme
  - PR #4, Commit: `0b2ba40`

### Infrastructure

- **Initial Cloud Deployment** - Deployed Andre to DigitalOcean
  - Ubuntu 22.04 LTS droplet with Docker Compose
  - Caddy reverse proxy with auto HTTPS
  - Live at https://andre.dylanbochman.com

### Security

- **Docker Security Hardening** - Implemented 11 security measures
  - Non-root containers
  - Pinned image versions with SHA256 digests
  - Network isolation (internal network for Redis)
  - Resource limits
  - Read-only filesystem
  - Dropped capabilities
  - Health checks

- **SSH Hardening** - Disabled root login and password authentication

- **Fail2ban** - Added SSH brute force protection with 365-day ban

- **Security Documentation** - Created comprehensive `SECURITY.md`
  - Commits: `2a091da`, `a243fd8`

---

## Earlier History

See git log for changes prior to 2026-02-04.
