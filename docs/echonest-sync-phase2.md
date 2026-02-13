# echonest-sync Phase 2: Desktop App

## Overview

Wrap the Phase 1 CLI sync engine in a native desktop tray app with one-click onboarding. Target: download → first sync in under 60 seconds, no terminal required.

**Framework**: rumps (macOS) + pystray (Windows) + tkinter onboarding dialog. Pure Python — imports the sync engine module directly.

## Package Structure

```
echonest-sync/
├── src/
│   └── echonest_sync/
│       ├── __init__.py
│       ├── cli.py                # Phase 1 (unchanged)
│       ├── sync.py               # Phase 1 engine (enhanced with command channel)
│       ├── player.py             # Phase 1 (unchanged)
│       ├── config.py             # Phase 1 (enhanced with keyring + config dir)
│       ├── tray_mac.py           # macOS tray app (rumps)
│       ├── tray_win.py           # Windows tray app (pystray + pillow)
│       ├── app.py                # Launcher: keyring check → onboarding subprocess → tray
│       ├── onboarding.py         # tkinter setup wizard (runs as separate process)
│       ├── ipc.py                # Thread-safe command/event channel
│       └── autostart.py          # LaunchAgent / Startup folder management
├── resources/
│   ├── icon_green.png            # Synced
│   ├── icon_yellow.png           # Reconnecting
│   ├── icon_grey.png             # Idle / snoozed
│   └── icon.icns                 # macOS app icon
├── build/
│   ├── macos/
│   │   ├── build_app.py          # PyInstaller spec for .app bundle
│   │   └── Info.plist
│   └── windows/
│       └── build_exe.py          # PyInstaller spec for .exe
├── tests/
│   ├── test_sync.py              # Phase 1 (unchanged)
│   ├── test_ipc.py               # IPC command/event tests
│   ├── test_onboarding.py        # Token exchange tests (mocked HTTP)
│   ├── test_snooze.py            # Snooze timer tests
│   └── test_autostart.py         # LaunchAgent/Startup tests
├── pyproject.toml
└── README.md
```

## 1. Server-Side: Invite Code → Token Exchange

**New endpoint**: `POST /api/sync-token`

```
Request:  { "invite_code": "futureofmusic" }
Response: { "token": "<bearer-token>", "server": "https://echone.st" }
Error:    { "error": "invalid_code" }, 401
```

Implementation in `app.py`:
- Config: `SYNC_INVITE_CODES` list in `local_config.yaml` (default: `["futureofmusic"]`)
- On valid code: return the existing `ECHONEST_API_TOKEN` (all sync clients share the same read-only token)
- Rate limit: 10 attempts per IP per hour (Redis counter)
- No auth decorator — the invite code IS the auth

## 2. Onboarding Dialog (`onboarding.py`)

tkinter window (~300x200px):

```
┌─────────────────────────────┐
│  🎵 EchoNest Sync Setup    │
│                             │
│  Invite code:               │
│  [futureofmusic________]    │
│                             │
│  [Connect]                  │
│                             │
│  Status: Ready              │
└─────────────────────────────┘
```

Flow:
1. Text field prefilled with `futureofmusic` (editable)
2. On "Connect": POST to `/api/sync-token`
3. On success: store token via keyring (see Security) **and persist the `server` URL from the response to `config.yaml`** via `save_config()`, show "Connected!", close after 2s
4. On failure: show error inline (see status label lifecycle below), stay open
5. Detect Spotify: if not running, show "Spotify not detected — start it for audio sync" (non-blocking warning, not a gate)
6. On success: exit process with code 0; parent process reads token from keyring, starts tray app

### Status Label Lifecycle

The status label updates in-place within the dialog to reflect the current state:

