# API Usage & Backoff

This document describes how EchoNest uses external APIs, what rate-limit signals it understands, and the exact retry/backoff behavior for queue-filling paths.

## Scope

Primary external APIs:

- Spotify Web API
- SoundCloud OAuth/token endpoint
- YouTube metadata APIs

The most important operational behavior in this area is Bender's empty-queue refill logic, because it can repeatedly hit Spotify-backed recommendation paths when no human songs are queued.

## Spotify API Usage

EchoNest uses Spotify in two broad modes:

### App-Level Usage

Used without per-user playback auth:

- search
- track metadata
- artist metadata
- album track listing
- Bender seed resolution and recommendation fetches

These calls are shared across all users and all nests.

### Per-User Usage

Used for playback/device control:

- device listing
- transfer playback
- playback status

These use cached per-user OAuth tokens and are separate from Bender queue-fill behavior.

## Global Spotify Rate-Limit State

Spotify rate limiting is tracked globally in Redis via `MISC|spotify-rate-limited`.

Behavior:

- when a Spotify API call returns HTTP `429`, `handle_spotify_exception()` stores the limit window in Redis
- the duration comes from Spotify's `Retry-After` header when available
- if the header is missing, EchoNest falls back to `3600` seconds
- `is_spotify_rate_limited()` checks this key before making additional Spotify API calls in guarded paths

Important consequence:

- rate limiting is treated as app-wide, not per-nest
- if one nest pushes the app into a Spotify rate limit, all nests should back off from Spotify-dependent fill work

## Bender Fill Backoff

### Where It Applies

This backoff applies only in the `master_player()` path when:

1. `pop_next()` returns no queued song
2. Bender is enabled
3. EchoNest tries to auto-fill the queue
4. `get_fill_song()` and/or `add_spotify_song()` keeps failing

This is the "empty queue, Bender must recover the session" path.

### Exact Strategy

EchoNest retries indefinitely, but with bounded linear backoff.

Formula:

```python
delay = min(30, max(1, failures * 2))
```

Resulting delays:

- attempt 1 failure: sleep `2s`
- attempt 2 failure: sleep `4s`
- attempt 3 failure: sleep `6s`
- attempt 4 failure: sleep `8s`
- ...
- capped at `30s`

The failure counter resets once a fill succeeds.

### Why This Exists

Before this change, the empty-queue fill path retried immediately with no delay. A persistent Spotify or recommendation failure could cause:

- log spam
- unnecessary CPU churn
- noisy recovery behavior during outages

The current strategy keeps recovery automatic while preventing tight retry loops.

### What It Does Not Do

It does not:

- stop retrying permanently
- back off normal queue playback
- change human-triggered queueing behavior
- override the separate global Spotify `429` tracking mechanism

## Operational Expectations

If Spotify or recommendation generation is unhealthy while the queue is empty:

- the player will keep trying to refill automatically
- retries will slow down to at most one attempt every `30s`
- logs should show the retry attempt count and next delay

If Spotify recovers:

- the next successful fill exits the retry loop
- playback resumes normally

## Related Files

- [`db.py`](/Users/dylanbochman/repos/EchoNest/db.py)
- [`docs/bender-queue-logic.md`](/Users/dylanbochman/repos/EchoNest/docs/bender-queue-logic.md)
- [`docs/spotify-api-constraints.md`](/Users/dylanbochman/repos/EchoNest/docs/spotify-api-constraints.md)
