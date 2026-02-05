# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Andre is a collaborative music queue system for offices and parties. Users share a queue where they can search for songs (Spotify), add them, vote to reorder, and trigger airhorns. The app uses WebSockets for real-time updates. "Bender mode" auto-fills the queue with recommendations when it runs low.

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

### Configuration

Copy `config.example.yaml` to `local_config.yaml` and fill in OAuth credentials. Environment variables override YAML config (e.g., `REDIS_HOST`, `DEBUG`, `DEV_AUTH_EMAIL`).

## Architecture

### Core Components

- **app.py** - Flask application with all routes, WebSocket handling, OAuth flows. Key classes: `WebSocketManager`, `MusicNamespace`, `VolumeNamespace`.
- **db.py** - Redis interface (`DB` class) and Bender recommendation engine. All queue operations, voting, and song filtering logic lives here.
- **history.py** - `PlayHistory` class for tracking played songs (powers Throwback feature).
- **run.py** - Entry point; starts gevent WSGI server on port 5000.
- **master_player.py** - Background worker that tracks playback timing and broadcasts queue updates.
- **config.py** - Loads YAML config with environment variable overrides.

### Services (Docker Compose)

```
andre (Flask app) → Redis ← player (master_player.py)
                      ↓
                  PostgreSQL (optional, user data)
```

- `andre` - Web server on port 5001 (maps to 5000 internally)
- `player` - Runs `master_player.py` for playback timing
- `redis` - Primary data store for queue, votes, sessions
- `db` - PostgreSQL (optional)

### Real-time Communication

WebSocket via gevent-websocket. The `before_request` hook intercepts WebSocket upgrades before Flask routing. Redis pub/sub coordinates between containers.

### Bender (Auto-fill) Engine

Spotify deprecated `/recommendations` and `/artists/{id}/related-artists` APIs (Nov 2024). The current approach uses:
1. `artist_top_tracks()` - Get top tracks from seed artist
2. `album_tracks()` - Get other tracks from same album
3. `search()` - Find artist collaborations

Seeds from: last-queued track → last-bender-track → now-playing → fallback.

### Frontend

Backbone.js + jQuery served as static files. Main logic in `static/js/app.js`. Nine color themes rotate.

## Key Patterns

### Authentication
- Google OAuth for login, Spotify OAuth per-user for playback
- `DEV_AUTH_EMAIL` bypasses OAuth when `DEBUG=true` on localhost
- Public endpoints defined in `SAFE_PATHS` and `SAFE_PARAM_PATHS` lists in `app.py`

### Redis Data
- Strings decoded automatically (`decode_responses=True`)
- Binary objects (datetimes) stored via base64-wrapped pickle (`pickle_dump_b64`/`pickle_load_b64` in `db.py`)

### Spotify Token Handling
Newer spotipy versions return dict from `get_access_token()`. Code handles both string and dict formats.

## Known Limitations

1. Spotify recommendations API deprecated - workaround uses top tracks + album tracks
2. HOSTNAME in config must exactly match Google OAuth redirect URI registration
