# Changelog

All notable changes to Andre are documented in this file.

---

## 2026-02-05

### Features

- **Podcast Support** - Added ability to search for and play Spotify podcast episodes
  - Separate podcast search input in the Search tab
  - Episode metadata display (show name, cover art)
  - Dynamic skip button text ("skip playing song" vs "skip playing podcast")
  - 9 new tests for episode handling
  - PR #5, Commit: `411b568`

### Bug Fixes

- **Visual Duplicate Fix** - Fixed issue where now-playing track appeared in both Now Playing section and queue due to WebSocket timing
  - Added client-side filtering in `PlaylistView.render()`
  - Commit: `7f97604`

- **Spotify Unpause Fix** - Fixed issue where Spotify playback wouldn't resume when unpausing Andre
  - Added state transition detection to call `resume_spotify_if_needed()` when going from paused to unpaused
  - Commit: `1ef478f`

- **Spotify 403 Error Fix** - Fixed 403 Forbidden errors when resuming Spotify without an active device
  - Changed `resume_spotify_if_needed()` to use `spotify_play()` with track URI instead of bare play endpoint
  - Commit: `f17cccf`

- **Missing Audio File Fix** - Fixed 404 error and console warnings for missing `wow.wav` airhorn file
  - Removed reference to non-existent audio file from `app.js`

- **Form Accessibility Fix** - Added missing `id` and `name` attributes to search input fields
  - Fixed 3 form fields in `main.html` that triggered browser accessibility warnings

- **Queue Profile Image Clipping** - Fixed profile images being clipped in queue items
  - Changed person-image from 43x65px to 65x65px square to match Gravatar aspect ratio
  - Adjusted controls and jammers positioning to accommodate wider images

### Security

- **Redis Authentication** - Added password authentication and protected mode in response to DigitalOcean security notice
  - `--requirepass` and `--protected-mode yes` flags
  - All Python Redis connections updated to use password
  - Commit: `895b62d`

- **Redis Security Documentation** - Added comprehensive best practices checklist with references
  - Commit: `a51d027`

---

## 2026-02-04

### Features

- **Enhanced Paused State Display** - Added visual indicator when playback is paused
  - Pause icon overlay on album art with Bender theme
  - PR #4, Commit: `0b2ba40`

### Infrastructure

- **Initial Cloud Deployment** - Deployed Andre to DigitalOcean
  - Ubuntu 22.04 LTS droplet with Docker Compose
  - Caddy reverse proxy with auto HTTPS
  - Live at https://andre.dylanbochman.com

### Security

- **Docker Security Hardening** - Implemented 11 security measures
  - Non-root containers
  - Pinned image versions with SHA256 digests
  - Network isolation (internal network for Redis)
  - Resource limits
  - Read-only filesystem
  - Dropped capabilities
  - Health checks

- **SSH Hardening** - Disabled root login and password authentication

- **Fail2ban** - Added SSH brute force protection with 365-day ban

- **Security Documentation** - Created comprehensive `SECURITY.md`
  - Commits: `2a091da`, `a243fd8`

---

## Earlier History

See git log for changes prior to 2026-02-04.
