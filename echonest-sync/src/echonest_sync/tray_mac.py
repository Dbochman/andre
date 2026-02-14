"""macOS tray app using rumps."""

import logging
import os
import time

import rumps

from .autostart import disable_autostart, enable_autostart, is_autostart_enabled

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
    return name  # Fallback


class EchoNestSync(rumps.App):
    def __init__(self, channel, restart_callback=None):
        super().__init__("EchoNest", icon=_resource_path("icon_grey.png"),
                         template=False, quit_button=None)
        self.channel = channel
        self.restart_callback = restart_callback

        # State
        self._sync_paused = False
        self._connected = False
        self._last_disconnect = 0
        self._current_track = "No track"

        # Menu items
        self.status_item = rumps.MenuItem("Status: Starting...", callback=None)
        self.track_item = rumps.MenuItem("No track", callback=None)
        self.pause_item = rumps.MenuItem("Pause Sync", callback=self.toggle_pause)
        self.snooze_item = rumps.MenuItem("Snooze 15 min", callback=self.snooze)
        self.autostart_item = rumps.MenuItem("Start at Login",
                                             callback=self.toggle_autostart)
        self.forget_item = rumps.MenuItem("Forget Server...",
                                          callback=self.forget)

        self.quit_item = rumps.MenuItem("Quit EchoNest Sync", callback=self.quit_app)

        self.menu = [
            self.status_item,
            self.track_item,
            None,  # separator
            self.pause_item,
            self.snooze_item,
            None,
            self.autostart_item,
            self.forget_item,
            None,
            self.quit_item,
        ]

        # Set initial autostart checkmark
        self.autostart_item.state = is_autostart_enabled()

    @rumps.timer(1)
    def poll_events(self, _):
        """Poll IPC events from the sync engine."""
        for event in self.channel.get_events():
            self._handle_event(event)

    def _handle_event(self, event):
        etype = event.type
        kw = event.kwargs

        if etype == "connected":
            was_connected = self._connected
            self._connected = True
            self._update_icon("green")
            self.status_item.title = "Status: In Sync"
            if was_connected:
                rumps.notification("EchoNest Sync", "", "Reconnected",
                                   sound=False)
            else:
                rumps.notification("EchoNest Sync", "", "Connected to EchoNest",
                                   sound=False)

        elif etype == "disconnected":
            self._connected = False
            self._last_disconnect = time.time()
            # Show yellow after 30s, but update status immediately
            self.status_item.title = "Status: Reconnecting..."
            self._update_icon("yellow")
            reason = kw.get("reason", "")
            if reason == "auth_failed":
                rumps.notification("EchoNest Sync", "",
                                   "Authentication failed", sound=False)

        elif etype == "track_changed":
            title = kw.get("title", "")
            artist = kw.get("artist", "")
            if title and artist:
                self._current_track = f"{title} - {artist}"
            elif title:
                self._current_track = title
            else:
                self._current_track = kw.get("uri", "Unknown")
            self.track_item.title = f"♪ {self._current_track}"

        elif etype == "status_changed":
            status = kw.get("status", "")
            if status == "paused":
                self._sync_paused = True
                self.status_item.title = "Status: Paused"
                self.pause_item.title = "Resume Sync"
                self._update_icon("grey")
            elif status == "snoozed":
                self._sync_paused = True
                until = kw.get("until", 0)
                mins = max(1, int((until - time.time()) / 60))
                self.status_item.title = f"Status: Snoozed ({mins}m)"
                self.pause_item.title = "Resume Sync"
                self._update_icon("grey")
            elif status == "syncing":
                self._sync_paused = False
                self.status_item.title = "Status: In Sync"
                self.pause_item.title = "Pause Sync"
                self._update_icon("green")
            elif status == "override":
                self._sync_paused = True
                self.status_item.title = "Status: Manual playback"
                self.pause_item.title = "Resume Sync"
                self._update_icon("grey")
                rumps.notification("EchoNest Sync", "",
                                   "You took over — click to rejoin",
                                   sound=False)
            elif status == "waiting":
                self.status_item.title = "Status: Waiting for Spotify..."
                self._update_icon("grey")

        elif etype == "user_override":
            pass  # Handled via status_changed

    def _update_icon(self, color):
        try:
            self.icon = _resource_path(f"icon_{color}.png")
        except Exception:
            pass

    def toggle_pause(self, _):
        if self._sync_paused:
            self.channel.send_command("resume")
        else:
            self.channel.send_command("pause")

    def snooze(self, _):
        self.channel.send_command("snooze", duration=900)

    def toggle_autostart(self, _):
        if is_autostart_enabled():
            disable_autostart()
            self.autostart_item.state = False
        else:
            enable_autostart()
            self.autostart_item.state = True

    def forget(self, _):
        if rumps.alert("Forget Server?",
                       "This will disconnect and clear your credentials.",
                       ok="Forget", cancel="Cancel"):
            self.channel.send_command("quit")
            from .config import delete_token
            delete_token()
            if self.restart_callback:
                self.restart_callback()
            else:
                rumps.quit_application()

    def quit_app(self, _):
        self.channel.send_command("quit")
        rumps.quit_application()
