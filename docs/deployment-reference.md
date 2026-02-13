# EchoNest Deployment Reference

This document captures the successful deployment of EchoNest to DigitalOcean on February 4, 2026.

## Live Instance

| Property | Value |
|----------|-------|
| **URL** | https://echone.st |
| **Server** | DigitalOcean Droplet (NYC1) |
| **IP Address** | 192.81.213.152 |
| **OS** | Ubuntu 22.04 LTS |
| **Size** | 1GB RAM / 1 CPU / 25GB SSD |
| **Cost** | $6/month |
| **SSL** | Let's Encrypt (auto-renewing via Caddy) |

---

## Architecture

```
Internet
    │
    ▼
┌─────────────────────────────────┐
│  echone.st (DNS)                │
│  Cloudflare DNS (proxied)       │
└───────────────┬─────────────────┘
                │
                ▼
┌─────────────────────────────────┐
│  DigitalOcean Droplet           │
│  192.81.213.152 (Tailscale:    │
│  100.92.192.62)                 │
│                                 │
│  ┌───────────────────────────┐  │
│  │  Caddy (systemd)          │  │
│  │  - Auto HTTPS             │  │
│  │  - Reverse proxy :443→5001│  │
│  │  - WebSocket support      │  │
│  └─────────────┬─────────────┘  │
│                │                │
│  ┌─────────────▼─────────────┐  │
│  │  Docker Compose           │  │
│  │  ├─ echonest_app (:5001)   │  │
│  │  ├─ echonest_player        │  │
│  │  └─ echonest_redis (:6379) │  │
│  └───────────────────────────┘  │
│                                 │
│  Data: /opt/echonest/              │
│  ├─ play_logs/                  │
│  ├─ oauth_creds/                │
│  └─ .env                        │
└─────────────────────────────────┘
```

---

## SSH Access

```bash
# As deploy user via public IP
ssh deploy@192.81.213.152

# As deploy user via Tailscale (bypasses fail2ban/UFW)
ssh deploy@100.92.192.62
```

**Note**: Root login is disabled. Tailscale provides backup SSH access if the public IP is blocked by fail2ban.

---

## Common Operations

### Check Service Status

```bash
cd /opt/echonest
docker compose ps
```

### View Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f echonest
docker compose logs -f player
docker compose logs -f redis
```

### Restart Services

```bash
cd /opt/echonest

# Restart all
docker compose restart

# Restart specific service
docker compose restart echonest

# Full rebuild (after code changes)
docker compose up -d --build
```

### Deploy Code Updates

From your local machine:
```bash
# Sync code to server (excludes local config to preserve server settings)
rsync -avz --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='.env' --exclude='local_config.yaml' --exclude='.cache' \
  /Users/dylanbochman/repos/EchoNest/ deploy@192.81.213.152:/opt/echonest/

# SSH in and rebuild
ssh deploy@192.81.213.152 "cd /opt/echonest && docker compose up -d --build"
```

**One-liner** (sync + rebuild):
```bash
rsync -avz --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' --exclude='.env' --exclude='local_config.yaml' --exclude='.cache' /Users/dylanbochman/repos/EchoNest/ deploy@192.81.213.152:/opt/echonest/ && ssh deploy@192.81.213.152 "cd /opt/echonest && docker compose up -d --build"
```

**Important**: `local_config.yaml` is excluded to prevent overwriting the server's production config (which has `HOSTNAME: echone.st`).

### Verify Deployment

```bash
# Check containers are healthy
ssh deploy@192.81.213.152 "cd /opt/echonest && docker compose ps"

# Check recent logs for errors
ssh deploy@192.81.213.152 "cd /opt/echonest && docker compose logs --tail=20 echonest"

# Test the site
curl -s -o /dev/null -w "%{http_code}" https://echone.st/health
```

### Check Caddy Status

```bash
systemctl status caddy
journalctl -u caddy -f
```

### View Caddy Config

```bash
cat /etc/caddy/Caddyfile
```

---

## Configuration Files

### Server Locations

| File | Purpose |
|------|---------|
| `/opt/echonest/.env` | Environment variables (secrets) |
| `/opt/echonest/local_config.yaml` | Application config |
| `/opt/echonest/docker-compose.yaml` | Container orchestration |
| `/etc/caddy/Caddyfile` | Reverse proxy config |

### Caddy Configuration

```
echone.st {
    reverse_proxy localhost:5001 {
        flush_interval -1
    }
}

andre.dylanbochman.com {
    redir https://echone.st{uri} permanent
}
```

Note: `flush_interval -1` is required for WebSocket support. `andre.dylanbochman.com` redirects to `echone.st`.

### Environment Variables

Key variables in `/opt/echonest/.env`:
- `HOSTNAME=echone.st`
- `DEBUG=false`
- `SECRET_KEY=<random-string>`
- `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
- `ALLOWED_EMAIL_DOMAINS=gmail.com,dylanbochman.com`
- `ECHONEST_API_TOKEN=<token>` (for REST API auth; stored in 1Password)
- `ECHONEST_SPOTIFY_EMAIL=dylanbochman@gmail.com` (Spotify account for device control API)
- `REDIS_PASSWORD=<password>`

