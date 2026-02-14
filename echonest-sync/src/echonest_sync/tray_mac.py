"""macOS tray app using rumps."""

import logging
import os
import time
import webbrowser

import rumps

from .autostart import disable_autostart, enable_autostart, is_autostart_enabled
from .updater import check_for_update, CURRENT_VERSION

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
    def __init__(self, channel, server=None, token=None):
        super().__init__("EchoNest", icon=_resource_path("icon_grey.png"),
                         template=False, quit_button=None)
        self.channel = channel
        self._server = server
        self._token = token

        # State
        self._sync_paused = False
        self._connected = False
        self._last_disconnect = 0
        self._current_track = "No track"
        self._airhorn_enabled = True
        self._devices = []  # list of {id, name, is_active}

        # Menu items
        self.status_item = rumps.MenuItem("Disconnected", callback=None)
        self.track_item = rumps.MenuItem("No track", callback=self.focus_spotify)
        self.queue_item = rumps.MenuItem("Up Next")
        self.queue_item.add(rumps.MenuItem("No upcoming tracks", callback=None))
        self.airhorn_item = rumps.MenuItem("Airhorns: On", callback=self.toggle_airhorn)
        self.devices_item = rumps.MenuItem("Spotify Devices")
        self.devices_item.add(rumps.MenuItem("Click to refresh", callback=self.refresh_devices))
        self.search_item = rumps.MenuItem("Search & Add Song", callback=self.open_search)
        self.pause_item = rumps.MenuItem("Pause Sync", callback=self.toggle_pause)
        self.open_item = rumps.MenuItem("Open EchoNest", callback=self.open_echonest)
        self.update_item = rumps.MenuItem("Check for Updates", callback=self.check_updates)
        self.autostart_item = rumps.MenuItem("Start at Login",
                                             callback=self.toggle_autostart)
        self.quit_item = rumps.MenuItem("Quit EchoNest Sync", callback=self.quit_app)

        self.menu = [
            self.status_item,
            self.track_item,
            self.queue_item,
            None,  # separator
            self.open_item,
            self.airhorn_item,
            self.devices_item,
            self.search_item,
            self.pause_item,
            None,
            self.update_item,
            self.autostart_item,
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
            self._refresh_status()
            if was_connected:
                rumps.notification("EchoNest Sync", "", "Reconnected",
                                   sound=False)
            else:
                rumps.notification("EchoNest Sync", "", "Connected to EchoNest",
                                   sound=False)

        elif etype == "disconnected":
            self._connected = False
            self._last_disconnect = time.time()
            self._update_icon("yellow")
            self._refresh_status()
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
            self._refresh_status()

        elif etype == "status_changed":
            status = kw.get("status", "")
            if status == "paused":
                self._sync_paused = True
                self.pause_item.title = "Resume Sync"
                self._update_icon("yellow")
            elif status == "syncing":
                self._sync_paused = False
                self.pause_item.title = "Pause Sync"
                self._update_icon("green")
            elif status == "override":
                self._sync_paused = True
                self.pause_item.title = "Resume Sync"
                self._update_icon("yellow")
                rumps.notification("EchoNest Sync", "",
                                   "You took over — click to rejoin",
                                   sound=False)
            elif status == "waiting":
                self._update_icon("grey")
            self._refresh_status()

        elif etype == "queue_updated":
            tracks = kw.get("tracks", [])
            self._update_queue(tracks)

        elif etype == "user_override":
            pass  # Handled via status_changed

        elif etype == "airhorn_toggled":
            self._airhorn_enabled = kw.get("enabled", True)
            self.airhorn_item.title = f"Airhorns: {'On' if self._airhorn_enabled else 'Off'}"

        elif etype == "airhorn":
            pass  # Sound played by sync engine

        elif etype == "devices_updated":
            self._devices = kw.get("devices", [])
            self._update_devices_menu()

        elif etype == "transfer_complete":
            self.channel.send_command("fetch_devices")

        elif etype == "transfer_failed":
            error = kw.get("error", "Unknown error")
            rumps.notification("EchoNest Sync", "", f"Transfer failed: {error}",
                               sound=False)

    def _refresh_status(self):
        """Update the status line to reflect connection + playback state."""
        if not self._connected:
            self.status_item.title = "Disconnected"
            return
        if self._sync_paused:
            self.status_item.title = "Connected - Paused"
        elif self._current_track and self._current_track != "No track":
            self.status_item.title = f"Connected - Now Playing"
        else:
            self.status_item.title = "Connected"

    def _update_queue(self, tracks):
        """Replace the Up Next submenu items with current queue tracks."""
        self.queue_item.clear()
        if not tracks:
            self.queue_item.add(rumps.MenuItem("No upcoming tracks", callback=None))
        else:
            for i, track in enumerate(tracks[:15]):
                self.queue_item.add(rumps.MenuItem(f"{i + 1}. {track}", callback=None))
            if len(tracks) > 15:
                self.queue_item.add(rumps.MenuItem(
                    f"  + {len(tracks) - 15} more...", callback=None))

    def _update_icon(self, color):
        try:
            self.icon = _resource_path(f"icon_{color}.png")
        except Exception:
            pass

    def focus_spotify(self, _):
        import subprocess
        subprocess.Popen(["open", "-a", "Spotify"])

    def open_echonest(self, _):
        webbrowser.open("https://echone.st")

    def toggle_pause(self, _):
        if self._sync_paused:
            self.channel.send_command("resume")
        else:
            self.channel.send_command("pause")

    def _alert(self, title, message, ok="OK", cancel=None):
        """Show an alert dialog with the EchoNest icon."""
        from AppKit import NSAlert, NSImage, NSAlertFirstButtonReturn
        alert = NSAlert.alloc().init()
        alert.setMessageText_(title)
        alert.setInformativeText_(message)
        alert.addButtonWithTitle_(ok)
        if cancel:
            alert.addButtonWithTitle_(cancel)
        icon_path = _resource_path("icon_app.png")
        ns_image = NSImage.alloc().initWithContentsOfFile_(icon_path)
        if ns_image:
            ns_image.setSize_((128, 128))
            alert.setIcon_(ns_image)
        return alert.runModal() == NSAlertFirstButtonReturn

    def check_updates(self, _):
        result = check_for_update()
        if result["available"]:
            v = result["version"]
            self.update_item.title = f"Update available: v{v}"
            if self._alert("Update Available",
                           f"Version {v} is ready to download.",
                           ok="Download", cancel="Later"):
                webbrowser.open(result["download_url"])
        else:
            self.update_item.title = f"Up to date (v{CURRENT_VERSION})"
            self._alert("No Updates",
                        f"You're on the latest version (v{CURRENT_VERSION}).")

    def toggle_airhorn(self, _):
        self._airhorn_enabled = not self._airhorn_enabled
        self.airhorn_item.title = f"Airhorns: {'On' if self._airhorn_enabled else 'Off'}"
        self.channel.send_command("toggle_airhorn")

    def refresh_devices(self, _):
        self.channel.send_command("fetch_devices")

    def _update_devices_menu(self):
        self.devices_item.clear()
        if not self._devices:
            self.devices_item.add(rumps.MenuItem("No devices found", callback=None))
        else:
            for dev in self._devices:
                name = dev.get("name", "Unknown")
                is_active = dev.get("is_active", False)
                device_id = dev.get("id", "")
                item = rumps.MenuItem(
                    f"{'✓ ' if is_active else ''}{name}",
                    callback=lambda _, did=device_id: self._transfer_to(did),
                )
                self.devices_item.add(item)
        self.devices_item.add(None)  # separator
        self.devices_item.add(rumps.MenuItem("Refresh", callback=self.refresh_devices))

    def _transfer_to(self, device_id):
        self.channel.send_command("transfer_playback", device_id=device_id)

    def open_search(self, _):
        if self._server and self._token:
            from .search import launch_search
            launch_search(self._server, self._token)

    def toggle_autostart(self, _):
        if is_autostart_enabled():
            disable_autostart()
            self.autostart_item.state = False
        else:
            enable_autostart()
            self.autostart_item.state = True

    def quit_app(self, _):
        self.channel.send_command("quit")
        rumps.quit_application()
