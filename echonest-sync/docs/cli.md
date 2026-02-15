# CLI Usage

The CLI is the recommended way to use EchoNest Sync via Homebrew, and an alternative to the desktop app for headless setups, scripts, or users who prefer the terminal.

## Installation

### Homebrew (macOS)

```bash
brew tap dbochman/echonest
brew install echonest-sync
```

### pip (all platforms)

```bash
pip install echonest-sync
```

This installs the CLI only. For the desktop tray app, add GUI extras:

```bash
# macOS
pip install 'echonest-sync[app,mac]'

# Windows / Linux
pip install 'echonest-sync[app]'
```

## Quick Start

```bash
# Log in (uses default server and invite code)
echonest-sync login

# Start syncing
echonest-sync
```

## Commands

| Command | Description |
|---------|-------------|
| *(default)* | Start syncing — connects to server and controls Spotify |
| `login` | Authenticate with an EchoNest server and save credentials |
| `logout` | Remove saved credentials from keyring |
| `status` | Show current configuration and connection status |

### `echonest-sync login`

Exchanges an invite code for an API token, stores it in your system keychain, and saves the server URL to config.

```bash
# Interactive (prompts for server and code with defaults)
echonest-sync login

# Non-interactive
echonest-sync login --server https://echone.st --code futureofmusic
```

### `echonest-sync status`

Shows your current setup at a glance:

```
echonest-sync 0.6.1

  Server:  https://echone.st
  Auth:    logged in (token in keyring)
  Account: you@gmail.com
```

### `echonest-sync logout`

Removes the API token from your system keychain.

## Options

| Flag | Short | Description | Default |
|------|-------|-------------|---------|
| `--version` | | Show version and exit | |
| `--server URL` | `-s` | EchoNest server URL | (from config/keyring) |
| `--token TOKEN` | `-t` | API token | (from config/keyring) |
| `--drift-threshold N` | `-d` | Seconds of drift before seeking | `3` |
| `--verbose` | `-v` | Enable debug logging | off |

## Config File

Instead of passing flags every time, use `login` or create a config file:

**Location**: `~/Library/Application Support/echonest-sync/config.yaml` (macOS), `~/.config/echonest-sync/config.yaml` (Linux), or `%APPDATA%\echonest-sync\config.yaml` (Windows)

Legacy path `~/.echonest-sync.yaml` is also supported.

```yaml
server: https://echone.st
drift_threshold: 3
```

Note: the token is stored securely in your system keychain (not in the config file).

## Environment Variables

| Variable | Maps To |
|----------|---------|
| `ECHONEST_SERVER` | `--server` |
| `ECHONEST_TOKEN` | `--token` |
| `ECHONEST_DRIFT_THRESHOLD` | `--drift-threshold` |

## Precedence

When the same setting is specified in multiple places, the highest-priority source wins:

1. CLI arguments (highest)
2. Environment variables
3. Config file
4. System keychain (lowest — token only)

## Examples

```bash
# First-time setup
echonest-sync login

# Check your setup
echonest-sync status

# Start syncing
echonest-sync

# Connect with debug logging
echonest-sync -v

# Override server for local dev
echonest-sync -s http://localhost:5001

# Use environment variables
export ECHONEST_SERVER=https://echone.st
export ECHONEST_TOKEN=YOUR_TOKEN
echonest-sync
```

## Account Linking

After logging in, link your Google account so songs you add appear under your name:

```
Visit https://echone.st/sync/link in your browser.
```

See [Account Linking](./account-linking.md) for details.

## Differences from the Desktop App

The CLI does not include:

- Tray icon or menu
- Onboarding dialog (use `echonest-sync login` instead)
- Search & Add songs
- Airhorn audio playback
- Autostart management
- Update checking

It does include the core sync features: playback control, drift correction, override detection, and automatic reconnection.
