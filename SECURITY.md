# Security Hardening

This document details all security hardening measures implemented for Andre's production deployment.

## Overview

The deployment has been hardened following industry best practices including [OWASP Docker Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Docker_Security_Cheat_Sheet.html) and CIS benchmarks.

---

## Server Security

### 1. SSH Hardening (Critical)

**Risks mitigated**: Brute force attacks, unauthorized root access, credential theft.

**Implementation**:
| Setting | Value | Purpose |
|---------|-------|---------|
| `PermitRootLogin` | `no` | Prevents direct root SSH access |
| `PasswordAuthentication` | `no` | Key-only authentication |
| `PubkeyAuthentication` | `yes` | SSH keys required |

### 2. Fail2ban (Critical)

**Risk**: Brute force SSH attacks from botnets.

**Implementation**:
- Monitors `/var/log/auth.log` for failed login attempts
- Bans IP addresses via UFW firewall after 3 failed attempts
- **Ban duration: 365 days**

```ini
# /etc/fail2ban/jail.local
[sshd]
enabled = true
maxretry = 3
bantime = 31536000  # 365 days
findtime = 86400    # 24 hour window
banaction = ufw
```

**Commands**:
```bash
# Check status
sudo fail2ban-client status sshd

# Unban an IP (if needed)
sudo fail2ban-client set sshd unbanip <IP>

# View banned IPs
sudo fail2ban-client get sshd banned
```

### 3. UFW Firewall (Critical)

**Risk**: Unauthorized network access to services.

**Implementation**:
| Port | Service | Access |
|------|---------|--------|
| 22/tcp | SSH | Allowed |
| 80/tcp | HTTP | Allowed (redirects to HTTPS) |
| 443/tcp | HTTPS | Allowed |
| 6379 | Redis | **Blocked** (internal only) |

### 4. Tailscale VPN (Critical)

**Risk**: SSH lockout from fail2ban or firewall misconfiguration.

**Implementation**:
- Tailscale installed on droplet, accessible at `100.92.192.62`
- Provides backup SSH access independent of public IP firewall rules
- Not exposed to the public internet
- Access restricted to tailnet members only (no external sharing enabled)

```bash
# Access via Tailscale (bypasses fail2ban/UFW)
ssh deploy@100.92.192.62

# Access via public IP (subject to fail2ban)
ssh deploy@192.81.213.152
```

**Lesson learned**: The previous droplet was permanently locked out when fail2ban (365-day ban) combined with `PasswordAuthentication no` made recovery impossible, even via DO web console. Tailscale prevents this scenario.

### 5. Automatic Security Updates (High)

**Risk**: Unpatched vulnerabilities.

**Implementation**:
- `unattended-upgrades` package installed and enabled
- Security patches applied automatically

---

## Docker Security

### 6. Non-Root Containers (Critical)

**Risk**: Container escape with root privileges.

**Implementation**:
- Created dedicated `andre` user (UID/GID 1000) in Dockerfile
- All app containers run as non-root via `user: "1000:1000"`
- Application files owned by non-root user

```dockerfile
RUN groupadd --gid 1000 andre && \
    useradd --uid 1000 --gid 1000 --shell /bin/bash --create-home andre
USER andre
```

### 7. Pinned Image Versions (High)

**Risk**: Supply chain attacks, unexpected breaking changes.

**Implementation**:
- Base images pinned with SHA256 digests for reproducibility
- Prevents tag mutation attacks

```yaml
image: python:3.11-slim-bookworm@sha256:549988ff0804593d8373682ef5c0f0ceee48328abaaa2e054241c23f5c324751
image: redis:7-alpine@sha256:02f2cc4882f8bf87c79a220ac958f58c700bdec0dfb9b9ea61b62fb0e8f1bfcf
```

### 8. Network Isolation (High)

**Risk**: Lateral movement, data exfiltration from compromised containers.