Generate a new API token: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`

---

## REST API Endpoints

Token-authenticated endpoints for programmatic queue management. All require `Authorization: Bearer <token>` header.

| Endpoint | Method | Body | Description |
|----------|--------|------|-------------|
| `/api/queue/skip` | POST | — | Skip current song |
| `/api/queue/remove` | POST | `{"id": "<track_id>"}` | Remove song from queue |
| `/api/queue/vote` | POST | `{"id": "<track_id>", "up": true}` | Upvote/downvote a song |
| `/api/queue/pause` | POST | — | Pause playback |
| `/api/queue/resume` | POST | — | Resume playback |
| `/api/queue/clear` | POST | — | Clear entire queue |
| `/api/queue` | GET | — | Full queue with vote, jam, comments, duration, score |
| `/api/playing` | GET | — | Now-playing with full metadata + server timestamp |
| `/api/events` | GET | — | SSE event stream (real-time updates) |
| `/api/spotify/devices` | GET | — | List Spotify Connect devices |
| `/api/spotify/transfer` | POST | `{"device_id": "<id>", "play": true}` | Transfer playback to a device |
| `/api/spotify/status` | GET | — | Current Spotify playback status |

Example:
```bash
curl -s -X POST https://echone.st/api/queue/skip \
  -H "Authorization: Bearer $ECHONEST_API_TOKEN"

# List Spotify devices
curl -s https://echone.st/api/spotify/devices \
  -H "Authorization: Bearer $ECHONEST_API_TOKEN"

# Transfer playback to a device
curl -s -X POST https://echone.st/api/spotify/transfer \
  -H "Authorization: Bearer $ECHONEST_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"device_id": "<id>", "play": true}'
```

Returns `{"ok": true}` on success or `{"error": "message"}` on failure.

**Read endpoints:**
```bash
# Rich queue data (includes vote, jam, comments, duration, score, auto)
curl -s https://echone.st/api/queue \
  -H "Authorization: Bearer $ECHONEST_API_TOKEN"

# Now-playing with full metadata
curl -s https://echone.st/api/playing \
  -H "Authorization: Bearer $ECHONEST_API_TOKEN"

# SSE event stream (Ctrl+C to stop)
curl -N https://echone.st/api/events \
  -H "Authorization: Bearer $ECHONEST_API_TOKEN"
```

**Note**: Spotify Connect endpoints require `ECHONEST_SPOTIFY_EMAIL` to be set in `.env` and the corresponding user to have completed Spotify OAuth via the browser UI ("sync audio" button).

---

## OAuth Configuration

### Google Cloud Console

- Project: Andre
- OAuth Client: Web application
- Authorized redirect URI: `https://echone.st/authentication/callback`

### Spotify Developer Dashboard

- App: Andre
- Redirect URI: `https://echone.st/authentication/spotify_callback`

---

## Firewall Rules (UFW)

```
22/tcp   - SSH
80/tcp   - HTTP (ACME challenges)
443/tcp  - HTTPS
```

Check status: `ufw status numbered`

---

## Troubleshooting

### App won't start

```bash
docker compose logs echonest
# Check for Python errors
```

### OAuth redirect errors

1. Verify redirect URI matches exactly in Google/Spotify console
2. Check HOSTNAME in config: `grep HOSTNAME /opt/echonest/local_config.yaml`
3. Ensure using `https://` not `http://`

### WebSocket not connecting

1. Check Caddy config has `flush_interval -1`
2. Check browser console for mixed content warnings
3. Test: `wscat -c "wss://echone.st/socket/"`

### Redis issues

```bash
# Check Redis memory
docker exec echonest_redis redis-cli INFO memory

# Check max memory setting
docker exec echonest_redis redis-cli CONFIG GET maxmemory
```

### SSL certificate issues

```bash
# Check certificate
echo | openssl s_client -servername echone.st -connect echone.st:443 2>/dev/null | openssl x509 -noout -dates

# Force Caddy to renew
systemctl restart caddy
```

---

## Backup & Recovery

### Manual Backup

```bash
ssh deploy@192.81.213.152
cd /opt/echonest

# Backup play_logs
tar -czvf ~/backup_play_logs_$(date +%Y%m%d).tar.gz play_logs/

# Backup oauth_creds
tar -czvf ~/backup_oauth_creds_$(date +%Y%m%d).tar.gz oauth_creds/

# Backup Redis
docker exec echonest_redis redis-cli BGSAVE
docker cp echonest_redis:/data/dump.rdb ~/backup_redis_$(date +%Y%m%d).rdb
```

### Recovery

```bash
# Restore from backup
tar -xzvf backup_play_logs_YYYYMMDD.tar.gz -C /opt/echonest/
tar -xzvf backup_oauth_creds_YYYYMMDD.tar.gz -C /opt/echonest/

# Restore Redis
docker cp backup_redis_YYYYMMDD.rdb echonest_redis:/data/dump.rdb
docker compose restart redis
```

---

## Costs

| Item | Monthly Cost |
|------|-------------|
| DigitalOcean Droplet (s-1vcpu-1gb) | $6.00 |
| Domain (subdomain) | $0 |
| SSL (Let's Encrypt) | $0 |
| **Total** | **$6.00** |

---

## Deployment Date

- **Initial Deployment**: February 4, 2026
- **Droplet Rebuilt**: February 7, 2026 (new IP: 192.81.213.152, added Tailscale + REST API)
- **Droplet ID**: 550073923
- **Tailscale IP**: 100.92.192.62
- **Deployed By**: Claude Code + Dylan Bochman
