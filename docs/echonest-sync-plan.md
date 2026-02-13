# echonest-sync: Local Spotify Sync Agent

## Problem

Spotify's dev mode restricts Web API access to 5 allowlisted users. EchoNest needs users to hear audio through their own local Spotify devices, but server-side playback control via the Web API (`PUT /me/player/play`) requires per-user OAuth — limited to 5 users.

## Solution

A lightweight CLI that subscribes to EchoNest's server-sent events and controls the user's **local** Spotify app to play the same track at the same position. No server-side Spotify auth needed — all Spotify control happens locally via OS-level automation (AppleScript on macOS, D-Bus on Linux).

## Architecture

```
EchoNest Server (source of truth)
    | GET /api/events (SSE stream)
    v
echonest-sync CLI (user's machine)
    | AppleScript / D-Bus / Spotify Web API
    v
User's Local Spotify App
```

### EchoNest API Surface (Already Built)

| Endpoint | Description |
|----------|-------------|
| `GET /api/playing` | Current track: `trackid`, `title`, `artist`, `src`, `starttime`, `endtime`, `paused`, `pos`, `now` (server timestamp) |
| `GET /api/events` | SSE stream: `now_playing`, `queue_update`, `player_position`, `volume` events. Keepalive every 15s |
| `GET /api/queue` | Full queue with metadata |

All require `Authorization: Bearer <token>`.

## Local Spotify Control Mechanisms

### macOS: AppleScript (No Spotify Auth Needed)

```applescript
tell application "Spotify"
    play track "spotify:track:4PTG3Z6ehGkBFwjybzWkR8"
    set player position to 42  -- seconds (not ms)
end tell
```

Capabilities: play specific URI, pause, resume, seek, get current track, get player position. Position is in **seconds**.

### Linux: D-Bus / playerctl (No Spotify Auth Needed)

```bash
playerctl --player=spotify open spotify:track:xxx
playerctl --player=spotify position 42  # seconds
```

Uses the MPRIS D-Bus interface (`org.mpris.MediaPlayer2.spotify`). Full play + seek support.

### Windows: No Native Scripting API

- `spotify:track:xxx` URI scheme: Opens the track via `start spotify:track:xxx`, but **no seek capability**
- Spotify Web API: Full control (play + seek) but requires OAuth — back to the auth problem
- Local web server (port 4381): **Dead** — deprecated and non-functional in modern Spotify clients

### Cross-Platform: Spotify Web API (Optional, Requires Auth)

```json
PUT /me/player/play
{
  "uris": ["spotify:track:4PTG3Z6ehGkBFwjybzWkR8"],
  "position_ms": 42000
}
```

Full control on all platforms but requires a Spotify developer app + OAuth. Optional fallback for Windows users or those wanting precise control.

## Implementation Plan

### Phase 1: Core CLI (macOS/Linux, No Spotify Auth)

**Package**: `echonest-sync` via pip

**Usage**:
```bash
pip install echonest-sync
echonest-sync --server https://echone.st --token YOUR_TOKEN
```

**Dependencies**: `requests`, `sseclient-py`

**Core loop**:
```python
import requests, sseclient, subprocess, platform, json, os, time
from datetime import datetime

DRIFT_THRESHOLD = 3  # seconds before correcting position

def sync_loop(server_url, token):
    headers = {'Authorization': f'Bearer {token}'}
    while True:
        try:
            response = requests.get(f'{server_url}/api/events',
                                   headers=headers, stream=True, timeout=30)
            client = sseclient.SSEClient(response)

            current_track = None
            for event in client.events():
                if event.event == 'now_playing':
                    data = json.loads(event.data)
                    track_uri = f"spotify:track:{data['trackid']}"
                    if track_uri != current_track:
                        play_track(track_uri)
                        current_track = track_uri
                        # Calculate elapsed time on server, seek to match
                        elapsed = calculate_elapsed(data)
                        if elapsed > 1:
                            seek_to(elapsed)

                elif event.event == 'player_position':
                    data = json.loads(event.data)
                    correct_drift(data)

        except (requests.ConnectionError, requests.Timeout):
            time.sleep(5)  # backoff and reconnect

def calculate_elapsed(data):
    """Calculate how many seconds into the track the server is."""
    starttime = data.get('starttime', 0)
    server_now = data.get('now', '')
    if server_now and starttime:
        now_ts = datetime.fromisoformat(server_now).timestamp()
        return max(0, now_ts - starttime)
    return 0

def play_track(uri):
    system = platform.system()
    if system == 'Darwin':
        subprocess.run(['osascript', '-e',
            f'tell application "Spotify" to play track "{uri}"'])
    elif system == 'Linux':
        subprocess.run(['playerctl', '--player=spotify', 'open', uri])
    else:  # Windows
        os.startfile(uri)

def seek_to(seconds):
    """Seek to an absolute position in seconds.
    macOS: AppleScript `player position` (seconds).
    Linux: playerctl >= 2.0 `position` (absolute seconds).
    """
    seconds = int(seconds)
    system = platform.system()
    if system == 'Darwin':
        subprocess.run(['osascript', '-e',
            f'tell application "Spotify" to set player position to {seconds}'])
    elif system == 'Linux':
        subprocess.run(['playerctl', '--player=spotify', 'position',
            str(seconds)])

def correct_drift(data):
    """Check local position against server and correct if drift exceeds threshold."""
    server_pos = data.get('pos', 0)
    # Compare with local Spotify position; seek if drift > DRIFT_THRESHOLD
    # (platform-specific position query omitted for brevity)
    pass
```

**SSE reconnection**: The sync loop wraps the SSE subscription in a `while True` with a 5-second backoff on connection errors. This handles transient network blips, server restarts, and deploy-triggered disconnects without the agent silently dying.