**Implementation**:
- `andre_network`: External network for Spotify/OAuth API access
- `andre_internal`: Internal-only network (**no internet access**)
- Redis isolated to internal network only

```yaml
networks:
  andre_network:
    internal: false  # Internet access for APIs
  andre_internal:
    internal: true   # No internet access
```

### 9. Resource Limits (Medium)

**Risk**: Resource exhaustion, DoS attacks.

**Implementation**:
| Service | CPU Limit | Memory Limit |
|---------|-----------|--------------|
| Redis   | 0.5       | 256M         |
| Andre   | 1.0       | 512M         |
| Player  | 0.5       | 256M         |

### 10. Read-Only Filesystem (Medium)

**Risk**: Malware persistence, unauthorized modifications.

**Implementation**:
- All containers use `read_only: true`
- tmpfs mounts for `/tmp` and `__pycache__`
- Only necessary directories mounted writable (`play_logs`, `oauth_creds`)

### 11. Dropped Capabilities (Medium)

**Risk**: Privilege escalation within containers.

**Implementation**:
```yaml
security_opt:
  - no-new-privileges:true
cap_drop:
  - ALL
```

**Note**: Redis requires `SETGID` and `SETUID` capabilities to switch to its internal user, so these are added back for Redis only.

### 12. Health Checks (Low)

**Risk**: Unhealthy containers serving traffic.

**Implementation**:
- Redis: `redis-cli ping`
- Andre: HTTP check on `/health` endpoint
- Automatic container restart on failure

### 13. Redis Authentication (High)

**Risk**: Unauthorized access to Redis data if network misconfiguration occurs.

**Implementation**:
- Password authentication via `--requirepass` flag
- Protected mode enabled via `--protected-mode yes`
- Password stored in `.env` file (not in source control)
- All Python Redis connections updated to use password

```yaml
# docker-compose.yaml
command: redis-server --maxmemory 128mb --maxmemory-policy allkeys-lru --requirepass ${REDIS_PASSWORD} --protected-mode yes
```

```python
# db.py, app.py
redis.StrictRedis(host=..., port=..., password=CONF.REDIS_PASSWORD, ...)
```

**Defense in Depth**: Even though Redis port 6379 is blocked by UFW firewall, authentication provides an additional security layer against:
- Firewall misconfiguration
- Internal network compromise
- Container escape scenarios

### 14. Redis Best Practices Checklist (Reference)

