# Andre Cloud Hosting Plan

## Overview

This document outlines the plan to deploy Andre to a cloud VPS, making it accessible externally at `andre.dylanbochman.com`.

**Target**: Simple, low-cost hosting for ~5 concurrent users.

---

## Architecture

```
                    ┌─────────────────────────────┐
                    │   andre.dylanbochman.com    │
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
                    │  │   ├─ andre (Flask)    │  │
                    │  │   ├─ player           │  │
                    │  │   ├─ redis            │  │
                    │  │   └─ postgres         │  │
                    │  └───────────────────────┘  │
                    │                             │
                    │  Volume: /data              │
                    │   ├─ play_logs/            │
                    │   ├─ oauth_creds/          │
                    │   └─ redis/                │
                    └─────────────────────────────┘
```

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
  - Use werkzeug's `ProxyFix` middleware

- [ ] **1.4** Remove `verify=False` security issue
  - Line 491 in app.py disables SSL verification on Google API call
  - Remove this for production security

- [ ] **1.5** Production config improvements
  - Create `.env.example` template
  - Update docker-compose for production (no mounted local_config.yaml)
  - Document all required environment variables

### Phase 2: Infrastructure Setup

- [ ] **2.1** Create DigitalOcean droplet
  - Ubuntu 22.04 LTS
  - 1GB RAM / 1 CPU ($6/mo)
  - Enable monitoring

- [ ] **2.2** Initial server setup
  - Create non-root user
  - Configure SSH keys
  - Enable firewall (UFW)
  - Install Docker + Docker Compose

- [ ] **2.3** Install and configure Caddy
  - Automatic HTTPS via Let's Encrypt
  - WebSocket proxy support
  - Reverse proxy to Docker containers

- [ ] **2.4** Configure DNS
  - Add A record: `andre.dylanbochman.com` → droplet IP
  - Wait for propagation

### Phase 3: Deploy Application

- [ ] **3.1** Clone repository to server
  - Set up deploy keys or use HTTPS clone

- [ ] **3.2** Configure production environment
  - Create `.env` file with secrets
  - Set `ANDRE_HOSTNAME=andre.dylanbochman.com`
  - Set `DEBUG=false`

- [ ] **3.3** Configure Caddy
  ```
  andre.dylanbochman.com {
      reverse_proxy localhost:5001
  }
  ```

- [ ] **3.4** Start services
  - `docker-compose up -d`
  - Verify all containers running
  - Check logs for errors

- [ ] **3.5** Update OAuth redirect URIs
  - **Google Console**: Add `https://andre.dylanbochman.com/authentication/callback`
  - **Spotify Dashboard**: Add `https://andre.dylanbochman.com/authentication/spotify_callback`

- [ ] **3.6** Test all functionality
  - Google OAuth login
  - Spotify OAuth connection
  - WebSocket connectivity
  - Queue/vote/airhorn features
  - Throwback feature

### Phase 4: Maintenance & Monitoring

- [ ] **4.1** Configure automatic restarts
  - Docker restart policies (already in docker-compose)
  - Systemd service for Caddy

- [ ] **4.2** Set up log rotation
  - Configure Docker logging driver
  - Rotate play_logs if needed

- [ ] **4.3** Optional: Basic monitoring
  - DigitalOcean built-in monitoring
  - Uptime check (UptimeRobot free tier)

- [ ] **4.4** Backup strategy
  - Periodic backup of play_logs
  - Periodic backup of oauth_creds
  - Redis RDB backups

---

## Configuration Reference

### Required Environment Variables

```bash
# Core
ANDRE_HOSTNAME=andre.dylanbochman.com
DEBUG=false
SECRET_KEY=<generate-random-32-char-string>

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

### Caddy Configuration

```
andre.dylanbochman.com {
    reverse_proxy localhost:5001
}
```

Caddy automatically:
- Obtains Let's Encrypt certificate
- Redirects HTTP to HTTPS
- Handles WebSocket upgrade headers
- Renews certificates before expiry

### Firewall Rules (UFW)

```bash
ufw allow 22/tcp    # SSH
ufw allow 80/tcp    # HTTP (for ACME challenge)
ufw allow 443/tcp   # HTTPS
ufw enable
```

---

## Rollback Plan

If deployment fails:

1. Andre continues running locally
2. DNS change can be reverted (remove A record)
3. VPS can be destroyed with no data loss (all data is local)

---

## Future Improvements

- [ ] CI/CD pipeline for automatic deployments
- [ ] Managed Redis (if scaling needed)
- [ ] CDN for static assets
- [ ] Database backups to S3
- [ ] Multiple replicas with load balancing

---

## References

- [DigitalOcean Docker Tutorial](https://www.digitalocean.com/community/tutorials/how-to-install-and-use-docker-on-ubuntu-22-04)
- [Caddy Documentation](https://caddyserver.com/docs/)
- [Let's Encrypt](https://letsencrypt.org/)
- [Google OAuth Setup](https://console.cloud.google.com/apis/credentials)
- [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