**playerctl version note**: Absolute position seeking (`playerctl position N`) requires playerctl >= 2.0. Older versions only support relative seeks. Recommend `playerctl --version` check on startup.

**Position sync strategy**:
- `now_playing` event includes `starttime` (when track started on server) and `now` (server ISO timestamp)
- Calculate: `elapsed = now_timestamp - starttime`
- Seek to `elapsed` seconds after starting the track
- `player_position` events provide periodic position updates for drift correction (correct if > 3 seconds off)

**Pause/unpause handling**:
- `now_playing` event includes `paused` field
- When `paused: true`, pause local Spotify
- When `paused: false`, resume and seek to correct position

**Configuration**: `~/.echonest-sync.yaml` or env vars
```yaml
server: https://echone.st
token: YOUR_API_TOKEN
drift_threshold: 3  # seconds before correcting position
```

### Phase 2: Windows Support + Web API Fallback

Add optional Spotify Web API integration for Windows users or anyone wanting precise seek:

```bash
echonest-sync --server https://echone.st --token YOUR_TOKEN \
  --spotify-client-id xxx --spotify-client-secret yyy
```

- On first run, open browser for Spotify OAuth (`user-modify-playback-state` scope)
- Cache refresh token in `~/.echonest-sync/spotify_token`
- Use `PUT /me/player/play` with `position_ms` for playback control
- Use `PUT /me/player/seek` for drift correction

**Note**: Each Windows user would need their own Spotify dev app (BYOA) with themselves on the allowlist. This is a per-user setup cost, but only affects Windows users.

### Phase 3: MCP Server Wrapper (Optional)

Thin MCP wrapper for Claude Desktop/Claude Code integration:

**Resources**:
- `echonest://now-playing` — current track info
- `echonest://queue` — current queue

**Tools**:
- `start_sync` / `stop_sync` — toggle background sync
- `sync_status` — check sync state and drift
- `play_track` — play a specific track
- `what_is_playing` — describe current track

Use case: "Hey Claude, what's playing on EchoNest?" or "Claude, start syncing my Spotify to the office queue."

Not needed for headless auto-sync — the CLI handles that. The MCP wrapper adds conversational interaction.

### Phase 4: Browser Extension (Optional)

Only if demand exists for zero-install experience:

- Chrome Manifest V3 extension
- Offscreen document for SSE subscription + Web Playback SDK
- Dual auth: EchoNest token + Spotify OAuth
- Audio plays through browser, not Spotify desktop app

**Challenges**: MV3 service worker lifecycle kills SSE connections. Offscreen documents help but add complexity. Chrome Web Store review process.

## Evaluation

| Criterion | Phase 1 (CLI) | Phase 2 (+ Web API) | Phase 3 (MCP) | Phase 4 (Extension) |
|-----------|---------------|---------------------|---------------|---------------------|
| Sync precision | 1-2 sec | Sub-second | Same as CLI | 1-3 sec |
| Setup friction | Low (`pip install`) | Medium (+ Spotify OAuth) | Medium (MCP config) | Medium (extension install) |
| macOS | Full (AppleScript) | Full | Full | Full |
| Linux | Full (D-Bus) | Full | Full | Full |
| Windows | Play only (no seek) | Full (Web API) | Full | Full |
| Spotify auth needed | No (macOS/Linux) | Yes (Windows) | Same as CLI | Yes |
| Maintenance | Low | Medium | Medium | High |

## Alternatives Considered

### librespot / go-librespot
Run an open-source Spotify Connect receiver on the server. One Premium account authenticates it; audio plays through a shared speaker. **Perfect for co-located office use**, but EchoNest users are now remote — each user needs audio on their own device. Not viable for distributed use.

### BYOA (Bring Your Own App)
Each nest creator registers their own Spotify developer app, gets 5 users per app. Technically works but high friction: requires Spotify Premium, burns their one allowed Client ID, manual 5-step setup, allowlist management.

### YouTube Fallback
Use Spotify for search/metadata (app-level creds, unlimited), play audio via YouTube embeds in the browser. No per-user auth needed. Trade-off: audio quality, track matching accuracy.

### Spotify Web Playback SDK (Single Account)
One authenticated account streams through a browser tab via the SDK. Everyone hears the same stream. Works as a "virtual shared speaker" but users must keep a browser tab open. One active stream per account.

### Spotify Jam / Group Session
Spotify's built-in sync feature. **No public API** — cannot be used programmatically.

### Spotify Local Web Server (Port 4381)
**Dead.** Deprecated and non-functional in modern Spotify clients.

## Key References

- [librespot](https://github.com/librespot-org/librespot) — Open-source Spotify Connect implementation
- [go-librespot](https://github.com/devgianlu/go-librespot) — Go implementation with HTTP API
- [varunneal/spotify-mcp](https://github.com/varunneal/spotify-mcp) — Python Spotify MCP server
- [marcelmarais/spotify-mcp-server](https://github.com/marcelmarais/spotify-mcp-server) — TypeScript Spotify MCP server
- [Spotify Web API: Start/Resume Playback](https://developer.spotify.com/documentation/web-api/reference/start-a-users-playback)
- [Spotify Web Playback SDK](https://developer.spotify.com/documentation/web-playback-sdk)
- [Spotify Developer Blog: Feb 2026 Update](https://developer.spotify.com/blog/2026-02-06-update-on-developer-access-and-platform-security)
- [playerctl](https://github.com/altdesktop/playerctl) — MPRIS D-Bus controller
- [MPRIS D-Bus Specification](https://specifications.freedesktop.org/mpris/latest/Player_Interface.html)
