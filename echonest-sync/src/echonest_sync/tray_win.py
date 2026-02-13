"""Windows tray app using pystray."""

import logging
import os
import threading
import time

import pystray
from PIL import Image

from .autostart import disable_autostart, enable_autostart, is_autostart_enabled

log = logging.getLogger(__name__)


def _resource_path(name):
    """Resolve resource path relative to package."""
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                        "..", "resources")
    alt = os.path.join(os.path.dirname(__file__), "..", "..", "resources")
    for d in (base, alt):
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
    def __init__(self, channel, restart_callback=None):
        self.channel = channel
        self.restart_callback = restart_callback

        # State
        self._sync_paused = False
        self._connected = False
        self._current_track = "No track"
        self._status_text = "Starting..."
        self._running = True

        self.icon = pystray.Icon("echonest-sync", _load_icon("grey"))
        self._build_menu()

    def _build_menu(self):
        self.icon.menu = pystray.Menu(
            pystray.MenuItem(
                lambda _: f"Status: {self._status_text}",
                None, enabled=False),
            pystray.MenuItem(
                lambda _: f"♪ {self._current_track}",
                None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda _: "Resume Sync" if self._sync_paused else "Pause Sync",
                self._toggle_pause),
            pystray.MenuItem("Snooze 15 min", self._snooze),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Start at Login", self._toggle_autostart,
                             checked=lambda _: is_autostart_enabled()),
            pystray.MenuItem("Forget Server...", self._forget),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit),
        )

    def _toggle_pause(self):
        if self._sync_paused:
            self.channel.send_command("resume")
        else:
            self.channel.send_command("pause")

    def _snooze(self):
        self.channel.send_command("snooze", duration=900)

    def _toggle_autostart(self):
        if is_autostart_enabled():
            disable_autostart()
        else:
            enable_autostart()

    def _forget(self):
        self.channel.send_command("quit")
        from .config import delete_token
        delete_token()
        self.icon.stop()
        if self.restart_callback:
            self.restart_callback()

    def _quit(self):
        self.channel.send_command("quit")
        self._running = False
        self.icon.stop()

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
            self._status_text = "In Sync"
            if was_connected:
                self._notify("EchoNest Sync", "Reconnected")
            else:
                self._notify("EchoNest Sync", "Connected to EchoNest")

        elif etype == "disconnected":
            self._connected = False
            self._status_text = "Reconnecting..."
            self._update_icon("yellow")

        elif etype == "track_changed":
            title = kw.get("title", "")
            artist = kw.get("artist", "")
            if title and artist:
                self._current_track = f"{title} - {artist}"
            elif title:
                self._current_track = title
            else:
                self._current_track = kw.get("uri", "Unknown")

        elif etype == "status_changed":
            status = kw.get("status", "")
            if status == "paused":
                self._sync_paused = True
                self._status_text = "Paused"
                self._update_icon("grey")
            elif status == "snoozed":
                self._sync_paused = True
                until = kw.get("until", 0)
                mins = max(1, int((until - time.time()) / 60))
                self._status_text = f"Snoozed ({mins}m)"
                self._update_icon("grey")
            elif status == "syncing":
                self._sync_paused = False
                self._status_text = "In Sync"
                self._update_icon("green")
            elif status == "override":
                self._sync_paused = True
                self._status_text = "Manual playback"
                self._update_icon("grey")
                self._notify("EchoNest Sync",
                             "You took over — click to rejoin")
            elif status == "waiting":
                self._status_text = "Waiting for Spotify..."
                self._update_icon("grey")

    def run(self):
        """Start the tray app (blocks on main thread)."""
        poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        poll_thread.start()
        self.icon.run()