| State | Text | Color | Trigger |
|---|---|---|---|
| Initial | `"Ready"` | default | Dialog opens |
| Connecting | `"Connecting..."` | default | Connect clicked (button disabled) |
| Success | `"Connected!"` | green | 200 response; auto-close after 2s |
| Invalid code | `"Invalid invite code"` | red | 401 response; button re-enabled |
| Rate limited | `"Too many attempts. Try again later."` | red | 429 response; button re-enabled |
| Unreachable | `"Could not reach server"` | red | Connection error; button re-enabled |
| Server error | `"Server error (NNN)"` | red | Other HTTP errors; button re-enabled |
| Spotify warning | `"Start Spotify for audio sync"` | orange | Non-blocking; Spotify not detected |

Shown on first launch (no config found) or after "Forget Server".

**Event loop isolation**: Onboarding runs as a **separate subprocess** (`subprocess.run([sys.executable, "-m", "echonest_sync.onboarding"])`), not a thread. This avoids conflicts between tkinter's event loop and rumps/pystray's Cocoa/Win32 run loop — both require the main thread. The onboarding process writes to keyring and exits; the parent process then starts the tray app with exclusive main-thread ownership.

"Forget Server" follows the same pattern: tray app clears keyring, stops the engine, then re-launches itself (which hits the "no token" path and spawns onboarding).

## 3. IPC Channel (`ipc.py`)

Thread-safe communication between tray GUI (main thread) and sync engine (background thread).

```python
class SyncChannel:
    """Bidirectional channel between GUI and engine."""

    # GUI → Engine commands
    def send_command(self, cmd: str, **kwargs):
        """Commands: 'pause', 'resume', 'snooze', 'forget', 'quit'"""

    # Engine → GUI events
    def get_events(self) -> list[dict]:
        """Events: 'connected', 'disconnected', 'track_changed',
                   'status_changed', 'user_override'"""
```

Implementation: two `queue.Queue` instances (commands, events). No sockets, no pipes — just thread queues since engine runs in-process.

## 4. Engine Enhancements (`sync.py`)

### 4a. Command Channel Integration

Modify `SyncAgent.run()` to check command queue between SSE events:

```python
# In the SSE event loop, after processing each event:
while not self.channel.commands.empty():
    cmd = self.channel.commands.get_nowait()
    if cmd.type == 'pause':
        self._sync_paused = True
    elif cmd.type == 'resume':
        self._sync_paused = False
        self._initial_sync()  # re-sync on resume
    elif cmd.type == 'snooze':
        self._snoozed_until = time.time() + cmd.duration
    elif cmd.type == 'quit':
        return
```

When `_sync_paused` or snoozed: engine stays connected to SSE (maintains state awareness) but skips all `player.*` calls.

### 4b. Manual Playback Detection

New method `_check_user_override()`, called every 5 seconds:

```python
def _check_user_override(self):
    if not self.current_track_uri:
        return
    local_track = self.player.get_current_track()
    if not local_track:
        # Player can't report current track (e.g. WindowsPlayer) — skip detection
        return
    if local_track != self.current_track_uri:
        self._override_count += 1
        if self._override_count >= 2:  # 10s of mismatch
            self.channel.emit('user_override', track=local_track)
            self._sync_paused = True  # auto-pause until user decides
    else:
        self._override_count = 0
```

**Windows limitation**: `WindowsPlayer.get_current_track()` returns `None`, so manual playback detection is silently disabled. This is acceptable — Windows already lacks seek support, so the sync experience is best-effort. Documented in README under "Platform Support".

### 4c. Spotify Process Watching

When `player.is_running()` returns False:
- Engine enters idle state (no SSE connection)
- Polls `is_running()` every 15 seconds
- On detection: connect SSE, initial sync, emit 'connected'

## 5. Tray App

### macOS (`tray_mac.py`) — rumps

