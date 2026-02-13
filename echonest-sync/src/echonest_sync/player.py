"""Platform-specific Spotify control via OS automation (no Spotify OAuth needed)."""

import logging
import platform
import shutil
import subprocess

log = logging.getLogger(__name__)


class SpotifyPlayer:
    """Abstract interface for controlling local Spotify."""

    def play_track(self, uri):
        raise NotImplementedError

    def pause(self):
        raise NotImplementedError

    def resume(self):
        raise NotImplementedError

    def seek_to(self, seconds):
        raise NotImplementedError

    def get_position(self):
        raise NotImplementedError

    def get_current_track(self):
        raise NotImplementedError

    def is_running(self):
        raise NotImplementedError


class MacOSPlayer(SpotifyPlayer):
    """Control Spotify via AppleScript (osascript)."""

    def _osascript(self, script):
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                log.warning("osascript error: %s", result.stderr.strip())
                return None
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            log.warning("osascript timed out")
            return None
        except FileNotFoundError:
            log.error("osascript not found")
            return None

    def play_track(self, uri):
        self._osascript(f'tell application "Spotify" to play track "{uri}"')

    def pause(self):
        self._osascript('tell application "Spotify" to pause')

    def resume(self):
        self._osascript('tell application "Spotify" to play')

    def seek_to(self, seconds):
        self._osascript(f'tell application "Spotify" to set player position to {seconds}')

    def get_position(self):
        result = self._osascript('tell application "Spotify" to player position')
        if result is not None:
            try:
                return float(result)
            except ValueError:
                pass
        return None

    def get_current_track(self):
        return self._osascript('tell application "Spotify" to id of current track')

    def is_running(self):
        result = self._osascript(
            'tell application "System Events" to (name of processes) contains "Spotify"'
        )
        return result == "true"


class LinuxPlayer(SpotifyPlayer):
    """Control Spotify via playerctl."""

    def __init__(self):
        if not shutil.which("playerctl"):
            log.error("playerctl not found — install it: sudo apt install playerctl")

    def _playerctl(self, *args):
        try:
            result = subprocess.run(
                ["playerctl", "--player=spotify", *args],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                log.warning("playerctl error: %s", result.stderr.strip())
                return None
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            log.warning("playerctl timed out")
            return None
        except FileNotFoundError:
            log.error("playerctl not found")
            return None

    def play_track(self, uri):
        self._playerctl("open", uri)

    def pause(self):
        self._playerctl("pause")

    def resume(self):
        self._playerctl("play")

    def seek_to(self, seconds):
        self._playerctl("position", str(seconds))

    def get_position(self):
        result = self._playerctl("position")
        if result is not None:
            try:
                return float(result)
            except ValueError:
                pass
        return None

    def get_current_track(self):
        return self._playerctl("metadata", "mpris:trackid")

    def is_running(self):
        result = self._playerctl("status")
        return result is not None


class WindowsPlayer(SpotifyPlayer):
    """Minimal Windows support — opens Spotify URIs but cannot seek."""

    def __init__(self):
        log.warning("Windows support is limited: seek is not available")

    def play_track(self, uri):
        import os
        os.startfile(uri)

    def pause(self):
        log.warning("pause not supported on Windows")

    def resume(self):
        log.warning("resume not supported on Windows")

    def seek_to(self, seconds):
        log.debug("seek not supported on Windows")

    def get_position(self):
        return None

    def get_current_track(self):
        return None

    def is_running(self):
        return True  # Assume running


def create_player():
    """Create the appropriate player for the current platform."""
    system = platform.system()
    if system == "Darwin":
        return MacOSPlayer()
    elif system == "Linux":
        return LinuxPlayer()
    elif system == "Windows":
        return WindowsPlayer()
    else:
        log.warning("Unknown platform %s, falling back to macOS player", system)
        return MacOSPlayer()
