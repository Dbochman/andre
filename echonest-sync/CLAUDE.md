# echonest-sync

Desktop sync client for EchoNest. Syncs local Spotify playback to an EchoNest server via SSE events and OS-level automation (AppleScript/playerctl).

## Commands

```bash
# Install via Homebrew (macOS)
brew tap dbochman/echonest && brew install echonest-sync

# Install in dev mode (macOS)
pip install -e ".[mac]"

# Run desktop app
echonest-sync-app

# Run CLI
echonest-sync --server https://echone.st --token YOUR_TOKEN

# Run tests
SKIP_SPOTIFY_PREFETCH=1 python3 -m pytest tests/ -v
```

## Building

### macOS (.app + DMG)

Must use system Python (`/usr/local/bin/python3`), NOT Xcode Python.

```bash
cd echonest-sync

# 1. Build the .app bundle
/usr/local/bin/python3 build/macos/build_app.py

# 2. Build the DMG installer
/usr/local/bin/python3 build/macos/build_dmg.py

# Output: dist/EchoNest-Sync.dmg
```

**Rebuilding**: The codesigned `.app` has immutable files. You must `sudo rm -rf "dist/EchoNest Sync.app"` before rebuilding.

**Installing locally**: Open the DMG, drag to Applications, then clear quarantine:
```bash
xattr -cr "/Applications/EchoNest Sync.app"
```

### Windows (.exe)

```bash
cd echonest-sync
pip install pyinstaller
python build/windows/build_exe.py
# Output: dist/EchoNest Sync.exe
```

## Key Gotchas

- **`sys.executable` in PyInstaller**: Points to the frozen binary, NOT Python. Never pass `-m module` args to it. Use `getattr(sys, 'frozen', False)` to detect.
- **Codesign required for Keychain**: PyInstaller bundle must be ad-hoc signed or macOS Keychain rejects `keyring.set_password()`. The build script handles this automatically.
- **tkinter + rumps**: Cannot create `Tk()` when rumps owns the main thread (segfault). Use native `NSAlert` with `setAccessoryView_()` for input dialogs on macOS.
- **config DEFAULTS**: `load_config()` only reads keys present in the `DEFAULTS` dict. New config keys must be added there or they're silently dropped.
- **DMG stuck eject**: Spotlight can hold DMG volumes open. The build script adds `.metadata_never_index` and uses `-nobrowse` mount flag to prevent this.
- **Port 5000**: macOS AirPlay Receiver uses port 5000. Use port 5001 for local dev.
- **rumps quirks**: Use `quit_button=None` (rumps adds its own), `template=False` (preserves icon colors), `NSAlert` for custom dialog icons (rumps.alert uses Python rocket).

## Architecture

| File | Purpose |
|------|---------|
| `sync.py` | Core SSE listener, play/seek/pause via OS automation, override detection |
| `app.py` | Desktop launcher: keyring check → onboarding → engine thread → tray |
| `tray_mac.py` | rumps menu bar app (macOS), polls IPC events every 1s |
| `tray_win.py` | pystray tray app (Windows + Linux) |
| `config.py` | OS config dirs, keyring, save_config (strips secrets), logging |
| `ipc.py` | Thread-safe command/event queues between GUI and engine |
| `onboarding.py` | tkinter dialog, invite code → `POST /api/sync-token` |
| `link.py` | Account linking dialog (NSAlert on macOS, tkinter elsewhere) |
| `search.py` | Spotify search & add dialog (tkinter) |
| `audio.py` | Cross-platform airhorn audio caching and playback |
| `autostart.py` | LaunchAgent (macOS) / Startup folder (Windows) / XDG .desktop (Linux) |
| `updater.py` | GitHub Releases API update checker (`sync-v*` tags) |
| `player.py` | Platform player abstraction (AppleScript/playerctl/startfile) |
