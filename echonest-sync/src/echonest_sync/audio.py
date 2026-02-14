"""Audio caching and cross-platform playback for airhorn sounds."""

import logging
import os
import platform
import subprocess
import threading
from pathlib import Path

import requests

from .config import get_config_dir

log = logging.getLogger(__name__)

EXTENSIONS = (".mp3", ".wav", ".ogg")


def _cache_dir() -> Path:
    d = get_config_dir() / "audio_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def download_audio(server: str, name: str) -> Path | None:
    """Download an audio file from the server, trying multiple extensions.

    Returns the cached file path, or None if all attempts fail.
    """
    cache = _cache_dir()

    # Check cache first
    for ext in EXTENSIONS:
        cached = cache / f"{name}{ext}"
        if cached.exists():
            return cached

    # Try downloading each extension
    server = server.rstrip("/")
    for ext in EXTENSIONS:
        url = f"{server}/static/audio/{name}{ext}"
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                dest = cache / f"{name}{ext}"
                dest.write_bytes(resp.content)
                log.info("Cached audio: %s", dest.name)
                return dest
        except Exception as e:
            log.debug("Failed to download %s: %s", url, e)

    log.warning("Could not download audio for '%s'", name)
    return None


def play_audio(filepath: Path, volume: float = 1.0) -> None:
    """Play an audio file in a background thread. Volume is 0.0-1.0."""
    thread = threading.Thread(
        target=_play_audio_sync, args=(filepath, volume), daemon=True
    )
    thread.start()


def _play_audio_sync(filepath: Path, volume: float) -> None:
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.run(
                ["afplay", "-v", str(volume), str(filepath)],
                capture_output=True, timeout=30,
            )
        elif system == "Linux":
            _play_linux(filepath, volume)
        else:
            _play_windows(filepath, volume)
    except Exception as e:
        log.warning("Audio playback failed: %s", e)


def _play_linux(filepath: Path, volume: float) -> None:
    pa_vol = int(volume * 65536)
    try:
        subprocess.run(
            ["paplay", f"--volume={pa_vol}", str(filepath)],
            capture_output=True, timeout=30,
        )
    except FileNotFoundError:
        subprocess.run(
            ["aplay", str(filepath)],
            capture_output=True, timeout=30,
        )


def _play_windows(filepath: Path, volume: float) -> None:
    # Try ffplay first (handles mp3/wav/ogg)
    try:
        subprocess.run(
            ["ffplay", "-nodisp", "-autoexit",
             "-volume", str(int(volume * 100)), str(filepath)],
            capture_output=True, timeout=30,
        )
        return
    except FileNotFoundError:
        pass

    # Try mpv
    try:
        subprocess.run(
            ["mpv", "--no-video", f"--volume={int(volume * 100)}", str(filepath)],
            capture_output=True, timeout=30,
        )
        return
    except FileNotFoundError:
        pass

    # Last resort: winsound (wav only)
    if filepath.suffix.lower() == ".wav":
        import winsound
        winsound.PlaySound(str(filepath), winsound.SND_FILENAME)
    else:
        log.warning("No audio player found for %s on Windows (install ffplay or mpv)", filepath.suffix)
