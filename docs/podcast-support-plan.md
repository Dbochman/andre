# Podcast Support Implementation Plan

## Status: COMPLETE ✓

Implemented and reviewed on 2026-02-05.

---

## Overview

Add podcast/episode support to Andre, enabling users to search for and play Spotify podcasts alongside music tracks. Episodes display properly with show name (instead of artist) and correct metadata.

---

## Scope

### Implemented (V1)
- ✓ Separate podcast search (dedicated search input)
- ✓ Play episodes via Spotify
- ✓ Display episode metadata correctly (title, show name, cover art)
- ✓ Queue display with proper episode formatting
- ✓ Dynamic skip button text ("skip playing song" vs "skip playing podcast")
- ✓ One-time-per-track sync to prevent choppy audio
- ✓ Proper error handling with HTTP status checks and timeouts

### Out of Scope (V1)
- Bender auto-fill with podcasts (music-only for recommendations)
- Podcast-specific features (chapters, playback speed)
- Show browsing (only episode search)

---

## Files Modified

| File | Changes |
|------|---------|
| `db.py` | Added `get_spotify_episode()`, `_extract_images()` helper, modified `add_spotify_song()` to detect episodes via URI parsing |
| `app.py` | Added `/search/podcast` endpoint for episode-only search |
| `templates/main.html` | Added episode template, podcast search form, fixed underscore.js variable scoping with `obj.property` pattern |
| `static/js/app.js` | Added `podcast_search_submit()`, one-time sync per track, dynamic skip button text, Spotify play with `position_ms` |
| `static/css/app.css` | Added podcast search styling, `.badge-podcast` class, text overflow handling |
| `test/test_episode.py` | 9 new tests for episode URI detection, image extraction, scrobbling |

---

## Key Implementation Details

### Backend - Episode Detection

Uses explicit URI parsing instead of substring matching:
```python
uri_parts = trackid.split(':')
is_episode = len(uri_parts) >= 2 and uri_parts[1] == 'episode'
```

### Backend - API Robustness

Both `get_spotify_song()` and `get_spotify_episode()` include:
- HTTP status code validation
- Request timeout (10 seconds)
- Error response body checking
- Proper logging

### Frontend - Template Variable Scoping

Underscore.js templates use `with(obj)` blocks, so `typeof` checks don't work. Fixed with:
```html
<% if (obj.secondary_text) { %><%=obj.secondary_text%><% } else { %><%=artist%><% } %>
```

### Frontend - Audio Sync

Syncs Spotify playback only once per track to avoid choppy audio:
```javascript
if (last_synced_spotify_track != id) {
    last_synced_spotify_track = id;
    spotify_play(id, pos);
}
```

### Frontend - Position in Play Request

Uses `position_ms` in the play request body instead of separate seek call (avoids 403 errors with podcasts):
```javascript
var playData = { "uris": [id] };
if (pos && pos > 0) {
    playData.position_ms = pos * 1000;
}
```

---

## Verification Checklist

- [x] Search for podcasts in dedicated search field
- [x] Episodes appear with show name in results
- [x] Add episode to queue
- [x] Episode plays via Spotify player
- [x] Now Playing shows episode title and show name
- [x] Queue displays episode with correct metadata
- [x] Skip button shows "skip playing podcast" for episodes
- [x] "sync spotify" button works for both tracks and podcasts
- [x] No choppy audio from repeated sync calls
- [x] All 9 tests pass

---

## Code Review

Passed Codex review after fixes for:
1. Substring check bug → Explicit URI parsing
2. Double-splitting → Conditional split with colon check
3. Missing HTTP status check → Added status validation
4. No request timeout → Added 10-second timeout

---

## Rollback

Changes are additive - if issues arise:
- Comment out `/search/podcast` endpoint to disable podcast search
- Existing track functionality unchanged
- No database migrations required
