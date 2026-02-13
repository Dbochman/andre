# EchoNest

A collaborative music queue system for offices and parties. Users can search for songs, add them to a shared queue, vote on songs, and enjoy features like airhorns and "bender mode" (auto-fill).

**Live at: https://echone.st**

## Features

- Spotify integration for music search and playback
- Real-time WebSocket updates for queue changes
- Voting system to promote/demote songs in queue
- "Jam" button for showing appreciation
- Airhorn sound effects
- Bender mode: auto-fills queue with recommendations when empty
- Throwback mode: pulls songs from the same day of week in history
- Guest login system
- Comments on songs

## How It Works

EchoNest is a **shared queue, individual playback** system:

1. Everyone sees the same queue and can add songs, vote, and jam
2. Each user connects their own Spotify Premium account
3. Users play along on their own devices - EchoNest is the DJ, not the speaker

## Getting Started (Users)

1. Open [echone.st](https://echone.st) and click **Sign in with Google**.
2. After signing in, you'll be prompted to **Connect Spotify** -- click the green button to link your account.
   - Spotify Premium is required for playback.
   - Make sure the Spotify app is open on your device before connecting.
3. That's it -- you're in the queue. Add songs, vote, and listen together.

For the full walkthrough (Bender auto-fill, preview tracks, Nests, airhorns, and more), see the **[Getting Started guide](docs/GETTING_STARTED.md)**.

## Quick Start (Docker)

```bash
# Clone the repo
git clone https://github.com/Dbochman/EchoNest.git
cd EchoNest

# Copy and configure
cp config.example.yaml local_config.yaml
# Edit local_config.yaml with your Spotify and Google OAuth credentials

# Start all services
docker compose up --build

# Visit http://localhost:5001
```

## Configuration

### Prerequisites

- Docker and Docker Compose
- Spotify Developer Account
- Google Cloud Console project (for OAuth)

### Setup

1. Copy the example config:
   ```bash
   cp config.example.yaml local_config.yaml
   ```

2. Edit `local_config.yaml` with your credentials:

   **Spotify** (https://developer.spotify.com/dashboard):
   ```yaml
   SPOTIFY_CLIENT_ID: "your-client-id"
   SPOTIFY_CLIENT_SECRET: "your-client-secret"
   SPOTIFY_USERNAME: your-username
   ```
   Add redirect URI: `http://localhost:5001/authentication/spotify_callback`

   **Google OAuth** (https://console.cloud.google.com/apis/credentials):
   ```yaml
   GOOGLE_CLIENT_ID: "your-client-id.apps.googleusercontent.com"
   GOOGLE_CLIENT_SECRET: "your-client-secret"
   ```
   Add redirect URI: `http://localhost:5001/authentication/callback`

   **Access Control:**
   ```yaml
   ALLOWED_EMAIL_DOMAINS:
     - gmail.com
     - yourdomain.com
   ```

## Running Locally (Without Docker)

```bash
# Install dependencies
pip install -r requirements.txt

# Start Redis
redis-server

# Run the app
python run.py
```

## Testing

```bash
# Quick (nest contract tests only)
make test-quick

# Nests + regression suite
make test-nests

# Full suite
make test-all
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/playing/` | GET | Current playing song |
| `/queue/` | GET | Current queue |
| `/add_song` | POST | Add a song |
| `/jam` | POST | Jam a song |
| `/blast_airhorn` | POST | Trigger airhorn |
| `/search/v2?q=` | GET | Search Spotify |

## Deployment

See [docs/cloud-hosting-plan.md](docs/cloud-hosting-plan.md) for production deployment instructions.

The live instance runs on a $6/month DigitalOcean droplet with:
- Caddy reverse proxy (auto HTTPS)
- Docker Compose (Flask app, Redis, background worker)
- Let's Encrypt SSL certificate

## Architecture

```
┌─────────────────────────────────┐
│           Web Browser               │
│  (Backbone.js + WebSocket client)   │
└───────────────┬─────────────────────┘
                │
┌───────────────▼─────────────────────┐
│         Flask App (app.py)          │
│  - OAuth (Google + Spotify)         │
│  - REST API                         │
│  - WebSocket (gevent)               │
└───────────────┬─────────────────────┘
                │
┌───────────────▼─────────────────────┐
│         Redis                       │
│  - Queue data                       │
│  - Votes & jams                     │
│  - Session state                    │
└───────────────┬─────────────────────┘
                │
┌───────────────▼─────────────────────┐
│    Background Worker (master_player)│
│  - Tracks playback timing           │
│  - Bender recommendations           │
│  - Broadcasts queue updates         │
└─────────────────────────────────────┘
```

## History

EchoNest has its roots in **Prosecco**, an internal tool originally developed at [The Echo Nest](https://en.wikipedia.org/wiki/The_Echo_Nest) in Somerville, MA. The name "Prosecco" was chosen as a more appealing alternative to "dogfooding" - the practice of using your own product internally. In this case, it was used to test and refine The Echo Nest's music recommendation algorithms in a real-world office environment.

After Spotify acquired The Echo Nest in 2014, Prosecco was forked and rebranded as **Andre** for use in Spotify's offices. The system continued to evolve, and was later forked again and rebranded as **Highlife** for other internal deployments.

This repository represents the EchoNest branch, which was resurrected from a 2018 snapshot and modernized to Python 3 in 2026. The historical play logs from 2017-2018 power the "Throwback" feature, which suggests songs that were played on the same day of the week years ago.

## Changelog
See `docs/changelog.md` for the resurrection change summary and testing notes.

## License

MIT