```python
import rumps

class EchoNestSync(rumps.App):
    def __init__(self, channel):
        super().__init__("EchoNest", icon="resources/icon_green.png")
        self.channel = channel
        self.menu = [
            rumps.MenuItem("Status: In Sync", callback=None),
            rumps.MenuItem("♪ No track", callback=None),
            None,  # separator
            rumps.MenuItem("Pause Sync", callback=self.toggle_pause),
            rumps.MenuItem("Snooze 15 min", callback=self.snooze),
            None,
            rumps.MenuItem("Start at Login", callback=self.toggle_autostart),
            rumps.MenuItem("Forget Server…", callback=self.forget),
        ]

    @rumps.timer(1)
    def poll_events(self, _):
        for event in self.channel.get_events():
            self._handle_event(event)
```

### Windows (`tray_win.py`) — pystray

Same menu structure, different API:

```python
import pystray
from PIL import Image

def create_tray(channel):
    icon = pystray.Icon("echonest-sync", Image.open("resources/icon_green.png"))
    icon.menu = pystray.Menu(
        pystray.MenuItem("Status: In Sync", None, enabled=False),
        pystray.MenuItem("♪ No track", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Pause Sync", lambda: channel.send_command("pause")),
        pystray.MenuItem("Snooze 15 min", lambda: channel.send_command("snooze", duration=900)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Start at Login", toggle_autostart, checked=lambda _: is_autostart()),
        pystray.MenuItem("Forget Server…", forget_server),
        pystray.MenuItem("Quit", lambda: channel.send_command("quit")),
    )
    icon.run()
```

### Tray State Machine

| Engine event | Icon | Status text | Notification |
|---|---|---|---|
| `connected` (first time) | green | "In Sync" | "Connected to EchoNest" |
| `connected` (reconnect) | green | "In Sync" | "Reconnected" |
| `disconnected` (>30s) | yellow | "Reconnecting..." | "Connection lost" |
| `track_changed` | green | "♪ {title} - {artist}" | (none) |
| `user_override` | grey | "Manual playback" | "You took over — click to rejoin" |
| Pause/Snooze | grey | "Paused" / "Snoozed until {time}" | (none) |
| Spotify not running | grey | "Waiting for Spotify..." | (none) |

## 6. Config Enhancements (`config.py`)

### Config Directory

Move from single `~/.echonest-sync.yaml` to a proper config dir:

```
~/.config/echonest-sync/          # Linux/macOS XDG
~/Library/Application Support/echonest-sync/  # macOS alternative
%APPDATA%/echonest-sync/          # Windows

Contents:
  config.yaml       # server URL, preferences (autostart, snooze prefs)
  sync.log          # rotating log (see Telemetry)
```

Token stored via `keyring` library (macOS Keychain / Windows DPAPI / SecretService on Linux), NOT in the yaml file.

### Config Schema

```yaml
server: https://echone.st
autostart: true
notifications: true
# token NOT stored here — lives in OS keychain
```

## 7. Autostart (`autostart.py`)

### macOS — LaunchAgent

Write/remove `~/Library/LaunchAgents/st.echone.sync.plist`:

```xml
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>st.echone.sync</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Applications/EchoNest Sync.app/Contents/MacOS/echonest-sync</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>
```

### Windows — Startup Folder

