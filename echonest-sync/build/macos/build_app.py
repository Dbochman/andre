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

        # App icon
        "--icon", os.path.join(ROOT, "resources", "icon.icns"),

        # Resources
        "--add-data", os.path.join(ROOT, "resources") + ":resources",

        # Hidden imports that PyInstaller may miss
        "--hidden-import", "rumps",
        "--hidden-import", "keyring.backends.macOS",
        "--hidden-import", "keyring.backends.SecretService",

        # Hidden imports for the app modules (relative imports in the package)
        "--hidden-import", "echonest_sync.config",
        "--hidden-import", "echonest_sync.ipc",
        "--hidden-import", "echonest_sync.player",
        "--hidden-import", "echonest_sync.sync",
        "--hidden-import", "echonest_sync.app",
        "--hidden-import", "echonest_sync.tray_mac",
        "--hidden-import", "echonest_sync.onboarding",
        "--hidden-import", "echonest_sync.autostart",

        # Entry point (uses absolute imports, not relative)
        os.path.join(ROOT, "src", "echonest_sync", "__main__.py"),
    ]

    print("Building macOS .app bundle...")
    print(" ".join(cmd))
    subprocess.check_call(cmd, cwd=ROOT)

    # Replace PyInstaller's generated Info.plist with our custom one
    app_path = os.path.join(ROOT, "dist", "EchoNest Sync.app")
    app_plist = os.path.join(app_path, "Contents", "Info.plist")
    custom_plist = os.path.join(BUILD_DIR, "Info.plist")
    if os.path.exists(custom_plist):
        print(f"Replacing Info.plist with {custom_plist}")
        shutil.copy2(custom_plist, app_plist)

    # Ad-hoc codesign so macOS Keychain allows keyring access
    print("Ad-hoc signing .app bundle...")
    subprocess.check_call([
        "codesign", "--force", "--deep", "--sign", "-", app_path,
    ])

    print("\nBuild complete: dist/EchoNest Sync.app")
    print("To create a DMG:")
    print("  python build/macos/build_dmg.py")


if __name__ == "__main__":
    build()
