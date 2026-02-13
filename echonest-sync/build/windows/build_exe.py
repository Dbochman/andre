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

        # Resources
        "--add-data", os.path.join(ROOT, "resources") + ";resources",

        # Hidden imports that PyInstaller may miss
        "--hidden-import", "pystray",
        "--hidden-import", "PIL",
        "--hidden-import", "keyring.backends.Windows",

        # Entry point
        os.path.join(ROOT, "src", "echonest_sync", "app.py"),
    ]

    print("Building Windows .exe...")
    print(" ".join(cmd))
    subprocess.check_call(cmd, cwd=ROOT)

    print("\nBuild complete: dist/EchoNest Sync.exe")


if __name__ == "__main__":
    build()