Based on [Redis Security Documentation](https://redis.io/docs/latest/operate/oss_and_stack/management/security/) and [DigitalOcean Best Practices](https://www.digitalocean.com/community/tutorials/how-to-install-and-secure-redis-on-ubuntu):

| Practice | Status | Notes |
|----------|--------|-------|
| Bind to loopback/trusted network | ✓ | Docker internal network only |
| Firewall protection | ✓ | UFW blocks port 6379 |
| Password authentication | ✓ | `--requirepass` enabled |
| Protected mode | ✓ | `--protected-mode yes` |
| Run as non-root | ✓ | Redis Alpine image default |
| Network isolation | ✓ | `andre_internal` network |
| TLS encryption | N/A | Not needed for internal Docker network |
| ACL-based command restrictions | Future | Would block FLUSHALL, CONFIG, etc. |
| Disable default user | Future | Requires ACL file configuration |
| Restrict key patterns | N/A | Single-tenant application |

**Future Enhancements** (for higher-security deployments):
- Use Redis ACLs to disable dangerous commands (`-@dangerous`)
- Create dedicated application user with minimal permissions
- Enable TLS for Redis connections (if spanning network boundaries)
- Implement Redis Sentinel or Cluster for HA

---

## Application Security

### 15. REST API Token Authentication (High)

**Risk**: Unauthorized programmatic access to queue management (skip, remove, clear, etc.).

**Implementation**:
- `@require_api_token` decorator on all `/api/queue/*` and `/api/spotify/*` endpoints
- Bearer token in `Authorization` header
- Constant-time comparison via `secrets.compare_digest()` (prevents timing side-channel attacks)
- Token stored in `.env` file and 1Password (`op://OpenClaw/Andre API Token/password`)
- Header format: `Authorization: Bearer <token>`
- Rotate token immediately if leaked (update `/opt/andre/.env` + 1Password, then `docker compose restart andre`)

```python
# app.py
def require_api_token(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        # ... validates Bearer token with secrets.compare_digest()
```

**Response codes**:
| Code | Meaning |
|------|---------|
| 200 | Success |
| 400 | Missing required field |
| 401 | Missing/malformed Authorization header (includes `WWW-Authenticate: Bearer`) |
| 403 | Invalid token |
| 503 | Token not configured on server |

**Key design decisions**:
- `/api/` added to `SAFE_PARAM_PATHS` to bypass session/OAuth auth (token auth handled by decorator)
- API paths return JSON errors, never 302 redirects to login page
- Fixed `API_EMAIL = 'openclaw@api'` used for audit trail (not a real user)

---

## Verification Commands

Run these commands to verify security measures:

```bash
# === Server Security ===

# 1. Check SSH config
ssh deploy@192.81.213.152 "sudo sshd -T | grep -E '^(permitrootlogin|passwordauthentication)'"
# Expected: permitrootlogin no, passwordauthentication no

# 2. Check fail2ban status
ssh deploy@192.81.213.152 "sudo fail2ban-client status sshd"
# Expected: Shows banned IPs and jail status

# 3. Check firewall
ssh deploy@192.81.213.152 "sudo ufw status"
# Expected: Only ports 22, 80, 443 allowed

# 4. Check Tailscale access
ssh deploy@100.92.192.62 "echo 'Tailscale SSH OK'"
# Expected: Tailscale SSH OK

# === Docker Security ===

# 4. Verify non-root user
ssh deploy@192.81.213.152 "docker exec andre_app whoami"
# Expected: andre (not root)

# 5. Verify read-only filesystem
ssh deploy@192.81.213.152 "docker exec andre_app touch /test 2>&1"
# Expected: Read-only file system error

# 6. Verify capabilities dropped
ssh deploy@192.81.213.152 "docker exec andre_app cat /proc/1/status | grep CapEff"
# Expected: CapEff: 0000000000000000

# 7. Verify resource limits
ssh deploy@192.81.213.152 "docker stats --no-stream"
# Expected: MEM LIMIT shows configured values

# 8. Verify network isolation
ssh deploy@192.81.213.152 "docker exec andre_redis ping -c 1 8.8.8.8 2>&1"
# Expected: Network unreachable

# 9. Verify health checks
ssh deploy@192.81.213.152 "docker inspect andre_app --format='{{.State.Health.Status}}'"
# Expected: healthy

# 10. Verify Redis authentication
ssh deploy@192.81.213.152 "docker exec andre_redis redis-cli PING 2>&1"
# Expected: NOAUTH Authentication required

ssh deploy@192.81.213.152 "docker exec andre_redis redis-cli -a \$REDIS_PASSWORD PING 2>&1"
# Expected: PONG

# 11. Verify Redis protected mode
ssh deploy@192.81.213.152 "docker exec andre_redis redis-cli -a \$REDIS_PASSWORD CONFIG GET protected-mode"
# Expected: protected-mode yes

# === API Security ===

# 12. Verify API rejects unauthenticated requests
curl -s -o /dev/null -w "%{http_code}" -X POST https://andre.dylanbochman.com/api/queue/skip
# Expected: 401

# 13. Verify API rejects invalid token
curl -s -o /dev/null -w "%{http_code}" -X POST https://andre.dylanbochman.com/api/queue/skip -H "Authorization: Bearer wrong"
# Expected: 403

# 14. Verify API accepts valid token
curl -s -o /dev/null -w "%{http_code}" -X POST https://andre.dylanbochman.com/api/queue/skip -H "Authorization: Bearer \$ANDRE_API_TOKEN"
# Expected: 200
```

---

## Incident Response

### If you suspect a compromise:

1. **Isolate**: `ssh deploy@192.81.213.152 "docker compose down"` (or via Tailscale: `ssh deploy@100.92.192.62`)
2. **Preserve logs**: `ssh deploy@... "docker logs andre_app > /tmp/app.log 2>&1"`
3. **Check for persistence**:
   ```bash
   # Check crontabs
   for user in root deploy; do sudo crontab -u $user -l; done

   # Check SSH keys
   cat ~/.ssh/authorized_keys
   sudo cat /root/.ssh/authorized_keys

   # Check running processes
   ps aux | grep -E 'curl|wget|nc|python.*-c'

   # Check listening ports
   sudo ss -tlnp
   ```
4. **Review fail2ban**: `sudo fail2ban-client status sshd`
5. **Check auth logs**: `sudo grep -i 'failed\|invalid' /var/log/auth.log | tail -50`

### Unban a legitimate IP:

```bash
sudo fail2ban-client set sshd unbanip <IP_ADDRESS>
```

---

## Rollback

If Docker security changes cause issues:

```bash
git checkout HEAD~1 -- docker-compose.yaml Dockerfile
docker compose down
docker compose up -d --build
```

---

## Files Modified

| File | Changes |
|------|---------|
| `Dockerfile` | Non-root user, curl for healthcheck, pinned base image |
| `docker-compose.yaml` | Networks, resource limits, read-only FS, security options, health checks |
| `app.py` | `require_api_token` decorator, `/api/` in SAFE_PARAM_PATHS, 9 REST API endpoints (queue + Spotify Connect) |
| `config.py` | `ANDRE_API_TOKEN`, `ANDRE_SPOTIFY_EMAIL` in ENV_OVERRIDES |
| `/etc/ssh/sshd_config` | Disabled root login and password auth |
| `/etc/fail2ban/jail.local` | SSH jail with 365-day ban |

---

## References

- [OWASP Docker Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Docker_Security_Cheat_Sheet.html)
- [CIS Docker Benchmark](https://www.cisecurity.org/benchmark/docker)
- [Docker Security Best Practices](https://docs.docker.com/develop/security-best-practices/)
- [Fail2ban Documentation](https://www.fail2ban.org/wiki/index.php/Main_Page)
- [Ubuntu Server Security Guide](https://ubuntu.com/server/docs/security-introduction)
- [Redis Security Documentation](https://redis.io/docs/latest/operate/oss_and_stack/management/security/)
- [Redis ACL Documentation](https://redis.io/docs/latest/operate/oss_and_stack/management/security/acl/)
- [DigitalOcean: How to Install and Secure Redis](https://www.digitalocean.com/community/tutorials/how-to-install-and-secure-redis-on-ubuntu)

---

## Changelog

| Date | Change |
|------|--------|
| 2026-02-04 | Initial Docker security hardening (7 measures) |
| 2026-02-04 | Added fail2ban with 365-day SSH ban |
| 2026-02-04 | Disabled SSH root login and password auth |
| 2026-02-04 | Verified automatic security updates enabled |
| 2026-02-05 | Added Redis password authentication and protected mode (response to DigitalOcean security notice) |
| 2026-02-05 | Documented Redis security best practices checklist with references |
| 2026-02-07 | Rebuilt droplet (new IP: 192.81.213.152) with cloud-init provisioning |
| 2026-02-07 | Added Tailscale VPN for backup SSH access (100.92.192.62) |
| 2026-02-07 | Added token-authenticated REST API endpoints with constant-time comparison |
| 2026-02-07 | Re-hardened SSH (PasswordAuthentication=no, PermitRootLogin=no) |
| 2026-02-07 | Added Spotify Connect REST API endpoints (devices, transfer, status) with token auth |
