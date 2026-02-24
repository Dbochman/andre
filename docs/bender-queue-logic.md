# Bender Queue & Preview Logic

## Overview

Bender is EchoNest's auto-fill engine. When the queue runs low, Bender picks songs using a weighted strategy rotation and adds them to the queue. The UI shows a "preview" of the next Bender pick at the bottom of the queue, with controls to approve (Queue), reject (Filter), or open in Spotify.

## Strategy Rotation

Each fill request rolls weighted dice to pick ONE strategy:

| Strategy | Default Weight | Source |
|----------|---------------|--------|
| Genre Search | 35% | `search(q='genre:"X"', type='track')` using seed artist's genres |
| Throwback | 30% | Historical plays from same day-of-week, attributed to original user |
| Artist Search | 25% | `search(artist_name, type='track')` — collabs/features |
| Top Tracks | 5% | `artist_top_tracks()` |
| Album | 5% | `album_tracks()` from seed album |

Weights are configurable via `BENDER_STRATEGY_WEIGHTS` in config. Each strategy maintains its own Redis cache (~20 tracks). When a cache is empty, a batch is fetched from Spotify. If a strategy fails, it falls through to another.

### Seed Resolution

The seed artist is resolved from (in priority order):
1. Last human-queued track (`MISC|last-queued`)
2. Last bender track (`MISC|last-bender-track`)
3. Now-playing track
4. Fallback: Billy Joel

Seed info (artist ID, name, album ID, genres) is cached in `BENDER|seed-info` with a 20-minute TTL. If the seed track changes, the cache is invalidated and re-fetched.

## Key Components

### `get_fill_song()` — Consuming Tracks

This is the core method that returns the next track to add to the queue.

**Flow:**
1. Check backup queue (manual override) — return if present
2. **Consume the preview** (`BENDER|next-preview`) if one exists — this ensures the UI preview matches what actually enters the queue
3. If preview was filtered since creation, fall through
4. If Spotify rate-limited, try throwback only
5. Otherwise: weighted random strategy selection → pop from cache → fill cache if empty → filter check → return

**Key behavior:** The preview is consumed first so the track the user sees in the UI is the track that actually gets queued.

### `_peek_next_fill_song()` — Generating Previews

Non-consuming peek that finds the next track Bender would play.

**Flow:**
1. If `BENDER|next-preview` already exists and isn't filtered, return it
2. Weighted random strategy selection (same `_select_strategy_excluding` as `get_fill_song`)
3. Peek at cache front (`lindex 0`), fill cache lazily if empty
4. Drain filtered tracks from cache front
5. Store result in `BENDER|next-preview` hash
6. Return `(track_uri, user, strategy)`

### `get_additional_src()` — UI Preview Data

Called by `get_queued()` to append the preview row to the queue data sent to the UI.

**Flow:**
1. Call `ensure_fill_songs()` to pre-warm caches
2. Call `_peek_next_fill_song()` to get/create the preview
3. Fetch track metadata via `get_fill_info()`
4. Return dict with `playlist_src: True`, title, image, user, etc.
5. Throwback previews show `"username (throwback)"`, others show `"Benderbot"`

### `ensure_queue_depth()` — Maintaining Queue Size

Called by the player after each song transition.

**Flow:**
1. Purge stale entries via `_purge_stale_queue_entries()` (see below)
2. Check `MISC|priority-queue` size vs `MIN_QUEUE_DEPTH` (default 3)
3. If queue is short, call `get_fill_song()` for each needed track
4. `get_fill_song()` consumes the preview first, so the previewed track flows into the queue
5. Respects `MAX_BENDER_MINUTES` streak limit

### `_purge_stale_queue_entries()` — Self-Healing

`QUEUE|{id}` hashes have a 24-hour TTL but the priority queue sorted set does not. If the system is paused >24h, the metadata expires while the IDs remain — creating ghost entries that `zcard` counts as real songs.

This helper scans the sorted set, checks which IDs have lost their hash, and removes them via `ZREM`. Called by `get_queued()` and `backfill_queue()` so depth checks always reflect real songs. `pop_next()` also independently skips entries with missing `src` field.

## Player Interactions

### Song Transition (natural end or skip)

```
master_player loop
  → song finishes or force-jump detected
  → pop_next()
      → pops first item from priority queue
      → makes it now-playing
      → if human song: clears all bender caches + preview (seed changed)
  → ensure_queue_depth()
      → queue has < MIN_QUEUE_DEPTH items
      → get_fill_song()
          → consumes BENDER|next-preview (the track UI was showing)
          → adds it to the queue
      → get_fill_song() again if still short
          → no preview exists, uses weighted random rotation
  → playlist_update sent to all clients
  → clients call get_queued() → get_additional_src() → _peek_next_fill_song()
  → new preview is generated and shown in UI
```

### Skip (kill_playing)

