"""Manage launch-at-login for macOS (LaunchAgent), Windows (Startup folder), and Linux (XDG autostart)."""

import logging
import os
import platform
import shutil
import sys
from pathlib import Path

log = logging.getLogger(__name__)

LABEL = "st.echone.sync"

# ---------------------------------------------------------------------------
# macOS — LaunchAgent plist
# ---------------------------------------------------------------------------

_PLIST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{executable}</string>
        <string>-m</string>
        <string>echonest_sync.app</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>
"""


def _plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _macos_enable() -> None:
    path = _plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_PLIST_TEMPLATE.format(
        label=LABEL,
        executable=sys.executable,
    ))
    log.info("LaunchAgent written: %s", path)


def _macos_disable() -> None:
    path = _plist_path()
    if path.exists():
        path.unlink()
        log.info("LaunchAgent removed: %s", path)


def _macos_is_enabled() -> bool:
    return _plist_path().exists()


# ---------------------------------------------------------------------------
# Windows — Startup folder shortcut
# ---------------------------------------------------------------------------

def _startup_dir() -> Path:
    appdata = os.environ.get("APPDATA", "")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _shortcut_path() -> Path:
    return _startup_dir() / "EchoNest Sync.lnk"


def _windows_enable() -> None:
    try:
        import winshell  # type: ignore[import-untyped]
        shortcut_path = str(_shortcut_path())
        with winshell.shortcut(shortcut_path) as link:
            link.path = sys.executable
            link.arguments = "-m echonest_sync.app"
            link.description = "EchoNest Sync"
        log.info("Startup shortcut created: %s", shortcut_path)
    except ImportError:
        # Fallback: write a .bat file instead
        bat = _startup_dir() / "EchoNest Sync.bat"
        bat.write_text(f'@echo off\n"{sys.executable}" -m echonest_sync.app\n')
        log.info("Startup batch file created: %s", bat)


def _windows_disable() -> None:
    for name in ("EchoNest Sync.lnk", "EchoNest Sync.bat"):
        p = _startup_dir() / name
        if p.exists():
            p.unlink()
            log.info("Startup entry removed: %s", p)


def _windows_is_enabled() -> bool:
    return _shortcut_path().exists() or (_startup_dir() / "EchoNest Sync.bat").exists()


# ---------------------------------------------------------------------------
# Linux — XDG autostart .desktop file
# ---------------------------------------------------------------------------

_DESKTOP_TEMPLATE = """\
[Desktop Entry]
Type=Application
Name=EchoNest Sync
Exec={executable} -m echonest_sync.app
Icon=echonest-sync
Terminal=false
Categories=Audio;Music;
Comment=Sync your local Spotify with an EchoNest server
"""


def _desktop_path() -> Path:
    xdg = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return xdg / "autostart" / "echonest-sync.desktop"


def _linux_enable() -> None:
    path = _desktop_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    exe = shutil.which("echonest-sync-app") or sys.executable
    path.write_text(_DESKTOP_TEMPLATE.format(executable=exe))
    log.info("XDG autostart written: %s", path)


def _linux_disable() -> None:
    path = _desktop_path()
    if path.exists():
        path.unlink()
        log.info("XDG autostart removed: %s", path)


def _linux_is_enabled() -> bool:
    return _desktop_path().exists()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def enable_autostart() -> None:
    system = platform.system()
    if system == "Darwin":
        _macos_enable()
    elif system == "Windows":
        _windows_enable()
    else:
        _linux_enable()


def disable_autostart() -> None:
    system = platform.system()
    if system == "Darwin":
        _macos_disable()
    elif system == "Windows":
        _windows_disable()
    else:
        _linux_disable()


def is_autostart_enabled() -> bool:
    system = platform.system()
    if system == "Darwin":
        return _macos_is_enabled()
    elif system == "Windows":
        return _windows_is_enabled()
    return _linux_is_enabled()