Create/remove shortcut in `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\`.

## 8. Notifications

Use `rumps.notification()` on macOS, `plyer` or `win10toast` on Windows.

Rules:
- On first connect: "Connected to EchoNest"
- On connection lost (after 30s of retries): "Connection lost — retrying..."
- On reconnect: "Reconnected"
- On user override: "You took over Spotify — click to rejoin"
- NEVER on track changes

## 9. Security

| Concern | Approach |
|---|---|
| Token storage | `keyring` library → macOS Keychain / Windows DPAPI |
| Invite code | Discarded after exchange; never persisted |
| HTTPS | `requests` verifies certs by default; reject self-signed |
| Process env | Engine thread inherits minimal env; no proxy vars forwarded |
| Config file | Contains server URL + prefs only; no secrets |

## 10. Packaging & Distribution

### macOS

1. PyInstaller → `.app` bundle (universal2 for Intel + Apple Silicon)
2. `Info.plist` with LSUIElement=true (no dock icon, tray-only)
3. Code sign with Developer ID
4. Notarize via `xcrun notarytool`
5. Wrap in `.dmg` with drag-to-Applications layout
6. Host on GitHub Releases

### Windows

1. PyInstaller → single `.exe` (onefile mode)
2. Package as MSI via WiX or NSIS
3. Sign with Authenticode certificate (or skip for now, accept SmartScreen warning)
4. Host on GitHub Releases

### Size Budget

| Component | Est. size |
|---|---|
| Python runtime (embedded) | ~12MB |
| Dependencies (requests, sseclient, click, pyyaml, rumps/pystray, keyring) | ~3MB |
| App code + resources | <1MB |
| **Total** | **~15-20MB** |

## 11. Logging

Rotating file log at `{config_dir}/sync.log`:
- Max 1MB, 3 rotations
- Logs: sync status changes, token fetch outcome (no token value), connection events, errors
- Debug level available via config toggle

## 12. Testing Plan

### Unit Tests (pytest, no GUI)

| Test file | Coverage |
|---|---|
| `test_ipc.py` | Command/event queue threading, command types |
| `test_onboarding.py` | Token exchange (mocked HTTP), error handling, prefill |
| `test_snooze.py` | Snooze timer, expiry, resume behavior |
| `test_autostart.py` | LaunchAgent plist write/remove, Startup shortcut |
| `test_override.py` | Manual playback detection, threshold, auto-pause |

### Integration Tests

- Simulated onboarding flow with mock server (Flask test server)
- Engine start → snooze → resume cycle
- Forget server → re-onboard cycle

### Manual QA Checklist

- [ ] Fresh install (no config) → onboarding dialog appears
- [ ] Valid invite code → connects, tray icon green
- [ ] Invalid invite code → error shown, stays on dialog
- [ ] Server unreachable → error shown, retry possible
- [ ] Spotify not running → grey icon, "Waiting for Spotify..."
- [ ] Spotify opens → auto-connects, green icon
- [ ] Track change on server → local Spotify follows
- [ ] Pause on server → local Spotify pauses
- [ ] Manual track change → "user override" prompt after 10s
- [ ] Snooze 15 min → grey icon, resumes after expiry
- [ ] Pause Sync → grey icon, no player control
- [ ] Resume Sync → re-syncs immediately
- [ ] Forget Server → config cleared, onboarding reappears
- [ ] Start at Login → LaunchAgent/Startup entry created
- [ ] Quit → clean shutdown, no orphan processes
- [ ] Network drop → yellow icon after 30s, auto-reconnect

## 13. Implementation Phases

### Phase 2a: Engine Enhancements
- IPC channel (`ipc.py`)
- Command handling in `sync.py` (pause, resume, snooze, quit)
- Manual playback detection
- Spotify process watching
- Config dir migration + keyring integration
- Tests for all of the above

### Phase 2b: Server Token Endpoint
- `POST /api/sync-token` in `app.py`
- Invite code config in `local_config.yaml`
- Rate limiting

### Phase 2c: Tray App + Onboarding
- `onboarding.py` (tkinter dialog)
- `tray_mac.py` (rumps)
- `tray_win.py` (pystray)
- `autostart.py`
- Notifications
- Icon assets

### Phase 2d: Packaging
- PyInstaller specs for macOS + Windows
- CI pipeline (GitHub Actions)
- Code signing (macOS)
- Distribution (.dmg, .exe on GitHub Releases)

## Open Items

- **Auto-update**: Not in Phase 2. For 5-50 users, "check GitHub Releases" + tray menu "Update available" badge is sufficient. Full auto-update (Sparkle/WinSparkle) is Phase 3.
- **Telemetry**: Deferred. Logging is sufficient for this user base.
- **Linux tray**: pystray works on Linux via AppIndicator, but packaging (AppImage/Flatpak) is a separate effort. CLI remains the primary Linux interface for now.