1. UI sends `kill_playing` → sets `MISC|force-jump`
2. Player loop detects flag, breaks out of timing loop
3. Cleans up `MISC|current-done`, queue keys
4. Loops back to top → calls `pop_next()` + `ensure_queue_depth()`
5. Same flow as natural song transition

### Human Queues a Song

When a human adds a song via search:
1. Song is added to `MISC|priority-queue` with a fair-scheduling score
2. `pop_next()` eventually pops it — detects `user != 'the@echonest.com'`
3. Sets `MISC|last-queued` (new seed for bender)
4. Calls `_clear_all_bender_caches()` — clears ALL `BENDER|cache:*`, `BENDER|seed-info`, `BENDER|throwback-users`, `BENDER|next-preview`
5. Calls `ensure_fill_songs()` to pre-warm with new seed
6. Bender streak timer resets

## UI Controls (Preview Row)

The preview row appears at the bottom of the queue with three controls:

### Spotify
Opens the track's Spotify URI in a new window.

### Queue (`benderQueue`)
Adds the preview track to the queue as a human-endorsed song:
1. Validates trackid matches `BENDER|next-preview`
2. Pops from strategy cache, clears preview
3. Calls `add_spotify_song()` with the clicking user's ID
4. Jams the original user (for throwback attribution)

### Filter (`benderFilter`)
Filters the preview track so Bender never picks it again, then rotates to a new preview:
1. Pops from strategy cache if preview matches
2. Clears `BENDER|next-preview`
3. Sets `FILTER|{trackid}` with 1-week TTL
4. Sends `playlist_update` → triggers new preview generation via `get_additional_src()`

**Note:** Filter is resilient to preview/trackid mismatches (e.g. if the player consumed the preview between renders). It always applies the filter and clears the preview regardless.

## Redis Keys

| Key | Type | TTL | Purpose |
|-----|------|-----|---------|
| `BENDER|cache:genre` | list | 20 min | Genre search track cache |
| `BENDER|cache:throwback` | list | 20 min | Throwback track cache |
| `BENDER|cache:artist-search` | list | 20 min | Artist search track cache |
| `BENDER|cache:top-tracks` | list | 20 min | Top tracks cache |
| `BENDER|cache:album` | list | 20 min | Album tracks cache |
| `BENDER|throwback-users` | hash | 20 min | Maps throwback track URI → original user email |
| `BENDER|seed-info` | hash | 20 min | Cached seed artist metadata (id, name, album, genres) |
| `BENDER|next-preview` | hash | none | Current preview: trackid, user, strategy. Cleared on consume/filter. |
| `FILTER\|{trackid}` | string | 1 week | Tracks bender should skip |
| `MISC\|last-queued` | string | none | Last human-queued trackid (primary seed) |
| `MISC\|last-bender-track` | string | none | Last bender-added trackid (fallback seed) |
| `MISC\|bender_streak_start` | string | none | Pickled datetime of streak start |
| `MISC\|priority-queue` | sorted set | none | The actual queue (score = display order). No TTL — stale entries purged by `_purge_stale_queue_entries()` |
| `QUEUE\|{id}` | hash | 24 hours | Song metadata (title, artist, trackid, etc.). TTL mismatch with sorted set is handled by stale-entry purging |

## Config

```yaml
USE_BENDER: true
MAX_BENDER_MINUTES: 120        # Stop auto-fill after this many minutes of no human songs
MIN_QUEUE_DEPTH: 3             # Maintain at least this many tracks in queue
BENDER_FILTER_TIME: 604800     # 1 week in seconds
BENDER_STRATEGY_WEIGHTS:
  genre: 35
  throwback: 30
  artist_search: 25
  top_tracks: 5
  album: 5
BENDER_REGIONS:
  - US
```

## UI Details

### Bender Avatar
Bender's user identity is `the@echonest.com`. The avatar image is `/static/theechonestcom.png` (180x269 portrait). In queue items, a `.bender-img` CSS class is conditionally applied to use `background-size: contain` with `background-position: left center` so the full image displays without cropping. Other user avatars use `background-size: cover` (standard for square Google profile photos).

Hover text shows "Bender" instead of "the@echonest.com" for all Bender elements (person-image, jammers, now-playing jammers).

### Hide Shame Mode
The "hide shame" toggle (`FEEL_SHAME`) replaces all user avatars with Gravatar monsterid monsters. Each user gets a consistent, unique monster based on a hash of their email. The `shame_image(email, size)` function generates Gravatar URLs with `?d=monsterid&f=y` (force default, never show real gravatar). This applies to person images, jammer icons, now-playing jammers, and airhorn user images.

## Fair Scheduling

Auto-fill songs (where `song['auto'] == True`) always score at the **end** of the queue. The `_score_track()` method has an early return for auto songs that places them after the last queued item, preventing bender tracks from being interleaved with human-queued songs.
