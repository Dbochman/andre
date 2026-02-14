"""Check GitHub Releases for newer versions of EchoNest Sync."""

import logging
import platform
import threading

import requests

log = logging.getLogger(__name__)

GITHUB_REPO = "Dbochman/EchoNest"
CURRENT_VERSION = "0.5.0"


def _parse_version(tag):
    """Parse 'sync-v0.3.0' or '0.3.0' into a comparable tuple."""
    v = tag.removeprefix("sync-v").removeprefix("v")
    try:
        return tuple(int(x) for x in v.split("."))
    except (ValueError, AttributeError):
        return (0,)


def check_for_update():
    """Check GitHub for a newer sync release.

    Returns dict with 'available', 'version', 'url', and 'download_url' keys,
    or {'available': False} if up to date or on error.
    """
    try:
        # List recent releases and find the latest sync-v* tag
        resp = requests.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases",
            params={"per_page": 10},
            timeout=8,
        )
        resp.raise_for_status()
        releases = resp.json()

        current = _parse_version(CURRENT_VERSION)
        system = platform.system()

        for release in releases:
            tag = release.get("tag_name", "")
            if not tag.startswith("sync-v"):
                continue
            latest = _parse_version(tag)
            if latest <= current:
                break  # No newer version

            # Find platform-appropriate asset
            download_url = None
            for asset in release.get("assets", []):
                name = asset["name"].lower()
                if system == "Darwin" and name.endswith((".app.zip", ".dmg")):
                    download_url = asset["browser_download_url"]
                    break
                elif system == "Windows" and name.endswith(".exe"):
                    download_url = asset["browser_download_url"]
                    break
                elif system == "Linux" and name.endswith((".tar.gz", ".appimage")):
                    download_url = asset["browser_download_url"]
                    break

            return {
                "available": True,
                "version": tag.removeprefix("sync-v"),
                "url": release["html_url"],
                "download_url": download_url or release["html_url"],
            }
    except Exception as e:
        log.debug("Update check failed: %s", e)

    return {"available": False}


def check_for_update_async(callback):
    """Run update check in background thread, call callback(result) when done."""
    def _run():
        result = check_for_update()
        callback(result)
    threading.Thread(target=_run, daemon=True).start()
