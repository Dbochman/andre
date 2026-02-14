"""SSE subscription loop + state machine for syncing local Spotify."""

import json
import logging
import time
from datetime import datetime

import requests
import sseclient

from .audio import download_audio, play_audio

log = logging.getLogger(__name__)


def _elapsed_seconds(starttime_str, now_str):
    """Seconds elapsed between two server timestamps (same clock, no TZ needed)."""
    start = datetime.fromisoformat(starttime_str)
    now = datetime.fromisoformat(now_str)
    return max(0, (now - start).total_seconds())


class SyncAgent:
    def __init__(self, server, token, player, drift_threshold=3, channel=None):
        self.server = server.rstrip("/")
        self.token = token
        self.player = player
        self.drift_threshold = drift_threshold
        self.channel = channel  # Optional SyncChannel for GUI IPC

        # State
        self.current_track_uri = None
        self.current_src = None
        self.paused = False

        # IPC state (only active when channel is not None)
        self._sync_paused = False
        self._override_count = 0
        self._last_override_check = 0
        self._override_grace_until = 0  # suppress override checks until this time
        self._running = True
        self._sse_response = None  # closed on quit to unblock SSE iterator

        # Airhorn state
        self.airhorn_enabled = True

    # ------------------------------------------------------------------
    # IPC helpers (no-ops when channel is None)
    # ------------------------------------------------------------------

    def _emit(self, event_type, **kwargs):
        if self.channel:
            self.channel.emit(event_type, **kwargs)

    def _process_commands(self):
        """Drain and handle all pending GUI commands."""
        if not self.channel:
            return
        for cmd in self.channel.get_commands():
            if cmd.type == "pause":
                self._sync_paused = True
                self._emit("status_changed", status="paused")
                log.info("Sync paused by user")
            elif cmd.type == "resume":
                self._sync_paused = False
                self._override_count = 0
                # Clear current track so _initial_sync re-plays it
                self.current_track_uri = None
                # Grace period: suppress override detection for 15s
                # to let Spotify load the track
                self._override_grace_until = time.time() + 15
                self._emit("status_changed", status="syncing")
                log.info("Sync resumed by user")
                self._initial_sync()
            elif cmd.type == "toggle_airhorn":
                self.airhorn_enabled = not self.airhorn_enabled
                self._emit("airhorn_toggled", enabled=self.airhorn_enabled)
                log.info("Airhorns %s", "enabled" if self.airhorn_enabled else "disabled")
            elif cmd.type == "fetch_devices":
                self._fetch_devices()
            elif cmd.type == "transfer_playback":
                device_id = cmd.kwargs.get("device_id")
                if device_id:
                    self._transfer_playback(device_id)
            elif cmd.type == "quit":
                self._running = False
                # Close the SSE stream to unblock the event iterator
                if self._sse_response is not None:
                    try:
                        self._sse_response.close()
                    except Exception:
                        pass
                log.info("Quit requested")

    def _is_sync_active(self):
        """Check if sync should control the player right now."""
        return not self._sync_paused

    def _check_user_override(self):
        """Detect if user manually changed Spotify playback."""
        if not self.channel or not self.current_track_uri:
            return

        now = time.time()
        # Grace period after track changes / resume to let Spotify load
        if now < self._override_grace_until:
            return
        if now - self._last_override_check < 5:
            return
        self._last_override_check = now

        try:
            local_track = self.player.get_current_track()
        except Exception:
            return

        if local_track is None:
            # Player can't report (e.g. WindowsPlayer) — skip detection
            return

        if local_track != self.current_track_uri:
            self._override_count += 1
            if self._override_count >= 2:  # 10s of mismatch
                self._emit("user_override", track=local_track)
                self._sync_paused = True
                self._emit("status_changed", status="override")
                log.info("User override detected — auto-pausing sync")
        else:
            self._override_count = 0

    # ------------------------------------------------------------------
    # Core handlers
    # ------------------------------------------------------------------

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def _initial_sync(self):
        """GET /api/playing to sync immediately on connect."""
        try:
            resp = requests.get(
                f"{self.server}/api/playing",
                headers=self._headers(),
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            log.debug("Initial sync data: %s", data)
            self._handle_now_playing(data)
        except Exception as e:
            log.warning("Initial sync failed: %s", e)

    def _handle_now_playing(self, data):
        """Process a now_playing event or /api/playing response."""
        src = data.get("src", "")
        trackid = data.get("trackid", "")
        starttime = data.get("starttime", "")
        server_now = data.get("now", "")
        is_paused = bool(data.get("paused"))

        if not trackid:
            log.debug("No track playing")
            self.current_track_uri = None
            self.current_src = None
            return

        if src != "spotify":
            log.info("Non-Spotify track (%s) — skipping local control", src)
            self.current_track_uri = None
            self.current_src = src
            return

        # trackid may already be a full URI (e.g. "spotify:track:ABC123")
        uri = trackid if trackid.startswith("spotify:") else f"spotify:track:{trackid}"
        self.current_src = src

        if uri != self.current_track_uri:
            log.info("Now playing: %s (paused=%s)", uri, is_paused)
            title = data.get("title", "")
            artist = data.get("artist", "")

            if self._is_sync_active() and not is_paused:
                self.player.play_track(uri)
            self.current_track_uri = uri
            self.paused = is_paused
            self._override_count = 0  # Reset on server track change
            # Grace period after track change to let Spotify load
            self._override_grace_until = time.time() + 15
            self._emit("track_changed", uri=uri, title=title, artist=artist)

            if starttime and server_now and not is_paused:
                elapsed = _elapsed_seconds(starttime, server_now)
                duration = data.get("duration")
                # Clamp: don't seek past the track's duration (stale starttime)
                if duration:
                    try:
                        duration_s = float(duration)
                        if elapsed > duration_s:
                            log.debug("Elapsed %.1fs exceeds duration %.1fs — skipping seek",
                                      elapsed, duration_s)
                            elapsed = 0
                    except (ValueError, TypeError):
                        pass
                if elapsed > 1 and self._is_sync_active():
                    log.debug("Seeking to %.1fs (elapsed since start)", elapsed)
                    # Small delay to let Spotify load the track
                    time.sleep(0.5)
                    self.player.seek_to(elapsed)
            return

        # Handle pause/resume for same track
        if is_paused and not self.paused:
            log.info("Pausing")
            if self._is_sync_active():
                self.player.pause()
            self.paused = True
        elif not is_paused and self.paused:
            log.info("Resuming")
            if self._is_sync_active():
                self.player.resume()
            self.paused = False
            if starttime and server_now and self._is_sync_active():
                elapsed = _elapsed_seconds(starttime, server_now)
                duration = data.get("duration")
                if duration:
                    try:
                        if elapsed > float(duration):
                            elapsed = 0
                    except (ValueError, TypeError):
                        pass
                if elapsed > 0:
                    self.player.seek_to(elapsed)

    def _handle_player_position(self, data):
        """Process a player_position event for drift correction."""
        src = data.get("src", "")
        if src != "spotify" or self.current_track_uri is None:
            return

        if not self._is_sync_active():
            return

        server_pos = data.get("pos", 0)
        local_pos = self.player.get_position()
        if local_pos is None:
            return

        drift = abs(local_pos - server_pos)
        if drift > self.drift_threshold:
            log.info("Drift correction: local=%.1fs server=%ds (drift=%.1fs)",
                     local_pos, server_pos, drift)
            self.player.seek_to(server_pos)

    def _handle_queue_update(self, data):
        """Process a queue_update event (list of queued tracks)."""
        if not isinstance(data, list):
            return
        tracks = []
        for item in data:
            title = item.get("title", "")
            artist = item.get("artist", "")
            if title and artist:
                tracks.append(f"{title} - {artist}")
            elif title:
                tracks.append(title)
        self._emit("queue_updated", tracks=tracks)

    def _handle_airhorn(self, data):
        """Play an airhorn sound locally."""
        if not self.airhorn_enabled:
            return
        name = data.get("name", "airhorn")
        volume = float(data.get("volume", 1.0))
        self._emit("airhorn", name=name)
        filepath = download_audio(self.server, name)
        if filepath:
            play_audio(filepath, volume)
        else:
            log.warning("Airhorn audio not available: %s", name)

    def _fetch_devices(self):
        """GET /api/spotify/devices and emit the list."""
        try:
            resp = requests.get(
                f"{self.server}/api/spotify/devices",
                headers=self._headers(),
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            devices = data.get("devices", [])
            self._emit("devices_updated", devices=devices)
        except Exception as e:
            log.warning("Failed to fetch devices: %s", e)
            self._emit("devices_updated", devices=[])

    def _transfer_playback(self, device_id):
        """POST /api/spotify/transfer to switch playback device."""
        try:
            resp = requests.post(
                f"{self.server}/api/spotify/transfer",
                headers={**self._headers(), "Content-Type": "application/json"},
                json={"device_id": device_id},
                timeout=10,
            )
            resp.raise_for_status()
            self._emit("transfer_complete", device_id=device_id)
            log.info("Playback transferred to %s", device_id)
        except Exception as e:
            self._emit("transfer_failed", error=str(e))
            log.warning("Transfer failed: %s", e)

    def _fetch_queue(self):
        """GET /api/queue to populate queue on connect."""
        try:
            resp = requests.get(
                f"{self.server}/api/queue",
                headers=self._headers(),
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            self._handle_queue_update(data.get("queue", []))
        except Exception as e:
            log.debug("Queue fetch failed: %s", e)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self):
        """Main loop: connect to SSE, process events, reconnect on failure."""
        backoff = 5
        max_backoff = 60

        while self._running:
            # Spotify process watching: idle when not running
            if not self.player.is_running():
                self._emit("status_changed", status="waiting")
                log.info("Spotify not running — waiting...")
                while self._running and not self.player.is_running():
                    self._process_commands()
                    if not self._running:
                        return
                    time.sleep(15)
                if not self._running:
                    return
                log.info("Spotify detected — connecting")

            try:
                log.info("Connecting to %s/api/events ...", self.server)
                resp = requests.get(
                    f"{self.server}/api/events",
                    headers=self._headers(),
                    stream=True,
                    timeout=(10, None),  # 10s connect, no read timeout
                )
                resp.raise_for_status()
                self._sse_response = resp
                log.info("Connected — listening for events")
                backoff = 5  # Reset on successful connect
                self._emit("connected")

                # Sync current state before waiting for events
                self._initial_sync()
                self._fetch_queue()
                self._fetch_devices()

                client = sseclient.SSEClient(resp)
                for event in client.events():
                    # Process IPC commands between events
                    self._process_commands()
                    if not self._running:
                        return

                    # Check for user override
                    self._check_user_override()

                    try:
                        data = json.loads(event.data)
                    except (json.JSONDecodeError, TypeError):
                        continue

                    if event.event == "now_playing":
                        self._handle_now_playing(data)
                    elif event.event == "player_position":
                        self._handle_player_position(data)
                    elif event.event == "queue_update":
                        self._handle_queue_update(data)
                    elif event.event == "airhorn":
                        self._handle_airhorn(data)

            except requests.exceptions.HTTPError as e:
                if e.response is not None and e.response.status_code == 401:
                    log.error("Authentication failed (401) — check your token")
                    self._emit("disconnected", reason="auth_failed")
                    return  # Don't retry auth failures
                log.warning("HTTP error: %s", e)
                self._emit("disconnected", reason="http_error")
            except requests.exceptions.ConnectionError as e:
                log.warning("Connection error: %s", e)
                self._emit("disconnected", reason="connection_error")
            except Exception as e:
                log.warning("Unexpected error: %s", e)
                self._emit("disconnected", reason="error")

            if not self._running:
                return

            log.info("Reconnecting in %ds ...", backoff)
            # Sleep in small increments so we can process quit commands
            sleep_until = time.time() + backoff
            while self._running and time.time() < sleep_until:
                self._process_commands()
                if not self._running:
                    return
                time.sleep(min(1, sleep_until - time.time()))
            backoff = min(backoff * 2, max_backoff)
