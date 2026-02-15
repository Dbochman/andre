# Features

## Playback Sync

The core feature: your local Spotify plays the same track at the same position as the EchoNest session. The app:

- Starts playing when a new track begins on the server
- Seeks to the correct position if you join mid-track
- Corrects drift if your playback gets more than 3 seconds out of sync
- Pauses and resumes automatically when the session does
- Reconnects with exponential backoff if the connection drops

### Override Detection

If you manually change the track in Spotify (skip, search for something else, etc.), the app detects this and automatically pauses sync. This prevents the app from fighting your manual control. To resume, click **Resume Sync** in the tray menu.

There's a 15-second grace period after each track change to let Spotify load — the app won't flag normal transitions as overrides.

## Mini Player

A floating always-on-top mini player window showing the current track, album art, and a live progress bar. Toggle it from the **Mini Player** item in the tray menu.

### What It Shows

- **Album art** (cached locally for fast loading)
- **Track title and artist**
- **Progress bar** with elapsed/total time (interpolated at 250ms for smooth updates)
- **Status dot** — green (syncing), yellow (paused/override), grey (disconnected)
- **Up next** — the next track in the queue

### Controls

| Control | Action |
|---------|--------|
| **Play/Pause icon** | Click to pause sync (stops local Spotify) or resume sync |
| **Airhorns indicator** | Click to toggle airhorn sounds on/off |
| **Close button** (✕) | Close the mini player |
| **Drag anywhere** | Move the window — position is remembered between sessions |

When paused, the time display blinks to indicate playback is stopped.

## Search & Add

Search Spotify and add songs directly to the EchoNest queue without opening a browser.

**Requires**: [Linked account](./account-linking.md)

### How to Use

1. Click **Search & Add Song** in the tray menu
2. Type an artist, song name, or both in the search bar
3. Press Enter or click Search
4. Double-click a result (or select it and click **Add to Queue**)
5. A confirmation appears and the song is added to the queue

The search dialog stays open so you can add multiple songs. Close it when you're done.

## Airhorns

When someone triggers an airhorn in the EchoNest web app, the sound plays through your speakers too.

Toggle this on or off with **Airhorns: On / Off** in the tray menu. Airhorn audio files are cached locally after the first play.

### Audio Playback by Platform

| Platform | Method |
|----------|--------|
| macOS | `afplay` (built-in) |
| Linux | PulseAudio (`paplay`) with `aplay` fallback |
| Windows | `ffplay` or `mpv` if installed, falls back to `winsound` for WAV files |

## Up Next Queue

The **Up Next** submenu shows the upcoming tracks in the queue (up to 15). This updates in real time as songs are added, removed, or reordered.

## Start at Login

Toggle **Start at Login** in the tray menu to have EchoNest Sync launch automatically when you log in.

### How It Works by Platform

| Platform | Mechanism |
|----------|-----------|
| macOS | LaunchAgent plist in `~/Library/LaunchAgents/` |
| Windows | Shortcut in the Startup folder |
| Linux | `.desktop` file in `~/.config/autostart/` |

The checkmark on the menu item reflects the current state. Toggling it on creates the autostart entry; toggling it off removes it.

## Check for Updates

Click **Check for Updates** to check GitHub for new releases. If an update is available:

- The menu item changes to **Update available: vX.Y.Z**
- Clicking it opens the download page in your browser

If you're already on the latest version, it shows **Up to date (vX.Y.Z)**.

## Open EchoNest

Opens [echone.st](https://echone.st) in your default browser — useful for voting, viewing the full queue, or managing the session.
