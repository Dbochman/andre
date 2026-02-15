# Getting Started with EchoNest Sync

EchoNest Sync is a desktop app that keeps your local Spotify in sync with an EchoNest listening session. When someone adds a song or the queue advances, your Spotify plays along automatically — no browser tab required.

## What You Need

- **Spotify desktop app** installed and running (not the web player)
- **Spotify Premium** account (required for playback control)
- **macOS**, **Windows**, or **Linux**

### Platform-Specific Requirements

| Platform | Extra Requirements |
|----------|-------------------|
| macOS    | None — uses AppleScript to control Spotify |
| Linux    | `playerctl` — install with `sudo apt install playerctl` (or your distro's equivalent) |
| Windows  | Limited: can open tracks but cannot seek to the correct position |

## Installation

### Option 1: Download the App (Recommended)

Download the latest release for your platform from [GitHub Releases](https://github.com/Dbochman/EchoNest/releases):

- **macOS**: Download the `.dmg` file, open it, and drag **EchoNest Sync** to your Applications folder
- **Windows**: Download the `.exe` file and run it

#### macOS Gatekeeper Warning

Since the app isn't signed with an Apple Developer ID, macOS will show a warning on first launch. To clear it:

1. Right-click the app in Applications and choose **Open**, or
2. Run in Terminal: `xattr -cr "/Applications/EchoNest Sync.app"`

You only need to do this once.

### Option 2: Homebrew (macOS — CLI only)

```bash
brew tap dbochman/echonest
brew install echonest-sync
```

This installs the CLI sync agent (no tray icon). Set up with:

```bash
echonest-sync login
echonest-sync
```

For the desktop tray app, use Option 1 (.dmg) instead.

### Option 3: Install from Source

```bash
cd echonest-sync

# CLI only
pip install -e .

# Desktop app (macOS)
pip install -e ".[app,mac]"

# Desktop app (Windows / Linux)
pip install -e ".[app]"
```

Then launch with:

```bash
# Desktop tray app
echonest-sync-app

# Or CLI
echonest-sync login
echonest-sync
```

## First Launch

When you open EchoNest Sync for the first time:

1. An onboarding dialog appears and automatically connects to EchoNest — no invite code needed
2. Your API token is securely stored in your system keychain (macOS Keychain / Windows Credential Manager)
3. A tray icon appears in your menu bar (macOS) or system tray (Windows/Linux)
4. Sync starts immediately if a session is active

That's it — you're synced.

## Tray Icon

The tray icon shows your connection status at a glance:

| Icon | Meaning |
|------|---------|
| 🪺 Green nest with eggs | Connected and syncing |
| 🪹 Yellow/brown empty nest | Connected but paused (manual override or paused sync) |
| 🪹 Grey empty nest | Disconnected or connecting |

## Tray Menu

Click the tray icon to access the menu:

| Item | What It Does |
|------|-------------|
| **Status line** | Shows current state (Connected, Now Playing, Paused, etc.) |
| **Now playing track** | Click to bring Spotify to the front |
| **Up Next** | Submenu showing the upcoming queue (up to 15 tracks) |
| **Open EchoNest** | Opens echone.st in your browser |
| **Pause Sync / Resume Sync** | Temporarily stop or restart syncing |
| **Airhorns: On / Off** | Toggle airhorn sound effects |
| **Search & Add Song** | Search Spotify and add songs to the queue (requires linked account) |
| **Link Account** | Link your Google account for identity |
| **Check for Updates** | Check GitHub for new releases |
| **Start at Login** | Toggle whether the app launches on startup |
| **Quit** | Exit the app |

## Next Steps

- [Link your account](./account-linking.md) to add songs and show your avatar
- [Search and add songs](./features.md#search--add) directly from the tray
- [Enable autostart](./features.md#start-at-login) so you never miss a beat
- [Troubleshoot issues](./troubleshooting.md) if something isn't working
