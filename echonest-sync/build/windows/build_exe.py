"""PyInstaller build script for Windows .exe.

Usage:
    cd echonest-sync
    pip install pyinstaller
    python build/windows/build_exe.py

Produces: dist/EchoNest Sync.exe
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUILD_DIR = os.path.dirname(os.path.abspath(__file__))


def build():
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "EchoNest Sync",
        "--onefile",                     # single .exe
        "--windowed",                    # no console window
        "--noconfirm",                   # overwrite without asking

        # App icon
        "--icon", os.path.join(ROOT, "resources", "icon.ico"),

        # Resources
        "--add-data", os.path.join(ROOT, "resources") + ";resources",

        # Hidden imports that PyInstaller may miss
        "--hidden-import", "pystray",
        "--hidden-import", "PIL",
        "--hidden-import", "keyring.backends.Windows",

        # Hidden imports for the app modules (relative imports in the package)
        "--hidden-import", "echonest_sync.config",
        "--hidden-import", "echonest_sync.ipc",
        "--hidden-import", "echonest_sync.player",
        "--hidden-import", "echonest_sync.sync",
        "--hidden-import", "echonest_sync.app",
        "--hidden-import", "echonest_sync.tray_win",
        "--hidden-import", "echonest_sync.onboarding",
        "--hidden-import", "echonest_sync.autostart",
        "--hidden-import", "echonest_sync.link",
        "--hidden-import", "echonest_sync.search",
        "--hidden-import", "echonest_sync.audio",
        "--hidden-import", "echonest_sync.miniplayer",
        "--hidden-import", "echonest_sync.updater",
        "--hidden-import", "echonest_sync.cli",

        # Entry point (uses absolute imports, not relative)
        os.path.join(ROOT, "src", "echonest_sync", "__main__.py"),
    ]

    print("Building Windows .exe...")
    print(" ".join(cmd))
    subprocess.check_call(cmd, cwd=ROOT)

    print("\nBuild complete: dist/EchoNest Sync.exe")


if __name__ == "__main__":
    build()
