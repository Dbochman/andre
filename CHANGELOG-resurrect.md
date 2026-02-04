# Andre Resurrection - Change Summary

This document captures the changes made to resurrect Andre from the original Python 2 codebase to a working Python 3 application.

## Overview

Andre is a collaborative music queue system that integrates with Spotify. This session focused on fixing runtime issues discovered during testing after the initial Python 3 migration.

## Files Changed

### app.py - Core Application Fixes

**WebSocket Handling (Critical Fix)**
- Moved WebSocket connection handling to `before_request` hook instead of Flask routes
- gevent-websocket processes WebSocket upgrades at the WSGI level, *before* Flask route dispatch
- Added helper functions: `_get_authenticated_email()`, `_handle_websocket()`, `_handle_volume_websocket()`
- The `require_auth()` function now intercepts `Upgrade: websocket` headers first

**Session Cookie Configuration**
- Added `SESSION_COOKIE_SAMESITE = 'Lax'` for browser compatibility
- Added `SESSION_COOKIE_SECURE = False` (should be True in production with HTTPS)

**WebSocket Manager Improvements**
- Better timeout handling with `gevent.Timeout(30, False)`
- Proper connection close detection using `getattr(self._ws, 'closed', False)`
- Added bytes-to-string decoding for messages
- Wrapped event handlers in try/except to prevent single handler errors from killing the connection

**Redis PubSub**
- Added `decode_responses=True` to Redis pubsub connections for consistent string handling
- Removed manual bytes decoding (no longer needed)

**Spotify Token Handling**
- Fixed `get_access_token()` to handle newer spotipy versions that return a dict instead of a string
- Applied fix to both `on_fetch_search_token()` and `search_spotify()`

**HOSTNAME Configuration**
- Fixed redirect URI construction to use `CONF.HOSTNAME` even in debug mode

### db.py - Database & Bender Fixes

**Redis String Handling**
- Changed main Redis connection to `decode_responses=True`
- Added base64-wrapped pickle helpers (`pickle_dump_b64`, `pickle_load_b64`) for storing binary datetime objects
- Removed all manual `bytes.decode()` calls throughout the codebase

**Bender Recommendation Engine (Major Rewrite)**
- Spotify deprecated the `/recommendations` API (Nov 2024) and `/artists/{id}/related-artists`
- New approach uses still-working endpoints:
  1. `artist_top_tracks()` - Get top tracks from seed artist(s)
  2. `album_tracks()` - Get other tracks from the same album
  3. `search()` - Search for artist name to find collaborations
- Continuous discovery loop: stores last track as seed for next batch
- Multiple seed sources: last-queued > last-bender-track > now-playing > fallback

**Airhorn Fix**
- Made `_do_horn()` defensive about missing fields in now-playing song
- Added `name=None` default parameter

**Loop Prevention**
- Added loop limits to `get_additional_src()` and `get_fill_song()`
- Fallback return object prevents `/queue` endpoint from hanging

**UUID Fix**
- Converted UUID to string in `master_player()` for Redis compatibility

### docker-compose.yaml

**New Player Service**
- Added `player` service that runs `master_player.py` separately
- The player handles the playback loop (popping songs, managing timing)
- Shares the same image and config as the main app

**Environment Variables**
- `DEBUG=false` for production-like testing
- `DEV_AUTH_EMAIL` commented out (for Google OAuth testing)

### history.py

**Redis API Update**
- Fixed `zadd()` call to use new redis-py API: `zadd(key, {member: score})` instead of `zadd(key, score, member)`

### static/js/app.js

**WebSocket Protocol**
- Fixed WebSocket URL to use `ws://` (not `wss://`) when hostname is `127.0.0.1`
- Original code only checked for `localhost`

### static/audio/dj_airhorn.mp3

**Audio Format Fix**
- Original file was a WAV file mislabeled as `.mp3`
- Converted to proper AAC/M4A format (browsers can decode this)

### templates/main.html

**CSS Class Fix**
- Changed Filter button class from `filter` to `bender-filter` to match JavaScript event handler

## Testing Checklist

- [x] Google OAuth login works
- [x] WebSocket connects (`ws://` on localhost/127.0.0.1)
- [x] Queue displays and updates in real-time
- [x] Search returns Spotify results
- [x] Adding songs to queue works
- [x] Bender recommendations work (using top tracks + album tracks + search)
- [x] Filter button rotates through Bender suggestions
- [x] Queue button adds Bender suggestion to queue
- [x] Airhorns work (when a song is "playing")
- [ ] Actual Spotify playback control (requires user OAuth token)

## Known Limitations

1. **Spotify Playback**: Andre shows the queue but doesn't control actual Spotify playback without user OAuth setup
2. **Deprecated APIs**: Spotify's recommendations and related-artists APIs return 404; workaround implemented
3. **Missing Audio Files**: `wow.wav` referenced but doesn't exist (non-blocking)

## Configuration Notes

For Google OAuth to work:
- `HOSTNAME` must exactly match the redirect URI registered in Google Cloud Console
- Use `127.0.0.1:5001` not `localhost:5001` if that's what's registered
