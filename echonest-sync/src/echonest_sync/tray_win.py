"""Cross-platform tray app using pystray (Windows + Linux)."""

import json
import logging
import os
import threading
import time
import webbrowser

import pystray
from PIL import Image

from .autostart import disable_autostart, enable_autostart, is_autostart_enabled
from .updater import check_for_update_async, check_for_update, CURRENT_VERSION

log = logging.getLogger(__name__)


def _resource_path(name):
    """Resolve resource path — works in dev, pip install, and PyInstaller."""
    import sys
    candidates = []
    # PyInstaller bundle: resources are at _MEIPASS/resources/
    if getattr(sys, '_MEIPASS', None):
        candidates.append(os.path.join(sys._MEIPASS, "resources"))
    # Dev layout: echonest-sync/resources/
    candidates.append(os.path.join(os.path.dirname(os.path.dirname(
        os.path.dirname(__file__))), "..", "resources"))
    # Pip install layout
    candidates.append(os.path.join(os.path.dirname(__file__), "..", "..", "resources"))
    for d in candidates:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return name


def _load_icon(color):
    try:
        return Image.open(_resource_path(f"icon_{color}.png"))
    except Exception:
        # Fallback: generate a solid circle
        img = Image.new("RGBA", (22, 22), (0, 0, 0, 0))
        colors = {"green": (76, 175, 80), "yellow": (255, 193, 7), "grey": (158, 158, 158)}
        rgb = colors.get(color, (158, 158, 158))
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        draw.ellipse([2, 2, 20, 20], fill=(*rgb, 255))
        return img


