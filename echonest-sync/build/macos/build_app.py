"""PyInstaller build script for macOS .app bundle.

Usage:
    cd echonest-sync
    pip install pyinstaller
    python build/macos/build_app.py

Produces: dist/EchoNest Sync.app
"""

import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUILD_DIR = os.path.dirname(os.path.abspath(__file__))


def build():
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "EchoNest Sync",
        "--windowed",                    # .app bundle, no console
        "--onedir",                      # directory bundle (smaller, faster startup)
        "--noconfirm",                   # overwrite without asking

        # macOS-specific
        "--osx-bundle-identifier", "st.echone.sync",
        "--target-architecture", "universal2",

        # App icon
        "--icon", os.path.join(ROOT, "resources", "icon.icns"),

        # Resources
        "--add-data", os.path.join(ROOT, "resources") + ":resources",

        # Hidden imports that PyInstaller may miss
        "--hidden-import", "rumps",
        "--hidden-import", "keyring.backends.macOS",
        "--hidden-import", "keyring.backends.SecretService",

        # Entry point
        os.path.join(ROOT, "src", "echonest_sync", "app.py"),
    ]

    print("Building macOS .app bundle...")
    print(" ".join(cmd))
    subprocess.check_call(cmd, cwd=ROOT)

    # Replace PyInstaller's generated Info.plist with our custom one
    app_plist = os.path.join(ROOT, "dist", "EchoNest Sync.app", "Contents", "Info.plist")
    custom_plist = os.path.join(BUILD_DIR, "Info.plist")
    if os.path.exists(custom_plist):
        print(f"Replacing Info.plist with {custom_plist}")
        shutil.copy2(custom_plist, app_plist)

    print("\nBuild complete: dist/EchoNest Sync.app")
    print("To create a DMG:")
    print("  hdiutil create -volname 'EchoNest Sync' -srcfolder 'dist/EchoNest Sync.app' "
          "-ov -format UDZO 'dist/EchoNest-Sync.dmg'")


if __name__ == "__main__":
    build()
