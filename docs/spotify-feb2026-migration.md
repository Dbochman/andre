# Spotify February 2026 API Migration Plan

**Date:** 2026-02-26
**Deadline:** March 9, 2026 (existing dev mode apps migrated)
**Changelog:** [Web API Changelog - February 2026](https://developer.spotify.com/blog/2026-02-11-changes-to-web-api)

## Context

Spotify is removing batch endpoints, `artist_top_tracks`, browse endpoints, and several response fields. Search limit drops from max 50 to max 10. All Player endpoints survive. EchoNest has 5 breaking changes and 1 search degradation to address.

## Impact Summary

| # | Severity | Issue | Location |
|---|----------|-------|----------|
| 1 | **Critical** | `GET /artists/{id}/top-tracks` removed | `db.py:560` (Bender), `app.js:1149` (artist URI) |
| 2 | **Critical** | `GET /tracks` batch removed | `app.js:1069` (search decoration) |
| 3 | **Critical** | `/playlists/{id}/tracks` → `/playlists/{id}/items` | `app.js:1162` (playlist paste) |
| 4 | **High** | Search limit max 50→10, default 20→5 | `app.py:1320`, `app.js:1360`, `app.js:1386` |
| 5 | **Low** | `show.publisher` removed from episodes | `db.py:1342` (already `.get()` safe) |

## Phase 1: Backend — Bender Engine (db.py)

### 1A. Replace `_fetch_top_tracks` with `_fetch_artist_albums_tracks`

`artist_top_tracks()` had weight 5/100 in Bender strategy weights — it's the least-used strategy. Replace it with a new strategy that fetches artist albums then samples tracks from them.

**File:** `db.py`

**Changes:**
1. Rename strategy from `top_tracks` to `artist_albums` everywhere:
   - `STRATEGY_WEIGHTS_DEFAULT`: `'top_tracks': 5` → `'artist_albums': 5`
   - `_STRATEGY_CACHE_KEYS`: `'top_tracks': 'BENDER|cache:top-tracks'` → `'artist_albums': 'BENDER|cache:artist-albums'`
   - `_fill_strategy_cache`: `elif strategy == 'top_tracks':` → `elif strategy == 'artist_albums':`

2. Replace `_fetch_top_tracks()` method body:
   ```python
   def _fetch_artist_albums_tracks(self, seed_info, market):
       """Get tracks from the seed artist's albums (replaces removed top-tracks endpoint)."""
       if not seed_info:
           return []
       artist_id = seed_info.get('artist_id', '')
       if not artist_id:
           return []
       try:
           # Fetch artist's albums (still available: GET /artists/{id}/albums)
           albums = spotify_client.artist_albums(artist_id, album_type='album,single',
                                                  country=market, limit=5)
           analytics.track(self._r, 'spotify_api_artist_albums')
           album_ids = [a['id'] for a in albums.get('items', [])]
           if not album_ids:
               return []
           # Sample tracks from each album (GET /albums/{id}/tracks still available)
           all_uris = []
           for aid in album_ids[:3]:  # Limit to 3 albums to conserve API calls
               try:
                   result = spotify_client.album_tracks(aid)
                   analytics.track(self._r, 'spotify_api_album_tracks')
                   all_uris.extend([t['uri'] for t in result.get('items', [])])
               except Exception:
                   continue
           return all_uris
       except Exception as e:
           if handle_spotify_exception(e):
               return []
           analytics.track(self._r, 'spotify_api_error')
           logger.warning("Error getting artist albums for %s: %s", artist_id, e)
           return []
   ```

3. Update `_fill_strategy_cache` dispatch:
   ```python
   elif strategy == 'artist_albums':
       uris = self._fetch_artist_albums_tracks(seed_info, market)
   ```

4. Add `spotify_api_artist_albums` to analytics event types in CLAUDE.md and `analytics.py` tracking.

### 1B. Reduce search limit in server-side search

**File:** `app.py:1320`

Change:
```python
search_result = sp.search(q, 25)
```
To:
```python
search_result = sp.search(q, 10)
```

Server-side search is used by the `/search/v2` endpoint which returns parsed results (uri, name, artist, image). The frontend already handles variable-length result lists. 10 results is sufficient for the primary "type and pick" use case.

### 1C. Reduce Bender search limits

**File:** `db.py`

The `_fetch_genre_tracks` and `_fetch_artist_search_tracks` methods use `limit` param (default 20 for main nest, 5 for temp nests). These need capping:

- `_fetch_genre_tracks` (`db.py:522`): Add `limit=min(limit, 10)` before the API call
- `_fetch_artist_search_tracks` (`db.py:541`): Add `limit=min(limit, 10)` before the API call
- Update `_bender_fetch_limit` property: change `20` to `10` for main nest

Optionally, implement pagination for Bender searches to recover volume:
```python
# Fetch two pages of 10 to get ~20 results
uris = []
for offset in range(0, min(limit, 20), 10):
    results = spotify_client.search(q, type='track', limit=10, offset=offset, market=market)
    uris.extend([t['uri'] for t in results.get('tracks', {}).get('items', [])])
```

This doubles API calls but recovers the previous fill rate. Consider making this conditional on rate-limit headroom.

## Phase 2: Frontend — JavaScript (app.js)

### 2A-NEW. Multi-URL paste support (IMPLEMENTED)

**Status:** Done — `static/js/app.js:1271-1322`

New feature that sidesteps the playlist API restriction for non-owned playlists. Users can select tracks in Spotify, copy (Ctrl/Cmd+C), and paste the resulting block of `https://open.spotify.com/track/...` URLs into the search box. The code:

1. Detects multi-line input with 2+ Spotify track URLs
2. Extracts track IDs via regex
3. Fetches each track individually via `GET /tracks/{id}` (still available)
4. Renders via existing `renderTrackList()` with "Add X Tracks to the Queue" header

**New functions:** `spotify_multi_track_fetch(trackIds)`, multi-line detection block in `uri_search_submit`.

This runs *before* the existing single-URL matching, so single track/album/playlist URLs still route to their existing handlers.

### 2B. Replace batch `GET /tracks` with individual fetches

**File:** `static/js/app.js:1069`

The `spotify_search()` function does: search → extract IDs → batch fetch full track objects. Replace the batch call with `Promise.all` of individual lookups:

```javascript
// Before (line 1069-1074):
return $.ajax({url:'https://api.spotify.com/v1/tracks',
    dataType:'json',
    headers:{Authorization:"Bearer "+search_token},
    data:{"ids": ids.join()}}).then(function(data) {
        return {'intent': intent, 'tracks': data.tracks};
    });

// After:
var trackPromises = ids.map(function(id) {
    return $.ajax({
        url: 'https://api.spotify.com/v1/tracks/' + id,
        dataType: 'json',
        headers: {Authorization: "Bearer " + search_token}
    });
});
return $.when.apply($, trackPromises).then(function() {
    var tracks = [];
    var results = trackPromises.length === 1 ? [arguments] : Array.prototype.slice.call(arguments);
    for (var i = 0; i < results.length; i++) {
        tracks.push(results[i][0]);  // $.when resolves as [data, status, xhr]
    }
    return {'intent': intent, 'tracks': tracks};
});
```

**Alternative (simpler):** Since `/search/v2` already returns parsed track data (name, artist, image, uri), we could skip the batch decoration entirely and use the server response directly. This would eliminate the client-side Spotify API calls for normal search. Evaluate whether the server response has enough data for the search result template.

### 2B. Replace artist top-tracks in URI handler

**File:** `static/js/app.js:1146-1156`

Replace the `artist` branch in `spotify_uri_search()`:

```javascript
} else if (type == 'artist') {
    // artist URI: fetch albums, then tracks from first few albums
    return $.ajax({
        url: 'https://api.spotify.com/v1/artists/' + id + '/albums',
        dataType: 'json',
        headers: {Authorization: "Bearer " + search_token},
        data: {include_groups: 'album,single', limit: 5}
    }).then(function(data) {
        if (!data.items || data.items.length === 0) return [];
        // Fetch tracks from first 3 albums
        var albumPromises = data.items.slice(0, 3).map(function(album) {
            return $.ajax({
                url: 'https://api.spotify.com/v1/albums/' + album.id,
                dataType: 'json',
                headers: {Authorization: "Bearer " + search_token}
            });
        });
        return $.when.apply($, albumPromises).then(function() {
            var tracks = [];
            var results = albumPromises.length === 1 ? [arguments] : Array.prototype.slice.call(arguments);
            for (var i = 0; i < results.length; i++) {
                var albumData = results[i][0];
                var albumClone = JSON.parse(JSON.stringify(albumData));
                albumClone.tracks = [];
                for (var j = 0; j < albumData.tracks.items.length; j++) {
                    albumData.tracks.items[j]['album'] = albumClone;
                    tracks.push(albumData.tracks.items[j]);
                }
            }
            return tracks;
        });
    });
}
```

### 2C. Update playlist endpoint and field names

**File:** `static/js/app.js:1160-1175`

```javascript
function spotify_playlist_search(playlistId) {
    return $.ajax({
        url: 'https://api.spotify.com/v1/playlists/' + playlistId + '/items',  // /tracks → /items
        dataType: 'json',
        headers: {Authorization: "Bearer " + search_token},
        data: {limit: 10, fields: 'items(item(uri,name,artists,album,duration_ms))'}  // track→item, limit 20→10
    }).then(function(data) {
        var tracks = [];
        if (!data.items) {
            // Non-owned playlist — items not available in dev mode
            console.warn('Playlist items not available (not owner/collaborator)');
            return tracks;
        }
        for (var i = 0; i < data.items.length; i++) {
            if (data.items[i].item) {  // .track → .item
                tracks.push(data.items[i].item);
            }
        }
        return tracks;
    });
}
```

### 2D. Reduce client-side search limits

**File:** `static/js/app.js:1360` — Track search:
```javascript
// Before: limit=50
data:{q:input+"&type=track&limit=50"}
// After: limit=10
data:{q:input+"&type=track&limit=10"}
```

**File:** `static/js/app.js:1386` — Podcast search:
```javascript
// Before: limit=50
data:{q:input+"&type=episode&limit=50&market=US"}
// After: limit=10
data:{q:input+"&type=episode&limit=10&market=US"}
```

Optionally add a "Load More" button that fetches the next page (`offset=10`).

## Phase 3: Cleanup & Documentation

### 3A. Update analytics tracking

- Rename `spotify_api_top_tracks` event to `spotify_api_artist_albums` in analytics docs
- Add new event to `analytics.py` event list and `/stats` dashboard

### 3B. Update CLAUDE.md

- Document the removed endpoints and new constraints
- Update Bender strategy list
- Note search limit of 10

### 3C. Update `docs/spotify-api-constraints.md`

- Add February 2026 changes
- Document 5-user dev mode limit (existing users grandfathered)
- Document Premium requirement for app owner

## Testing Plan

```bash
# Run all existing tests (ensure no regressions)
SKIP_SPOTIFY_PREFETCH=1 python3 -m pytest -v

# Manual testing checklist:
# [ ] Search returns results (capped at 10)
# [ ] Paste spotify:track:... URI → adds song
# [ ] Paste spotify:album:... URI → shows album tracks
# [ ] Paste spotify:artist:... URI → shows artist tracks (via albums)
# [ ] Paste spotify:playlist:... URI → shows playlist tracks (owned playlist)
# [ ] Bender fills queue when idle (all strategies)
# [ ] Podcast search returns results
# [ ] Player controls (play/pause/volume/seek) work
```

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Artist albums returns no useful tracks | Low | Bender quality drop | Weight is only 5/100; genre + artist_search carry the load |
| Search pagination doubles API calls | Medium | Faster rate limiting | Only paginate for Bender, not user search |
| Non-owned playlists return no items | High | Can't add from shared playlists | Show user-facing error message |
| 5-user cap blocks new users | High | Growth blocked | Apply for Extended Quota Mode; evaluate BYOA per-user credentials |
| spotipy library doesn't support new endpoints | Low | Need raw HTTP calls | Verify spotipy version; most changes are removals, not additions |

## Implementation Order

1. **Phase 1B + 1C** (search limits) — smallest change, biggest blast radius if we don't fix
2. **Phase 2D** (client search limits) — same reason
3. **Phase 2C** (playlist endpoint rename) — simple find/replace
4. **Phase 1A** (Bender top_tracks replacement) — most complex but lowest weight strategy
5. **Phase 2A** (batch tracks replacement) — affects search decoration flow
6. **Phase 2B** (artist URI handler) — edge case, artist URI paste
7. **Phase 3** (docs/cleanup) — last

**Estimated effort:** 2-3 hours for all changes + testing.