class EchoNestSyncTray:
    def __init__(self, channel, server=None, token=None, email=None, player=None):
        self.channel = channel
        self._server = server
        self._token = token
        self._linked_email = email
        self._player = player  # local Spotify player for mini player controls

        # State
        self._sync_paused = False
        self._player_paused = False  # Server playback paused
        self._connected = False
        self._current_track = "No track"
        self._status_text = "Disconnected"
        self._running = True
        self._update_text = "Check for Updates"
        self._queue_tracks = []
        self._airhorn_enabled = True

        # Mini player subprocess
        self._miniplayer_proc = None
        self._miniplayer_state = {}  # buffered track/paused state

        self.icon = pystray.Icon("echonest-sync", _load_icon("grey"))
        self._build_menu()

    def _build_menu(self):
        self.icon.menu = pystray.Menu(
            pystray.MenuItem(
                lambda _: f"Status: {self._status_text}",
                None, enabled=False),
            pystray.MenuItem(
                lambda _: f"♪ {self._current_track}",
                self._focus_spotify),
            pystray.MenuItem("Up Next", pystray.Menu(
                lambda: self._queue_menu_items())),
            pystray.MenuItem("Open EchoNest", self._open_echonest),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda _: "Resume Sync" if self._sync_paused else "Pause Sync",
                self._toggle_pause),
            pystray.MenuItem("Mini Player", self._toggle_miniplayer,
                             checked=lambda _: self._miniplayer_proc is not None
                             and self._miniplayer_proc.poll() is None),
            pystray.MenuItem(
                lambda _: "Airhorns: Off (sync paused)" if self._sync_paused else f"Airhorns: {'On' if self._airhorn_enabled else 'Off'}",
                self._toggle_airhorn,
                enabled=lambda _: not self._sync_paused),
            pystray.MenuItem(
                lambda _: "Search & Add Song" if self._linked_email else "Search & Add Song (link account first)",
                self._open_search,
                enabled=lambda _: bool(self._linked_email)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda _: f"Linked: {self._linked_email}" if self._linked_email else "Link Account",
                self._open_link,
                enabled=lambda _: not self._linked_email),
            pystray.MenuItem(
                lambda _: self._update_text,
                self._check_updates),
            pystray.MenuItem("Start at Login", self._toggle_autostart,
                             checked=lambda _: is_autostart_enabled()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit),
        )

    def _focus_spotify(self):
        import platform
        import subprocess
        system = platform.system()
        if system == "Darwin":
            subprocess.Popen(["open", "-a", "Spotify"])
        elif system == "Windows":
            subprocess.Popen(["cmd", "/c", "start", "spotify:"], shell=True)
        else:
            subprocess.Popen(["xdg-open", "spotify:"])

    def _open_echonest(self):
        webbrowser.open("https://echone.st")

    def _toggle_pause(self):
        if self._sync_paused:
            self.channel.send_command("resume")
        else:
            self.channel.send_command("pause")

    def _check_updates(self):
        self._update_text = "Checking for updates..."
        result = check_for_update()
        if result["available"]:
            v = result["version"]
            self._update_text = f"Update available: v{v}"
            self._notify("Update Available", f"Version {v} is ready to download")
            webbrowser.open(result["download_url"])
        else:
            self._update_text = f"Up to date (v{CURRENT_VERSION})"
            self._notify("No Updates",
                         f"You're on the latest version (v{CURRENT_VERSION})")

    def _toggle_autostart(self):
        if is_autostart_enabled():
            disable_autostart()
        else:
            enable_autostart()

    def _queue_menu_items(self):
        """Generate submenu items for the Up Next queue."""
        if not self._queue_tracks:
            return [pystray.MenuItem("No upcoming tracks", None, enabled=False)]
        items = []
        for i, track in enumerate(self._queue_tracks[:15]):
            items.append(pystray.MenuItem(f"{i + 1}. {track}", None, enabled=False))
        if len(self._queue_tracks) > 15:
            items.append(pystray.MenuItem(
                f"  + {len(self._queue_tracks) - 15} more...", None, enabled=False))
        return items

    def _toggle_airhorn(self):
        self._airhorn_enabled = not self._airhorn_enabled
        self.channel.send_command("toggle_airhorn")

    def _open_search(self):
        if self._server and self._token:
            from .search import launch_search
            launch_search(self._server, self._token)

    def _refresh_status(self):
        """Update the status line to reflect connection + playback state."""
        if not self._connected:
            self._status_text = "Disconnected"
            return
        if self._sync_paused:
            self._status_text = "Connected - Sync Paused"
        elif self._player_paused:
            self._status_text = "Connected - Paused"
        elif self._current_track and self._current_track != "No track":
            self._status_text = "Connected - Now Playing"
        else:
            self._status_text = "Connected"

    def _update_icon(self, color):
        try:
            self.icon.icon = _load_icon(color)
        except Exception:
            pass

    def _notify(self, title, message):
        try:
            self.icon.notify(message, title)
        except Exception:
            pass

    def _poll_loop(self):
        """Background thread that polls IPC events."""
        while self._running:
            for event in self.channel.get_events():
                self._handle_event(event)
            self.icon.update_menu()
            time.sleep(1)

    def _handle_event(self, event):
        etype = event.type
        kw = event.kwargs

        if etype == "connected":
            was_connected = self._connected
            self._connected = True
            self._update_icon("green")
            self._refresh_status()
            self._miniplayer_state["status"] = "connected"
            self._mp_send({"type": "status", "status": "connected"})
            if was_connected:
                self._notify("EchoNest Sync", "Reconnected")
            else:
                self._notify("EchoNest Sync", "Connected to EchoNest")

        elif etype == "disconnected":
            self._connected = False
            self._update_icon("yellow")
            self._refresh_status()
            self._miniplayer_state["status"] = "disconnected"
            self._mp_send({"type": "status", "status": "disconnected"})

        elif etype == "track_changed":
            title = kw.get("title", "")
            artist = kw.get("artist", "")
            if title and artist:
                self._current_track = f"{title} - {artist}"
            elif title:
                self._current_track = title
            else:
                self._current_track = kw.get("uri", "Unknown")
            self._refresh_status()
            # Buffer + forward to mini player
            self._miniplayer_state["track"] = {
                "type": "track", "title": title, "artist": artist,
                "big_img": kw.get("big_img", ""),
                "duration": kw.get("duration", 0),
                "paused": self._player_paused,
            }
            self._mp_send(self._miniplayer_state["track"])

        elif etype == "status_changed":
            status = kw.get("status", "")
            if status == "paused":
                self._sync_paused = True
                self._update_icon("yellow")
            elif status == "syncing":
                self._sync_paused = False
                self._update_icon("green")
            elif status == "override":
                self._sync_paused = True
                self._update_icon("yellow")
                self._notify("EchoNest Sync",
                             "You took over — click to rejoin")
            elif status == "waiting":
                self._update_icon("grey")
            self._refresh_status()
            self._miniplayer_state["status"] = status
            self._mp_send({"type": "status", "status": status})

        elif etype == "player_paused":
            self._player_paused = kw.get("paused", False)
            self._refresh_status()
            self._miniplayer_state["paused"] = self._player_paused
            self._mp_send({"type": "paused", "paused": self._player_paused})

        elif etype == "player_position":
            self._mp_send({"type": "position", "pos": kw.get("pos", 0)})

        elif etype == "queue_updated":
            self._queue_tracks = kw.get("tracks", [])
            self._miniplayer_state["queue"] = self._queue_tracks
            self._mp_send({"type": "queue", "tracks": self._queue_tracks})

        elif etype == "airhorn_toggled":
            self._airhorn_enabled = kw.get("enabled", True)
            self._miniplayer_state["airhorn"] = self._airhorn_enabled
            self._mp_send({"type": "airhorn", "enabled": self._airhorn_enabled})

        elif etype == "airhorn":
            pass  # Sound played by sync engine

        elif etype == "account_linked":
            email = kw.get("email", "")
            user_token = kw.get("user_token", "")
            if email:
                self._linked_email = email
            if user_token:
                self._token = user_token

    def _open_link(self):
        if self._server and self._token and not self._linked_email:
            import webbrowser as wb
            wb.open(f"{self._server}/sync/link")
            from .link import launch_link

            def _on_linked(result):
                self.channel.emit("account_linked", email=result["email"],
                                  user_token=result.get("user_token", ""))

            launch_link(self._server, self._token, callback=_on_linked)

    # ------------------------------------------------------------------
    # Mini player subprocess
    # ------------------------------------------------------------------

    def _toggle_miniplayer(self):
        if self._miniplayer_proc and self._miniplayer_proc.poll() is None:
            self._mp_send({"type": "quit"})
            self._miniplayer_proc = None
        else:
            self._spawn_miniplayer()

    def _spawn_miniplayer(self):
        import subprocess
        import sys

        _is_frozen = getattr(sys, "frozen", False)
        try:
            if _is_frozen:
                cmd = [sys.executable, "--miniplayer"]
            else:
                cmd = [sys.executable, "-m", "echonest_sync.miniplayer"]
            # On Windows --windowed builds, the exe has subsystem=WINDOWS
            # which means child processes don't get stdin/stdout by default.
            # Pass CREATE_NO_WINDOW + startupinfo to ensure pipes work.
            kwargs = dict(
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if sys.platform == "win32":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESTDHANDLES
                kwargs["startupinfo"] = startupinfo
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            self._miniplayer_proc = subprocess.Popen(cmd, **kwargs)
            log.info("Mini player spawned (pid=%d)", self._miniplayer_proc.pid)

            # Send buffered state
            status = self._miniplayer_state.get("status", "disconnected")
            self._mp_send({"type": "status", "status": status})
            track = self._miniplayer_state.get("track")
            if track:
                self._mp_send(track)
            if "paused" in self._miniplayer_state:
                self._mp_send({"type": "paused", "paused": self._miniplayer_state["paused"]})
            queue = self._miniplayer_state.get("queue", [])
            if queue:
                self._mp_send({"type": "queue", "tracks": queue})
            self._mp_send({"type": "airhorn", "enabled": self._miniplayer_state.get("airhorn", True)})

            # Start stdout reader thread
            threading.Thread(
                target=self._mp_read_loop, daemon=True
            ).start()
        except Exception as e:
            log.error("Failed to spawn mini player: %s", e)
            self._miniplayer_proc = None

    def _mp_send(self, msg):
        """Send a JSON message to the mini player subprocess stdin."""
        proc = self._miniplayer_proc
        if proc is None or proc.poll() is not None:
            return
        try:
            data = json.dumps(msg) + "\n"
            proc.stdin.write(data.encode())
            proc.stdin.flush()
        except (BrokenPipeError, OSError):
            log.debug("Mini player pipe broken")
            self._miniplayer_proc = None

    def _mp_read_loop(self):
        """Read mini player stdout in a dedicated thread."""
        proc = self._miniplayer_proc
        if proc is None:
            return
        try:
            for line in proc.stdout:
                line = line.decode().strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if msg.get("type") == "closed":
                    self._miniplayer_proc = None
                    return
                elif msg.get("type") == "command":
                    cmd = msg.get("cmd", "")
                    if cmd == "toggle_airhorn":
                        self.channel.send_command("toggle_airhorn")
                    elif cmd == "pause":
                        self.channel.send_command("pause")
                    elif cmd == "resume":
                        self.channel.send_command("resume")
        except (OSError, ValueError):
            pass
        finally:
            if self._miniplayer_proc is proc:
                self._miniplayer_proc = None

    def _quit(self):
        # Shut down mini player if running
        if self._miniplayer_proc and self._miniplayer_proc.poll() is None:
            self._mp_send({"type": "quit"})
            try:
                self._miniplayer_proc.wait(timeout=2)
            except Exception:
                self._miniplayer_proc.kill()
            self._miniplayer_proc = None
        self.channel.send_command("quit")
        self._running = False
        self.icon.stop()

    def run(self):
        """Start the tray app (blocks on main thread)."""
        poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        poll_thread.start()
        self.icon.run()
