# Slim Homebrew Formula — Completed

**Status**: Done (v0.6.1, February 2026)

## What Changed

The Homebrew formula was simplified from 20+ resource blocks (including native wheel workarounds for pillow, pyobjc, pystray) to 14 pure-python sdist resources. Install size dropped from 26.8MB to 2.7MB.

### Summary of Changes

| File | Change |
|------|--------|
| `pyproject.toml` | `pystray` + `pillow` moved to `[app]` optional extra |
| `src/echonest_sync/app.py` | Import guard: friendly error when GUI deps missing |
| `src/echonest_sync/cli.py` | Added `--version`, `status` subcommand, post-login linking hint |
| `homebrew-echonest/Formula/echonest-sync.rb` | Slim formula — pure-python deps only, no native wheels |
| `homebrew-echonest/README.md` | Updated to reflect CLI-only install |

### Install Extras

| Extra | Deps | Use Case |
|-------|------|----------|
| *(base)* | requests, sseclient-py, click, pyyaml, keyring | CLI sync agent |
| `[app]` | + pystray, pillow | Desktop tray app (Windows/Linux) |
| `[mac]` | + rumps | macOS menu bar integration |
| `[app,mac]` | all of the above | Full desktop app on macOS |

### Homebrew Experience

```bash
brew tap dbochman/echonest
brew install echonest-sync    # ~2.7MB, <70s

echonest-sync login            # interactive setup
echonest-sync status           # verify config
echonest-sync                  # start syncing
echonest-sync --version        # 0.6.1
```
