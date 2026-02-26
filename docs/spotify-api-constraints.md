# Spotify API Constraints & Strategy

## Current Status (Feb 2026)

EchoNest uses a Spotify app in **Development Mode** with Client ID created before Feb 11, 2026.

- **Allowlist**: 5 users (Ben Cooper, Eric Swenson, Dave Rodger, Ajay Kalia + 1 slot)
- **Authenticated users with cached tokens**: ~13
- **Enforcement reality**: The 5-user allowlist doesn't appear to gate playback endpoints (`/v1/me/player/play`). Non-allowlisted users are successfully syncing audio. The `/v1/me` endpoint does return 403 for non-allowlisted users, but playback works regardless.

## Upcoming Changes

### Feb 11, 2026 (new Client IDs)
- Premium required for app owner
- 1 Client ID per developer
- 5 authorized users max
- Reduced endpoint access

### March 9, 2026 (existing Client IDs)
- **Same restrictions apply retroactively** to all existing Development Mode apps
- No grandfathering for apps exceeding 5 users
- Source: [Spotify Developer Blog](https://developer.spotify.com/blog/2026-02-06-update-on-developer-access-and-platform-security)

### Extended Quota Mode (unreachable)
- Requires: legally registered business, 250K MAU, key Spotify markets presence
- 6-week review process
- Source: [Quota Modes Docs](https://developer.spotify.com/documentation/web-api/concepts/quota-modes)

## How EchoNest Uses Spotify

### App-Level (no per-user auth needed)
- **Search**: Uses app-level SpotifyOAuth token — not subject to per-user limits
- **Metadata**: Track info, album art, artist data
- **Bender recommendations**: `artist_album_tracks()` + `album_tracks()`, `search()` (paginated, max 10/page)

### Per-User Auth (subject to 5-user limit)
- **Sync Audio / Playback Control**: `PUT /v1/me/player/play` — requires per-user OAuth token with `streaming user-read-currently-playing user-read-playback-state user-modify-playback-state` scopes
- **Token storage**: Cached at `/opt/echonest/oauth_creds/{email}` via spotipy
- **Premium required**: Spotify's `streaming` scope requires the user to have Premium

## Known Issues

### Stale Tokens
If a user's initial OAuth flow fails silently (popup blocked, closed early, transient error), a bad token gets cached and auto-refreshed indefinitely. Symptoms: 403 on playback endpoints even though the user has Premium.

**Fix**: Delete the cached token and have the user click "reconnect spotify":
```bash
ssh deploy@echone.st 'rm /opt/echonest/oauth_creds/{email}'
```

The "reconnect spotify" button in the Other tab now does this automatically (deletes cached token server-side, redirects to fresh OAuth).

### Rate Limits
- Rolling 30-second window, exact numbers undisclosed
- Dev mode has lower limits than extended quota
- `Retry-After` header on 429 responses
- EchoNest already handles this via `is_spotify_rate_limited()` in `db.py`

## Web Playback SDK — Investigated, Not a Workaround

The [Web Playback SDK](https://developer.spotify.com/documentation/web-playback-sdk) turns the browser into a Spotify Connect device that streams audio directly. It does NOT bypass the 5-user limit:

- Uses the same OAuth tokens and Client ID
- Same development mode restrictions apply
- Requires Spotify Premium for each user

A **single-account architecture** (one Spotify account powering all playback) would dodge the per-user limit, but Spotify only allows one active stream per account — so it only works for a single shared speaker (co-located office), not multi-location sync.

## Options After March 9

### Option 1: Accept 5-User Cap
- Keep current per-user Spotify sync
- Pick 5 most active users for the allowlist
- Everyone else can still search/queue/vote (app-level auth), just can't sync audio via Spotify
- **Effort**: None
- **Tradeoff**: Most users lose sync audio

### Option 2: YouTube as Default Playback Source
- YouTube has no per-user auth limits
- Already supported in EchoNest for playback
- When a Spotify track is queued, auto-match to YouTube for playback
- Spotify remains the search/metadata source (app-level creds, no limit)
- **Effort**: Medium — need Spotify-to-YouTube track matching
- **Tradeoff**: Audio quality differences, occasional mismatches

### Option 3: Hybrid
- Spotify sync for 5 allowlisted power users
- YouTube fallback for everyone else
- **Effort**: Medium — conditional playback routing
- **Tradeoff**: Two-tier experience

### Option 4: Shared Speaker (Web Playback SDK)
- One Spotify Premium account streams via SDK in a designated browser
- Everyone else queues/votes, audio plays from one location
- Best for co-located office use (original Prosecco model)
- **Effort**: Medium — integrate Web Playback SDK, single-token architecture
- **Tradeoff**: Only works for co-located scenarios

### Option 5: BYOA — Bring Your Own App (per-Nest Spotify credentials) **(Recommended)**
Each nest creator registers their own Spotify Developer app and provides their Client ID/Secret when creating a nest. This multiplies the 5-user cap by the number of nests.

**How it works:**
- Nest creation form adds optional fields: Spotify Client ID, Client Secret
- Per-nest credentials stored in Redis (alongside other nest config)
- SpotifyOAuth uses the nest's credentials for per-user auth (sync audio)
- Global app credentials remain the fallback for search/metadata (no per-user auth needed)
- Redirect URI stays `https://echone.st/authentication/spotify_callback/` — nest creators just add this to their Spotify app settings
- Each nest gets its own 5-user allowlist on its own Spotify app

**User flow for nest creator:**
1. Go to [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard)
2. Create app, add `https://echone.st/authentication/spotify_callback/` as redirect URI
3. Copy Client ID + Secret
4. Paste into EchoNest nest creation/settings
5. Add up to 5 Spotify emails to their app's allowlist

**Implementation changes:**
- `nests.py` / nest config: add `spotify_client_id`, `spotify_client_secret` fields
- `app.py`: when building SpotifyOAuth for per-user auth, check if the user's current nest has custom credentials; use those instead of global `CONF.SPOTIFY_CLIENT_ID`
- `app.py:spotify_callback()`: need to resolve which nest's credentials to use (store nest_id in session or OAuth state param)
- `templates/main.html`: nest settings UI for entering credentials
- Token cache: namespace by nest to avoid cross-nest token confusion (e.g., `oauth_creds/{nest_id}/{email}`)

**Pros:**
- Scales linearly: N nests = N * 5 Spotify sync users
- Decentralized — nest creators manage their own allowlist
- No changes to core playback flow
- Main Nest keeps using the global app credentials (backwards compatible)

**Cons:**
- Friction for nest creators (need Spotify Developer account + Premium)
- Users moving between nests may need to re-auth
- More OAuth state to manage (which nest's credentials to use)
- Spotify requires each app owner to have Premium

**Effort**: Medium-Large — per-nest credential storage, OAuth routing, nest settings UI
**Tradeoff**: Best scaling option, but requires technical nest creators

## February 2026 API Endpoint Removals

Spotify removed several endpoints in Feb 2026 (enforced March 9 for existing apps). See `docs/spotify-feb2026-migration.md` for the full migration plan.

**Removed endpoints we used (all migrated):**
- `GET /artists/{id}/top-tracks` — replaced with `artist_album_tracks()` + `album_tracks()`
- `GET /tracks` (batch) — replaced with individual `GET /tracks/{id}` calls
- `GET /playlists/{id}/tracks` — renamed to `/playlists/{id}/items`, field `track` → `item`

**Search limit reduced:** max 50 → 10, default 20 → 5. Bender uses offset pagination (2 pages of 10) to compensate.

**Removed response fields (none affected us):** `popularity`, `available_markets`, `external_ids`, `show.publisher`, `user.email`, `user.product`

**Playlist restriction:** Items only returned for playlists the user owns or collaborates on. Non-owned playlists show a message guiding users to copy-paste track URLs instead.

## Additional Constraints Discovered

### Allowlist Rate Limit
Spotify limits adding users to the allowlist: **max 5 users per app per 24-hour period**. Even removing and re-adding counts. This means you can't rapidly iterate on who's on the list.

### Enforcement Timeline
The 5-user cap is enforced NOW for apps that added allowlist users after Feb 11, 2026 — not just after March 9. Existing cached tokens from before enforcement may continue working until they expire and can't refresh.

## References

- [Spotify Developer Blog — Feb 2026 Update](https://developer.spotify.com/blog/2026-02-06-update-on-developer-access-and-platform-security)
- [Quota Modes](https://developer.spotify.com/documentation/web-api/concepts/quota-modes)
- [Rate Limits](https://developer.spotify.com/documentation/web-api/concepts/rate-limits)
- [Scopes](https://developer.spotify.com/documentation/web-api/concepts/scopes)
- [Web Playback SDK](https://developer.spotify.com/documentation/web-playback-sdk)
- [TechCrunch — Spotify API Changes](https://techcrunch.com/2026/02/06/spotify-changes-developer-mode-api-to-require-premium-accounts-limits-test-users/)
