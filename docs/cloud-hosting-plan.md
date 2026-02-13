# EchoNest Cloud Hosting Plan

## Overview

This document outlines the plan to deploy EchoNest to a cloud VPS, making it accessible externally at `echone.st`.

**Target**: Simple, low-cost hosting for ~5 concurrent users.

**Playback Model**: Each user connects their own Spotify account and controls playback on their own devices. EchoNest is the shared queue - users add songs, vote, and jam together, but each person listens through their individual Spotify app.

---

## Architecture

```
                    ┌─────────────────────────────┐
                    │       echone.st             │
                    │      (DNS A record)         │
                    └─────────────┬───────────────┘
                                  │
                    ┌─────────────▼───────────────┐
                    │    DigitalOcean Droplet     │
                    │         $6/month            │
                    │                             │
                    │  ┌───────────────────────┐  │
                    │  │   Caddy (reverse      │  │
                    │  │   proxy + auto HTTPS) │  │
                    │  └───────────┬───────────┘  │
                    │              │              │
                    │  ┌───────────▼───────────┐  │
                    │  │   Docker Compose      │  │
                    │  │   ├─ echonest (Flask)  │  │
                    │  │   ├─ player           │  │
                    │  │   └─ redis            │  │
                    │  └───────────────────────┘  │
                    │                             │
                    │  Volume: /opt/echonest/data    │
                    │   ├─ play_logs/  (REQUIRED) │
                    │   ├─ oauth_creds/           │
                    │   └─ redis/                 │
                    └─────────────────────────────┘
```

**Note**: PostgreSQL is optional and not required for core functionality. Redis handles all queue, voting, and session data.

---

## Estimated Costs

