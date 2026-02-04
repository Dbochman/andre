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

### 4. Automatic Security Updates (High)

**Risk**: Unpatched vulnerabilities.

**Implementation**:
- `unattended-upgrades` package installed and enabled
- Security patches applied automatically

---

## Docker Security

### 5. Non-Root Containers (Critical)

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

### 6. Pinned Image Versions (High)

**Risk**: Supply chain attacks, unexpected breaking changes.

**Implementation**:
- Base images pinned with SHA256 digests for reproducibility
- Prevents tag mutation attacks

```yaml
image: python:3.11-slim-bookworm@sha256:549988ff0804593d8373682ef5c0f0ceee48328abaaa2e054241c23f5c324751
image: redis:7-alpine@sha256:02f2cc4882f8bf87c79a220ac958f58c700bdec0dfb9b9ea61b62fb0e8f1bfcf
```

### 7. Network Isolation (High)

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

### 8. Resource Limits (Medium)

**Risk**: Resource exhaustion, DoS attacks.

**Implementation**:
| Service | CPU Limit | Memory Limit |
|---------|-----------|--------------|
| Redis   | 0.5       | 256M         |
| Andre   | 1.0       | 512M         |
| Player  | 0.5       | 256M         |

### 9. Read-Only Filesystem (Medium)

**Risk**: Malware persistence, unauthorized modifications.

**Implementation**:
- All containers use `read_only: true`
- tmpfs mounts for `/tmp` and `__pycache__`
- Only necessary directories mounted writable (`play_logs`, `oauth_creds`)

### 10. Dropped Capabilities (Medium)

**Risk**: Privilege escalation within containers.

**Implementation**:
```yaml
security_opt:
  - no-new-privileges:true
cap_drop:
  - ALL
```

**Note**: Redis requires `SETGID` and `SETUID` capabilities to switch to its internal user, so these are added back for Redis only.

### 11. Health Checks (Low)

**Risk**: Unhealthy containers serving traffic.

**Implementation**:
- Redis: `redis-cli ping`
- Andre: HTTP check on `/health` endpoint
- Automatic container restart on failure

---

## Verification Commands

Run these commands to verify security measures:

```bash
# === Server Security ===

# 1. Check SSH config
ssh deploy@192.241.153.83 "sudo sshd -T | grep -E '^(permitrootlogin|passwordauthentication)'"
# Expected: permitrootlogin no, passwordauthentication no

# 2. Check fail2ban status
ssh deploy@192.241.153.83 "sudo fail2ban-client status sshd"
# Expected: Shows banned IPs and jail status

# 3. Check firewall
ssh deploy@192.241.153.83 "sudo ufw status"
# Expected: Only ports 22, 80, 443 allowed

# === Docker Security ===

# 4. Verify non-root user
ssh deploy@192.241.153.83 "docker exec andre_app whoami"
# Expected: andre (not root)

# 5. Verify read-only filesystem
ssh deploy@192.241.153.83 "docker exec andre_app touch /test 2>&1"
# Expected: Read-only file system error

# 6. Verify capabilities dropped
ssh deploy@192.241.153.83 "docker exec andre_app cat /proc/1/status | grep CapEff"
# Expected: CapEff: 0000000000000000

# 7. Verify resource limits
ssh deploy@192.241.153.83 "docker stats --no-stream"
# Expected: MEM LIMIT shows configured values

# 8. Verify network isolation
ssh deploy@192.241.153.83 "docker exec andre_redis ping -c 1 8.8.8.8 2>&1"
# Expected: Network unreachable

# 9. Verify health checks
ssh deploy@192.241.153.83 "docker inspect andre_app --format='{{.State.Health.Status}}'"
# Expected: healthy
```

---

## Incident Response

### If you suspect a compromise:

1. **Isolate**: `ssh deploy@... "docker compose down"`
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
| `/etc/ssh/sshd_config` | Disabled root login and password auth |
| `/etc/fail2ban/jail.local` | SSH jail with 365-day ban |

---

## References

- [OWASP Docker Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Docker_Security_Cheat_Sheet.html)
- [CIS Docker Benchmark](https://www.cisecurity.org/benchmark/docker)
- [Docker Security Best Practices](https://docs.docker.com/develop/security-best-practices/)
- [Fail2ban Documentation](https://www.fail2ban.org/wiki/index.php/Main_Page)
- [Ubuntu Server Security Guide](https://ubuntu.com/server/docs/security-introduction)

---

## Changelog

| Date | Change |
|------|--------|
| 2026-02-04 | Initial Docker security hardening (7 measures) |
| 2026-02-04 | Added fail2ban with 365-day SSH ban |
| 2026-02-04 | Disabled SSH root login and password auth |
| 2026-02-04 | Verified automatic security updates enabled |
