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

def _plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _build_plist(label: str, program_args: list) -> str:
    args_xml = "\n".join(f"        <string>{a}</string>" for a in program_args)
    return f"""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
{args_xml}
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>
"""


def _macos_enable() -> None:
    path = _plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if getattr(sys, 'frozen', False):
        # PyInstaller bundle: sys.executable is the binary itself
        args = [sys.executable]
    else:
        args = [sys.executable, "-m", "echonest_sync.app"]
    path.write_text(_build_plist(LABEL, args))
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
    frozen = getattr(sys, 'frozen', False)
    exe = sys.executable
    args = "" if frozen else "-m echonest_sync.app"
    try:
        import winshell  # type: ignore[import-untyped]
        shortcut_path = str(_shortcut_path())
        with winshell.shortcut(shortcut_path) as link:
            link.path = exe
            link.arguments = args
            link.description = "EchoNest Sync"
        log.info("Startup shortcut created: %s", shortcut_path)
    except ImportError:
        # Fallback: write a .bat file instead
        bat = _startup_dir() / "EchoNest Sync.bat"
        cmd = f'"{exe}"' if frozen else f'"{exe}" -m echonest_sync.app'
        bat.write_text(f'@echo off\n{cmd}\n')
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
Exec={exec_line}
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
    if getattr(sys, 'frozen', False):
        exec_line = sys.executable
    else:
        exe = shutil.which("echonest-sync-app") or sys.executable
        exec_line = f"{exe} -m echonest_sync.app"
    path.write_text(_DESKTOP_TEMPLATE.format(exec_line=exec_line))
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