| Item | Cost |
|------|------|
| DigitalOcean droplet (1GB RAM, 1 CPU) | $6/mo |
| Domain (subdomain of dylanbochman.com) | $0 |
| SSL certificate (Let's Encrypt via Caddy) | $0 |
| **Total** | **~$6/month** |

---

## Implementation Phases

### Phase 1: Code Changes (Before Deployment)

Make the codebase production-ready:

- [ ] **1.1** Add HTTPS support to OAuth redirect URIs
  - Update `app.py` to detect HTTPS via `X-Forwarded-Proto` header
  - Use `https://` for redirect URIs when behind reverse proxy

- [ ] **1.2** Fix `SESSION_COOKIE_SECURE`
  - Set to `True` when not in DEBUG mode
  - Cookies must be secure over HTTPS

- [ ] **1.3** Add reverse proxy header support
  - Handle `X-Forwarded-For`, `X-Forwarded-Proto`, `X-Forwarded-Host`
  - Use werkzeug's `ProxyFix` middleware (only in production)
  ```python
  if not CONF.DEBUG:
      from werkzeug.middleware.proxy_fix import ProxyFix
      app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
  ```

- [ ] **1.4** Remove `verify=False` security issue
  - Line 491 in app.py disables SSL verification on Google API call
  - Remove this for production security

- [ ] **1.5** Production config improvements
  - Create `.env.example` template (see Configuration Reference below)
  - Add Redis memory limit and log rotation to `docker-compose.yaml`
  - Document all required environment variables

- [ ] **1.6** Add Redis memory limit
  - Configure `maxmemory` to prevent OOM on 1GB droplet
  - Add to docker-compose redis service

**Verification**: Run `python -m py_compile app.py` to confirm no syntax errors after changes.

---

### Phase 2: Infrastructure Setup

- [ ] **2.1** Create DigitalOcean droplet

  ```bash
  # Via DigitalOcean web console or doctl CLI:
  doctl compute droplet create echonest \
    --image ubuntu-22-04-x64 \
    --size s-1vcpu-1gb \
    --region nyc1 \
    --ssh-keys <your-ssh-key-id> \
    --enable-monitoring
  ```

  **Verify**: `doctl compute droplet list` shows the droplet with an IP address.

- [ ] **2.2** Initial server setup

  SSH into the droplet:
  ```bash
  ssh root@<droplet-ip>
  ```

  Create non-root user:
  ```bash
  adduser deploy
  usermod -aG sudo deploy

  # Copy SSH keys to new user
  mkdir -p /home/deploy/.ssh
  cp ~/.ssh/authorized_keys /home/deploy/.ssh/
  chown -R deploy:deploy /home/deploy/.ssh
  chmod 700 /home/deploy/.ssh
  chmod 600 /home/deploy/.ssh/authorized_keys
  ```

  Configure firewall:
  ```bash
  ufw allow 22/tcp    # SSH
  ufw allow 80/tcp    # HTTP (for ACME challenge)
  ufw allow 443/tcp   # HTTPS
  ufw --force enable
  ```

  **Verify firewall**:
  ```bash
  ufw status
  # Should show: 22, 80, 443 ALLOW
  ```

  Install Docker:
  ```bash
  # Install Docker
  curl -fsSL https://get.docker.com | sh

  # Add deploy user to docker group
  usermod -aG docker deploy

  # Install Docker Compose plugin
  apt-get update
  apt-get install -y docker-compose-plugin
  ```

  **Verify Docker**:
  ```bash
  docker --version
  docker compose version
  # Both should return version numbers
  ```

- [ ] **2.3** Install and configure Caddy

  ```bash
  # Install Caddy
  apt install -y debian-keyring debian-archive-keyring apt-transport-https
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
  apt update
  apt install -y caddy
  ```

  **Verify Caddy installed**:
  ```bash
  caddy version
  systemctl status caddy
  ```

- [ ] **2.4** Configure DNS

  Add A record in your DNS provider:
  - **Name**: `echone.st`
  - **Type**: `A`
  - **Value**: `<droplet-ip>`
  - **TTL**: `300` (5 minutes - allows fast rollback)

  **Verify DNS propagation**:
  ```bash
  # From local machine
  dig echone.st +short
  # Should return the droplet IP

  # Or use online tool: https://dnschecker.org
  ```

**Verification for Phase 2**: From your local machine, confirm external access:
```bash
nc -zvw3 <droplet-ip> 22   # SSH
nc -zvw3 <droplet-ip> 80   # HTTP
nc -zvw3 <droplet-ip> 443  # HTTPS
```

---

### Phase 3: Deploy Application

- [ ] **3.1** Clone repository to server

  ```bash
  # As deploy user
  su - deploy

  mkdir -p /opt/echonest
  cd /opt/echonest
  git clone https://github.com/yourusername/EchoNest.git .
  ```

  **Verify**: `ls -la` shows repository files including `docker-compose.yaml`.

- [ ] **3.2** Copy data directories to server

  From your local machine:
  ```bash
  # Copy historical play_logs (required for Throwback feature)
  scp -r play_logs/ deploy@<droplet-ip>:/opt/echonest/play_logs/

  # Copy oauth_creds (required for OAuth token caching)
  scp -r oauth_creds/ deploy@<droplet-ip>:/opt/echonest/oauth_creds/
  ```

  **Verify on server**:
  ```bash
  ls -la /opt/echonest/play_logs/
  # Should show play_log_*.json files (~11,600 plays from Nov 2017 - May 2018)

  ls -la /opt/echonest/oauth_creds/
  # Should show OAuth cache files (or empty dir if fresh install)
  ```

  Set permissions:
  ```bash
  chown -R deploy:deploy /opt/echonest/play_logs /opt/echonest/oauth_creds
  chmod -R 755 /opt/echonest/play_logs /opt/echonest/oauth_creds
  ```

- [ ] **3.3** Configure production environment

  Create `.env` file at `/opt/echonest/.env`:
  ```bash
  cat > /opt/echonest/.env << 'EOF'
  # Core
  HOSTNAME=echone.st
  DEBUG=false
  SECRET_KEY=<generate-with: python3 -c "import secrets; print(secrets.token_hex(32))">

  # Redis (internal Docker network)
  REDIS_HOST=redis
  REDIS_PORT=6379

  # Spotify OAuth
  SPOTIFY_CLIENT_ID=<from-spotify-dashboard>
  SPOTIFY_CLIENT_SECRET=<from-spotify-dashboard>
  SPOTIFY_USERNAME=<your-spotify-username>

  # Google OAuth
  GOOGLE_CLIENT_ID=<from-google-console>
  GOOGLE_CLIENT_SECRET=<from-google-console>

  # Access Control
  ALLOWED_EMAIL_DOMAINS=gmail.com,dylanbochman.com
  EOF
  ```

  Secure the file:
  ```bash
  chmod 600 /opt/echonest/.env
  ```

  **Verify**: `cat /opt/echonest/.env` shows all variables populated (no `<placeholders>`).

- [ ] **3.4** Configure Caddy

  Edit `/etc/caddy/Caddyfile`:
  ```bash
  cat > /etc/caddy/Caddyfile << 'EOF'
  echone.st {
      reverse_proxy localhost:5001 {
          flush_interval -1
      }
  }

  andre.dylanbochman.com {
      redir https://echone.st{uri} permanent
  }
  EOF
  ```

  Reload Caddy:
  ```bash
  systemctl reload caddy
  ```

  **Verify Caddy config**:
  ```bash
  caddy validate --config /etc/caddy/Caddyfile
  systemctl status caddy
  # Should show active (running)
  ```

  **Note**: `flush_interval -1` is critical for WebSocket connections. Without it, WebSocket frames are buffered and cause connection failures.

- [ ] **3.5** Start services

  ```bash
  cd /opt/echonest
  docker compose up -d
  ```

  **Verify containers running**:
  ```bash
  docker compose ps
  # Should show: echonest, player, redis all "Up"

  # Check for errors in logs
  docker compose logs --tail=50 echonest
  docker compose logs --tail=50 player
  docker compose logs --tail=50 redis
  ```

  **Verify Redis memory limit**:
  ```bash
  docker exec echonest_redis redis-cli CONFIG GET maxmemory
  # Should return: maxmemory, 134217728 (128MB in bytes)
  ```

  **Verify health endpoint**:
  ```bash
  curl -f http://localhost:5001/health
  # Should return: {"status": "ok"}
  ```

- [ ] **3.6** Verify HTTPS and external access

  **Verify HTTPS certificate**:
  ```bash
  curl -I https://echone.st
  # Should return HTTP/2 200 with no certificate errors

  # Check certificate details
  echo | openssl s_client -servername echone.st -connect echone.st:443 2>/dev/null | openssl x509 -noout -dates
  ```

- [ ] **3.7** Update OAuth redirect URIs

  **Google Cloud Console** (https://console.cloud.google.com/apis/credentials):
  - Add authorized redirect URI: `https://echone.st/authentication/callback`

  **Spotify Developer Dashboard** (https://developer.spotify.com/dashboard):
  - Add redirect URI: `https://echone.st/authentication/spotify_callback`

  **Verify OAuth** (manual test):
  1. Open `https://echone.st` in browser
  2. Click login → should redirect to Google
  3. After Google auth → should redirect back to EchoNest (not error)
  4. Connect Spotify → should redirect to Spotify
  5. After Spotify auth → should return to EchoNest with "Connected" status

- [ ] **3.8** Run smoke test

  ```bash
  # Test health endpoint
  curl -f https://echone.st/health

  # Test queue endpoint (public)
  curl -f https://echone.st/queue/

  # Test playing endpoint (public)
  curl -f https://echone.st/playing/

  # Test WebSocket connectivity (from local machine with wscat)
  # Install: npm install -g wscat
  wscat -c "wss://echone.st/socket/"
  # Should connect without error (may timeout if no auth, but connection works)
  ```

  **Manual smoke test checklist**:
  - [ ] Google OAuth login works
  - [ ] Spotify OAuth connection works
  - [ ] WebSocket connects (queue updates in real-time)
  - [ ] Search returns Spotify results
  - [ ] Can add song to queue
  - [ ] Can vote on songs
  - [ ] Can trigger airhorn
  - [ ] Throwback songs appear (if same day-of-week has history)

---

### Phase 4: Maintenance & Monitoring

- [ ] **4.1** Configure automatic restarts

  Docker restart policies are already in docker-compose.yaml. Verify:
  ```bash
  docker inspect echonest_app --format='{{.HostConfig.RestartPolicy.Name}}'
  # Should return: unless-stopped (or always)
  ```

  Caddy runs via systemd (auto-restarts by default):
  ```bash
  systemctl is-enabled caddy
  # Should return: enabled
  ```

- [ ] **4.2** Set up log rotation

  Docker logs (add to docker-compose.yaml for each service):
  ```yaml
  logging:
    driver: "json-file"
    options:
      max-size: "10m"
      max-file: "3"
  ```

  Verify log rotation config:
  ```bash
  docker inspect echonest_app --format='{{.HostConfig.LogConfig}}'
  ```

- [ ] **4.3** Set up monitoring

  **DigitalOcean monitoring**: Already enabled at droplet creation.

  **UptimeRobot** (free tier):
  1. Create account at https://uptimerobot.com
  2. Add new monitor: `https://echone.st/health`
  3. Set check interval: 5 minutes
  4. Enable email alerts

- [ ] **4.4** Backup strategy

  Create backup script at `/opt/echonest/backup.sh`:
  ```bash
  #!/bin/bash
  BACKUP_DIR="/opt/echonest/backups/$(date +%Y%m%d)"
  mkdir -p "$BACKUP_DIR"

  # Backup play_logs
  cp -r /opt/echonest/play_logs "$BACKUP_DIR/"

  # Backup oauth_creds
  cp -r /opt/echonest/oauth_creds "$BACKUP_DIR/"

  # Backup Redis
  docker exec echonest_redis redis-cli BGSAVE
  sleep 2
  docker cp echonest_redis:/data/dump.rdb "$BACKUP_DIR/"

  # Keep only last 7 days
  find /opt/echonest/backups -type d -mtime +7 -exec rm -rf {} +

  echo "Backup completed: $BACKUP_DIR"
  ```

  Add to crontab:
  ```bash
  chmod +x /opt/echonest/backup.sh
  crontab -e
  # Add: 0 3 * * * /opt/echonest/backup.sh >> /var/log/echonest-backup.log 2>&1
  ```

---

## Configuration Reference

### Production Environment File (.env)

Location: `/opt/echonest/.env`

```bash
# Core
HOSTNAME=echone.st
DEBUG=false
SECRET_KEY=<generate-random-64-char-hex-string>

# Redis (internal Docker network)
REDIS_HOST=redis
REDIS_PORT=6379

# Spotify OAuth
SPOTIFY_CLIENT_ID=<from-spotify-dashboard>
SPOTIFY_CLIENT_SECRET=<from-spotify-dashboard>
SPOTIFY_USERNAME=<your-spotify-username>

# Google OAuth
GOOGLE_CLIENT_ID=<from-google-console>
GOOGLE_CLIENT_SECRET=<from-google-console>

# Access Control
ALLOWED_EMAIL_DOMAINS=gmail.com,dylanbochman.com

# Optional
YT_API_KEY=<youtube-api-key>
SOUNDCLOUD_CLIENT_ID=<soundcloud-client-id>
```

Generate SECRET_KEY:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### Caddy Configuration

Location: `/etc/caddy/Caddyfile`

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

Caddy automatically:
- Obtains Let's Encrypt certificate
- Redirects HTTP to HTTPS
- Handles WebSocket upgrade headers
- Renews certificates before expiry

### Redis Configuration (Memory Limit)

Add to docker-compose.yaml redis service:
```yaml
redis:
  image: redis:7-alpine
  command: redis-server --maxmemory 128mb --maxmemory-policy allkeys-lru
  ...
```

This prevents Redis from consuming all available memory on the 1GB droplet.

### Firewall Rules (UFW)

```bash
ufw allow 22/tcp    # SSH
ufw allow 80/tcp    # HTTP (for ACME challenge)
ufw allow 443/tcp   # HTTPS
ufw enable
```

---

## Spotify Playback Architecture

EchoNest uses a **shared queue, individual playback** model:

1. **Shared Queue**: All users see the same queue, can add songs, vote, jam, and airhorn
2. **Individual Playback**: Each user connects their own Spotify Premium account
3. **Sync Point**: The "now playing" track is the reference - users play along on their own devices

This means:
- No central speaker/playback device needed
- Each user needs Spotify Premium
- Users are responsible for starting playback on their own Spotify app
- The master_player service tracks queue timing but doesn't control individual devices

---

## Rollback Plan

If deployment fails:

### Quick Rollback (DNS)
1. Remove or update DNS A record to point elsewhere
2. DNS TTL is 300 seconds (5 min), so changes propagate quickly
3. EchoNest continues running locally during this time

### Full Rollback
1. Stop services: `docker compose down`
2. Remove DNS A record
3. Destroy droplet: `doctl compute droplet delete echonest`
4. No data loss - all data (play_logs, oauth_creds) remains on local machine

### Data Restore (if needed)
If you need to restore from backup:
```bash
# Stop services
docker compose down

# Restore play_logs
cp -r /opt/echonest/backups/<date>/play_logs/* /opt/echonest/play_logs/

# Restore oauth_creds
cp -r /opt/echonest/backups/<date>/oauth_creds/* /opt/echonest/oauth_creds/

# Restore Redis
docker compose up -d redis
docker cp /opt/echonest/backups/<date>/dump.rdb echonest_redis:/data/
docker exec echonest_redis redis-cli DEBUG RELOAD

# Restart all services
docker compose up -d
```

---

## Troubleshooting

### WebSocket not connecting
1. Check Caddy config has `flush_interval -1`
2. Check browser console for mixed content (HTTP vs HTTPS)
3. Verify with: `wscat -c "wss://echone.st/socket/"`

### OAuth redirect fails
1. Verify redirect URIs match exactly in Google/Spotify console
2. Check HOSTNAME env var matches the domain
3. Check logs: `docker compose logs echonest | grep -i oauth`

### Redis out of memory
1. Check memory: `docker exec echonest_redis redis-cli INFO memory`
2. Verify maxmemory: `docker exec echonest_redis redis-cli CONFIG GET maxmemory`
3. Clear if needed: `docker exec echonest_redis redis-cli FLUSHALL` (destructive!)

### Container won't start
1. Check logs: `docker compose logs <service>`
2. Verify .env file exists and has correct permissions
3. Try rebuilding: `docker compose build --no-cache && docker compose up -d`

---

## Future Improvements

- [ ] CI/CD pipeline for automatic deployments
- [ ] Managed Redis (if scaling needed)
- [ ] CDN for static assets
- [ ] Database backups to S3
- [ ] Multiple replicas with load balancing
- [ ] Spotify Connect integration for synced playback

---

## References

- [DigitalOcean Docker Tutorial](https://www.digitalocean.com/community/tutorials/how-to-install-and-use-docker-on-ubuntu-22-04)
- [Caddy Documentation](https://caddyserver.com/docs/)
- [Caddy reverse_proxy directive](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)
- [Let's Encrypt](https://letsencrypt.org/)
- [Google OAuth Setup](https://console.cloud.google.com/apis/credentials)
- [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
